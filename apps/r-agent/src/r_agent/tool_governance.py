"""Fail-closed governance boundaries for local tools.

The model is deliberately not a caller of this module.  A caller must create a
``ToolRequest`` and obtain an explicit ``ToolDecision`` before a handler can be
run.  Requests marked as ``model_shadow`` are always denied by default, even if
some future caller accidentally passes ``approved=True``.  This keeps a model
proposal useful for observability without turning prompt text into authority.

Only normalized JSON parameters and hashes are written to the audit store.  A
handler result is returned to the caller, but is persisted only when a tool
explicitly opts in with ``persist_result=True``.  The first production tool
(``server_status``) is read-only and has no arbitrary path or shell access.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class ToolGovernanceError(RuntimeError):
    """Base class for a local tool governance failure."""


class ToolValidationError(ToolGovernanceError, ValueError):
    """A tool, request, or result violated the bounded JSON contract."""


class ToolAuditError(ToolGovernanceError):
    """The append-only/idempotency audit store could not be used safely."""


class ToolReceiptState(StrEnum):
    """Terminal state of a governed tool invocation."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    DENIED = "denied"
    RATE_LIMITED = "rate_limited"
    DUPLICATE = "duplicate"
    TIMED_OUT = "timed_out"


class ToolRequestSource(StrEnum):
    """Trusted source labels; unrecognized labels are denied."""

    OWNER_COMMAND = "owner_command"
    MODEL_SHADOW = "model_shadow"
    SYSTEM = "system"


_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_ACTOR_ROLE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_SOURCE_VALUES = frozenset(item.value for item in ToolRequestSource)
_MAX_PARAMETER_DEPTH = 8
_MAX_PARAMETER_ITEMS = 64
_MAX_PARAMETER_STRING = 4_096
_MAX_RESULT_BYTES = 256 * 1024
_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


def _reject_control_characters(value: str, *, label: str, max_length: int) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    if not normalized or len(normalized) > max_length:
        raise ToolValidationError(f"{label} is empty or too long")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in normalized):
        raise ToolValidationError(f"{label} contains control characters")
    return normalized


def _normalize_json(value: Any, *, depth: int) -> Any:
    if depth > _MAX_PARAMETER_DEPTH:
        raise ToolValidationError("tool parameters are too deeply nested")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _reject_control_characters(
            value,
            label="tool parameter",
            max_length=_MAX_PARAMETER_STRING,
        )
    if isinstance(value, int):
        if abs(value) > 2**63 - 1:
            raise ToolValidationError("tool integer parameter is out of range")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ToolValidationError("tool parameters must not contain NaN or infinity")
        return value
    if isinstance(value, Mapping):
        if len(value) > _MAX_PARAMETER_ITEMS:
            raise ToolValidationError("tool parameter object has too many fields")
        normalized: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ToolValidationError("tool parameter keys must be strings")
            clean_key = _reject_control_characters(key, label="tool parameter key", max_length=128)
            if clean_key.startswith(("__", "$")):
                raise ToolValidationError("reserved tool parameter key")
            if clean_key in normalized:
                raise ToolValidationError("duplicate normalized tool parameter key")
            normalized[clean_key] = _normalize_json(child, depth=depth + 1)
        return normalized
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_PARAMETER_ITEMS:
            raise ToolValidationError("tool parameter array has too many items")
        return [_normalize_json(child, depth=depth + 1) for child in value]
    raise ToolValidationError(f"unsupported tool parameter type: {type(value).__name__}")


def normalize_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Return bounded, canonicalizable JSON parameters.

    Strings receive Unicode NFKC normalization, object keys are sorted only at
    serialization time, and no executable values are accepted.  The function
    intentionally does not interpret paths, URLs, shell syntax, or model text;
    each tool must impose its own narrower schema after this common boundary.
    """

    if not isinstance(parameters, Mapping):
        raise ToolValidationError("tool parameters must be a JSON object")
    normalized = _normalize_json(parameters, depth=0)
    if not isinstance(normalized, dict):  # pragma: no cover - guarded above
        raise ToolValidationError("tool parameters must be a JSON object")
    return normalized


def canonical_parameters(parameters: Mapping[str, Any]) -> str:
    """Serialize normalized parameters without whitespace or non-finite values."""

    normalized = normalize_parameters(parameters)
    try:
        return json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:  # defensive if JSON gains a new type
        raise ToolValidationError("tool parameters are not canonical JSON") from exc


def parameter_approval_hash(tool_name: str, parameters: Mapping[str, Any]) -> str:
    """Hash the tool name together with exact normalized parameters.

    Including the tool name prevents an approval for one tool being replayed for
    another tool with the same JSON shape.
    """

    clean_name = _reject_control_characters(tool_name, label="tool name", max_length=64)
    encoded = f"{clean_name}\0{canonical_parameters(parameters)}".encode()
    return hashlib.sha256(encoded).hexdigest()


# Compatibility spelling for callers that prefer the shorter name.
approval_hash = parameter_approval_hash


def _schema_matches_value(value: Any, schema: Mapping[str, Any], *, depth: int) -> bool:
    if depth > _MAX_PARAMETER_DEPTH or not isinstance(schema, Mapping):
        return False
    expected = schema.get("type")
    valid_types = {
        None,
        "string",
        "integer",
        "number",
        "boolean",
        "array",
        "object",
        "null",
    }
    if expected not in valid_types:
        return False
    if expected == "string":
        if not isinstance(value, str):
            return False
        maximum = schema.get("maxLength")
        minimum = schema.get("minLength")
        if isinstance(maximum, int) and len(value) > maximum:
            return False
        if isinstance(minimum, int) and len(value) < minimum:
            return False
    elif expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
    elif expected == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
    elif expected == "boolean" and not isinstance(value, bool):
        return False
    elif expected == "array":
        if not isinstance(value, list):
            return False
        maximum = schema.get("maxItems")
        minimum = schema.get("minItems")
        if isinstance(maximum, int) and len(value) > maximum:
            return False
        if isinstance(minimum, int) and len(value) < minimum:
            return False
        item_schema = schema.get("items")
        if item_schema is not None and (
            not isinstance(item_schema, Mapping)
            or any(not _schema_matches_value(item, item_schema, depth=depth + 1) for item in value)
        ):
            return False
    elif expected == "object":
        if not isinstance(value, Mapping):
            return False
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, Mapping) or not isinstance(required, list):
            return False
        if any(not isinstance(key, str) or key not in value for key in required):
            return False
        if schema.get("additionalProperties", True) is False and any(
            key not in properties for key in value
        ):
            return False
        for key, child in value.items():
            rule = properties.get(key)
            if rule is None:
                continue
            if not isinstance(rule, Mapping) or not _schema_matches_value(
                child,
                rule,
                depth=depth + 1,
            ):
                return False
    elif expected == "null" and value is not None:
        return False
    enum = schema.get("enum")
    return not (isinstance(enum, list) and value not in enum)


def _schema_matches(parameters: Mapping[str, Any], schema: Mapping[str, Any]) -> bool:
    """Validate the intentionally small JSON-schema subset used by ToolSpec."""

    return _schema_matches_value(parameters, schema, depth=0)


def _safe_error_code(value: str | None) -> str | None:
    """Keep handler diagnostics bounded and content-free in receipts/audits."""

    if value is None:
        return None
    if not isinstance(value, str):
        return "handler_error"
    clean = unicodedata.normalize("NFKC", value).casefold()
    return clean if _ERROR_CODE_RE.fullmatch(clean) else "handler_error"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Static contract and policy for one tool handler."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    caller_roles: frozenset[str] = frozenset({"owner"})
    surfaces: frozenset[str] = frozenset({"owner_command_private"})
    enabled: bool = False
    requires_explicit_approval: bool = True
    allow_model_execution: bool = False
    timeout_seconds: float = 5.0
    rate_limit_per_minute: int = 6
    persist_result: bool = False

    def __post_init__(self) -> None:
        if _TOOL_NAME_RE.fullmatch(self.name) is None:
            raise ToolValidationError("tool name is invalid")
        _reject_control_characters(self.description, label="tool description", max_length=512)
        if not isinstance(self.input_schema, Mapping) or self.input_schema.get("type") != "object":
            raise ToolValidationError("tool input_schema must describe an object")
        if not self.caller_roles or any(
            _ACTOR_ROLE_RE.fullmatch(role) is None for role in self.caller_roles
        ):
            raise ToolValidationError("tool caller roles are invalid")
        if not self.surfaces or any(
            not isinstance(surface, str) or not surface or len(surface) > 64
            for surface in self.surfaces
        ):
            raise ToolValidationError("tool surfaces are invalid")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not 0.01 <= self.timeout_seconds <= 300
        ):
            raise ToolValidationError("tool timeout must be between 0.01 and 300 seconds")
        if (
            isinstance(self.rate_limit_per_minute, bool)
            or not isinstance(self.rate_limit_per_minute, int)
            or not 1 <= self.rate_limit_per_minute <= 600
        ):
            raise ToolValidationError("tool rate limit must be between 1 and 600 per minute")


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """One proposed invocation, defaulting to the non-executable shadow source."""

    tool_name: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    actor_role: str = "unknown"
    actor_id: str = ""
    source: str = ToolRequestSource.MODEL_SHADOW.value
    surface: str = "unknown"
    idempotency_key: str | None = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def __post_init__(self) -> None:
        if _TOOL_NAME_RE.fullmatch(self.tool_name) is None:
            raise ToolValidationError("tool request name is invalid")
        object.__setattr__(self, "parameters", normalize_parameters(self.parameters))
        if _ACTOR_ROLE_RE.fullmatch(self.actor_role) is None:
            raise ToolValidationError("tool request actor role is invalid")
        if not isinstance(self.actor_id, str) or len(self.actor_id) > 256:
            raise ToolValidationError("tool request actor id is invalid")
        if self.actor_id:
            _reject_control_characters(self.actor_id, label="tool request actor id", max_length=256)
        if self.source not in _SOURCE_VALUES:
            raise ToolValidationError("tool request source is unknown")
        _reject_control_characters(self.surface, label="tool request surface", max_length=64)
        if not isinstance(self.request_id, str) or not 1 <= len(self.request_id) <= 128:
            raise ToolValidationError("tool request id is invalid")
        key = self.idempotency_key or self.request_id
        _reject_control_characters(key, label="tool idempotency key", max_length=256)
        object.__setattr__(self, "idempotency_key", key)
        if (
            isinstance(self.created_at_ms, bool)
            or not isinstance(self.created_at_ms, int)
            or self.created_at_ms <= 0
        ):
            raise ToolValidationError("tool request timestamp is invalid")

    @property
    def parameter_sha256(self) -> str:
        return parameter_approval_hash(self.tool_name, self.parameters)

    @property
    def approval_hash(self) -> str:
        return self.parameter_sha256


@dataclass(frozen=True, slots=True)
class ToolDecision:
    """Authorization result that must match the request before execution."""

    request_id: str
    tool_name: str
    allowed: bool = False
    reason: str = "default_deny"
    parameter_sha256: str | None = None
    decided_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    approved_by: str | None = None

    @property
    def approved(self) -> bool:
        return self.allowed

    @property
    def approval_hash(self) -> str | None:
        return self.parameter_sha256


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    """Optional typed handler result for an explicit unknown/failed outcome."""

    state: ToolReceiptState = ToolReceiptState.SUCCEEDED
    payload: Any = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        try:
            state = ToolReceiptState(self.state)
        except (TypeError, ValueError) as exc:
            raise ToolValidationError("tool handler state is invalid") from exc
        object.__setattr__(self, "state", state)


ToolResult = ToolExecutionResult
ToolHandler = Callable[[Mapping[str, Any]], Any | Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ToolReceipt:
    """Auditable result; ``UNKNOWN`` is never treated as success."""

    request_id: str
    tool_name: str
    state: ToolReceiptState
    idempotency_key: str
    parameter_sha256: str
    reason: str
    result: Any = None
    error_code: str | None = None
    audit_id: int | None = None
    started_at_ms: int | None = None
    completed_at_ms: int | None = None
    prior_state: ToolReceiptState | None = None

    def __post_init__(self) -> None:
        try:
            state = ToolReceiptState(self.state)
            prior = ToolReceiptState(self.prior_state) if self.prior_state is not None else None
        except (TypeError, ValueError) as exc:
            raise ToolValidationError("tool receipt state is invalid") from exc
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "prior_state", prior)

    @property
    def successful(self) -> bool:
        return self.state is ToolReceiptState.SUCCEEDED

    @property
    def status(self) -> ToolReceiptState:
        """Alias useful to callers that use status terminology."""

        return self.state


@dataclass(frozen=True, slots=True)
class _Reservation:
    kind: str
    request_id: str
    audit_id: int | None = None
    prior_state: ToolReceiptState | None = None
    error_code: str | None = None
    result: Any = None


class ToolAuditStore:
    """SQLite-backed audit and idempotency store with no plaintext parameters."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path.expanduser().resolve() if path is not None else None
        self._lock = threading.RLock()
        self._events: list[dict[str, Any]] = []
        self._runs: dict[str, dict[str, Any]] = {}
        if self.path is not None:
            self.initialize()

    def initialize(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=5) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    actor_sha256 TEXT NOT NULL,
                    parameter_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    error_code TEXT,
                    result_json TEXT,
                    created_at_ms INTEGER NOT NULL,
                    completed_at_ms INTEGER
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_audit_events (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    actor_sha256 TEXT NOT NULL,
                    parameter_sha256 TEXT NOT NULL,
                    state TEXT,
                    reason TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tool_audit_rate
                ON tool_audit_events(tool_name, actor_sha256, event_type, created_at_ms)
                """
            )
        with suppress(OSError):
            # Permissions are enforced by the deployment directory on systems
            # that do not permit chmod (for example, some Windows test drives).
            self.path.chmod(0o600)

    @staticmethod
    def _actor_hash(actor_id: str) -> str:
        return hashlib.sha256(actor_id.encode("utf-8")).hexdigest()

    @staticmethod
    def _state(value: str | None) -> ToolReceiptState | None:
        if value is None:
            return None
        try:
            return ToolReceiptState(value)
        except ValueError:
            return ToolReceiptState.UNKNOWN

    def _event_memory(
        self,
        *,
        event_type: str,
        request: ToolRequest,
        reason: str,
        state: ToolReceiptState | None,
        now_ms: int,
    ) -> int:
        event = {
            "event_type": event_type,
            "request_id": request.request_id,
            "idempotency_key": request.idempotency_key,
            "tool_name": request.tool_name,
            "actor_role": request.actor_role,
            "actor_sha256": self._actor_hash(request.actor_id),
            "parameter_sha256": request.parameter_sha256,
            "state": state.value if state is not None else None,
            "reason": reason,
            "created_at_ms": now_ms,
        }
        self._events.append(event)
        return len(self._events)

    def record_event(
        self,
        *,
        event_type: str,
        request: ToolRequest,
        reason: str,
        state: ToolReceiptState | None = None,
        now_ms: int,
    ) -> int:
        if self.path is None:
            with self._lock:
                return self._event_memory(
                    event_type=event_type,
                    request=request,
                    reason=reason,
                    state=state,
                    now_ms=now_ms,
                )
        try:
            with sqlite3.connect(self.path, timeout=5) as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO tool_audit_events(
                        event_type, request_id, idempotency_key, tool_name,
                        actor_role, actor_sha256, parameter_sha256, state,
                        reason, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_type,
                        request.request_id,
                        request.idempotency_key,
                        request.tool_name,
                        request.actor_role,
                        self._actor_hash(request.actor_id),
                        request.parameter_sha256,
                        state.value if state is not None else None,
                        reason,
                        now_ms,
                    ),
                )
                return int(cursor.lastrowid)
        except sqlite3.Error as exc:
            raise ToolAuditError("tool audit write failed") from exc

    def reserve(self, request: ToolRequest, spec: ToolSpec, *, now_ms: int) -> _Reservation:
        """Atomically reserve an invocation or return a persisted duplicate."""

        actor_hash = self._actor_hash(request.actor_id)
        if self.path is None:
            with self._lock:
                existing = self._runs.get(str(request.idempotency_key))
                if existing is not None:
                    same = (
                        existing["tool_name"] == request.tool_name
                        and existing["parameter_sha256"] == request.parameter_sha256
                    )
                    if not same:
                        self._event_memory(
                            event_type="idempotency_conflict",
                            request=request,
                            reason="idempotency_key_reused_for_different_request",
                            state=ToolReceiptState.DENIED,
                            now_ms=now_ms,
                        )
                        return _Reservation(
                            "conflict",
                            request.request_id,
                            error_code="idempotency_conflict",
                        )
                    self._event_memory(
                        event_type="duplicate",
                        request=request,
                        reason="idempotency_key_already_seen",
                        state=self._state(existing["state"]),
                        now_ms=now_ms,
                    )
                    result = None
                    if existing.get("result_json") is not None:
                        result = json.loads(existing["result_json"])
                    return _Reservation(
                        "duplicate",
                        str(existing["request_id"]),
                        prior_state=self._state(existing["state"]),
                        error_code=existing.get("error_code"),
                        result=result,
                    )
                recent = sum(
                    1
                    for event in self._events
                    if event["event_type"] == "reserved"
                    and event["tool_name"] == request.tool_name
                    and event["actor_sha256"] == actor_hash
                    and now_ms - int(event["created_at_ms"]) < 60_000
                )
                if recent >= spec.rate_limit_per_minute:
                    self._event_memory(
                        event_type="rate_limited",
                        request=request,
                        reason="tool_rate_limit_per_minute",
                        state=ToolReceiptState.RATE_LIMITED,
                        now_ms=now_ms,
                    )
                    return _Reservation("rate_limited", request.request_id, error_code="rate_limit")
                self._runs[str(request.idempotency_key)] = {
                    "request_id": request.request_id,
                    "tool_name": request.tool_name,
                    "parameter_sha256": request.parameter_sha256,
                    "state": ToolReceiptState.UNKNOWN.value,
                    "error_code": None,
                    "result_json": None,
                }
                audit_id = self._event_memory(
                    event_type="reserved",
                    request=request,
                    reason="execution_reserved",
                    state=None,
                    now_ms=now_ms,
                )
                return _Reservation("new", request.request_id, audit_id=audit_id)

        try:
            with sqlite3.connect(self.path, timeout=5) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM tool_idempotency WHERE idempotency_key=?",
                    (request.idempotency_key,),
                ).fetchone()
                if existing is not None:
                    same = (
                        str(existing["tool_name"]) == request.tool_name
                        and str(existing["parameter_sha256"]) == request.parameter_sha256
                    )
                    reason = (
                        "idempotency_key_reused_for_different_request"
                        if not same
                        else "idempotency_key_already_seen"
                    )
                    state = ToolReceiptState.DENIED if not same else self._state(existing["state"])
                    cursor = connection.execute(
                        """
                        INSERT INTO tool_audit_events(
                            event_type, request_id, idempotency_key, tool_name,
                            actor_role, actor_sha256, parameter_sha256, state,
                            reason, created_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "idempotency_conflict" if not same else "duplicate",
                            request.request_id,
                            request.idempotency_key,
                            request.tool_name,
                            request.actor_role,
                            actor_hash,
                            request.parameter_sha256,
                            state.value if state is not None else None,
                            reason,
                            now_ms,
                        ),
                    )
                    if not same:
                        return _Reservation(
                            "conflict",
                            request.request_id,
                            audit_id=int(cursor.lastrowid),
                            error_code="idempotency_conflict",
                        )
                    result = None
                    if existing["result_json"] is not None:
                        try:
                            result = json.loads(str(existing["result_json"]))
                        except json.JSONDecodeError:
                            result = None
                    return _Reservation(
                        "duplicate",
                        str(existing["request_id"]),
                        audit_id=int(cursor.lastrowid),
                        prior_state=state,
                        error_code=str(existing["error_code"]) if existing["error_code"] else None,
                        result=result,
                    )
                recent = connection.execute(
                    """
                    SELECT COUNT(*) FROM tool_audit_events
                    WHERE event_type='reserved' AND tool_name=? AND actor_sha256=?
                      AND created_at_ms>=?
                    """,
                    (request.tool_name, actor_hash, now_ms - 60_000),
                ).fetchone()
                if recent is None or int(recent[0]) >= spec.rate_limit_per_minute:
                    cursor = connection.execute(
                        """
                        INSERT INTO tool_audit_events(
                            event_type, request_id, idempotency_key, tool_name,
                            actor_role, actor_sha256, parameter_sha256, state,
                            reason, created_at_ms
                        ) VALUES ('rate_limited', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            request.request_id,
                            request.idempotency_key,
                            request.tool_name,
                            request.actor_role,
                            actor_hash,
                            request.parameter_sha256,
                            ToolReceiptState.RATE_LIMITED.value,
                            "tool_rate_limit_per_minute",
                            now_ms,
                        ),
                    )
                    return _Reservation(
                        "rate_limited",
                        request.request_id,
                        audit_id=int(cursor.lastrowid),
                        error_code="rate_limit",
                    )
                connection.execute(
                    """
                    INSERT INTO tool_idempotency(
                        idempotency_key, request_id, tool_name, actor_role,
                        actor_sha256, parameter_sha256, state, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request.idempotency_key,
                        request.request_id,
                        request.tool_name,
                        request.actor_role,
                        actor_hash,
                        request.parameter_sha256,
                        ToolReceiptState.UNKNOWN.value,
                        now_ms,
                    ),
                )
                cursor = connection.execute(
                    """
                    INSERT INTO tool_audit_events(
                        event_type, request_id, idempotency_key, tool_name,
                        actor_role, actor_sha256, parameter_sha256, state,
                        reason, created_at_ms
                    ) VALUES ('reserved', ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        request.request_id,
                        request.idempotency_key,
                        request.tool_name,
                        request.actor_role,
                        actor_hash,
                        request.parameter_sha256,
                        "execution_reserved",
                        now_ms,
                    ),
                )
                return _Reservation("new", request.request_id, audit_id=int(cursor.lastrowid))
        except sqlite3.Error as exc:
            raise ToolAuditError("tool reservation failed") from exc

    def complete(
        self,
        request: ToolRequest,
        *,
        state: ToolReceiptState,
        reason: str,
        error_code: str | None,
        result: Any,
        persist_result: bool,
        now_ms: int,
    ) -> int:
        result_json: str | None = None
        if persist_result and result is not None:
            try:
                result_json = json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            except (TypeError, ValueError) as exc:
                raise ToolAuditError("tool result could not be persisted") from exc
            if len(result_json.encode("utf-8")) > _MAX_RESULT_BYTES:
                raise ToolAuditError("tool result exceeded audit size limit")
        actor_hash = self._actor_hash(request.actor_id)
        if self.path is None:
            with self._lock:
                run = self._runs.get(str(request.idempotency_key))
                if run is None:
                    raise ToolAuditError("tool idempotency reservation is missing")
                run.update(
                    {
                        "state": state.value,
                        "error_code": error_code,
                        "result_json": result_json,
                    }
                )
                return self._event_memory(
                    event_type="completed",
                    request=request,
                    reason=reason,
                    state=state,
                    now_ms=now_ms,
                )
        try:
            with sqlite3.connect(self.path, timeout=5) as connection:
                connection.execute(
                    """
                    UPDATE tool_idempotency
                    SET state=?, error_code=?, result_json=?, completed_at_ms=?
                    WHERE idempotency_key=? AND tool_name=? AND parameter_sha256=?
                    """,
                    (
                        state.value,
                        error_code,
                        result_json,
                        now_ms,
                        request.idempotency_key,
                        request.tool_name,
                        request.parameter_sha256,
                    ),
                )
                cursor = connection.execute(
                    """
                    INSERT INTO tool_audit_events(
                        event_type, request_id, idempotency_key, tool_name,
                        actor_role, actor_sha256, parameter_sha256, state,
                        reason, created_at_ms
                    ) VALUES ('completed', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request.request_id,
                        request.idempotency_key,
                        request.tool_name,
                        request.actor_role,
                        actor_hash,
                        request.parameter_sha256,
                        state.value,
                        reason,
                        now_ms,
                    ),
                )
                return int(cursor.lastrowid)
        except sqlite3.Error as exc:
            raise ToolAuditError("tool completion audit failed") from exc

    def events(self) -> tuple[dict[str, Any], ...]:
        """Return metadata-only events for diagnostics and tests."""

        if self.path is None:
            with self._lock:
                return tuple(dict(event) for event in self._events)
        try:
            with sqlite3.connect(self.path, timeout=5) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    "SELECT * FROM tool_audit_events ORDER BY audit_id"
                ).fetchall()
            return tuple(dict(row) for row in rows)
        except sqlite3.Error as exc:
            raise ToolAuditError("tool audit read failed") from exc


class ToolRegistry:
    """Explicit map of descriptors and handlers; unknown names fail closed."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._specs:
            raise ToolValidationError("tool name is already registered")
        if not callable(handler):
            raise ToolValidationError("tool handler must be callable")
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise ToolValidationError("unknown tool") from exc

    def handler(self, name: str) -> ToolHandler:
        try:
            return self._handlers[name]
        except KeyError as exc:
            raise ToolValidationError("unknown tool") from exc

    def has(self, name: str) -> bool:
        return name in self._specs

    def list(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs[name] for name in sorted(self._specs))


class ToolGovernance:
    """Authorize and execute tools only after all safety gates pass."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        *,
        audit: ToolAuditStore | None = None,
        audit_path: Path | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        if audit is not None and audit_path is not None:
            raise ValueError("pass audit or audit_path, not both")
        self.registry = registry or ToolRegistry()
        self.audit = audit or ToolAuditStore(audit_path)
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        self.registry.register(spec, handler)

    def authorize(
        self,
        request: ToolRequest,
        *,
        approved: bool = False,
        approved_by: str | None = None,
    ) -> ToolDecision:
        """Explicit alias for callers that use authorization terminology."""

        return self.decide(request, approved=approved, approved_by=approved_by)

    def decide(
        self,
        request: ToolRequest,
        *,
        approved: bool = False,
        approved_by: str | None = None,
    ) -> ToolDecision:
        now = self._clock_ms()
        parameter_sha256 = request.parameter_sha256
        try:
            spec = self.registry.get(request.tool_name)
        except ToolValidationError:
            return self._deny(request, "unknown_tool", parameter_sha256, now)
        if not spec.enabled:
            return self._deny(request, "tool_disabled", parameter_sha256, now)
        if request.actor_role not in spec.caller_roles:
            return self._deny(request, "caller_role_not_allowed", parameter_sha256, now)
        if request.surface not in spec.surfaces:
            return self._deny(request, "surface_not_allowed", parameter_sha256, now)
        if (
            request.source == ToolRequestSource.MODEL_SHADOW.value
            and not spec.allow_model_execution
        ):
            return self._deny(request, "model_shadow_only", parameter_sha256, now)
        if request.source not in _SOURCE_VALUES:
            return self._deny(request, "source_not_allowed", parameter_sha256, now)
        if not _schema_matches(request.parameters, spec.input_schema):
            return self._deny(request, "invalid_parameters", parameter_sha256, now)
        if spec.requires_explicit_approval and not approved:
            return self._deny(request, "default_deny", parameter_sha256, now)
        if spec.requires_explicit_approval and not approved_by:
            return self._deny(request, "approval_principal_missing", parameter_sha256, now)
        if spec.requires_explicit_approval and approved_by != request.actor_id:
            return self._deny(request, "approval_principal_mismatch", parameter_sha256, now)
        if request.source == ToolRequestSource.SYSTEM.value and request.actor_role != "system":
            return self._deny(request, "system_source_role_mismatch", parameter_sha256, now)
        return ToolDecision(
            request_id=request.request_id,
            tool_name=request.tool_name,
            allowed=True,
            reason="explicit_approval",
            parameter_sha256=parameter_sha256,
            decided_at_ms=now,
            approved_by=approved_by,
        )

    def _deny(
        self,
        request: ToolRequest,
        reason: str,
        parameter_sha256: str,
        now_ms: int,
    ) -> ToolDecision:
        return ToolDecision(
            request_id=request.request_id,
            tool_name=request.tool_name,
            allowed=False,
            reason=reason,
            parameter_sha256=parameter_sha256,
            decided_at_ms=now_ms,
        )

    def _denied_receipt(self, request: ToolRequest, decision: ToolDecision) -> ToolReceipt:
        now = self._clock_ms()
        try:
            audit_id = self.audit.record_event(
                event_type="decision",
                request=request,
                reason=decision.reason,
                state=ToolReceiptState.DENIED,
                now_ms=now,
            )
        except ToolAuditError:
            audit_id = None
        return ToolReceipt(
            request_id=request.request_id,
            tool_name=request.tool_name,
            state=ToolReceiptState.DENIED,
            idempotency_key=str(request.idempotency_key),
            parameter_sha256=request.parameter_sha256,
            reason=decision.reason,
            error_code=decision.reason,
            audit_id=audit_id,
            completed_at_ms=now,
        )

    def _preflight(
        self,
        request: ToolRequest,
        decision: ToolDecision | None,
    ) -> tuple[ToolSpec, ToolDecision] | ToolReceipt:
        chosen = decision or self.decide(request)
        if (
            chosen.request_id != request.request_id
            or chosen.tool_name != request.tool_name
            or chosen.parameter_sha256 != request.parameter_sha256
        ):
            return self._denied_receipt(
                request,
                ToolDecision(
                    request_id=request.request_id,
                    tool_name=request.tool_name,
                    reason="decision_mismatch",
                    parameter_sha256=request.parameter_sha256,
                    decided_at_ms=self._clock_ms(),
                ),
            )
        if not chosen.allowed:
            return self._denied_receipt(request, chosen)
        # ToolDecision is a public value object, so do not trust a caller-built
        # ``allowed=True`` instance.  Re-evaluate role, surface, source, schema,
        # and approval principal before opening the execution gate.
        validated = self.decide(
            request,
            approved=True,
            approved_by=chosen.approved_by,
        )
        if not validated.allowed:
            return self._denied_receipt(request, validated)
        try:
            return self.registry.get(request.tool_name), chosen
        except ToolValidationError:
            return self._denied_receipt(
                request,
                ToolDecision(
                    request_id=request.request_id,
                    tool_name=request.tool_name,
                    reason="unknown_tool",
                    parameter_sha256=request.parameter_sha256,
                    decided_at_ms=self._clock_ms(),
                ),
            )

    @staticmethod
    async def _call(handler: ToolHandler, parameters: Mapping[str, Any]) -> Any:
        # Calling in a worker prevents a synchronous local handler from blocking
        # the event loop.  Native async handlers must be called in the event
        # loop first; otherwise a very small timeout can cancel the worker
        # before it ever awaits the coroutine, leaking an unawaited coroutine.
        if inspect.iscoroutinefunction(handler) or inspect.iscoroutinefunction(handler.__call__):
            value = handler(parameters)
            if inspect.isawaitable(value):
                return await value
            return value
        value = await asyncio.to_thread(handler, parameters)
        if inspect.isawaitable(value):
            return await value
        return value

    @staticmethod
    def _classify(value: Any) -> ToolExecutionResult:
        if isinstance(value, ToolExecutionResult):
            if value.state not in {
                ToolReceiptState.SUCCEEDED,
                ToolReceiptState.FAILED,
                ToolReceiptState.UNKNOWN,
            }:
                return ToolExecutionResult(
                    ToolReceiptState.FAILED,
                    error_code="invalid_handler_state",
                )
            return value
        if isinstance(value, ToolReceipt):
            return ToolExecutionResult(value.state, value.result, value.error_code)
        return ToolExecutionResult(payload=value)

    @staticmethod
    def _validate_result(result: Any) -> Any:
        try:
            encoded = json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ToolValidationError("tool result is not safe JSON") from exc
        if len(encoded.encode("utf-8")) > _MAX_RESULT_BYTES:
            raise ToolValidationError("tool result exceeded size limit")
        return json.loads(encoded)

    async def execute(
        self,
        request: ToolRequest,
        *,
        decision: ToolDecision | None = None,
    ) -> ToolReceipt:
        """Execute only an approved request and return a non-ambiguous receipt."""

        preflight = self._preflight(request, decision)
        if isinstance(preflight, ToolReceipt):
            return preflight
        spec, _ = preflight
        started = self._clock_ms()
        try:
            reservation = self.audit.reserve(request, spec, now_ms=started)
        except ToolAuditError:
            return ToolReceipt(
                request_id=request.request_id,
                tool_name=request.tool_name,
                state=ToolReceiptState.UNKNOWN,
                idempotency_key=str(request.idempotency_key),
                parameter_sha256=request.parameter_sha256,
                reason="audit_reservation_failed",
                error_code="audit_unavailable",
                started_at_ms=started,
                completed_at_ms=self._clock_ms(),
            )
        if reservation.kind == "duplicate":
            state = ToolReceiptState.DUPLICATE
            if reservation.prior_state is ToolReceiptState.UNKNOWN:
                # A previous process may have died while the handler was in
                # flight.  Never retry an unknown operation automatically.
                state = ToolReceiptState.UNKNOWN
            return ToolReceipt(
                request_id=request.request_id,
                tool_name=request.tool_name,
                state=state,
                idempotency_key=str(request.idempotency_key),
                parameter_sha256=request.parameter_sha256,
                reason="idempotency_key_already_seen",
                result=reservation.result,
                error_code=reservation.error_code,
                audit_id=reservation.audit_id,
                prior_state=reservation.prior_state,
                completed_at_ms=self._clock_ms(),
            )
        if reservation.kind == "rate_limited":
            return ToolReceipt(
                request_id=request.request_id,
                tool_name=request.tool_name,
                state=ToolReceiptState.RATE_LIMITED,
                idempotency_key=str(request.idempotency_key),
                parameter_sha256=request.parameter_sha256,
                reason="tool_rate_limit_per_minute",
                error_code=reservation.error_code,
                audit_id=reservation.audit_id,
                completed_at_ms=self._clock_ms(),
            )
        if reservation.kind == "conflict":
            return ToolReceipt(
                request_id=request.request_id,
                tool_name=request.tool_name,
                state=ToolReceiptState.DENIED,
                idempotency_key=str(request.idempotency_key),
                parameter_sha256=request.parameter_sha256,
                reason="idempotency_key_reused_for_different_request",
                error_code=reservation.error_code,
                audit_id=reservation.audit_id,
                completed_at_ms=self._clock_ms(),
            )
        try:
            raw = await asyncio.wait_for(
                self._call(self.registry.handler(request.tool_name), request.parameters),
                timeout=spec.timeout_seconds,
            )
            execution = self._classify(raw)
            safe_result = self._validate_result(execution.payload)
            state = execution.state
            reason = (
                "execution_completed"
                if state is ToolReceiptState.SUCCEEDED
                else "handler_reported_unknown"
            )
            error_code = _safe_error_code(execution.error_code)
        except TimeoutError:
            state = ToolReceiptState.TIMED_OUT
            safe_result = None
            reason = "tool_timeout"
            error_code = "timeout"
        except ToolValidationError as exc:
            state = ToolReceiptState.FAILED
            safe_result = None
            reason = "invalid_tool_result"
            error_code = _safe_error_code(str(exc))
        except asyncio.CancelledError:
            state = ToolReceiptState.UNKNOWN
            safe_result = None
            reason = "execution_cancelled"
            error_code = "cancelled"
        except Exception as exc:  # handler failures never escape as success
            state = ToolReceiptState.FAILED
            safe_result = None
            reason = "handler_failed"
            error_code = _safe_error_code(type(exc).__name__)
        try:
            audit_id = self.audit.complete(
                request,
                state=state,
                reason=reason,
                error_code=error_code,
                result=safe_result,
                persist_result=spec.persist_result and state is ToolReceiptState.SUCCEEDED,
                now_ms=self._clock_ms(),
            )
        except ToolAuditError:
            # The side effect may have happened, but the durable receipt did
            # not.  Surface UNKNOWN so an operator cannot mistake it for a
            # success and blindly retry.
            state = ToolReceiptState.UNKNOWN
            safe_result = None
            reason = "audit_completion_failed"
            error_code = "audit_unavailable"
            audit_id = None
        return ToolReceipt(
            request_id=request.request_id,
            tool_name=request.tool_name,
            state=state,
            idempotency_key=str(request.idempotency_key),
            parameter_sha256=request.parameter_sha256,
            reason=reason,
            result=safe_result,
            error_code=error_code,
            audit_id=audit_id,
            started_at_ms=started,
            completed_at_ms=self._clock_ms(),
        )

    def execute_sync(
        self,
        request: ToolRequest,
        *,
        decision: ToolDecision | None = None,
    ) -> ToolReceipt:
        """Run a bounded synchronous handler for deterministic command paths.

        Synchronous owner commands are intentionally limited to local read-only
        handlers.  A slow synchronous handler cannot be interrupted safely by
        CPython, so elapsed time is checked and reported as ``TIMED_OUT`` after
        it returns; network/side-effectful tools must use :meth:`execute`.
        """

        preflight = self._preflight(request, decision)
        if isinstance(preflight, ToolReceipt):
            return preflight
        spec, _ = preflight
        started = self._clock_ms()
        try:
            reservation = self.audit.reserve(request, spec, now_ms=started)
        except ToolAuditError:
            return ToolReceipt(
                request_id=request.request_id,
                tool_name=request.tool_name,
                state=ToolReceiptState.UNKNOWN,
                idempotency_key=str(request.idempotency_key),
                parameter_sha256=request.parameter_sha256,
                reason="audit_reservation_failed",
                error_code="audit_unavailable",
                started_at_ms=started,
                completed_at_ms=self._clock_ms(),
            )
        if reservation.kind != "new":
            state = (
                ToolReceiptState.DUPLICATE
                if reservation.kind == "duplicate"
                else (
                    ToolReceiptState.RATE_LIMITED
                    if reservation.kind == "rate_limited"
                    else ToolReceiptState.DENIED
                )
            )
            if (
                reservation.kind == "duplicate"
                and reservation.prior_state is ToolReceiptState.UNKNOWN
            ):
                state = ToolReceiptState.UNKNOWN
            return ToolReceipt(
                request_id=request.request_id,
                tool_name=request.tool_name,
                state=state,
                idempotency_key=str(request.idempotency_key),
                parameter_sha256=request.parameter_sha256,
                reason={
                    "duplicate": "idempotency_key_already_seen",
                    "rate_limited": "tool_rate_limit_per_minute",
                    "conflict": "idempotency_key_reused_for_different_request",
                }.get(reservation.kind, "reservation_failed"),
                result=reservation.result,
                error_code=reservation.error_code,
                audit_id=reservation.audit_id,
                prior_state=reservation.prior_state,
                completed_at_ms=self._clock_ms(),
            )
        try:
            raw = self.registry.handler(request.tool_name)(request.parameters)
            if inspect.isawaitable(raw):
                raise ToolValidationError("async handler requires execute()")
            execution = self._classify(raw)
            safe_result = self._validate_result(execution.payload)
            elapsed_ms = self._clock_ms() - started
            if elapsed_ms > int(spec.timeout_seconds * 1000):
                state = ToolReceiptState.TIMED_OUT
                safe_result = None
                reason = "tool_timeout"
                error_code = "timeout"
            else:
                state = execution.state
                reason = (
                    "execution_completed"
                    if state is ToolReceiptState.SUCCEEDED
                    else "handler_reported_unknown"
                )
                error_code = _safe_error_code(execution.error_code)
        except ToolValidationError as exc:
            state = ToolReceiptState.FAILED
            safe_result = None
            reason = "invalid_tool_result"
            error_code = _safe_error_code(str(exc))
        except Exception as exc:
            state = ToolReceiptState.FAILED
            safe_result = None
            reason = "handler_failed"
            error_code = _safe_error_code(type(exc).__name__)
        try:
            audit_id = self.audit.complete(
                request,
                state=state,
                reason=reason,
                error_code=error_code,
                result=safe_result,
                persist_result=spec.persist_result and state is ToolReceiptState.SUCCEEDED,
                now_ms=self._clock_ms(),
            )
        except ToolAuditError:
            state = ToolReceiptState.UNKNOWN
            safe_result = None
            reason = "audit_completion_failed"
            error_code = "audit_unavailable"
            audit_id = None
        return ToolReceipt(
            request_id=request.request_id,
            tool_name=request.tool_name,
            state=state,
            idempotency_key=str(request.idempotency_key),
            parameter_sha256=request.parameter_sha256,
            reason=reason,
            result=safe_result,
            error_code=error_code,
            audit_id=audit_id,
            started_at_ms=started,
            completed_at_ms=self._clock_ms(),
        )


# Small aliases keep the boundary discoverable without introducing a second
# implementation or a second set of receipt states.
ToolExecutor = ToolGovernance
ToolStatus = ToolReceiptState
