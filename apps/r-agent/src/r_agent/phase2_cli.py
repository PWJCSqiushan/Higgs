"""Opt-in Phase 2 runner. Existing `r-agent listen` remains read-only."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from r_agent.access import IngressPolicy
from r_agent.agenda import AgendaStore
from r_agent.amap import AmapRouteClient
from r_agent.backup import BackupError, BackupManager
from r_agent.config import ConfigError, Settings, parse_qq_set
from r_agent.context import ContextBuilder
from r_agent.conversation import ConversationStore
from r_agent.conversation_guard import ConversationCircuitBreaker
from r_agent.daily_plan import DailyPlanConfig, DailyPlanService
from r_agent.embedding import (
    EmbeddingConfig,
    EmbeddingError,
    LocalHashEmbeddingClient,
    OpenAICompatibleEmbeddingClient,
)
from r_agent.events import ConversationKind, InboundEvent
from r_agent.group_debounce import GroupMessageDebouncer
from r_agent.health import HealthReporter
from r_agent.identity import IdentityStore, Principal
from r_agent.ingest import IngestResult, IngestService
from r_agent.journal import Journal
from r_agent.memory import MemoryError, MemoryStore
from r_agent.memory_v2 import MemoryObservationStore, MemoryReconciler
from r_agent.model_client import ModelConfig, ModelError, OpenAICompatibleClient
from r_agent.model_memory_candidates import (
    MODEL_CANDIDATE_DEFAULT_MODE,
    ModelCandidateExtractor,
    ModelCandidateShadowStore,
)
from r_agent.official_qq import OfficialQQAdapter, OfficialQQConfig
from r_agent.onebot import OneBotParseError, parse_message_event
from r_agent.onebot_adapter import OneBotAdapter
from r_agent.online_reliability import OnlineState, PushPlusNotifier, onebot_online_hint
from r_agent.operator_control import LiveOperatorControl
from r_agent.owner_commands import OwnerCommandContext, OwnerCommandRouter
from r_agent.passive_memory import PassiveMemoryLearner
from r_agent.phase2_outbound import (
    OutboundError,
    get_onebot_account_status,
    get_onebot_message_sender,
)
from r_agent.phase2_reply import PersonaBrain, ReplyAudit, ReplyDecision, ReplyPlan, ReplyPolicy
from r_agent.qq_text import QqTextError, to_qq_plain_text
from r_agent.recall import RecallLedger
from r_agent.reminders import DueOccurrence, ReminderStore
from r_agent.risk_ledger import RiskLedger, RiskLimits
from r_agent.safety import OutboundSafetyPolicy, SafetyError
from r_agent.server_status import ServerStatusCommand, ServerStatusReader
from r_agent.skills import SkillApprovalStore, default_skill_registry
from r_agent.tool_governance import ToolGovernance
from r_agent.transport import DeliveryReceipt, DeliveryState, OutboundTarget, TransportUnavailable
from r_agent.transport_state import TransportStateStore
from r_agent.vector_memory import MemoryVectorStore

_log = logging.getLogger(__name__)

ONLINE_PROBE_INTERVAL_SECONDS = 30.0
ONLINE_PROBE_TIMEOUT_SECONDS = 20.0
ONLINE_PROBE_MAX_DETECTION_SECONDS = ONLINE_PROBE_INTERVAL_SECONDS + ONLINE_PROBE_TIMEOUT_SECONDS


def _value(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _boolean(name: str, default: bool) -> bool:
    raw = _value(name, "true" if default else "false").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean")


def _env_path() -> Path:
    """Return the writable operator configuration path for this runtime."""
    return Path(os.environ.get("R_AGENT_ENV_FILE", ".env")).expanduser().resolve()


@dataclass(frozen=True, slots=True)
class Phase2Settings:
    mode: str
    private_users: frozenset[str]
    groups: frozenset[str]
    natural_trigger_groups: frozenset[str]
    natural_trigger_terms: frozenset[str]
    runtime_enabled: bool
    require_mention: bool
    max_per_minute: int
    global_max_per_minute: int
    non_owner_hourly_limit: int
    non_owner_daily_limit: int
    owner_conversation_per_minute: int
    owner_hourly_limit: int
    owner_daily_limit: int
    global_hourly_limit: int
    global_daily_limit: int
    group_debounce_seconds: float
    private_debounce_seconds: float
    safety_enabled: bool
    safety_terms_file: Path | None
    passive_learning_enabled: bool
    memory_auto_review_enabled: bool
    memory_auto_review_confidence: float
    memory_auto_review_evidence: int
    embedding_enabled: bool
    embedding_model: str
    embedding_dimensions: int
    history_turns: int
    memory_items: int
    backup_dir: Path
    backup_interval_minutes: int
    backup_retention: int
    daily_plan_mode: str
    daily_plan_drafts_per_day: int
    daily_plan_map_optimizations_per_day: int


def _phase2_settings(settings: Settings) -> Phase2Settings:
    mode = _value("R_AGENT_REPLY_MODE", "off").lower()
    if mode not in {"off", "draft", "live"}:
        raise ConfigError("R_AGENT_REPLY_MODE must be off, draft, or live")
    live_enabled = _boolean("R_AGENT_PHASE2_ENABLE_LIVE", False)
    if mode == "live" and not live_enabled:
        raise ConfigError("live mode requires R_AGENT_PHASE2_ENABLE_LIVE=true")
    if mode == "live" and settings.shadow_mode:
        raise ConfigError("live mode requires R_AGENT_SHADOW_MODE=false")
    if mode == "live" and settings.owner_qq is None:
        raise ConfigError("live mode requires R_AGENT_OWNER_QQ")
    if mode != "live" and not settings.shadow_mode:
        raise ConfigError("off and draft modes require R_AGENT_SHADOW_MODE=true")
    private_users = parse_qq_set(
        _value("R_AGENT_REPLY_ALLOWED_PRIVATE_QQS"),
        name="R_AGENT_REPLY_ALLOWED_PRIVATE_QQS",
    )
    if not private_users.issubset(settings.allowed_private_qqs):
        raise ConfigError("reply private QQs must be a subset of ingress private QQs")
    groups = parse_qq_set(
        _value("R_AGENT_REPLY_ALLOWED_GROUPS"),
        name="R_AGENT_REPLY_ALLOWED_GROUPS",
    )
    if not groups.issubset(settings.allowed_groups):
        raise ConfigError("reply groups must be a subset of ingress groups")
    natural_trigger_groups = parse_qq_set(
        _value("R_AGENT_REPLY_NATURAL_TRIGGER_GROUPS"),
        name="R_AGENT_REPLY_NATURAL_TRIGGER_GROUPS",
    )
    if not natural_trigger_groups.issubset(groups):
        raise ConfigError("natural trigger groups must be a subset of reply groups")

    raw_terms = _value("R_AGENT_REPLY_NATURAL_TRIGGER_TERMS", "higgs")
    natural_trigger_terms = frozenset(
        term.strip().casefold() for term in raw_terms.split(",") if term.strip()
    )
    if not natural_trigger_terms:
        raise ConfigError("R_AGENT_REPLY_NATURAL_TRIGGER_TERMS must not be empty")
    if len(natural_trigger_terms) > 16 or any(
        len(term) > 32 or "\n" in term or "\r" in term for term in natural_trigger_terms
    ):
        raise ConfigError("R_AGENT_REPLY_NATURAL_TRIGGER_TERMS is invalid")

    def bounded_int(name: str, default: str, minimum: int, maximum: int) -> int:
        try:
            value = int(_value(name, default))
        except ValueError as exc:
            raise ConfigError(f"{name} must be an integer") from exc
        if not minimum <= value <= maximum:
            raise ConfigError(f"{name} must be between {minimum} and {maximum}")
        return value

    def bounded_float(name: str, default: str, minimum: float, maximum: float) -> float:
        try:
            value = float(_value(name, default))
        except ValueError as exc:
            raise ConfigError(f"{name} must be a number") from exc
        if not minimum <= value <= maximum:
            raise ConfigError(f"{name} must be between {minimum} and {maximum}")
        return value

    safety_file_value = _value("R_AGENT_SAFETY_TERMS_FILE")
    safety_terms_file = (
        Path(safety_file_value).expanduser().resolve() if safety_file_value else None
    )
    embedding_model = _value("R_AGENT_EMBEDDING_MODEL", "embedding-3")
    if not embedding_model or len(embedding_model) > 128:
        raise ConfigError("R_AGENT_EMBEDDING_MODEL is invalid")
    embedding_dimensions = bounded_int("R_AGENT_EMBEDDING_DIMENSIONS", "256", 256, 2048)
    if embedding_dimensions not in {256, 512, 1024, 2048}:
        raise ConfigError("R_AGENT_EMBEDDING_DIMENSIONS is unsupported")
    daily_plan_mode = _value("R_AGENT_DAILY_PLAN_MODE", "off").lower()
    if daily_plan_mode not in {"off", "shadow", "live"}:
        raise ConfigError("R_AGENT_DAILY_PLAN_MODE must be off, shadow, or live")
    if daily_plan_mode == "live" and mode != "live":
        raise ConfigError("live daily plans require R_AGENT_REPLY_MODE=live")
    backup_dir_value = _value("R_AGENT_BACKUP_DIR")
    backup_dir = (
        Path(backup_dir_value).expanduser().resolve()
        if backup_dir_value
        else settings.data_dir / "backups"
    )
    return Phase2Settings(
        mode=mode,
        private_users=private_users,
        groups=groups,
        natural_trigger_groups=natural_trigger_groups,
        natural_trigger_terms=natural_trigger_terms,
        runtime_enabled=_boolean("R_AGENT_RUNTIME_ENABLED", True),
        require_mention=_boolean("R_AGENT_REPLY_GROUP_REQUIRE_MENTION", True),
        max_per_minute=bounded_int("R_AGENT_REPLY_MAX_PER_MINUTE", "2", 1, 10),
        history_turns=bounded_int("R_AGENT_HISTORY_TURNS", "8", 1, 20),
        memory_items=bounded_int("R_AGENT_MEMORY_CONTEXT_ITEMS", "8", 0, 20),
        global_max_per_minute=bounded_int("R_AGENT_REPLY_GLOBAL_MAX_PER_MINUTE", "6", 1, 60),
        non_owner_hourly_limit=bounded_int("R_AGENT_REPLY_NON_OWNER_HOURLY_LIMIT", "20", 1, 500),
        non_owner_daily_limit=bounded_int("R_AGENT_REPLY_NON_OWNER_DAILY_LIMIT", "80", 1, 2000),
        owner_conversation_per_minute=bounded_int(
            "R_AGENT_REPLY_OWNER_CONVERSATION_PER_MINUTE", "4", 1, 6
        ),
        owner_hourly_limit=bounded_int("R_AGENT_REPLY_OWNER_HOURLY_LIMIT", "40", 1, 500),
        owner_daily_limit=bounded_int("R_AGENT_REPLY_OWNER_DAILY_LIMIT", "120", 1, 2000),
        global_hourly_limit=bounded_int("R_AGENT_REPLY_GLOBAL_HOURLY_LIMIT", "60", 1, 1000),
        global_daily_limit=bounded_int("R_AGENT_REPLY_GLOBAL_DAILY_LIMIT", "200", 1, 5000),
        group_debounce_seconds=bounded_float("R_AGENT_GROUP_DEBOUNCE_SECONDS", "2.5", 0.5, 10.0),
        private_debounce_seconds=bounded_float(
            "R_AGENT_PRIVATE_DEBOUNCE_SECONDS", "4.0", 0.5, 10.0
        ),
        safety_enabled=_boolean("R_AGENT_SAFETY_ENABLED", True),
        safety_terms_file=safety_terms_file,
        passive_learning_enabled=_boolean("R_AGENT_PASSIVE_LEARNING_ENABLED", False),
        memory_auto_review_enabled=_boolean("R_AGENT_MEMORY_AUTO_REVIEW_ENABLED", True),
        memory_auto_review_confidence=bounded_float(
            "R_AGENT_MEMORY_AUTO_REVIEW_CONFIDENCE", "0.90", 0.8, 0.99
        ),
        memory_auto_review_evidence=bounded_int("R_AGENT_MEMORY_AUTO_REVIEW_EVIDENCE", "2", 2, 5),
        embedding_enabled=_boolean("R_AGENT_EMBEDDING_ENABLED", True),
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        backup_dir=backup_dir,
        backup_interval_minutes=bounded_int("R_AGENT_BACKUP_INTERVAL_MINUTES", "360", 15, 1440),
        backup_retention=bounded_int("R_AGENT_BACKUP_RETENTION", "20", 3, 100),
        daily_plan_mode=daily_plan_mode,
        daily_plan_drafts_per_day=bounded_int("R_AGENT_DAILY_PLAN_DRAFTS_PER_DAY", "10", 1, 50),
        daily_plan_map_optimizations_per_day=bounded_int(
            "R_AGENT_DAILY_PLAN_MAP_OPTIMIZATIONS_PER_DAY", "3", 0, 20
        ),
    )


def _persona_text() -> str:
    file_value = _value("R_AGENT_PERSONA_FILE")
    if not file_value:
        return _value("R_AGENT_PERSONA", "你是一个稳重、诚实、简洁的中文助手。")
    path = Path(file_value).expanduser().resolve()
    try:
        if not path.is_file() or path.stat().st_size > 64 * 1024:
            raise ConfigError("R_AGENT_PERSONA_FILE must be a file no larger than 64 KiB")
        content = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ConfigError("R_AGENT_PERSONA_FILE could not be read as UTF-8") from exc
    if not content:
        raise ConfigError("R_AGENT_PERSONA_FILE must not be empty")
    return content


def _model_client(*, required: bool) -> OpenAICompatibleClient | None:
    key = _value("R_AGENT_MODEL_API_KEY")
    if not key:
        if required:
            raise ConfigError("draft/live mode requires R_AGENT_MODEL_API_KEY")
        return None
    thinking = _value("R_AGENT_MODEL_THINKING").lower() or None
    try:
        return OpenAICompatibleClient(
            ModelConfig(
                provider=_value("R_AGENT_MODEL_PROVIDER", "openai-compatible"),
                base_url=_value("R_AGENT_MODEL_BASE_URL", "https://api.openai.com/v1"),
                model=_value("R_AGENT_MODEL_NAME", "gpt-5-mini"),
                api_key=key,
                thinking=thinking,
            )
        )
    except ModelError as exc:
        raise ConfigError(f"invalid model configuration: {exc}") from exc


def _embedding_client(
    *, enabled: bool, phase: Phase2Settings
) -> OpenAICompatibleEmbeddingClient | LocalHashEmbeddingClient | None:
    if not enabled:
        return None
    backend = _value("R_AGENT_EMBEDDING_BACKEND", "local").casefold()
    if backend == "local":
        return LocalHashEmbeddingClient(dimensions=phase.embedding_dimensions)
    if backend != "remote":
        raise ConfigError("R_AGENT_EMBEDDING_BACKEND must be local or remote")
    key = _value("R_AGENT_EMBEDDING_API_KEY") or _value("R_AGENT_MODEL_API_KEY")
    base_url = _value("R_AGENT_EMBEDDING_BASE_URL") or _value("R_AGENT_MODEL_BASE_URL")
    try:
        return OpenAICompatibleEmbeddingClient(
            EmbeddingConfig(
                base_url=base_url,
                model=phase.embedding_model,
                api_key=key,
                dimensions=phase.embedding_dimensions,
            )
        )
    except EmbeddingError as exc:
        raise ConfigError(f"invalid embedding configuration: {exc}") from exc


def _safety_policy(phase: Phase2Settings) -> OutboundSafetyPolicy | None:
    if not phase.safety_enabled:
        return None
    try:
        return OutboundSafetyPolicy.with_optional_file(phase.safety_terms_file)
    except SafetyError as exc:
        raise ConfigError(f"invalid outbound safety configuration: {exc}") from exc


async def process_reply(
    *,
    event: InboundEvent,
    result: IngestResult,
    policy: ReplyPolicy,
    brain: PersonaBrain,
    sender: Callable[[InboundEvent, str], Awaitable[DeliveryReceipt]],
    safety: OutboundSafetyPolicy | None = None,
    breaker: ConversationCircuitBreaker | None = None,
    owner_qq: str | None = None,
    qq_online: bool = True,
    risk_ledger: RiskLedger | None = None,
) -> ReplyPlan:
    """Create one auditable outcome without letting provider errors stop the listener."""
    decision = policy.gate(event, result)
    if decision not in {ReplyDecision.DRAFTED, ReplyDecision.SENT}:
        return ReplyPlan(decision)
    if not qq_online:
        return ReplyPlan(ReplyDecision.QQ_OFFLINE)
    if breaker is not None:
        guard = await asyncio.to_thread(
            breaker.check_and_reserve,
            event.conversation_id,
            is_owner=event.sender_id == owner_qq,
        )
        if not guard.allowed:
            return ReplyPlan(ReplyDecision.CIRCUIT_BREAKER)
    reservation_id: int | None = None
    if decision is ReplyDecision.SENT and risk_ledger is not None:
        budget = await asyncio.to_thread(
            risk_ledger.reserve_send,
            event_type="reply",
            actor_class="owner" if event.sender_id == owner_qq else "non_owner",
            account_id=event.account_id,
            conversation_id=event.conversation_id,
        )
        if not budget.allowed:
            return ReplyPlan(ReplyDecision.GLOBAL_RATE_LIMITED)
        reservation_id = budget.reservation_id
    try:
        text = to_qq_plain_text(await brain.draft(event))
    except (ModelError, QqTextError):
        if risk_ledger is not None and reservation_id is not None:
            await asyncio.to_thread(risk_ledger.finish_send, reservation_id, outcome="failed")
        return ReplyPlan(ReplyDecision.MODEL_FAILED)

    if safety is not None and not safety.evaluate(text).allowed:
        if risk_ledger is not None and reservation_id is not None:
            await asyncio.to_thread(risk_ledger.finish_send, reservation_id, outcome="failed")
        return ReplyPlan(ReplyDecision.SENSITIVE_BLOCKED)
    policy.mark_generated(event)
    if decision is ReplyDecision.DRAFTED:
        return ReplyPlan(ReplyDecision.DRAFTED, text)
    try:
        receipt = await sender(event, text)
        if receipt.state is not DeliveryState.SENT:
            raise OutboundError(
                "transport delivery was not acknowledged",
                delivery_unknown=receipt.state is DeliveryState.UNKNOWN,
            )
    except OutboundError as exc:
        if risk_ledger is not None and reservation_id is not None:
            outcome = "unknown" if exc.delivery_unknown else "failed"
            await asyncio.to_thread(risk_ledger.finish_send, reservation_id, outcome=outcome)
        return ReplyPlan(ReplyDecision.SEND_FAILED, text)
    except TransportUnavailable:
        if risk_ledger is not None and reservation_id is not None:
            await asyncio.to_thread(risk_ledger.finish_send, reservation_id, outcome="failed")
        return ReplyPlan(ReplyDecision.SEND_FAILED, text)
    if risk_ledger is not None and reservation_id is not None:
        await asyncio.to_thread(risk_ledger.finish_send, reservation_id, outcome="sent")
    return ReplyPlan(ReplyDecision.SENT, text)


def _onebot_reminder_target(occurrence: DueOccurrence) -> OutboundTarget | None:
    """Build a NapCat target only from the persisted channel-bound origin."""

    if occurrence.origin_channel.casefold() != "qq":
        return None
    if occurrence.origin_surface == "group":
        kind = ConversationKind.GROUP
    elif occurrence.origin_surface == "private":
        kind = ConversationKind.PRIVATE
    else:
        return None
    conversation_id = occurrence.origin_conversation_id.strip()
    if not conversation_id.casefold().startswith("qq:"):
        return None
    return OutboundTarget(
        channel="qq",
        conversation_kind=kind,
        conversation_id=conversation_id,
    )


async def listen() -> None:
    import websockets

    env_path = _env_path()
    settings = Settings.from_env(env_file=env_path, require_shadow=False)
    phase = _phase2_settings(settings)
    official_config = OfficialQQConfig.from_env()
    official_owner_openid = official_config.active_owner_openid
    official_group_openids = official_config.active_group_openids
    embeddings = _embedding_client(enabled=phase.embedding_enabled, phase=phase)
    safety = _safety_policy(phase)
    client = _model_client(required=phase.mode in {"draft", "live"})

    service = IngestService(
        policy=IngressPolicy(
            enabled=settings.ingest_enabled,
            owner_qq=settings.owner_qq,
            allowed_private_qqs=settings.allowed_private_qqs,
            allowed_groups=settings.allowed_groups,
            owner_ids=frozenset(
                value for value in (settings.owner_qq, official_owner_openid) if value is not None
            ),
            additional_private_ids=(
                frozenset({official_owner_openid}) if official_owner_openid else frozenset()
            ),
            additional_group_ids=official_group_openids,
        ),
        identities=IdentityStore(
            settings.data_dir / "identity.sqlite",
            owner_qq=settings.owner_qq,
            owner_identities=(
                (("qq_official", official_owner_openid),) if official_owner_openid else ()
            ),
        ),
        journal=Journal(settings.data_dir / "journal.sqlite"),
    )
    service.initialize()
    history = ConversationStore(settings.data_dir / "conversation.sqlite")
    history.initialize()
    await asyncio.to_thread(history.purge_expired, settings.journal_retention_days)
    memory = MemoryStore(settings.data_dir / "memory.sqlite")
    memory.initialize()
    vectors = MemoryVectorStore(memory.path, memory=memory)
    recall = RecallLedger(settings.data_dir / "memory.sqlite")
    recall.initialize()
    audit = ReplyAudit(settings.data_dir / "reply_audit.sqlite")
    audit.initialize()
    observations = MemoryObservationStore(settings.data_dir / "memory.sqlite")
    observations.initialize()
    model_candidate_mode = _value(
        "R_AGENT_MEMORY_MODEL_CANDIDATES", MODEL_CANDIDATE_DEFAULT_MODE
    ).casefold()
    if model_candidate_mode not in {"off", "shadow"}:
        raise ConfigError("R_AGENT_MEMORY_MODEL_CANDIDATES must be off or shadow")
    if model_candidate_mode == "shadow" and client is None:
        raise ConfigError("model memory candidate shadow requires a configured model")
    model_candidate_store = ModelCandidateShadowStore(settings.data_dir / "memory.sqlite")
    model_candidate_store.initialize()
    model_candidate_extractor = (
        ModelCandidateExtractor(client)
        if model_candidate_mode == "shadow" and client is not None
        else None
    )
    reminders = ReminderStore(settings.data_dir / "reminders.sqlite")
    reminders.initialize()
    agenda = AgendaStore(settings.data_dir / "agenda.sqlite")
    agenda.initialize()
    skill_approvals = SkillApprovalStore(settings.data_dir / "skills.sqlite")
    skill_approvals.initialize()
    breaker = ConversationCircuitBreaker(settings.data_dir / "conversation_guard.sqlite")
    breaker.initialize()
    risk_ledger = RiskLedger(
        settings.data_dir / "risk_ledger.sqlite",
        limits=RiskLimits(
            conversation_per_minute=phase.max_per_minute,
            global_per_minute=phase.global_max_per_minute,
            non_owner_per_hour=phase.non_owner_hourly_limit,
            non_owner_per_day=phase.non_owner_daily_limit,
            owner_conversation_per_minute=phase.owner_conversation_per_minute,
            owner_per_hour=phase.owner_hourly_limit,
            owner_per_day=phase.owner_daily_limit,
            global_per_hour=phase.global_hourly_limit,
            global_per_day=phase.global_daily_limit,
        ),
    )
    risk_ledger.initialize()
    risk_ledger.record_event(
        "version",
        client_version=_value("R_AGENT_QQ_CLIENT_VERSION"),
        transport_version=_value("R_AGENT_NAPCAT_VERSION"),
        egress_asn=_value("R_AGENT_EGRESS_ASN"),
    )
    transport_state = TransportStateStore(settings.data_dir / "transport.sqlite")
    transport_state.initialize()
    tool_governance = ToolGovernance(audit_path=settings.data_dir / "tool_audit.sqlite")
    server_status = ServerStatusCommand(tool_governance, ServerStatusReader())
    policy = ReplyPolicy(
        mode=phase.mode,
        private_users=phase.private_users.union(
            {settings.owner_qq} if settings.owner_qq else (),
            {official_owner_openid} if official_owner_openid else (),
        ),
        groups=phase.groups.union(official_group_openids),
        natural_trigger_groups=phase.natural_trigger_groups,
        natural_trigger_terms=phase.natural_trigger_terms,
        global_max_per_minute=phase.global_max_per_minute,
        owner_max_per_minute=phase.owner_conversation_per_minute,
        owner_qq=settings.owner_qq,
        owner_ids=frozenset(
            value for value in (settings.owner_qq, official_owner_openid) if value is not None
        ),
        runtime_enabled=phase.runtime_enabled,
        require_mention=phase.require_mention,
        max_per_minute=phase.max_per_minute,
    )
    persona = _persona_text()
    context_builder = ContextBuilder(
        history=history,
        memory=memory,
        recall=recall,
        persona=persona,
        history_limit=phase.history_turns,
        memory_limit=phase.memory_items,
        vectors=vectors,
        history_outcome="sent" if phase.mode == "live" else "drafted",
    )
    if settings.owner_qq is None:
        raise ConfigError("chat operator control requires R_AGENT_OWNER_QQ")
    operator_control = LiveOperatorControl(
        env_path=env_path,
        owner_qq=settings.owner_qq,
        service=service,
        reply_policy=policy,
        debounce_seconds=phase.group_debounce_seconds,
        memory_auto_review_enabled=phase.memory_auto_review_enabled,
        memory_auto_review_confidence=phase.memory_auto_review_confidence,
        memory_auto_review_evidence=phase.memory_auto_review_evidence,
    )
    backup = BackupManager(
        data_dir=settings.data_dir,
        backup_dir=phase.backup_dir,
        interval_minutes=phase.backup_interval_minutes,
        retention=phase.backup_retention,
        config_snapshot=lambda: asdict(operator_control.snapshot()),
    )
    operator_control.attach_risk_ledger(risk_ledger)
    operator_control.attach_backup(backup.create)
    try:
        await asyncio.to_thread(backup.create, "startup")
    except BackupError as exc:
        _log.warning("startup_backup_failed type=%s", type(exc).__name__)

    health_path = Path(
        os.environ.get("R_AGENT_HEALTH_FILE", str(settings.data_dir / "health.json"))
    )
    napcat_health_path = Path(
        os.environ.get(
            "R_AGENT_NAPCAT_HEALTH_FILE",
            "/run/higgs-napcat-health/heartbeat",
        )
    )
    health = HealthReporter(health_path, napcat_health_path=napcat_health_path)
    online = OnlineState(
        health,
        PushPlusNotifier(_value("R_AGENT_PUSHPLUS_TOKEN")),
        risk_ledger=risk_ledger,
        transport_state=transport_state,
    )
    health.set_transport_connected(False)
    expected_bot_qq = _value("R_AGENT_EXPECTED_BOT_QQ")
    if phase.mode == "live":
        expected_values = parse_qq_set(
            expected_bot_qq,
            name="R_AGENT_EXPECTED_BOT_QQ",
        )
        if len(expected_values) != 1:
            raise ConfigError("live mode requires one R_AGENT_EXPECTED_BOT_QQ")
        expected_bot_qq = next(iter(expected_values))
    onebot_adapter = OneBotAdapter(
        settings.onebot_ws_url,
        settings.onebot_access_token,
        expected_account_id=expected_bot_qq or None,
    )
    official_transport_state = TransportStateStore(
        settings.data_dir / "transport.sqlite", channel="qq_official"
    )
    if official_config.enabled:
        official_transport_state.initialize()
    reconciler = MemoryReconciler(
        observations=observations,
        memory=memory,
        vectors=vectors,
        embedding_client=embeddings,
        auto_review_enabled=lambda: operator_control.snapshot().memory_auto_review_enabled,
        auto_review_confidence=(lambda: operator_control.snapshot().memory_auto_review_confidence),
        auto_review_evidence=(lambda: operator_control.snapshot().memory_auto_review_evidence),
        model_candidate_extractor=model_candidate_extractor,
        model_candidate_shadow_store=(
            model_candidate_store if model_candidate_extractor is not None else None
        ),
    )

    owner_commands = OwnerCommandRouter(
        context=OwnerCommandContext(
            mode=phase.mode,
            private_user_count=len(policy.private_users),
            group_count=len(phase.groups),
            natural_group_count=len(phase.natural_trigger_groups),
            safety_enabled=phase.safety_enabled,
            passive_learning_enabled=phase.passive_learning_enabled,
            embedding_enabled=phase.embedding_enabled,
        ),
        vectors=vectors,
        control=operator_control,
        memory=memory,
        backup=backup,
        observations=observations,
        reminders=reminders,
        journal_path=settings.data_dir / "journal.sqlite",
        conversation_guard=breaker,
        risk_ledger=risk_ledger,
        recall_ledger=recall,
        transport_state=transport_state,
        server_status=server_status,
        model_candidate_shadow_store=model_candidate_store,
    )
    amap_key = _value("R_AGENT_AMAP_WEB_KEY")
    daily_plans = DailyPlanService(
        store=agenda,
        reminders=reminders,
        registry=default_skill_registry(),
        approvals=skill_approvals,
        config=DailyPlanConfig(
            mode=phase.daily_plan_mode,
            drafts_per_day=phase.daily_plan_drafts_per_day,
            map_optimizations_per_day=phase.daily_plan_map_optimizations_per_day,
        ),
        model_client=client,
        amap=AmapRouteClient(amap_key) if amap_key else None,
    )
    brain = PersonaBrain(
        client,
        persona,
        identities=service.identities,
        context_builder=context_builder,
        embedding_client=embeddings,
        owner_commands=owner_commands,
        reminders=reminders,
        daily_plans=daily_plans,
    )
    passive_learner = (
        PassiveMemoryLearner(
            memory=memory,
            vectors=vectors,
            embedding_client=embeddings,
            auto_review_policy=operator_control.memory_auto_review_policy,
            on_auto_review=backup.create,
        )
        if phase.passive_learning_enabled
        else None
    )
    headers = (
        {"Authorization": f"Bearer {settings.onebot_access_token}"}
        if settings.onebot_access_token
        else None
    )

    official_adapter: OfficialQQAdapter | None = None
    official_supervisor_task: asyncio.Task[None] | None = None

    async def sender(event: InboundEvent, text: str) -> DeliveryReceipt:
        if event.channel == "qq_official":
            if official_adapter is None:
                return DeliveryReceipt(
                    channel=event.channel,
                    state=DeliveryState.FAILED,
                    idempotency_key=f"reply:{event.channel}:{event.account_id}:{event.message_id}",
                )
            return await official_adapter.send_text(
                OutboundTarget(
                    channel=event.channel,
                    conversation_kind=event.conversation_kind,
                    conversation_id=event.conversation_id,
                ),
                text,
                idempotency_key=(f"reply:{event.channel}:{event.account_id}:{event.message_id}"),
                reply_message_id=event.message_id,
            )
        return await onebot_adapter.send_reply(event, text)

    async def handle_event(event: InboundEvent, result: IngestResult) -> None:
        """Finish one logical message after the group quiet-window has closed."""
        try:
            if event.channel == "qq_official" and official_adapter is not None:
                official_status = await official_adapter.status()
                channel_online = official_status.connected and official_status.authenticated
            else:
                channel_online = online.snapshot().qq_online
            owner_sender_id = (
                official_owner_openid if event.channel == "qq_official" else settings.owner_qq
            )
            plan = await process_reply(
                event=event,
                result=result,
                policy=policy,
                brain=brain,
                sender=sender,
                safety=safety,
                breaker=breaker,
                owner_qq=owner_sender_id,
                qq_online=channel_online,
                risk_ledger=risk_ledger,
            )
            await asyncio.to_thread(audit.record, event, plan)
            principal = None
            if plan.decision in {
                ReplyDecision.DRAFTED,
                ReplyDecision.SENT,
                ReplyDecision.MODEL_FAILED,
                ReplyDecision.SEND_FAILED,
            } or (
                passive_learner is not None
                and plan.decision
                in {
                    ReplyDecision.MENTION_REQUIRED,
                    ReplyDecision.GROUP_TRIGGER_REQUIRED,
                    ReplyDecision.RATE_LIMITED,
                    ReplyDecision.GLOBAL_RATE_LIMITED,
                    ReplyDecision.SENSITIVE_BLOCKED,
                }
            ):
                principal = await asyncio.to_thread(
                    service.identities.resolve,
                    event.channel,
                    event.sender_id,
                )
            if principal is not None and plan.decision in {
                ReplyDecision.DRAFTED,
                ReplyDecision.SENT,
                ReplyDecision.MODEL_FAILED,
                ReplyDecision.SEND_FAILED,
            }:
                await asyncio.to_thread(
                    history.record,
                    event,
                    principal_id=principal.principal_id,
                    outcome=plan.decision.value,
                    assistant_text=plan.text,
                )
            if (
                passive_learner is not None
                and principal is not None
                and plan.decision
                in {
                    ReplyDecision.MENTION_REQUIRED,
                    ReplyDecision.GROUP_TRIGGER_REQUIRED,
                    ReplyDecision.RATE_LIMITED,
                    ReplyDecision.GLOBAL_RATE_LIMITED,
                    ReplyDecision.SENSITIVE_BLOCKED,
                }
            ):
                learned = await passive_learner.observe(
                    event,
                    principal_id=principal.principal_id,
                )
                if learned.candidate is not None:
                    _log.info(
                        "phase2_memory_candidate embedded=%s auto_review=%s evidence=%s",
                        learned.embedded,
                        learned.auto_review_decision,
                        learned.evidence_count,
                    )
            _log.info("phase2_event decision=%s", plan.decision)
        except (MemoryError, Exception) as exc:
            _log.error("phase2_handler_failed type=%s", type(exc).__name__)

    debouncer = GroupMessageDebouncer(
        quiet_seconds=phase.group_debounce_seconds,
        private_quiet_seconds=phase.private_debounce_seconds,
        handler=handle_event,
    )
    operator_control.attach_debouncer(debouncer)

    async def route_inbound_event(
        event: InboundEvent,
        *,
        resolve_onebot_reply: bool,
    ) -> None:
        owner_ids = {value for value in (settings.owner_qq, official_owner_openid) if value}
        learning_allowed = await asyncio.to_thread(
            risk_ledger.note_inbound,
            event.conversation_id,
            actor_class="owner" if event.sender_id in owner_ids else "non_owner",
            account_id=event.account_id,
            now_ms=event.occurred_at_ms,
        )
        if (
            resolve_onebot_reply
            and event.group_id in phase.natural_trigger_groups
            and event.reply_message_id is not None
        ):
            try:
                replied_sender = await get_onebot_message_sender(
                    settings.onebot_ws_url,
                    settings.onebot_access_token,
                    event.reply_message_id,
                )
            except OutboundError:
                _log.warning("phase2_reply_reference_lookup_failed")
            else:
                if replied_sender == event.account_id:
                    event = replace(event, replied_to_account=True)
        result = await asyncio.to_thread(service.ingest, event)
        if result.stored and learning_allowed:
            principal = await asyncio.to_thread(
                service.identities.resolve,
                event.channel,
                event.sender_id,
            )
            await asyncio.to_thread(
                observations.enqueue,
                event,
                principal_id=principal.principal_id,
                principal_role=principal.role,
            )
        await debouncer.submit(event, result)

    async def route_official_event(event: InboundEvent) -> None:
        await route_inbound_event(event, resolve_onebot_reply=False)

    official_adapter = OfficialQQAdapter(
        official_config,
        event_handler=route_official_event,
        data_dir=settings.data_dir,
        transport_state=official_transport_state if official_config.enabled else None,
    )
    if official_config.enabled:
        try:
            await official_adapter.start()
        except TransportUnavailable as exc:
            _log.error("official_qq_start_failed type=%s", type(exc).__name__)
        official_supervisor_task = asyncio.create_task(official_adapter.supervise())
        official_supervisor_task.add_done_callback(
            lambda task: task.exception() if not task.cancelled() else None
        )
    backup_task = asyncio.create_task(backup.run_periodically())
    backup_task.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)

    reconcile_task = asyncio.create_task(reconciler.run_periodically(interval_seconds=900))
    reconcile_task.add_done_callback(
        lambda task: task.exception() if not task.cancelled() else None
    )

    async def online_probe_loop() -> None:
        while True:
            if online.snapshot().transport_connected:
                try:
                    status = await asyncio.wait_for(
                        get_onebot_account_status(
                            settings.onebot_ws_url, settings.onebot_access_token
                        ),
                        timeout=ONLINE_PROBE_TIMEOUT_SECONDS,
                    )
                except (OutboundError, TimeoutError):
                    await online.set_qq_online(False, reason="onebot_status_probe_failed")
                else:
                    if not status.online:
                        await online.set_qq_online(False, reason="get_status_offline")
                    elif not status.good:
                        await online.set_qq_online(False, reason="get_status_unhealthy")
                    elif expected_bot_qq and status.account_id != expected_bot_qq:
                        await online.set_qq_online(False, reason="wrong_qq_account")
                    else:
                        await online.set_qq_online(True, reason="get_status_ok")
            await asyncio.sleep(ONLINE_PROBE_INTERVAL_SECONDS)

    async def reminder_loop() -> None:
        while True:
            await asyncio.to_thread(reminders.recover_stale_prepared)
            if online.snapshot().qq_online:
                due = await asyncio.to_thread(reminders.prepare_due)
                for occurrence in due:
                    if occurrence.delivery_policy == "agenda_once":
                        text = occurrence.content
                    else:
                        text = (
                            f"\u63d0\u9192\uff1a{occurrence.content}\n"
                            f"ID: {occurrence.job_id[:8]}\n"
                            "\u8bf7\u56de\u590d\u201c\u6536\u5230\u201d\uff0c\u6216\u53d1\u9001 "
                            f"/higgs remind ack {occurrence.job_id[:8]}"
                        )
                    target = _onebot_reminder_target(occurrence)
                    if target is None:
                        # Official QQ reminders are intentionally blocked until
                        # explicit channel+target binding is implemented.  Never
                        # reinterpret an OpenID as a NapCat QQ number.
                        _log.warning(
                            "reminder_delivery_blocked channel=%s surface=%s",
                            occurrence.origin_channel,
                            occurrence.origin_surface,
                        )
                        await asyncio.to_thread(
                            reminders.finish_occurrence,
                            occurrence.occurrence_key,
                            state="failed",
                        )
                        continue
                    target_conversation = target.conversation_id
                    budget = await asyncio.to_thread(
                        risk_ledger.reserve_send,
                        event_type="reminder",
                        actor_class="owner",
                        account_id=expected_bot_qq or "unknown",
                        conversation_id=target_conversation,
                    )
                    if not budget.allowed or budget.reservation_id is None:
                        continue
                    try:
                        receipt = await onebot_adapter.send_text(
                            target,
                            text,
                            idempotency_key=occurrence.occurrence_key,
                        )
                    except OutboundError as exc:
                        await asyncio.to_thread(
                            risk_ledger.finish_send,
                            budget.reservation_id,
                            outcome="unknown" if exc.delivery_unknown else "failed",
                        )
                        await asyncio.to_thread(
                            reminders.finish_occurrence,
                            occurrence.occurrence_key,
                            state="unknown",
                        )
                    else:
                        if receipt.state is DeliveryState.SENT:
                            await asyncio.to_thread(
                                risk_ledger.finish_send, budget.reservation_id, outcome="sent"
                            )
                            await asyncio.to_thread(
                                reminders.finish_occurrence,
                                occurrence.occurrence_key,
                                state="sent",
                                message_id=receipt.provider_message_id,
                            )
                        else:
                            outcome = (
                                "unknown" if receipt.state is DeliveryState.UNKNOWN else "failed"
                            )
                            await asyncio.to_thread(
                                risk_ledger.finish_send,
                                budget.reservation_id,
                                outcome=outcome,
                            )
                            await asyncio.to_thread(
                                reminders.finish_occurrence,
                                occurrence.occurrence_key,
                                state=outcome,
                            )
            await asyncio.sleep(5)

    async def candidate_review_notification_loop() -> None:
        await asyncio.sleep(60)
        while True:
            if online.snapshot().qq_online and settings.owner_qq:
                counts = await asyncio.to_thread(
                    memory.status_counts,
                    actor=Principal("higgs-runtime", "owner"),
                )
                total = counts["candidate"]
                if await asyncio.to_thread(observations.candidate_notification_due, total):
                    budget = await asyncio.to_thread(
                        risk_ledger.reserve_send,
                        event_type="proactive",
                        actor_class="owner",
                        account_id=expected_bot_qq or "unknown",
                        conversation_id=f"qq:private:owner:{settings.owner_qq}",
                    )
                    if budget.allowed and budget.reservation_id is not None:
                        try:
                            receipt = await onebot_adapter.send_text(
                                OutboundTarget(
                                    channel="qq",
                                    conversation_kind=ConversationKind.PRIVATE,
                                    conversation_id=f"qq:private:owner:{settings.owner_qq}",
                                ),
                                (
                                    f"Higgs 有 {total} 条候选记忆等待审核。\n"
                                    "发送 /higgs memory list candidate 1 查看。"
                                ),
                                idempotency_key=f"memory-candidates:{total // 8}",
                            )
                        except OutboundError as exc:
                            outcome = "unknown" if exc.delivery_unknown else "failed"
                            await asyncio.to_thread(
                                risk_ledger.finish_send,
                                budget.reservation_id,
                                outcome=outcome,
                            )
                        else:
                            if receipt.state is DeliveryState.SENT:
                                await asyncio.to_thread(
                                    risk_ledger.finish_send,
                                    budget.reservation_id,
                                    outcome="sent",
                                )
                                await asyncio.to_thread(observations.mark_candidate_notified, total)
                            else:
                                outcome = (
                                    "unknown"
                                    if receipt.state is DeliveryState.UNKNOWN
                                    else "failed"
                                )
                                await asyncio.to_thread(
                                    risk_ledger.finish_send,
                                    budget.reservation_id,
                                    outcome=outcome,
                                )
            await asyncio.sleep(900)

    online_probe_task = asyncio.create_task(online_probe_loop())
    reminder_task = asyncio.create_task(reminder_loop())
    candidate_notification_task = asyncio.create_task(candidate_review_notification_loop())
    background_tasks: tuple[asyncio.Task[object], ...] = (
        online_probe_task,
        reminder_task,
        candidate_notification_task,
        *((official_supervisor_task,) if official_supervisor_task is not None else ()),
    )
    for background_task in background_tasks:
        background_task.add_done_callback(
            lambda task: task.exception() if not task.cancelled() else None
        )
    health_task = asyncio.create_task(health.run_periodically())
    health_task.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)

    delay = 1.0
    while True:
        try:
            async with websockets.connect(
                settings.onebot_ws_url,
                additional_headers=headers,
                max_size=2 * 1024 * 1024,
                max_queue=64,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
            ) as socket:
                _log.info(
                    "phase2_connected mode=%s model_configured=%s",
                    phase.mode,
                    client is not None,
                )
                delay = 1.0
                await online.set_transport(True)
                try:
                    status = await get_onebot_account_status(
                        settings.onebot_ws_url, settings.onebot_access_token
                    )
                except OutboundError:
                    await online.set_qq_online(False, reason="initial_status_probe_failed")
                else:
                    if not status.online:
                        await online.set_qq_online(False, reason="get_status_offline")
                    elif not status.good:
                        await online.set_qq_online(False, reason="get_status_unhealthy")
                    else:
                        account_ok = not expected_bot_qq or status.account_id == expected_bot_qq
                        await online.set_qq_online(
                            account_ok,
                            reason="get_status_ok" if account_ok else "wrong_qq_account",
                        )
                async for frame in socket:
                    if not isinstance(frame, str):
                        continue
                    try:
                        raw = json.loads(frame)
                        hint = onebot_online_hint(raw)
                        if hint is not None and hint[0] is False:
                            await online.set_qq_online(
                                False,
                                reason=hint[1],
                                health_receipt=False,
                            )

                        if not isinstance(raw, dict) or raw.get("post_type") != "message":
                            continue
                        event = parse_message_event(raw)
                        await route_inbound_event(event, resolve_onebot_reply=True)
                    except (json.JSONDecodeError, OneBotParseError) as exc:
                        _log.warning("phase2_event_rejected type=%s", type(exc).__name__)
                    except Exception as exc:
                        _log.error("phase2_event_failed type=%s", type(exc).__name__)
                await online.set_transport(False)
        except asyncio.CancelledError:
            await online.set_transport(False)
            for background_task in background_tasks:
                background_task.cancel()
            await asyncio.gather(*background_tasks, return_exceptions=True)
            if official_adapter is not None:
                await official_adapter.stop()
            raise
        except Exception as exc:
            await online.set_transport(False)
            _log.warning(
                "phase2_disconnected type=%s retry_seconds=%.1f",
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("listen", nargs="?", default="listen")
    parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(listen())
    except (ConfigError, KeyboardInterrupt) as exc:
        if isinstance(exc, ConfigError):
            print(f"configuration_error: {exc}")
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
