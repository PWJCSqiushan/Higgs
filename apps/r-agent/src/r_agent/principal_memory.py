"""Governed v5 personal-memory updates for ordinary users.

The service in this module is intentionally separate from the owner memory
governance API and from the v4 self-memory pipeline.  It accepts a trusted
principal context assembled by the inbound pipeline, stores only hashes in
the intent/evidence ledger, and changes ``memory_items`` only in ``active``
mode.  A model or chat caller cannot choose a scope, status, or memory item
identifier.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from r_agent.memory import (
    MemoryKind,
    MemoryRisk,
    MemoryStatus,
    MemoryStore,
    MemoryValidationError,
    is_auto_review_safe_text,
)

if TYPE_CHECKING:
    from r_agent.memory_v2 import Observation
else:
    Observation = Any  # type: ignore[misc,assignment]


class PersonalMemoryMode(StrEnum):
    """Runtime mode for the ordinary-user memory lane."""

    OFF = "off"
    SHADOW = "shadow"
    ACTIVE = "active"


class PersonalMemoryIntent(StrEnum):
    """User-level memory operations accepted by the service."""

    EXPLICIT_REMEMBER = "explicit_remember"
    REPEATED_OBSERVATION = "repeated_observation"
    CORRECTION = "correction"
    FORGET_REQUEST = "forget_request"


class PersonalMemoryDecision(StrEnum):
    DISABLED = "disabled"
    CANDIDATE = "candidate"
    ACTIVATED = "activated"
    SUPERSEDED = "superseded"
    FORGOTTEN = "forgotten"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"
    NO_MATCH = "no_match"
    AMBIGUOUS = "ambiguous"
    SHADOW = "shadow"


_PERSONAL_KINDS = frozenset(
    {
        MemoryKind.USER_FACT,
        MemoryKind.PREFERENCE,
        MemoryKind.RELATIONSHIP,
        MemoryKind.COMMITMENT,
        MemoryKind.EPISODE_SUMMARY,
    }
)
_ROLES = frozenset({"owner", "user", "blocked"})
_SENSITIVITY_LEVELS = frozenset({"low", "medium", "high"})
_MAX_TEXT = 4000
_MAX_QUERY = 4000
_MIN_REPEATED_CONFIDENCE = 0.94


@dataclass(frozen=True, slots=True)
class PersonalMemoryRequest:
    """A memory intent with trusted source context.

    The normal caller passes ``observation`` from ``MemoryObservationStore``.
    Tests and controlled adapters may instead pass all ``principal_id`` and
    ``source_*`` fields explicitly after resolving identity.  The service
    cross-checks both forms when supplied.  ``target_item_id`` is retained as
    an explicit rejected field so a caller cannot accidentally turn an item
    identifier into an authority token; correction/forget use exact
    ``target_query`` matching in the current principal scope.
    """

    intent: PersonalMemoryIntent | str
    kind: MemoryKind | str
    text: str = ""
    confidence: float = 0.5
    risk: MemoryRisk | str = MemoryRisk.LOW
    sensitive_level: str = "low"
    sensitive: bool = False
    semantic_key: str | None = None
    target_query: str | None = None
    target_text: str | None = None
    observation: Observation | None = None
    principal_id: str | None = None
    principal_role: str | None = None
    # Explicit-source aliases mirror the existing memory row vocabulary.  A
    # caller may use either spelling, but supplying conflicting values is a
    # validation failure rather than an implicit precedence rule.
    source_principal_id: str | None = None
    source_principal_role: str | None = None
    source_channel: str | None = None
    source_account_id: str | None = None
    source_message_id: str | None = None
    observation_id: str | None = None
    occurred_at_ms: int | None = None
    idempotency_key: str | None = None
    target_item_id: str | None = None


@dataclass(frozen=True, slots=True)
class PersonalMemoryOutcome:
    """Content-free result of submitting one personal-memory intent."""

    decision: str
    reason: str
    item_id: str | None = None
    intent_id: str | None = None
    evidence_count: int = 0

    @property
    def result_item_id(self) -> str | None:
        """Alias used by callers that mirror the v5 column name."""

        return self.item_id

    @property
    def reason_code(self) -> str:
        """Alias used by audit/telemetry adapters."""

        return self.reason


@dataclass(frozen=True, slots=True)
class _SourceContext:
    principal_id: str
    principal_role: str
    source_channel: str
    source_account_id: str
    source_message_id: str
    observation_id: str
    occurred_at_ms: int


class PersonalMemoryService:
    """Transactional ordinary-user personal-memory service.

    ``off`` is side-effect free and does not require v5 tables.  ``shadow``
    records a decision ledger row only; it never activates or invalidates an
    existing memory item.  ``active`` performs all intent, evidence, item,
    state, and audit writes under one ``BEGIN IMMEDIATE`` transaction.
    """

    def __init__(
        self,
        memory: MemoryStore,
        *,
        mode: PersonalMemoryMode | str = PersonalMemoryMode.OFF,
    ) -> None:
        if not isinstance(memory, MemoryStore):
            raise TypeError("memory must be a MemoryStore")
        try:
            self.mode = mode if isinstance(mode, PersonalMemoryMode) else PersonalMemoryMode(mode)
        except ValueError as exc:
            raise MemoryValidationError(
                "personal memory mode must be off, shadow, or active"
            ) from exc
        self.memory = memory

    @property
    def enabled(self) -> bool:
        return self.mode is not PersonalMemoryMode.OFF

    def schema_enabled(self) -> bool:
        """Return whether the opt-in v5 ledger exists, without migrating it."""

        with self.memory._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='personal_memory_intents'
                """
            ).fetchone()
        return row is not None

    def submit(self, request: PersonalMemoryRequest) -> PersonalMemoryOutcome:
        """Submit one intent and return a deterministic, auditable outcome."""

        if not isinstance(request, PersonalMemoryRequest):
            raise TypeError("request must be a PersonalMemoryRequest")
        if self.mode is PersonalMemoryMode.OFF:
            return PersonalMemoryOutcome(
                PersonalMemoryDecision.DISABLED.value,
                "mode_off",
            )
        if not self.schema_enabled():
            raise MemoryValidationError("personal memory schema v5 is not enabled")

        normalized = self._normalize(request)
        with self.memory._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = self._existing_intent(
                conn,
                idempotency_key=normalized["idempotency_key"],
                observation_id=normalized["source"].observation_id,
            )
            if existing is not None:
                if str(existing["request_sha256"]) != normalized["request_sha256"]:
                    return PersonalMemoryOutcome(
                        PersonalMemoryDecision.REJECTED.value,
                        "idempotency_conflict",
                        intent_id=str(existing["intent_id"]),
                    )
                return self._outcome_from_row(existing)

            intent_id = str(uuid.uuid4())
            source = normalized["source"]
            try:
                conn.execute(
                    """
                    INSERT INTO personal_memory_intents(
                        intent_id, idempotency_key, request_sha256, observation_id,
                        principal_id, principal_role, source_channel, source_account_id,
                        source_message_id, intent, kind, semantic_sha256, confidence,
                        risk, sensitive_level, decision, reason_code, result_item_id,
                        created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              'pending', 'processing', NULL, ?, ?)
                    """,
                    (
                        intent_id,
                        normalized["idempotency_key"],
                        normalized["request_sha256"],
                        source.observation_id,
                        source.principal_id,
                        source.principal_role,
                        source.source_channel,
                        source.source_account_id,
                        source.source_message_id,
                        normalized["intent"].value,
                        normalized["kind"].value,
                        normalized["semantic_sha256"],
                        normalized["confidence"],
                        normalized["risk"].value,
                        normalized["sensitive_level"],
                        normalized["now_ms"],
                        normalized["now_ms"],
                    ),
                )
            except sqlite3.IntegrityError:
                # A concurrent/replayed source identity can only be accepted
                # if its complete request hash matches.  Do not guess which
                # row should win after a uniqueness race.
                raced = self._existing_intent(
                    conn,
                    idempotency_key=normalized["idempotency_key"],
                    observation_id=source.observation_id,
                )
                if (
                    raced is not None
                    and str(raced["request_sha256"]) == normalized["request_sha256"]
                ):
                    return self._outcome_from_row(raced)
                return PersonalMemoryOutcome(
                    PersonalMemoryDecision.REJECTED.value,
                    "idempotency_conflict",
                    intent_id=str(raced["intent_id"]) if raced is not None else None,
                )

            outcome = self._decide(
                conn,
                intent_id=intent_id,
                request=request,
                normalized=normalized,
            )
            return outcome

    def _normalize(self, request: PersonalMemoryRequest) -> dict[str, Any]:
        try:
            intent = (
                request.intent
                if isinstance(request.intent, PersonalMemoryIntent)
                else PersonalMemoryIntent(request.intent)
            )
        except ValueError as exc:
            raise MemoryValidationError("personal memory intent is invalid") from exc
        try:
            kind = (
                request.kind if isinstance(request.kind, MemoryKind) else MemoryKind(request.kind)
            )
        except ValueError as exc:
            raise MemoryValidationError("personal memory kind is invalid") from exc
        if kind not in _PERSONAL_KINDS:
            raise MemoryValidationError("personal memory kind is not user-scoped")
        try:
            risk = (
                request.risk if isinstance(request.risk, MemoryRisk) else MemoryRisk(request.risk)
            )
        except ValueError as exc:
            raise MemoryValidationError("personal memory risk is invalid") from exc
        if not isinstance(request.confidence, (int, float)) or isinstance(request.confidence, bool):
            raise MemoryValidationError("confidence must be numeric")
        confidence = float(request.confidence)
        if not 0 <= confidence <= 1:
            raise MemoryValidationError("confidence must be between 0 and 1")
        sensitive_level = str(request.sensitive_level).strip().casefold()
        if request.sensitive:
            sensitive_level = "high"
        if sensitive_level not in _SENSITIVITY_LEVELS:
            raise MemoryValidationError("sensitive_level is invalid")
        source = self._source_context(request)
        clean_text = self._clean_text(
            request.text, field="text", allow_empty=intent is PersonalMemoryIntent.FORGET_REQUEST
        )
        target_query = request.target_query
        if request.target_text is not None:
            if target_query is not None and request.target_text.strip() != target_query.strip():
                raise MemoryValidationError("target_query and target_text conflict")
            target_query = request.target_text
        clean_target = (
            self._clean_text(target_query, field="target_query", allow_empty=False)
            if target_query is not None
            else None
        )
        if request.target_item_id is not None and str(request.target_item_id).strip():
            raise MemoryValidationError("target_item_id is not accepted; use an exact target query")
        if intent is PersonalMemoryIntent.FORGET_REQUEST and clean_target is None:
            raise MemoryValidationError("target_query is required for forget")
        if (
            intent
            in {
                PersonalMemoryIntent.EXPLICIT_REMEMBER,
                PersonalMemoryIntent.REPEATED_OBSERVATION,
                PersonalMemoryIntent.CORRECTION,
            }
            and not clean_text
        ):
            raise MemoryValidationError("text is required for this intent")
        semantic_source = request.semantic_key if request.semantic_key is not None else clean_text
        if intent is PersonalMemoryIntent.FORGET_REQUEST and request.semantic_key is None:
            semantic_source = clean_target or ""
        semantic = self._clean_text(semantic_source, field="semantic_key", allow_empty=False)
        now_ms = int(time.time() * 1000)
        canonical = {
            "intent": intent.value,
            "kind": kind.value,
            "text": clean_text,
            "target_query": clean_target,
            "semantic_key": semantic,
            "confidence": confidence,
            "risk": risk.value,
            "sensitive_level": sensitive_level,
            "source": {
                "principal_id": source.principal_id,
                "principal_role": source.principal_role,
                "source_channel": source.source_channel,
                "source_account_id": source.source_account_id,
                "source_message_id": source.source_message_id,
                "observation_id": source.observation_id,
            },
        }
        request_sha256 = self._sha256_json(canonical)
        idempotency_key = self._idempotency_key(request, source)
        return {
            "intent": intent,
            "kind": kind,
            "risk": risk,
            "confidence": confidence,
            "sensitive_level": sensitive_level,
            "text": clean_text,
            "target_query": clean_target,
            "semantic_sha256": hashlib.sha256(semantic.casefold().encode("utf-8")).hexdigest(),
            "request_sha256": request_sha256,
            "idempotency_key": idempotency_key,
            "source": source,
            "now_ms": now_ms,
        }

    @staticmethod
    def _clean_text(value: str | None, *, field: str, allow_empty: bool) -> str:
        if value is None:
            if allow_empty:
                return ""
            raise MemoryValidationError(f"{field} is required")
        if not isinstance(value, str):
            raise MemoryValidationError(f"{field} must be text")
        cleaned = " ".join(value.split())
        if not allow_empty and not cleaned:
            raise MemoryValidationError(f"{field} is required")
        limit = _MAX_QUERY if field == "target_query" else _MAX_TEXT
        if len(cleaned) > limit:
            raise MemoryValidationError(f"{field} exceeds {limit} characters")
        return cleaned

    @staticmethod
    def _sha256_json(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _idempotency_key(request: PersonalMemoryRequest, source: _SourceContext) -> str:
        supplied = request.idempotency_key
        if supplied is not None and str(supplied).strip():
            clean = str(supplied).strip()
            if len(clean) > 256:
                raise MemoryValidationError("idempotency_key exceeds 256 characters")
            return clean
        seed = "\x1f".join(
            (
                source.source_channel,
                source.source_account_id,
                source.source_message_id,
            )
        )
        return "personal:v5:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:48]

    @staticmethod
    def _source_context(request: PersonalMemoryRequest) -> _SourceContext:
        observation = request.observation
        values: dict[str, Any] = {}
        if observation is not None:
            required = (
                "principal_id",
                "principal_role",
                "channel",
                "account_id",
                "message_id",
                "observation_id",
                "occurred_at_ms",
            )
            if not all(hasattr(observation, field) for field in required):
                raise MemoryValidationError("observation is not a trusted memory observation")
            values = {
                "principal_id": str(observation.principal_id),
                "principal_role": str(observation.principal_role),
                "source_channel": str(observation.channel),
                "source_account_id": str(observation.account_id),
                "source_message_id": str(observation.message_id),
                "observation_id": str(observation.observation_id),
                "occurred_at_ms": int(observation.occurred_at_ms),
            }
            supplements = {
                "principal_id": request.principal_id,
                "principal_role": request.principal_role,
                "source_channel": request.source_channel,
                "source_account_id": request.source_account_id,
                "source_message_id": request.source_message_id,
                "observation_id": request.observation_id,
            }
            alias_supplements = {
                "principal_id": request.source_principal_id,
                "principal_role": request.source_principal_role,
            }
            for name, value in supplements.items():
                if value is not None and str(value).strip() != str(values[name]).strip():
                    raise MemoryValidationError(f"{name} conflicts with observation")
            for name, value in alias_supplements.items():
                if value is not None and str(value).strip() != str(values[name]).strip():
                    raise MemoryValidationError(f"{name} conflicts with observation")
        else:
            if (
                request.principal_id is not None
                and request.source_principal_id is not None
                and request.principal_id.strip() != request.source_principal_id.strip()
            ):
                raise MemoryValidationError("principal_id and source_principal_id conflict")
            if (
                request.principal_role is not None
                and request.source_principal_role is not None
                and request.principal_role.strip().casefold()
                != request.source_principal_role.strip().casefold()
            ):
                raise MemoryValidationError("principal_role and source_principal_role conflict")
            values = {
                "principal_id": request.principal_id or request.source_principal_id,
                "principal_role": request.principal_role or request.source_principal_role,
                "source_channel": request.source_channel,
                "source_account_id": request.source_account_id,
                "source_message_id": request.source_message_id,
                "observation_id": request.observation_id,
                "occurred_at_ms": request.occurred_at_ms,
            }
        for name in (
            "principal_id",
            "principal_role",
            "source_channel",
            "source_account_id",
            "source_message_id",
        ):
            value = values.get(name)
            if not isinstance(value, str) or not value.strip():
                raise MemoryValidationError(f"{name} is required")
            if len(value.strip()) > 256:
                raise MemoryValidationError(f"{name} exceeds 256 characters")
        role = str(values["principal_role"]).strip().casefold()
        if role not in _ROLES:
            raise MemoryValidationError("principal_role is invalid")
        observation_id = values.get("observation_id")
        if observation_id is None or not str(observation_id).strip():
            observation_id = str(values["source_message_id"]).strip()
        if len(str(observation_id).strip()) > 256:
            raise MemoryValidationError("observation_id exceeds 256 characters")
        occurred = values.get("occurred_at_ms")
        if occurred is None:
            occurred = int(time.time() * 1000)
        if isinstance(occurred, bool) or not isinstance(occurred, int):
            raise MemoryValidationError("occurred_at_ms must be an integer")
        return _SourceContext(
            principal_id=str(values["principal_id"]).strip(),
            principal_role=role,
            source_channel=str(values["source_channel"]).strip().casefold(),
            source_account_id=str(values["source_account_id"]).strip(),
            source_message_id=str(values["source_message_id"]).strip(),
            observation_id=str(observation_id).strip(),
            occurred_at_ms=occurred,
        )

    @staticmethod
    def _existing_intent(
        conn: sqlite3.Connection,
        *,
        idempotency_key: str,
        observation_id: str,
    ) -> sqlite3.Row | None:
        row = conn.execute(
            "SELECT * FROM personal_memory_intents WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if row is not None:
            return row
        return conn.execute(
            "SELECT * FROM personal_memory_intents WHERE observation_id = ?",
            (observation_id,),
        ).fetchone()

    @staticmethod
    def _outcome_from_row(row: sqlite3.Row) -> PersonalMemoryOutcome:
        return PersonalMemoryOutcome(
            decision=str(row["decision"]),
            reason=str(row["reason_code"]),
            item_id=str(row["result_item_id"]) if row["result_item_id"] is not None else None,
            intent_id=str(row["intent_id"]),
        )

    def _decide(
        self,
        conn: sqlite3.Connection,
        *,
        intent_id: str,
        request: PersonalMemoryRequest,
        normalized: dict[str, Any],
    ) -> PersonalMemoryOutcome:
        source: _SourceContext = normalized["source"]
        intent: PersonalMemoryIntent = normalized["intent"]
        text: str = normalized["text"]
        now_ms = int(normalized["now_ms"])
        unsafe = (
            source.principal_role in {"blocked", "owner"}
            or normalized["risk"] is not MemoryRisk.LOW
            or normalized["sensitive_level"] != "low"
            or not is_auto_review_safe_text(text)
            or (
                normalized["target_query"] is not None
                and not is_auto_review_safe_text(str(normalized["target_query"]))
            )
        )
        if unsafe:
            decision = (
                PersonalMemoryDecision.REJECTED.value
                if source.principal_role in {"blocked", "owner"}
                else PersonalMemoryDecision.QUARANTINED.value
            )
            reason = (
                "blocked_principal"
                if source.principal_role == "blocked"
                else "owner_requires_governance"
                if source.principal_role == "owner"
                else "sensitive_or_unsafe"
            )
            self._finish_intent(conn, intent_id, decision, reason, now_ms=now_ms)
            return PersonalMemoryOutcome(decision, reason, intent_id=intent_id)

        if self.mode is PersonalMemoryMode.SHADOW:
            reason = self._shadow_reason(intent, normalized)
            self._finish_intent(
                conn, intent_id, PersonalMemoryDecision.SHADOW.value, reason, now_ms=now_ms
            )
            return PersonalMemoryOutcome(
                PersonalMemoryDecision.SHADOW.value,
                reason,
                intent_id=intent_id,
            )

        if intent is PersonalMemoryIntent.EXPLICIT_REMEMBER:
            return self._explicit_remember(conn, intent_id, normalized)
        if intent is PersonalMemoryIntent.REPEATED_OBSERVATION:
            return self._repeated_observation(conn, intent_id, normalized)
        if intent is PersonalMemoryIntent.CORRECTION:
            return self._correction(conn, intent_id, normalized)
        if intent is PersonalMemoryIntent.FORGET_REQUEST:
            return self._forget(conn, intent_id, normalized)
        raise MemoryValidationError("unsupported personal memory intent")

    @staticmethod
    def _shadow_reason(intent: PersonalMemoryIntent, normalized: dict[str, Any]) -> str:
        if intent is PersonalMemoryIntent.REPEATED_OBSERVATION:
            if normalized["confidence"] < _MIN_REPEATED_CONFIDENCE:
                return "shadow_below_confidence"
            return "shadow_would_wait_for_corroboration"
        if intent is PersonalMemoryIntent.CORRECTION:
            return "shadow_would_check_unique_target"
        if intent is PersonalMemoryIntent.FORGET_REQUEST:
            return "shadow_would_check_unique_target"
        return "shadow_would_activate"

    def _explicit_remember(
        self,
        conn: sqlite3.Connection,
        intent_id: str,
        normalized: dict[str, Any],
    ) -> PersonalMemoryOutcome:
        source: _SourceContext = normalized["source"]
        existing = self._find_active_semantic(conn, normalized)
        if existing is not None:
            self._finish_intent(
                conn,
                intent_id,
                PersonalMemoryDecision.ACTIVATED.value,
                "already_active",
                result_item_id=str(existing["item_id"]),
                now_ms=normalized["now_ms"],
            )
            return PersonalMemoryOutcome(
                PersonalMemoryDecision.ACTIVATED.value,
                "already_active",
                item_id=str(existing["item_id"]),
                intent_id=intent_id,
            )
        item_id = self._insert_item(
            conn,
            intent_id=intent_id,
            normalized=normalized,
            status=MemoryStatus.ACTIVE,
            supersedes_item_id=None,
        )
        self._insert_evidence(
            conn,
            intent_id=intent_id,
            item_id=item_id,
            normalized=normalized,
            kind="explicit_remember",
        )
        self.memory._audit(
            conn,
            item_id=item_id,
            action="personal_explicit_activated",
            actor_principal_id=source.principal_id,
            actor_role=source.principal_role,
            details="personal_memory_v5:explicit_remember",
            now_ms=normalized["now_ms"],
        )
        self._finish_intent(
            conn,
            intent_id,
            PersonalMemoryDecision.ACTIVATED.value,
            "explicit_remember",
            result_item_id=item_id,
            now_ms=normalized["now_ms"],
        )
        return PersonalMemoryOutcome(
            PersonalMemoryDecision.ACTIVATED.value,
            "explicit_remember",
            item_id=item_id,
            intent_id=intent_id,
        )

    def _repeated_observation(
        self,
        conn: sqlite3.Connection,
        intent_id: str,
        normalized: dict[str, Any],
    ) -> PersonalMemoryOutcome:
        if normalized["confidence"] < _MIN_REPEATED_CONFIDENCE:
            self._finish_intent(
                conn,
                intent_id,
                PersonalMemoryDecision.REJECTED.value,
                "confidence_below_threshold",
                now_ms=normalized["now_ms"],
            )
            return PersonalMemoryOutcome(
                PersonalMemoryDecision.REJECTED.value,
                "confidence_below_threshold",
                intent_id=intent_id,
            )
        existing = self._find_candidate_or_active_semantic(conn, normalized)
        if existing is None:
            item_id = self._insert_item(
                conn,
                intent_id=intent_id,
                normalized=normalized,
                status=MemoryStatus.CANDIDATE,
                supersedes_item_id=None,
            )
        else:
            item_id = str(existing["item_id"])
        self._insert_evidence(
            conn, intent_id=intent_id, item_id=item_id, normalized=normalized, kind="observation"
        )
        evidence_count = self._evidence_count(conn, item_id=item_id, normalized=normalized)
        if existing is not None and str(existing["status"]) == MemoryStatus.ACTIVE.value:
            decision = PersonalMemoryDecision.ACTIVATED.value
            reason = "already_active"
        elif evidence_count >= 2:
            cursor = conn.execute(
                """
                UPDATE memory_items
                SET status='active', reviewed_at_ms=?, reviewed_by='personal-memory-v5',
                    invalidated_reason=NULL
                WHERE item_id=? AND status='candidate'
                """,
                (normalized["now_ms"], item_id),
            )
            if cursor.rowcount != 1:
                raise MemoryValidationError("candidate changed during corroboration")
            self.memory._audit(
                conn,
                item_id=item_id,
                action="personal_repeated_activated",
                actor_principal_id=normalized["source"].principal_id,
                actor_role=normalized["source"].principal_role,
                details="personal_memory_v5:two_independent_observations",
                now_ms=normalized["now_ms"],
            )
            conn.execute(
                """
                UPDATE personal_memory_intents
                SET decision='activated', reason_code='corroborated', updated_at_ms=?
                WHERE result_item_id=? AND decision='candidate'
                """,
                (normalized["now_ms"], item_id),
            )
            decision = PersonalMemoryDecision.ACTIVATED.value
            reason = "corroborated"
        else:
            decision = PersonalMemoryDecision.CANDIDATE.value
            reason = "awaiting_corroboration"
        self._finish_intent(
            conn,
            intent_id,
            decision,
            reason,
            result_item_id=item_id,
            now_ms=normalized["now_ms"],
        )
        return PersonalMemoryOutcome(
            decision,
            reason,
            item_id=item_id,
            intent_id=intent_id,
            evidence_count=evidence_count,
        )

    def _correction(
        self,
        conn: sqlite3.Connection,
        intent_id: str,
        normalized: dict[str, Any],
    ) -> PersonalMemoryOutcome:
        matches = self._find_target_matches(conn, normalized)
        if not matches:
            return self._finish_outcome(
                conn,
                intent_id,
                PersonalMemoryDecision.NO_MATCH.value,
                "target_not_found",
                normalized,
            )
        if len(matches) > 1:
            return self._finish_outcome(
                conn,
                intent_id,
                PersonalMemoryDecision.AMBIGUOUS.value,
                "target_ambiguous",
                normalized,
            )
        previous = matches[0]
        if str(previous["text"]) == normalized["text"]:
            return self._finish_outcome(
                conn,
                intent_id,
                PersonalMemoryDecision.REJECTED.value,
                "replacement_is_unchanged",
                normalized,
            )
        item_id = self._insert_item(
            conn,
            intent_id=intent_id,
            normalized=normalized,
            status=MemoryStatus.ACTIVE,
            supersedes_item_id=str(previous["item_id"]),
        )
        timestamp = normalized["now_ms"]
        cursor = conn.execute(
            """
            UPDATE memory_items
            SET status='invalidated', valid_to_ms=?, reviewed_at_ms=?,
                reviewed_by='personal-memory-v5', invalidated_reason='user_correction'
            WHERE item_id=? AND status='active'
            """,
            (timestamp, timestamp, str(previous["item_id"])),
        )
        if cursor.rowcount != 1:
            raise MemoryValidationError("target changed during correction")
        self._insert_evidence(
            conn, intent_id=intent_id, item_id=item_id, normalized=normalized, kind="correction"
        )
        self.memory._audit(
            conn,
            item_id=str(previous["item_id"]),
            action="personal_correction_invalidated",
            actor_principal_id=normalized["source"].principal_id,
            actor_role=normalized["source"].principal_role,
            details="personal_memory_v5:user_correction",
            now_ms=timestamp,
        )
        self.memory._audit(
            conn,
            item_id=item_id,
            action="personal_correction_activated",
            actor_principal_id=normalized["source"].principal_id,
            actor_role=normalized["source"].principal_role,
            details="personal_memory_v5:supersedes_previous",
            now_ms=timestamp,
        )
        return self._finish_outcome(
            conn,
            intent_id,
            PersonalMemoryDecision.SUPERSEDED.value,
            "corrected",
            normalized,
            item_id=item_id,
        )

    def _forget(
        self,
        conn: sqlite3.Connection,
        intent_id: str,
        normalized: dict[str, Any],
    ) -> PersonalMemoryOutcome:
        matches = self._find_target_matches(conn, normalized)
        if not matches:
            return self._finish_outcome(
                conn,
                intent_id,
                PersonalMemoryDecision.NO_MATCH.value,
                "target_not_found",
                normalized,
            )
        if len(matches) > 1:
            return self._finish_outcome(
                conn,
                intent_id,
                PersonalMemoryDecision.AMBIGUOUS.value,
                "target_ambiguous",
                normalized,
            )
        item_id = str(matches[0]["item_id"])
        timestamp = normalized["now_ms"]
        cursor = conn.execute(
            """
            UPDATE memory_items
            SET status='invalidated', valid_to_ms=?, reviewed_at_ms=?,
                reviewed_by='personal-memory-v5', invalidated_reason='user_forget_request'
            WHERE item_id=? AND status='active'
            """,
            (timestamp, timestamp, item_id),
        )
        if cursor.rowcount != 1:
            raise MemoryValidationError("target changed during forget request")
        self._insert_evidence(
            conn, intent_id=intent_id, item_id=item_id, normalized=normalized, kind="forget_request"
        )
        self.memory._audit(
            conn,
            item_id=item_id,
            action="personal_forget_invalidated",
            actor_principal_id=normalized["source"].principal_id,
            actor_role=normalized["source"].principal_role,
            details="personal_memory_v5:user_forget_request",
            now_ms=timestamp,
        )
        return self._finish_outcome(
            conn,
            intent_id,
            PersonalMemoryDecision.FORGOTTEN.value,
            "forgotten",
            normalized,
            item_id=item_id,
        )

    @staticmethod
    def _finish_intent(
        conn: sqlite3.Connection,
        intent_id: str,
        decision: str,
        reason: str,
        *,
        result_item_id: str | None = None,
        now_ms: int,
    ) -> None:
        conn.execute(
            """
            UPDATE personal_memory_intents
            SET decision=?, reason_code=?, result_item_id=?, updated_at_ms=?
            WHERE intent_id=? AND decision='pending'
            """,
            (decision, reason, result_item_id, now_ms, intent_id),
        )

    def _finish_outcome(
        self,
        conn: sqlite3.Connection,
        intent_id: str,
        decision: str,
        reason: str,
        normalized: dict[str, Any],
        *,
        item_id: str | None = None,
    ) -> PersonalMemoryOutcome:
        self._finish_intent(
            conn,
            intent_id,
            decision,
            reason,
            result_item_id=item_id,
            now_ms=normalized["now_ms"],
        )
        return PersonalMemoryOutcome(decision, reason, item_id=item_id, intent_id=intent_id)

    def _insert_item(
        self,
        conn: sqlite3.Connection,
        *,
        intent_id: str,
        normalized: dict[str, Any],
        status: MemoryStatus,
        supersedes_item_id: str | None,
    ) -> str:
        source: _SourceContext = normalized["source"]
        item_id = str(uuid.uuid4())
        fingerprint_payload = {
            "item_id": item_id,
            "intent_id": intent_id,
            "principal_id": source.principal_id,
            "channel": source.source_channel,
            "account_id": source.source_account_id,
            "kind": normalized["kind"].value,
            "text": normalized["text"],
            "semantic_sha256": normalized["semantic_sha256"],
            "supersedes_item_id": supersedes_item_id,
        }
        fingerprint = self._sha256_json(fingerprint_payload)
        conn.execute(
            """
            INSERT INTO memory_items(
                item_id, fingerprint, scope_type, scope_id, kind, text,
                source_channel, source_account_id, source_message_id,
                source_principal_id, source_principal_role, created_by, risk,
                confidence, status, created_at_ms, reviewed_at_ms,
                reviewed_by, invalidated_reason, importance, source_trust,
                valid_from_ms, valid_to_ms, supersedes_item_id
            ) VALUES (?, ?, 'principal', ?, ?, ?, ?, ?, ?, ?, ?,
                      'personal-memory-v5', ?, ?, ?, ?, ?, ?, NULL, 0.5, 0.5,
                      ?, NULL, ?)
            """,
            (
                item_id,
                fingerprint,
                source.principal_id,
                normalized["kind"].value,
                normalized["text"],
                source.source_channel,
                source.source_account_id,
                source.source_message_id,
                source.principal_id,
                source.principal_role,
                normalized["risk"].value,
                normalized["confidence"],
                status.value,
                normalized["now_ms"],
                normalized["now_ms"] if status is MemoryStatus.ACTIVE else None,
                "personal-memory-v5" if status is MemoryStatus.ACTIVE else None,
                normalized["now_ms"],
                supersedes_item_id,
            ),
        )
        self.memory._audit(
            conn,
            item_id=item_id,
            action="personal_candidate_created"
            if status is MemoryStatus.CANDIDATE
            else "personal_item_created",
            actor_principal_id=source.principal_id,
            actor_role=source.principal_role,
            details=f"personal_memory_v5:{status.value}",
            now_ms=normalized["now_ms"],
        )
        return item_id

    @staticmethod
    def _insert_evidence(
        conn: sqlite3.Connection,
        *,
        intent_id: str,
        item_id: str,
        normalized: dict[str, Any],
        kind: str,
    ) -> None:
        source: _SourceContext = normalized["source"]
        content = normalized["text"] or str(normalized["target_query"] or "")
        content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        conn.execute(
            """
            INSERT INTO personal_memory_evidence(
                evidence_id, item_id, intent_id, source_observation_id,
                principal_id, source_channel, source_account_id,
                source_message_id, evidence_kind, content_sha256,
                confidence, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                item_id,
                intent_id,
                source.observation_id,
                source.principal_id,
                source.source_channel,
                source.source_account_id,
                source.source_message_id,
                kind,
                content_sha256,
                normalized["confidence"],
                normalized["now_ms"],
            ),
        )

    @staticmethod
    def _evidence_count(
        conn: sqlite3.Connection,
        *,
        item_id: str,
        normalized: dict[str, Any],
    ) -> int:
        source: _SourceContext = normalized["source"]
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT source_message_id)
            FROM personal_memory_evidence
            WHERE item_id=? AND principal_id=? AND source_channel=?
              AND source_account_id=?
            """,
            (item_id, source.principal_id, source.source_channel, source.source_account_id),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    @staticmethod
    def _find_active_semantic(
        conn: sqlite3.Connection,
        normalized: dict[str, Any],
    ) -> sqlite3.Row | None:
        source: _SourceContext = normalized["source"]
        return conn.execute(
            """
            SELECT i.*
            FROM memory_items i
            JOIN personal_memory_intents p ON p.result_item_id=i.item_id
            WHERE i.scope_type='principal' AND i.scope_id=? AND i.kind=?
              AND i.source_channel=? AND i.source_account_id=?
              AND i.status='active'
              AND p.semantic_sha256=?
            ORDER BY i.created_at_ms DESC LIMIT 1
            """,
            (
                source.principal_id,
                normalized["kind"].value,
                source.source_channel,
                source.source_account_id,
                normalized["semantic_sha256"],
            ),
        ).fetchone()

    @classmethod
    def _find_candidate_or_active_semantic(
        cls,
        conn: sqlite3.Connection,
        normalized: dict[str, Any],
    ) -> sqlite3.Row | None:
        source: _SourceContext = normalized["source"]
        return conn.execute(
            """
            SELECT i.*
            FROM memory_items i
            JOIN personal_memory_intents p ON p.result_item_id=i.item_id
            WHERE i.scope_type='principal' AND i.scope_id=? AND i.kind=?
              AND i.source_channel=? AND i.source_account_id=?
              AND i.status IN ('candidate','active')
              AND p.semantic_sha256=?
            ORDER BY CASE i.status WHEN 'candidate' THEN 0 ELSE 1 END,
                     i.created_at_ms ASC LIMIT 1
            """,
            (
                source.principal_id,
                normalized["kind"].value,
                source.source_channel,
                source.source_account_id,
                normalized["semantic_sha256"],
            ),
        ).fetchone()

    @staticmethod
    def _find_target_matches(
        conn: sqlite3.Connection,
        normalized: dict[str, Any],
    ) -> list[sqlite3.Row]:
        source: _SourceContext = normalized["source"]
        clauses = [
            "scope_type='principal'",
            "scope_id=?",
            "kind=?",
            "source_channel=?",
            "source_account_id=?",
            "status='active'",
            "valid_from_ms <= ?",
            "(valid_to_ms IS NULL OR valid_to_ms > ?)",
        ]
        params: list[str | int] = [
            source.principal_id,
            normalized["kind"].value,
            source.source_channel,
            source.source_account_id,
            normalized["now_ms"],
            normalized["now_ms"],
        ]
        target_query = normalized["target_query"]
        if target_query is not None:
            clauses.append("text=?")
            params.append(target_query)
        return conn.execute(
            "SELECT * FROM memory_items WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at_ms ASC, item_id ASC LIMIT 3",
            params,
        ).fetchall()


__all__ = [
    "PersonalMemoryDecision",
    "PersonalMemoryIntent",
    "PersonalMemoryMode",
    "PersonalMemoryOutcome",
    "PersonalMemoryRequest",
    "PersonalMemoryService",
]
