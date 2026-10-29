"""Opt-in Phase 2 runner. Existing `r-agent listen` remains read-only."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from r_agent.access import IngressDecision, IngressPolicy
from r_agent.agenda import AgendaStore
from r_agent.agent_tools import AgentLoop, ToolAudit, ToolRegistry
from r_agent.amap import AmapRouteClient
from r_agent.backup import BackupError, BackupManager
from r_agent.builtin_tools import BuiltinToolDeps, register_builtin_tools
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
from r_agent.group_memory import (
    GroupMemoryService,
    GroupMemorySource,
    ModelGroupMemoryExtractor,
)
from r_agent.group_timeline import GroupTimeline
from r_agent.health import HealthReporter
from r_agent.identity import IdentityStore, Principal
from r_agent.ingest import IngestResult, IngestService
from r_agent.inner_life import InnerLife, InnerLifeScheduler, InnerLifeStore
from r_agent.journal import Journal
from r_agent.memory import MemoryKind, MemoryStore
from r_agent.memory_v2 import MemoryObservationStore, MemoryReconciler
from r_agent.model_client import ModelConfig, ModelError, OpenAICompatibleClient
from r_agent.model_memory_candidates import (
    MODEL_CANDIDATE_DEFAULT_MODE,
    ModelCandidateExtractor,
    ModelCandidateShadowStore,
)
from r_agent.official_processing import OfficialDurableProcessor, OfficialProcessingStore
from r_agent.official_qq import (
    OfficialQQAdapter,
    OfficialQQConfig,
    OfficialQQSidecarAdapter,
)
from r_agent.onebot import OneBotParseError, parse_message_event
from r_agent.onebot_adapter import OneBotAdapter
from r_agent.online_reliability import OnlineState, PushPlusNotifier, onebot_online_hint
from r_agent.operator_control import LiveOperatorControl
from r_agent.owner_commands import OwnerCommandContext, OwnerCommandRouter
from r_agent.passive_memory import PassiveMemoryLearner
from r_agent.persona_bundle import (
    PersonaBundle,
    PersonaBundleError,
    PersonaV2Gate,
    load_persona_bundle,
)
from r_agent.persona_evolution import (
    EvolutionDecision,
    EvolutionSource,
    ModelEvolutionExtractor,
    SelfMemoryService,
    ShadowRunState,
)
from r_agent.phase2_outbound import (
    OutboundError,
    call_onebot_action,
    get_onebot_account_status,
    get_onebot_message_sender,
    get_onebot_quoted_message,
    send_onebot_group_message,
    send_onebot_private_message,
)
from r_agent.phase2_reply import (
    PersonaBrain,
    PreparedReply,
    ReplyAudit,
    ReplyDecision,
    ReplyPlan,
    ReplyPolicy,
)
from r_agent.principal_memory import PersonalMemoryService
from r_agent.principal_memory_intents import (
    parse_personal_memory_intent,
    personal_memory_feedback,
    submit_personal_memory_observation,
)
from r_agent.qq_text import QqTextError, to_qq_plain_text
from r_agent.qzone import (
    QzoneSchedule,
    QzoneScheduler,
    QzoneService,
    QzoneStore,
    register_qzone_tools,
)
from r_agent.recall import RecallLedger
from r_agent.reminders import DueOccurrence, ReminderStore
from r_agent.risk_ledger import RiskLedger, RiskLimits
from r_agent.safety import OutboundSafetyPolicy, SafetyError
from r_agent.server_status import ServerStatusCommand, ServerStatusReader
from r_agent.skills import SkillApprovalStore, default_skill_registry
from r_agent.tool_governance import ToolGovernance
from r_agent.transport import (
    DeliveryReceipt,
    DeliveryState,
    DeliveryTarget,
    DeliveryTargetError,
    OutboundTarget,
    TransportUnavailable,
)
from r_agent.transport_state import TransportStateStore
from r_agent.vector_memory import MemoryVectorStore
from r_agent.web_providers import SafePageReader, SearxngSearch, ZhipuWebSearch
from r_agent.willingness import (
    THUMBS_UP_FACE_ID,
    InterestGate,
    ProactiveChatter,
    is_react,
    is_skip,
)

_log = logging.getLogger(__name__)

ONLINE_PROBE_INTERVAL_SECONDS = 30.0
ONLINE_PROBE_TIMEOUT_SECONDS = 20.0
ONLINE_PROBE_MAX_DETECTION_SECONDS = ONLINE_PROBE_INTERVAL_SECONDS + ONLINE_PROBE_TIMEOUT_SECONDS
_SHADOW_PARSER_FAILURE_REASONS = frozenset(
    {
        "invalid_json_envelope",
        "markdown_not_allowed",
        "invalid_json",
        "invalid_top_level_schema",
        "unsupported_schema_version",
        "invalid_candidate_count",
        "invalid_candidate_schema",
    }
)


async def reconcile_group_public_memory(
    event: InboundEvent,
    *,
    principal: Principal,
    service: GroupMemoryService,
    extractor: ModelGroupMemoryExtractor | None,
    final_sent: bool,
) -> int:
    """Queue public-group evidence only after a reply is durably SENT.

    The final delivery state is passed explicitly so UNKNOWN/FAILED replies and
    non-group events cannot accidentally create group-memory evidence.  This
    helper is intentionally content-free in its logs and keeps the model lane
    independent from the ordinary principal-memory reconciler.
    """

    if (
        not final_sent
        or extractor is None
        or not service.enabled
        or event.channel.casefold() != "qq_official"
        or event.conversation_kind is not ConversationKind.GROUP
        or not event.group_id
        or not event.mentioned
    ):
        return 0
    try:
        results = await extractor.extract(
            GroupMemorySource(
                group_id=event.group_id,
                message_id=event.message_id,
                principal_role=principal.role,
                text=event.text,
            )
        )
        submitted = 0
        for parsed in results:
            candidate = parsed.candidate
            if candidate is None or parsed.decision.value != "waiting_corroboration":
                continue
            outcome = await asyncio.to_thread(
                service.submit_event_evidence,
                event,
                candidate=candidate,
                member_role=principal.role,
            )
            submitted += 1
            _log.info(
                "group_memory_evidence decision=%s supports=%d",
                outcome.decision.value,
                outcome.support_count,
            )
        if submitted == 0:
            _log.info("group_memory_evidence decision=none supports=0")
        return submitted
    except Exception as exc:
        # Group learning is optional and must never turn a delivered reply
        # into a retry.  Log only the exception type; event/member/content
        # identifiers are intentionally absent.
        _log.warning("group_memory_evolution_failed type=%s", type(exc).__name__)
        return 0


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
    self_memory_mode: str
    self_memory_schema_v4_enabled: bool
    personal_memory_mode: str
    personal_memory_schema_v5_enabled: bool
    group_memory_enabled: bool
    identity_schema_v2_enabled: bool
    backup_dir: Path
    backup_interval_minutes: int
    backup_retention: int
    daily_plan_mode: str
    daily_plan_drafts_per_day: int
    daily_plan_map_optimizations_per_day: int
    ordinary_task_mode: str = "off"
    ordinary_task_drafts_per_day: int = 10
    ordinary_task_reminders_per_day: int = 20
    ordinary_task_active_reminders: int = 10
    group_timeline_enabled: bool = True
    group_timeline_limit: int = 30
    group_timeline_retention_days: int = 7
    group_reply_quote: str = "auto"
    group_reply_mention: bool = False
    agent_tools_enabled: bool = True
    agent_max_steps: int = 4
    agent_user_daily_tool_calls: int = 30
    web_search_provider: str = "off"
    web_search_endpoint: str = ""
    web_read_enabled: bool = False
    qzone_enabled: bool = True
    qzone_mode: str = "confirm"
    qzone_posts_per_day: int = 1
    qzone_active_start_hour: int = 9
    qzone_active_end_hour: int = 23
    qzone_visibility: int = 1
    qzone_browse_enabled: bool = False
    qzone_browse_interval_minutes: int = 180
    qzone_daily_likes: int = 20
    qzone_daily_comments: int = 6
    inner_life_enabled: bool = True
    inner_diary_hour: int = 23
    inner_diary_minute: int = 30
    inner_impression_interval_minutes: int = 60
    interest_enabled: bool = True
    interest_groups: frozenset[str] = frozenset()
    interest_frequency: float = 1.0
    interest_hourly_cap: int = 6
    interest_daily_cap: int = 30
    interest_min_gap_seconds: float = 90.0
    proactive_groups: frozenset[str] = frozenset()
    proactive_idle_minutes: int = 90
    proactive_daily_cap: int = 3
    proactive_start_hour: int = 10
    proactive_end_hour: int = 23
    typing_status_enabled: bool = True


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
    ordinary_task_mode = _value("R_AGENT_OFFICIAL_QQ_ORDINARY_TASK_MODE", "off").casefold()
    if ordinary_task_mode not in {"off", "shadow", "live"}:
        raise ConfigError("R_AGENT_OFFICIAL_QQ_ORDINARY_TASK_MODE must be off, shadow, or live")
    if ordinary_task_mode == "live" and mode != "live":
        raise ConfigError("live ordinary tasks require R_AGENT_REPLY_MODE=live")
    self_memory_mode = _value("R_AGENT_SELF_MEMORY_MODE", "off").casefold()
    if self_memory_mode not in {"off", "shadow", "autonomous-low-risk"}:
        raise ConfigError("R_AGENT_SELF_MEMORY_MODE must be off, shadow, or autonomous-low-risk")
    self_memory_schema_v4_enabled = _boolean(
        "R_AGENT_SELF_MEMORY_SCHEMA_V4_ENABLED",
        False,
    )
    if self_memory_mode != "off" and not self_memory_schema_v4_enabled:
        raise ConfigError("self-memory modes require explicit schema v4 enablement")
    personal_memory_mode = _value("R_AGENT_PERSONAL_MEMORY_MODE", "off").casefold()
    if personal_memory_mode not in {"off", "shadow", "active"}:
        raise ConfigError("R_AGENT_PERSONAL_MEMORY_MODE must be off, shadow, or active")
    personal_memory_schema_v5_enabled = _boolean(
        "R_AGENT_PERSONAL_MEMORY_SCHEMA_V5_ENABLED",
        False,
    )
    if personal_memory_mode != "off" and not personal_memory_schema_v5_enabled:
        raise ConfigError("personal-memory modes require explicit schema v5 enablement")
    group_memory_enabled = _boolean("R_AGENT_GROUP_MEMORY_ENABLED", False)
    web_search_provider = _value("R_AGENT_WEB_SEARCH_PROVIDER", "off").casefold()
    if web_search_provider not in {"off", "zhipu", "searxng"}:
        raise ConfigError("R_AGENT_WEB_SEARCH_PROVIDER must be off, zhipu, or searxng")
    web_search_endpoint = _value("R_AGENT_WEB_SEARCH_ENDPOINT")
    if web_search_provider == "searxng" and not web_search_endpoint.startswith(
        ("http://", "https://")
    ):
        raise ConfigError("searxng search requires R_AGENT_WEB_SEARCH_ENDPOINT")
    qzone_mode = _value("R_AGENT_QZONE_MODE", "confirm").casefold()
    if qzone_mode not in {"off", "confirm", "auto"}:
        raise ConfigError("R_AGENT_QZONE_MODE must be off, confirm, or auto")
    qzone_hours = _value("R_AGENT_QZONE_ACTIVE_HOURS", "9-23")
    try:
        start_text, end_text = qzone_hours.split("-", 1)
        qzone_start, qzone_end = int(start_text), int(end_text)
    except ValueError as exc:
        raise ConfigError("R_AGENT_QZONE_ACTIVE_HOURS must look like 9-23") from exc
    if not 0 <= qzone_start < qzone_end <= 24:
        raise ConfigError("R_AGENT_QZONE_ACTIVE_HOURS must look like 9-23")
    qzone_visibility = _value("R_AGENT_QZONE_VISIBILITY", "1")
    if qzone_visibility not in {"1", "4", "64"}:
        raise ConfigError("R_AGENT_QZONE_VISIBILITY must be 1, 4, or 64")
    interest_raw = _value("R_AGENT_INTEREST_GROUPS")
    interest_groups = (
        parse_qq_set(interest_raw, name="R_AGENT_INTEREST_GROUPS") if interest_raw else groups
    )
    if not interest_groups.issubset(groups):
        raise ConfigError("interest groups must be a subset of reply groups")
    proactive_groups = parse_qq_set(
        _value("R_AGENT_PROACTIVE_GROUPS"), name="R_AGENT_PROACTIVE_GROUPS"
    )
    if not proactive_groups.issubset(groups):
        raise ConfigError("proactive groups must be a subset of reply groups")
    proactive_hours = _value("R_AGENT_PROACTIVE_ACTIVE_HOURS", "10-23")
    try:
        p_start_text, p_end_text = proactive_hours.split("-", 1)
        proactive_start, proactive_end = int(p_start_text), int(p_end_text)
    except ValueError as exc:
        raise ConfigError("R_AGENT_PROACTIVE_ACTIVE_HOURS must look like 10-23") from exc
    if not 0 <= proactive_start < proactive_end <= 24:
        raise ConfigError("R_AGENT_PROACTIVE_ACTIVE_HOURS must look like 10-23")
    diary_time = _value("R_AGENT_INNER_DIARY_TIME", "23:30")
    try:
        diary_hour_text, diary_minute_text = diary_time.split(":", 1)
        diary_hour, diary_minute = int(diary_hour_text), int(diary_minute_text)
    except ValueError as exc:
        raise ConfigError("R_AGENT_INNER_DIARY_TIME must look like 23:30") from exc
    if not (0 <= diary_hour <= 23 and 0 <= diary_minute <= 59):
        raise ConfigError("R_AGENT_INNER_DIARY_TIME must look like 23:30")
    group_reply_quote = _value("R_AGENT_GROUP_REPLY_QUOTE", "auto").casefold()
    if group_reply_quote not in {"off", "auto", "always"}:
        raise ConfigError("R_AGENT_GROUP_REPLY_QUOTE must be off, auto, or always")
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
        self_memory_mode=self_memory_mode,
        self_memory_schema_v4_enabled=self_memory_schema_v4_enabled,
        personal_memory_mode=personal_memory_mode,
        personal_memory_schema_v5_enabled=personal_memory_schema_v5_enabled,
        group_memory_enabled=group_memory_enabled,
        identity_schema_v2_enabled=_boolean("R_AGENT_IDENTITY_SCHEMA_V2_ENABLED", False),
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
        ordinary_task_mode=ordinary_task_mode,
        ordinary_task_drafts_per_day=bounded_int(
            "R_AGENT_OFFICIAL_QQ_ORDINARY_TASK_DRAFTS_PER_DAY", "10", 1, 50
        ),
        ordinary_task_reminders_per_day=bounded_int(
            "R_AGENT_OFFICIAL_QQ_ORDINARY_TASK_REMINDERS_PER_DAY", "20", 1, 100
        ),
        ordinary_task_active_reminders=bounded_int(
            "R_AGENT_OFFICIAL_QQ_ORDINARY_TASK_ACTIVE_REMINDERS", "10", 1, 100
        ),
        group_timeline_enabled=_boolean("R_AGENT_GROUP_TIMELINE_ENABLED", True),
        group_timeline_limit=bounded_int("R_AGENT_GROUP_TIMELINE_LIMIT", "30", 5, 100),
        group_timeline_retention_days=bounded_int(
            "R_AGENT_GROUP_TIMELINE_RETENTION_DAYS", "7", 1, 90
        ),
        group_reply_quote=group_reply_quote,
        group_reply_mention=_boolean("R_AGENT_GROUP_REPLY_MENTION", False),
        agent_tools_enabled=_boolean("R_AGENT_AGENT_TOOLS_ENABLED", True),
        agent_max_steps=bounded_int("R_AGENT_AGENT_MAX_STEPS", "4", 1, 8),
        agent_user_daily_tool_calls=bounded_int(
            "R_AGENT_AGENT_USER_DAILY_TOOL_CALLS", "30", 0, 1000
        ),
        web_search_provider=web_search_provider,
        web_search_endpoint=web_search_endpoint,
        web_read_enabled=_boolean("R_AGENT_WEB_READ_ENABLED", False),
        qzone_enabled=_boolean("R_AGENT_QZONE_ENABLED", True),
        qzone_mode=qzone_mode,
        qzone_posts_per_day=bounded_int("R_AGENT_QZONE_POSTS_PER_DAY", "1", 1, 5),
        qzone_active_start_hour=qzone_start,
        qzone_active_end_hour=qzone_end,
        qzone_visibility=int(qzone_visibility),
        qzone_browse_enabled=_boolean("R_AGENT_QZONE_BROWSE_ENABLED", False),
        qzone_browse_interval_minutes=bounded_int(
            "R_AGENT_QZONE_BROWSE_INTERVAL_MINUTES", "180", 30, 1440
        ),
        qzone_daily_likes=bounded_int("R_AGENT_QZONE_DAILY_LIKES", "20", 0, 100),
        qzone_daily_comments=bounded_int("R_AGENT_QZONE_DAILY_COMMENTS", "6", 0, 30),
        inner_life_enabled=_boolean("R_AGENT_INNER_LIFE_ENABLED", True),
        inner_diary_hour=diary_hour,
        inner_diary_minute=diary_minute,
        inner_impression_interval_minutes=bounded_int(
            "R_AGENT_INNER_IMPRESSION_INTERVAL_MINUTES", "60", 10, 1440
        ),
        interest_enabled=_boolean("R_AGENT_INTEREST_ENABLED", True),
        interest_groups=interest_groups,
        interest_frequency=bounded_float("R_AGENT_INTEREST_FREQUENCY", "1.0", 0.0, 3.0),
        interest_hourly_cap=bounded_int("R_AGENT_INTEREST_HOURLY_CAP", "6", 0, 60),
        interest_daily_cap=bounded_int("R_AGENT_INTEREST_DAILY_CAP", "30", 0, 300),
        interest_min_gap_seconds=bounded_float(
            "R_AGENT_INTEREST_MIN_GAP_SECONDS", "90", 0.0, 3600.0
        ),
        proactive_groups=proactive_groups,
        proactive_idle_minutes=bounded_int("R_AGENT_PROACTIVE_IDLE_MINUTES", "90", 10, 1440),
        proactive_daily_cap=bounded_int("R_AGENT_PROACTIVE_DAILY_CAP", "3", 0, 20),
        proactive_start_hour=proactive_start,
        proactive_end_hour=proactive_end,
        typing_status_enabled=_boolean("R_AGENT_TYPING_STATUS_ENABLED", True),
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


def _persona_v2() -> tuple[PersonaV2Gate, PersonaBundle | None]:
    """Load Persona V2 only when its owner-only rollout flag is enabled."""

    try:
        gate = PersonaV2Gate.from_env()
        return gate, load_persona_bundle() if gate.enabled else None
    except PersonaBundleError as exc:
        raise ConfigError(f"invalid Persona V2 configuration: {exc}") from exc


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


async def prepare_reply(
    *,
    event: InboundEvent,
    result: IngestResult,
    policy: ReplyPolicy,
    brain: PersonaBrain,
    safety: OutboundSafetyPolicy | None = None,
    breaker: ConversationCircuitBreaker | None = None,
    owner_qq: str | None = None,
    qq_online: bool = True,
    risk_ledger: RiskLedger | None = None,
    risk_idempotency_key: str | None = None,
    response_override: str | None = None,
) -> PreparedReply:
    """Prepare an exact reply without crossing the outbound provider boundary."""
    decision = policy.gate(event, result)
    if decision not in {ReplyDecision.DRAFTED, ReplyDecision.SENT}:
        return PreparedReply(decision)
    if not qq_online:
        return PreparedReply(ReplyDecision.QQ_OFFLINE)
    source_id = event.sender_id if event.conversation_kind is ConversationKind.GROUP else None
    if breaker is not None:
        guard = await asyncio.to_thread(
            breaker.check_and_reserve,
            event.conversation_id,
            is_owner=event.sender_id == owner_qq,
            source_id=source_id,
            idempotency_key=risk_idempotency_key,
        )
        if not guard.allowed:
            return PreparedReply(ReplyDecision.CIRCUIT_BREAKER)
    reservation_id: int | None = None
    if decision is ReplyDecision.SENT and risk_ledger is not None:
        budget = await asyncio.to_thread(
            risk_ledger.reserve_send,
            event_type="reply",
            actor_class="owner" if event.sender_id == owner_qq else "non_owner",
            account_id=event.account_id,
            conversation_id=event.conversation_id,
            source_id=source_id,
            idempotency_key=risk_idempotency_key,
        )
        if not budget.allowed:
            return PreparedReply(ReplyDecision.GLOBAL_RATE_LIMITED)
        reservation_id = budget.reservation_id
    try:
        raw_text = response_override if response_override is not None else await brain.draft(event)
        if event.interjection and (is_skip(raw_text) or is_react(raw_text)):
            if risk_ledger is not None and reservation_id is not None:
                await asyncio.to_thread(risk_ledger.finish_send, reservation_id, outcome="failed")
            decision = ReplyDecision.REACTED if is_react(raw_text) else ReplyDecision.SKIPPED
            return PreparedReply(decision)
        text = to_qq_plain_text(raw_text)
    except (ModelError, QqTextError):
        if risk_ledger is not None and reservation_id is not None:
            await asyncio.to_thread(risk_ledger.finish_send, reservation_id, outcome="failed")
        return PreparedReply(ReplyDecision.MODEL_FAILED)

    if safety is not None and not safety.evaluate(text).allowed:
        if risk_ledger is not None and reservation_id is not None:
            await asyncio.to_thread(risk_ledger.finish_send, reservation_id, outcome="failed")
        return PreparedReply(ReplyDecision.SENSITIVE_BLOCKED)
    policy.mark_generated(event)
    if decision is ReplyDecision.DRAFTED:
        return PreparedReply(ReplyDecision.DRAFTED, text)
    return PreparedReply(ReplyDecision.SENT, text, reservation_id)


async def deliver_prepared_reply(
    *,
    event: InboundEvent,
    prepared: PreparedReply,
    sender: Callable[[InboundEvent, str], Awaitable[DeliveryReceipt]],
    risk_ledger: RiskLedger | None = None,
    retry_transport_unavailable: bool = False,
    on_sent: Callable[[InboundEvent, str, DeliveryReceipt], Awaitable[None]] | None = None,
) -> ReplyPlan:
    """Deliver one persisted preparation; the transport owns provider idempotency."""
    if not prepared.requires_delivery:
        return ReplyPlan(prepared.decision, prepared.text)
    if prepared.text is None:
        raise RuntimeError("a sendable prepared reply requires text")
    try:
        receipt = await sender(event, prepared.text)
        if receipt.state is not DeliveryState.SENT:
            raise OutboundError(
                "transport delivery was not acknowledged",
                delivery_unknown=receipt.state is DeliveryState.UNKNOWN,
            )
    except OutboundError as exc:
        if risk_ledger is not None and prepared.reservation_id is not None:
            outcome = "unknown" if exc.delivery_unknown else "failed"
            await asyncio.to_thread(
                risk_ledger.finish_send, prepared.reservation_id, outcome=outcome
            )
        return ReplyPlan(ReplyDecision.SEND_FAILED, prepared.text)
    except TransportUnavailable:
        if retry_transport_unavailable:
            raise
        if risk_ledger is not None and prepared.reservation_id is not None:
            await asyncio.to_thread(
                risk_ledger.finish_send, prepared.reservation_id, outcome="failed"
            )
        return ReplyPlan(ReplyDecision.SEND_FAILED, prepared.text)
    if on_sent is not None:
        try:
            await on_sent(event, prepared.text, receipt)
        except Exception as exc:
            # The provider has already acknowledged SENT.  Observation and
            # memory are best-effort post-send lanes and must never turn that
            # durable outcome back into a retryable send.
            _log.warning("post_send_observer_failed type=%s", type(exc).__name__)
    if risk_ledger is not None and prepared.reservation_id is not None:
        try:
            await asyncio.to_thread(
                risk_ledger.finish_send,
                prepared.reservation_id,
                outcome="sent",
            )
        except Exception as exc:
            _log.error("post_send_risk_finalize_failed type=%s", type(exc).__name__)
    return ReplyPlan(ReplyDecision.SENT, prepared.text)


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
    risk_idempotency_key: str | None = None,
    on_sent: Callable[[InboundEvent, str, DeliveryReceipt], Awaitable[None]] | None = None,
    response_override: str | None = None,
) -> ReplyPlan:
    """Backward-compatible one-shot pipeline used by the OneBot listener."""
    prepared = await prepare_reply(
        event=event,
        result=result,
        policy=policy,
        brain=brain,
        safety=safety,
        breaker=breaker,
        owner_qq=owner_qq,
        qq_online=qq_online,
        risk_ledger=risk_ledger,
        risk_idempotency_key=risk_idempotency_key,
        response_override=response_override,
    )
    return await deliver_prepared_reply(
        event=event,
        prepared=prepared,
        sender=sender,
        risk_ledger=risk_ledger,
        on_sent=on_sent,
    )


def _onebot_reminder_target(occurrence: DueOccurrence) -> OutboundTarget | None:
    """Build a NapCat target only from the explicit persisted delivery binding."""

    try:
        binding = DeliveryTarget(
            occurrence.delivery_channel,
            occurrence.delivery_account_id,
            occurrence.delivery_target_id,
            occurrence.delivery_surface,
        )
    except DeliveryTargetError:
        return None
    if binding.channel != "qq":
        return None
    if binding.surface == "group":
        kind = ConversationKind.GROUP
    elif binding.surface == "private":
        kind = ConversationKind.PRIVATE
    else:
        return None
    return OutboundTarget(
        channel="qq",
        conversation_kind=kind,
        conversation_id=binding.conversation_id,
    )


def _official_reminder_target(
    occurrence: DueOccurrence,
    *,
    owner_openid: str | None,
    account_id: str | None,
    owner_proactive_enabled: bool = False,
    allowed_private_openids: frozenset[str] | None = None,
    ordinary_proactive_enabled: bool = False,
) -> OutboundTarget | None:
    """Build a bound official C2C target for owner or ordinary delivery."""

    try:
        binding = DeliveryTarget(
            occurrence.delivery_channel,
            occurrence.delivery_account_id,
            occurrence.delivery_target_id,
            occurrence.delivery_surface,
        )
    except DeliveryTargetError:
        return None
    if (
        binding.channel != "qq_official"
        or binding.surface != "private"
        or not account_id
        or binding.bot_account != account_id
    ):
        return None
    if binding.target_id == owner_openid:
        if not owner_proactive_enabled:
            return None
    elif (
        not ordinary_proactive_enabled
        or allowed_private_openids is None
        or binding.target_id not in allowed_private_openids
    ):
        return None
    return OutboundTarget(
        channel="qq_official",
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id=binding.conversation_id,
    )


def _official_event_quiet_seconds(
    event: InboundEvent,
    control: LiveOperatorControl,
) -> float:
    """Read the live debounce value instead of the startup configuration."""

    return control.debounce_seconds_for(private=event.conversation_kind is ConversationKind.PRIVATE)


def _build_official_adapter(
    config: OfficialQQConfig,
    *,
    event_handler: Callable[[InboundEvent], Awaitable[None]],
    data_dir: Path,
    transport_state: TransportStateStore | None,
) -> OfficialQQAdapter | OfficialQQSidecarAdapter:
    if config.transport == "sidecar":
        return OfficialQQSidecarAdapter(
            config,
            event_handler=event_handler,
            transport_state=transport_state,
        )
    return OfficialQQAdapter(
        config,
        event_handler=event_handler,
        data_dir=data_dir,
        transport_state=transport_state,
    )


async def listen() -> None:
    import websockets

    env_path = _env_path()
    settings = Settings.from_env(env_file=env_path, require_shadow=False)
    phase = _phase2_settings(settings)
    official_config = OfficialQQConfig.from_env()
    official_owner_openid = official_config.active_owner_openid
    official_private_openids = official_config.active_private_openids
    official_group_openids = official_config.active_group_openids
    persona_v2_gate, persona_bundle = _persona_v2()
    if persona_v2_gate.enabled and official_owner_openid is None:
        raise ConfigError("Persona V2 rollout requires the bound official owner OpenID")
    if persona_v2_gate.ordinary_private_enabled and not official_config.ordinary_private_enabled:
        raise ConfigError("ordinary Persona V2 requires the ordinary official C2C gate")
    if persona_v2_gate.group_enabled and not official_config.group_enabled:
        raise ConfigError("group Persona V2 requires the official group gate")
    if phase.ordinary_task_mode != "off" and not official_config.ordinary_private_enabled:
        raise ConfigError(
            "ordinary task modes require R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED=true"
        )
    if (
        official_config.ordinary_private_enabled or official_config.group_enabled
    ) and not phase.identity_schema_v2_enabled:
        raise ConfigError("ordinary official audiences require identity schema v2")
    embeddings = _embedding_client(enabled=phase.embedding_enabled, phase=phase)
    safety = _safety_policy(phase)
    client = _model_client(
        required=(
            phase.mode in {"draft", "live"}
            or phase.self_memory_mode != "off"
            or phase.group_memory_enabled
        )
    )

    service = IngestService(
        policy=IngressPolicy(
            enabled=settings.ingest_enabled,
            owner_qq=settings.owner_qq,
            allowed_private_qqs=settings.allowed_private_qqs,
            allowed_groups=settings.allowed_groups,
            owner_ids=frozenset(
                value for value in (settings.owner_qq, official_owner_openid) if value is not None
            ),
            additional_private_ids=official_private_openids,
            additional_group_ids=official_group_openids,
        ),
        identities=IdentityStore(
            settings.data_dir / "identity.sqlite",
            owner_qq=settings.owner_qq,
            owner_identities=(
                (("qq_official", official_owner_openid),) if official_owner_openid else ()
            ),
            account_scoped_official_enabled=phase.identity_schema_v2_enabled,
        ),
        journal=Journal(settings.data_dir / "journal.sqlite"),
    )
    service.initialize()
    history = ConversationStore(settings.data_dir / "conversation.sqlite")
    history.initialize()
    await asyncio.to_thread(history.purge_expired, settings.journal_retention_days)
    memory = MemoryStore(settings.data_dir / "memory.sqlite")
    memory.initialize(
        self_memory_v4=phase.self_memory_schema_v4_enabled,
        personal_memory_v5=phase.personal_memory_schema_v5_enabled,
    )
    self_memory = (
        SelfMemoryService(memory, mode=phase.self_memory_mode)
        if phase.self_memory_schema_v4_enabled
        else None
    )
    personal_memory = PersonalMemoryService(memory, mode=phase.personal_memory_mode)
    group_memory = GroupMemoryService(memory, enabled=phase.group_memory_enabled)
    if phase.group_memory_enabled:
        group_memory.initialize()
    group_memory_extractor = (
        ModelGroupMemoryExtractor(client)
        if phase.group_memory_enabled and client is not None
        else None
    )
    evolution_extractor = (
        ModelEvolutionExtractor(client)
        if phase.self_memory_mode != "off" and client is not None
        else None
    )
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
    official_processing = OfficialProcessingStore(settings.data_dir / "official_processing.sqlite")
    official_processing.initialize()
    await asyncio.to_thread(
        official_processing.purge_completed,
        before_ms=int(time.time() * 1000) - settings.journal_retention_days * 86_400_000,
    )
    tool_governance = ToolGovernance(audit_path=settings.data_dir / "tool_audit.sqlite")
    server_status = ServerStatusCommand(tool_governance, ServerStatusReader())
    policy = ReplyPolicy(
        mode=phase.mode,
        private_users=phase.private_users.union(
            {settings.owner_qq} if settings.owner_qq else (),
            official_private_openids,
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
    group_timeline: GroupTimeline | None = None
    if phase.group_timeline_enabled:
        group_timeline = GroupTimeline(
            settings.data_dir / "group_timeline.sqlite",
            retention_days=phase.group_timeline_retention_days,
        )
        group_timeline.initialize()
        await asyncio.to_thread(group_timeline.purge_expired)
    qzone_service: QzoneService | None = None
    context_providers: list = []
    if phase.qzone_enabled:
        qzone_store = QzoneStore(settings.data_dir / "qzone.sqlite")
        qzone_store.initialize()

        async def qzone_action(action: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
            return await call_onebot_action(
                settings.onebot_ws_url,
                settings.onebot_access_token,
                action=action,
                params=params,
                echo=f"r-agent:qzone:{action}:{uuid.uuid4().hex[:12]}",
                max_size=4 * 1024 * 1024,
            )

        async def qzone_notify_owner(text: str) -> None:
            if settings.owner_qq is None:
                return
            await send_onebot_private_message(
                settings.onebot_ws_url,
                settings.onebot_access_token,
                user_id=settings.owner_qq,
                text=text[:2000],
                idempotency_key=f"qzone-{uuid.uuid4().hex[:16]}",
            )

        qzone_service = QzoneService(
            store=qzone_store,
            call_action=qzone_action,
            client=client,
            persona=persona_bundle.render() if persona_bundle is not None else persona,
            safety=safety,
            notify_owner=qzone_notify_owner,
            bot_account_id=_value("R_AGENT_EXPECTED_BOT_QQ") or None,
            visibility=phase.qzone_visibility,
        )
        _qzone = qzone_service

        def qzone_context(_event: InboundEvent, _principal_id: str):
            lines = _qzone.context_lines(3)
            return ("你最近在 QQ 空间发过的说说（你自己的经历）", lines) if lines else None

        context_providers.append(qzone_context)
    inner_life: InnerLife | None = None
    if phase.inner_life_enabled and client is not None:
        inner_store = InnerLifeStore(settings.data_dir / "inner_life.sqlite")
        inner_store.initialize()

        async def inner_extra_material() -> str:
            if qzone_service is None:
                return ""
            posts = qzone_service.context_lines(2)
            return ("今天前后发过的说说：\n" + "\n".join(posts)) if posts else ""

        inner_life = InnerLife(
            store=inner_store,
            timeline=group_timeline,
            client=client,
            persona=persona_bundle.render() if persona_bundle is not None else persona,
            owner_ids=frozenset(value for value in (settings.owner_qq,) if value is not None),
            safety=safety,
            extra_material=inner_extra_material,
        )
        context_providers.append(inner_life.self_context)
        context_providers.append(inner_life.people_context)
        if qzone_service is not None:
            qzone_service.material = inner_life.material
    context_builder = ContextBuilder(
        context_providers=tuple(context_providers),
        history=history,
        memory=memory,
        recall=recall,
        persona=persona,
        persona_bundle=persona_bundle,
        self_memory=self_memory,
        group_memory=group_memory,
        history_limit=phase.history_turns,
        memory_limit=phase.memory_items,
        vectors=vectors,
        history_outcome="sent" if phase.mode == "live" else "drafted",
        group_timeline=group_timeline,
        owner_ids=frozenset(value for value in (settings.owner_qq,) if value is not None),
        timeline_limit=phase.group_timeline_limit,
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
        personal_memory_handler=(
            (
                lambda observation: submit_personal_memory_observation(
                    observation,
                    service=personal_memory,
                )
            )
            if phase.personal_memory_mode != "off"
            else None
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
        official_transport_state=(official_transport_state if official_config.enabled else None),
        server_status=server_status,
        model_candidate_shadow_store=model_candidate_store,
        tool_governance=tool_governance,
        self_memory=self_memory,
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
            ordinary_mode=phase.ordinary_task_mode,
            ordinary_proactive_enabled=official_config.ordinary_proactive_enabled,
            ordinary_drafts_per_day=phase.ordinary_task_drafts_per_day,
            ordinary_reminders_per_day=phase.ordinary_task_reminders_per_day,
            ordinary_active_reminders=phase.ordinary_task_active_reminders,
        ),
        model_client=client,
        amap=AmapRouteClient(amap_key) if amap_key else None,
        official_proactive_enabled=official_config.proactive_enabled,
    )
    agent_loop: AgentLoop | None = None
    if phase.agent_tools_enabled and client is not None:
        tool_registry = ToolRegistry()
        web_search = None
        if phase.web_search_provider == "zhipu":
            web_search = ZhipuWebSearch(
                api_key=_value("R_AGENT_MODEL_API_KEY"),
                base_url=_value("R_AGENT_MODEL_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
            )
        elif phase.web_search_provider == "searxng":
            web_search = SearxngSearch(endpoint=phase.web_search_endpoint)
        tool_deps = BuiltinToolDeps(
            memory=memory,
            reminders=reminders,
            group_timeline=group_timeline,
            owner_ids=frozenset(value for value in (settings.owner_qq,) if value is not None),
            web_search=web_search,
            web_reader=SafePageReader() if phase.web_read_enabled else None,
        )
        register_builtin_tools(tool_registry, tool_deps)
        if qzone_service is not None:
            register_qzone_tools(tool_registry, qzone_service)
        agent_audit = ToolAudit(settings.data_dir / "agent_tools.sqlite")
        agent_audit.initialize()
        agent_loop = AgentLoop(
            client=client,
            registry=tool_registry,
            audit=agent_audit,
            max_steps=phase.agent_max_steps,
            user_daily_budget=phase.agent_user_daily_tool_calls,
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
        official_proactive_enabled=official_config.proactive_enabled,
        ordinary_task_mode=phase.ordinary_task_mode,
        ordinary_proactive_enabled=official_config.ordinary_proactive_enabled,
        ordinary_reminders_per_day=phase.ordinary_task_reminders_per_day,
        ordinary_active_reminders=phase.ordinary_task_active_reminders,
        persona_bundle=persona_bundle,
        persona_v2_gate=persona_v2_gate,
        official_owner_id=official_owner_openid,
        agent=agent_loop,
        qzone=qzone_service,
        owner_async_commands=(
            (("/higgs inner", inner_life.handle_command),) if inner_life is not None else ()
        ),
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

    official_adapter: OfficialQQAdapter | OfficialQQSidecarAdapter | None = None
    official_supervisor_task: asyncio.Task[None] | None = None
    official_processing_task: asyncio.Task[None] | None = None

    async def sender(event: InboundEvent, text: str) -> DeliveryReceipt:
        if event.channel == "qq_official":
            if official_adapter is None or not official_config.reply_enabled:
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
        quote = False
        if event.conversation_kind is ConversationKind.GROUP:
            if phase.group_reply_quote == "always":
                quote = True
            elif phase.group_reply_quote == "auto" and group_timeline is not None:
                # Quote when other members spoke after the question, so the
                # answer visibly lands on the right person.
                try:
                    quote = (
                        await asyncio.to_thread(
                            group_timeline.others_after, event, sender_id=event.sender_id
                        )
                        > 0
                    )
                except Exception as exc:
                    _log.warning("group_timeline_quote_check_failed type=%s", type(exc).__name__)
        return await onebot_adapter.send_reply(
            event,
            text,
            quote=quote,
            mention=phase.group_reply_mention,
        )

    async def observe_sent_reply(
        event: InboundEvent,
        text: str,
        receipt: DeliveryReceipt,
    ) -> None:
        if (
            group_timeline is not None
            and event.channel == "qq"
            and event.conversation_kind is ConversationKind.GROUP
        ):
            try:
                await asyncio.to_thread(
                    group_timeline.record_outbound,
                    event,
                    text=text,
                    provider_message_id=receipt.provider_message_id,
                )
            except Exception as exc:
                _log.warning("group_timeline_outbound_failed type=%s", type(exc).__name__)
        if self_memory is None or phase.self_memory_mode == "off":
            return
        try:
            principal = await asyncio.to_thread(
                service.identities.resolve_event,
                event,
            )
            await asyncio.to_thread(
                self_memory.record_delivery,
                receipt=receipt,
                text=text,
                account_id=event.account_id,
                conversation_id=event.conversation_id,
                principal_id=principal.principal_id,
                now_ms=event.occurred_at_ms,
            )
        except Exception as exc:
            _log.warning("self_memory_sent_observation_failed type=%s", type(exc).__name__)

    async def reconcile_self_evolution(
        event: InboundEvent,
        *,
        principal: Principal,
        reply_text: str,
    ) -> None:
        if self_memory is None or evolution_extractor is None:
            return
        key = f"reply:{event.channel}:{event.account_id}:{event.message_id}"
        if phase.self_memory_mode == "shadow":

            async def run_shadow_lane(
                *,
                run_key: str,
                lane: MemoryKind,
                source_builder: Callable[[], Awaitable[tuple[object, object | None]]],
            ) -> None:
                """Run one extractor lane behind a durable, hard-gated receipt."""

                run = None
                observation = None
                candidate_count = 0
                rejected_count = 0
                quarantined_count = 0
                try:
                    run = await asyncio.to_thread(
                        self_memory.begin_shadow_run,
                        run_key=run_key,
                        lane=lane,
                        input_text=reply_text if lane is MemoryKind.SELF_STANCE else event.text,
                        now_ms=event.occurred_at_ms,
                    )
                    if run.state is ShadowRunState.COMPLETE:
                        return
                    source, observation = await source_builder()
                    results = await evolution_extractor.extract(
                        source,
                        allowed_kind=lane,
                    )
                    for parsed in results:
                        if parsed.reason in _SHADOW_PARSER_FAILURE_REASONS:
                            raise ValueError("shadow parser rejected model envelope")
                        if parsed.candidate is None:
                            if parsed.decision is EvolutionDecision.QUARANTINED:
                                quarantined_count += 1
                            elif parsed.decision is EvolutionDecision.REJECTED:
                                rejected_count += 1
                            continue
                        if parsed.decision is EvolutionDecision.REJECTED:
                            rejected_count += 1
                            continue
                        if lane is MemoryKind.SELF_STANCE:
                            if observation is None:
                                raise RuntimeError("self shadow observation is missing")
                            result = await asyncio.to_thread(
                                self_memory.propose_shadow_from_self_observation,
                                observation,
                                candidate=parsed.candidate,
                                allow_auto_activate=True,
                                now_ms=event.occurred_at_ms,
                            )
                        else:
                            result = await asyncio.to_thread(
                                self_memory.submit_shadow_candidate,
                                parsed.candidate,
                                source_message_id=event.message_id,
                                source_principal_id=principal.principal_id,
                                source_principal_role=principal.role,
                                allow_auto_activate=True,
                                now_ms=event.occurred_at_ms,
                            )
                        if result.decision is EvolutionDecision.QUARANTINED:
                            quarantined_count += 1
                        elif result.decision is EvolutionDecision.REJECTED:
                            rejected_count += 1
                        else:
                            candidate_count += 1
                    await asyncio.to_thread(
                        self_memory.complete_shadow_run,
                        run,
                        candidate_count=candidate_count,
                        rejected_count=rejected_count,
                        quarantined_count=quarantined_count,
                        now_ms=event.occurred_at_ms,
                    )
                except Exception as exc:
                    if run is not None:
                        try:
                            await asyncio.to_thread(
                                self_memory.fail_shadow_run,
                                run,
                                error=exc,
                                candidate_count=candidate_count,
                                rejected_count=rejected_count,
                                quarantined_count=quarantined_count,
                                now_ms=event.occurred_at_ms,
                            )
                        except Exception as receipt_exc:
                            _log.warning(
                                "self_memory_shadow_receipt_failed type=%s",
                                type(receipt_exc).__name__,
                            )
                    _log.warning(
                        "self_memory_shadow_failed lane=%s type=%s",
                        lane.value,
                        type(exc).__name__,
                    )
                finally:
                    if lane is MemoryKind.SELF_STANCE:
                        try:
                            if observation is None:
                                observation = await asyncio.to_thread(
                                    self_memory.get_observation_by_idempotency_key,
                                    key,
                                    reply_text=reply_text,
                                )
                            await asyncio.to_thread(
                                self_memory.release_observation_payload,
                                observation.observation_id,
                            )
                        except Exception as cleanup_exc:
                            _log.warning(
                                "self_memory_observation_cleanup_failed type=%s",
                                type(cleanup_exc).__name__,
                            )

            async def build_self_source() -> tuple[object, object | None]:
                observation = await asyncio.to_thread(
                    self_memory.get_observation_by_idempotency_key,
                    key,
                    reply_text=reply_text,
                )
                return (
                    EvolutionSource(
                        message_id=observation.reply_message_id,
                        principal_id="persona:higgs",
                        principal_role="owner",
                        text=reply_text,
                        observation_id=observation.observation_id,
                    ),
                    observation,
                )

            async def build_external_source() -> tuple[object, object | None]:
                return (
                    EvolutionSource(
                        message_id=event.message_id,
                        principal_id=principal.principal_id,
                        principal_role=principal.role,
                        text=event.text,
                    ),
                    None,
                )

            await run_shadow_lane(
                run_key=f"self:{key}",
                lane=MemoryKind.SELF_STANCE,
                source_builder=build_self_source,
            )
            await run_shadow_lane(
                run_key=f"external:{key}",
                lane=MemoryKind.ADOPTED_IDEA,
                source_builder=build_external_source,
            )
            return
        allow_auto = phase.self_memory_mode == "autonomous-low-risk"
        observation = None
        try:
            observation = await asyncio.to_thread(
                self_memory.get_observation_by_idempotency_key,
                key,
                reply_text=reply_text,
            )
            self_results = await evolution_extractor.extract(
                EvolutionSource(
                    message_id=observation.reply_message_id,
                    principal_id="persona:higgs",
                    principal_role="owner",
                    text=reply_text,
                    observation_id=observation.observation_id,
                ),
                allowed_kind=MemoryKind.SELF_STANCE,
            )
            for parsed in self_results:
                if parsed.candidate is None:
                    continue
                await asyncio.to_thread(
                    self_memory.propose_from_self_observation,
                    observation,
                    candidate=parsed.candidate,
                    allow_auto_activate=allow_auto,
                    now_ms=event.occurred_at_ms,
                )
            external_results = await evolution_extractor.extract(
                EvolutionSource(
                    message_id=event.message_id,
                    principal_id=principal.principal_id,
                    principal_role=principal.role,
                    text=event.text,
                ),
                allowed_kind=MemoryKind.ADOPTED_IDEA,
            )
            for parsed in external_results:
                if parsed.candidate is None:
                    continue
                await asyncio.to_thread(
                    self_memory.submit_candidate,
                    parsed.candidate,
                    source_message_id=event.message_id,
                    source_principal_id=principal.principal_id,
                    source_principal_role=principal.role,
                    allow_auto_activate=allow_auto,
                    now_ms=event.occurred_at_ms,
                )
        except Exception as exc:
            _log.warning("self_memory_evolution_failed type=%s", type(exc).__name__)
        finally:
            if observation is not None:
                try:
                    await asyncio.to_thread(
                        self_memory.release_observation_payload,
                        observation.observation_id,
                    )
                except Exception as cleanup_exc:
                    _log.warning(
                        "self_memory_observation_cleanup_failed type=%s",
                        type(cleanup_exc).__name__,
                    )

    async def reconcile_group_memory(
        event: InboundEvent,
        *,
        principal: Principal,
    ) -> None:
        """Extract and queue public norms from a final official group reply."""

        await reconcile_group_public_memory(
            event,
            principal=principal,
            service=group_memory,
            extractor=group_memory_extractor,
            final_sent=True,
        )

    async def finalize_event(event: InboundEvent, plan: ReplyPlan) -> None:
        """Persist idempotent audit/history after an outbound outcome is durable."""
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
                service.identities.resolve_event,
                event,
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
        if principal is not None and plan.decision is ReplyDecision.SENT and plan.text is not None:
            await reconcile_self_evolution(
                event,
                principal=principal,
                reply_text=plan.text,
            )
            await reconcile_group_memory(event, principal=principal)
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

    side_tasks: set[asyncio.Task[None]] = set()

    async def onebot_side_action(action: str, params: Mapping[str, Any]) -> None:
        try:
            await call_onebot_action(
                settings.onebot_ws_url,
                settings.onebot_access_token,
                action=action,
                params=params,
                echo=f"r-agent:side:{action}:{uuid.uuid4().hex[:10]}",
            )
        except Exception as exc:
            _log.info("onebot_side_action_failed action=%s type=%s", action, type(exc).__name__)

    async def handle_event(event: InboundEvent, result: IngestResult) -> None:
        """Finish one OneBot logical message after the quiet-window has closed."""
        try:
            if (
                interest_gate is not None
                and event.channel == "qq"
                and event.conversation_kind is ConversationKind.GROUP
                and policy.gate(event, result)
                in {ReplyDecision.GROUP_TRIGGER_REQUIRED, ReplyDecision.MENTION_REQUIRED}
                and await asyncio.to_thread(interest_gate.should_interject, event)
            ):
                event = replace(event, interjection=True)
            if (
                phase.typing_status_enabled
                and event.channel == "qq"
                and event.conversation_kind is ConversationKind.PRIVATE
                and result.stored
            ):
                typing_task = asyncio.create_task(
                    onebot_side_action(
                        "set_input_status", {"user_id": event.sender_id, "event_type": 1}
                    )
                )
                side_tasks.add(typing_task)
                typing_task.add_done_callback(side_tasks.discard)
            plan = await process_reply(
                event=event,
                result=result,
                policy=policy,
                brain=brain,
                sender=sender,
                safety=safety,
                breaker=breaker,
                owner_qq=settings.owner_qq,
                qq_online=online.snapshot().qq_online,
                risk_ledger=risk_ledger,
                on_sent=observe_sent_reply,
            )
            if plan.decision is ReplyDecision.REACTED:
                await onebot_side_action(
                    "set_msg_emoji_like",
                    {"message_id": event.message_id, "emoji_id": THUMBS_UP_FACE_ID, "set": True},
                )
            await finalize_event(event, plan)
        except Exception as exc:
            _log.error("phase2_handler_failed type=%s", type(exc).__name__)

    async def prepare_official_event(event: InboundEvent, result: IngestResult) -> PreparedReply:
        if not official_config.reply_enabled:
            channel_online = False
        elif official_adapter is None:
            raise TransportUnavailable("official QQ adapter is unavailable")
        else:
            official_status = await official_adapter.status()
            if not (official_status.connected and official_status.authenticated):
                raise TransportUnavailable("official QQ transport is not authenticated")
            channel_online = True
        response_override = None
        if phase.personal_memory_mode != "off":
            observation = await asyncio.to_thread(observations.get_for_event, event)
            if observation is not None:
                parsed = parse_personal_memory_intent(observation)
                if parsed is not None:
                    personal_result = await asyncio.to_thread(
                        submit_personal_memory_observation,
                        observation,
                        service=personal_memory,
                    )
                    response_override = personal_memory_feedback(parsed, personal_result)
        prepared = await prepare_reply(
            event=event,
            result=result,
            policy=policy,
            brain=brain,
            safety=safety,
            breaker=breaker,
            owner_qq=official_owner_openid,
            qq_online=channel_online,
            risk_ledger=risk_ledger,
            risk_idempotency_key=(f"reply:{event.channel}:{event.account_id}:{event.message_id}"),
            response_override=response_override,
        )
        if prepared.text is not None and len(prepared.text) > 2_000:
            return replace(prepared, text=prepared.text[:2_000])
        return prepared

    async def deliver_official_event(event: InboundEvent, prepared: PreparedReply) -> ReplyPlan:
        if not official_config.reply_enabled:
            if prepared.reservation_id is not None:
                await asyncio.to_thread(
                    risk_ledger.finish_send,
                    prepared.reservation_id,
                    outcome="failed",
                )
            return ReplyPlan(ReplyDecision.QQ_OFFLINE)
        if official_adapter is None:
            raise TransportUnavailable("official QQ adapter is unavailable")
        official_status = await official_adapter.status()
        if not (official_status.connected and official_status.authenticated):
            raise TransportUnavailable("official QQ transport is not authenticated")
        return await deliver_prepared_reply(
            event=event,
            prepared=prepared,
            sender=sender,
            risk_ledger=risk_ledger,
            retry_transport_unavailable=True,
            on_sent=observe_sent_reply,
        )

    interest_gate: InterestGate | None = None
    if phase.interest_enabled and group_timeline is not None and phase.interest_groups:
        interest_gate = InterestGate(
            timeline=group_timeline,
            groups=phase.interest_groups,
            names=frozenset({*phase.natural_trigger_terms, "higgs", "希格斯"}),
            frequency=phase.interest_frequency,
            hourly_cap=phase.interest_hourly_cap,
            daily_cap=phase.interest_daily_cap,
            min_gap_seconds=phase.interest_min_gap_seconds,
        )
    debouncer = GroupMessageDebouncer(
        quiet_seconds=phase.group_debounce_seconds,
        private_quiet_seconds=phase.private_debounce_seconds,
        handler=handle_event,
    )
    operator_control.attach_debouncer(debouncer)

    async def resolve_group_quote(event: InboundEvent) -> InboundEvent:
        """Attach the quoted message (timeline first, then NapCat ``get_msg``)."""
        if group_timeline is None or event.group_id is None or event.reply_message_id is None:
            return event
        quoted = None
        try:
            entry = await asyncio.to_thread(
                group_timeline.get,
                channel=event.channel,
                account_id=event.account_id,
                group_id=event.group_id,
                message_id=event.reply_message_id,
            )
            if entry is not None:
                quoted = group_timeline.as_quoted(entry)
        except Exception as exc:
            _log.warning("group_timeline_quote_lookup_failed type=%s", type(exc).__name__)
        if quoted is None:
            try:
                quoted = await get_onebot_quoted_message(
                    settings.onebot_ws_url,
                    settings.onebot_access_token,
                    event.reply_message_id,
                )
            except OutboundError:
                _log.warning("phase2_reply_reference_lookup_failed")
                return event
        return replace(
            event,
            quoted=quoted,
            replied_to_account=event.replied_to_account
            or quoted.is_self
            or quoted.sender_id == event.account_id,
        )

    async def route_inbound_event(
        event: InboundEvent,
        *,
        resolve_onebot_reply: bool,
    ) -> None:
        owner_ids = {value for value in (settings.owner_qq, official_owner_openid) if value}
        if (
            resolve_onebot_reply
            and group_timeline is not None
            and event.conversation_kind is ConversationKind.GROUP
            and event.group_id in settings.allowed_groups
            and event.reply_message_id is not None
        ):
            event = await resolve_group_quote(event)
        elif (
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
        if (
            group_timeline is not None
            and event.channel == "qq"
            and event.conversation_kind is ConversationKind.GROUP
            and result.decision is IngressDecision.ACCEPT
        ):
            try:
                await asyncio.to_thread(group_timeline.record_inbound, event)
            except Exception as exc:
                _log.warning("group_timeline_inbound_failed type=%s", type(exc).__name__)
        learning_allowed = False
        if result.stored:
            learning_allowed = await asyncio.to_thread(
                risk_ledger.note_inbound,
                event.conversation_id,
                actor_class="owner" if event.sender_id in owner_ids else "non_owner",
                account_id=event.account_id,
                source_id=(
                    event.sender_id if event.conversation_kind is ConversationKind.GROUP else None
                ),
                now_ms=event.occurred_at_ms,
            )
        if result.stored and learning_allowed:
            principal = await asyncio.to_thread(
                service.identities.resolve_event,
                event,
            )
            await asyncio.to_thread(
                observations.enqueue,
                event,
                principal_id=principal.principal_id,
                principal_role=principal.role,
            )
        if event.channel == "qq_official":
            await asyncio.to_thread(
                official_processing.enqueue,
                event,
                result,
                quiet_seconds=_official_event_quiet_seconds(event, operator_control),
            )
            return
        await debouncer.submit(event, result)

    async def route_official_event(event: InboundEvent) -> None:
        await route_inbound_event(event, resolve_onebot_reply=False)

    official_adapter = _build_official_adapter(
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
        official_processor = OfficialDurableProcessor(
            store=official_processing,
            prepare=prepare_official_event,
            deliver=deliver_official_event,
            finalize=finalize_event,
        )
        official_processing_task = asyncio.create_task(official_processor.run())
        official_processing_task.add_done_callback(
            lambda task: task.exception() if not task.cancelled() else None
        )
    backup_task = asyncio.create_task(backup.run_periodically())
    backup_task.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)

    qzone_task: asyncio.Task[None] | None = None
    if qzone_service is not None and phase.mode == "live":
        qzone_scheduler = QzoneScheduler(
            qzone_service,
            QzoneSchedule(
                mode=phase.qzone_mode,
                posts_per_day=phase.qzone_posts_per_day,
                active_start_hour=phase.qzone_active_start_hour,
                active_end_hour=phase.qzone_active_end_hour,
                browse_enabled=phase.qzone_browse_enabled,
                browse_interval_minutes=phase.qzone_browse_interval_minutes,
                daily_likes=phase.qzone_daily_likes,
                daily_comments=phase.qzone_daily_comments,
            ),
        )
        qzone_task = asyncio.create_task(qzone_scheduler.run_forever())
        qzone_task.add_done_callback(
            lambda task: task.exception() if not task.cancelled() else None
        )
    inner_task: asyncio.Task[None] | None = None
    if inner_life is not None and phase.mode == "live":
        inner_task = asyncio.create_task(
            InnerLifeScheduler(
                inner_life,
                impression_interval_minutes=phase.inner_impression_interval_minutes,
                diary_hour=phase.inner_diary_hour,
                diary_minute=phase.inner_diary_minute,
            ).run_forever()
        )
        inner_task.add_done_callback(
            lambda task: task.exception() if not task.cancelled() else None
        )
    proactive_task: asyncio.Task[None] | None = None
    if (
        phase.proactive_groups
        and group_timeline is not None
        and client is not None
        and phase.mode == "live"
        and expected_bot_qq
    ):
        bot_qq = expected_bot_qq

        async def proactive_send(group_id: str, text: str) -> str | None:
            budget = await asyncio.to_thread(
                risk_ledger.reserve_send,
                event_type="proactive",
                actor_class="system",
                account_id=bot_qq,
                conversation_id=f"qq:group:{bot_qq}:{group_id}",
                source_id=None,
                idempotency_key=f"proactive:{group_id}:{uuid.uuid4().hex[:12]}",
            )
            if not budget.allowed or budget.reservation_id is None:
                raise OutboundError("proactive budget exhausted", delivery_unknown=False)
            try:
                provider_id = await send_onebot_group_message(
                    settings.onebot_ws_url,
                    settings.onebot_access_token,
                    group_id=group_id,
                    text=text,
                    idempotency_key=f"proactive-{uuid.uuid4().hex[:16]}",
                )
            except OutboundError:
                await asyncio.to_thread(
                    risk_ledger.finish_send, budget.reservation_id, outcome="failed"
                )
                raise
            await asyncio.to_thread(risk_ledger.finish_send, budget.reservation_id, outcome="sent")
            return provider_id

        def proactive_context() -> list[str]:
            if inner_life is None:
                return []
            section = inner_life.self_context(None, "")  # type: ignore[arg-type]
            return list(section[1]) if section else []

        proactive_task = asyncio.create_task(
            ProactiveChatter(
                timeline=group_timeline,
                client=client,
                persona=persona_bundle.render() if persona_bundle is not None else persona,
                send_group=proactive_send,
                account_id=bot_qq,
                groups=phase.proactive_groups,
                context=proactive_context,
                idle_minutes=phase.proactive_idle_minutes,
                active_start_hour=phase.proactive_start_hour,
                active_end_hour=phase.proactive_end_hour,
                daily_cap=phase.proactive_daily_cap,
            ).run_forever()
        )
        proactive_task.add_done_callback(
            lambda task: task.exception() if not task.cancelled() else None
        )
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
            delivery_channels: set[str] = set()
            official_reminder_status = None
            if online.snapshot().qq_online:
                delivery_channels.add("qq")
            if (
                official_config.proactive_enabled or official_config.ordinary_proactive_enabled
            ) and official_adapter is not None:
                try:
                    candidate_status = await official_adapter.status()
                except Exception:
                    candidate_status = None
                if (
                    candidate_status is not None
                    and candidate_status.connected
                    and candidate_status.authenticated
                    and candidate_status.account_id is not None
                ):
                    official_reminder_status = candidate_status
                    delivery_channels.add("qq_official")
            due = await asyncio.to_thread(
                reminders.prepare_due,
                delivery_channels=frozenset(delivery_channels),
            )
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
                if occurrence.delivery_channel == "qq":
                    target = _onebot_reminder_target(occurrence)
                    delivery_adapter = onebot_adapter
                elif occurrence.delivery_channel == "qq_official":
                    target = _official_reminder_target(
                        occurrence,
                        owner_openid=official_owner_openid,
                        account_id=(
                            official_reminder_status.account_id
                            if official_reminder_status is not None
                            else None
                        ),
                        owner_proactive_enabled=official_config.proactive_enabled,
                        allowed_private_openids=official_private_openids,
                        ordinary_proactive_enabled=official_config.ordinary_proactive_enabled,
                    )
                    delivery_adapter = official_adapter
                else:
                    target = None
                    delivery_adapter = None
                if target is None:
                    _log.warning(
                        "reminder_delivery_blocked channel=%s surface=%s",
                        occurrence.delivery_channel,
                        occurrence.delivery_surface,
                    )
                    await asyncio.to_thread(
                        reminders.finish_occurrence,
                        occurrence.occurrence_key,
                        state="failed",
                    )
                    continue
                target_conversation = target.conversation_id
                ordinary_target = (
                    occurrence.delivery_channel == "qq_official"
                    and occurrence.delivery_surface == "private"
                    and occurrence.delivery_target_id != official_owner_openid
                )
                budget = await asyncio.to_thread(
                    risk_ledger.reserve_send,
                    event_type="reminder",
                    actor_class="non_owner" if ordinary_target else "owner",
                    account_id=occurrence.delivery_account_id,
                    conversation_id=target_conversation,
                )
                if not budget.allowed or budget.reservation_id is None:
                    continue
                try:
                    assert delivery_adapter is not None
                    receipt = await delivery_adapter.send_text(
                        target,
                        text,
                        idempotency_key=occurrence.occurrence_key,
                    )
                except (OutboundError, TransportUnavailable) as exc:
                    outcome = (
                        "unknown"
                        if isinstance(exc, TransportUnavailable) or exc.delivery_unknown
                        else "failed"
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
                        outcome = "unknown" if receipt.state is DeliveryState.UNKNOWN else "failed"
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
        *((official_processing_task,) if official_processing_task is not None else ()),
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
