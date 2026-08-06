"""Governed skill metadata and parameter-bound owner approvals.

The registry is deliberately transport-neutral.  Registering a descriptor does not
enable execution; callers must still pass the descriptor's role/surface policy and,
when required, present an approval for the exact normalized input parameters.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class ApprovalMode(StrEnum):
    NONE = "none"
    OWNER_CONFIRM = "owner_confirm"
    OWNER_PREAUTHORIZED = "owner_preauthorized"


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any]
    caller_roles: frozenset[str]
    surfaces: frozenset[str]
    external_side_effects: bool
    approval_mode: ApprovalMode
    idempotency_strategy: str
    audit_policy: str
    timeout_seconds: int
    enabled: bool = False


def normalized_parameter_hash(parameters: dict[str, Any]) -> str:
    """Return a stable hash without retaining parameter plaintext in approvals."""
    encoded = json.dumps(
        parameters,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SkillRegistry:
    def __init__(self) -> None:
        self._descriptors: dict[str, SkillDescriptor] = {}

    def register(self, descriptor: SkillDescriptor) -> None:
        if not descriptor.name or descriptor.name in self._descriptors:
            raise ValueError("skill name is empty or already registered")
        if not 1 <= descriptor.timeout_seconds <= 3600:
            raise ValueError("skill timeout must be between 1 and 3600 seconds")
        self._descriptors[descriptor.name] = descriptor

    def get(self, name: str) -> SkillDescriptor:
        try:
            return self._descriptors[name]
        except KeyError as exc:
            raise LookupError("unknown skill") from exc

    def list(self) -> tuple[SkillDescriptor, ...]:
        return tuple(self._descriptors[name] for name in sorted(self._descriptors))

    def authorize_surface(self, name: str, *, caller_role: str, surface: str) -> bool:
        """Fail closed when the descriptor is disabled or scope does not match."""
        try:
            descriptor = self.get(name)
        except LookupError:
            return False
        return (
            descriptor.enabled
            and caller_role in descriptor.caller_roles
            and surface in descriptor.surfaces
        )

    def authorize_execution(
        self,
        name: str,
        *,
        caller_role: str,
        surface: str,
        parameters: dict[str, Any],
        approvals: SkillApprovalStore | None,
        now_ms: int | None = None,
    ) -> bool:
        """Authorize one exact invocation, failing closed on every uncertainty.

        Surface authorization alone is intentionally insufficient for skills that
        require approval.  The persisted approval includes both the skill name and
        canonical parameter hash, so even a one-field change requires approval again.
        """
        try:
            descriptor = self.get(name)
            if not self.authorize_surface(name, caller_role=caller_role, surface=surface):
                return False
            if not _parameters_match_schema(parameters, descriptor.input_schema):
                return False
            if descriptor.approval_mode is ApprovalMode.NONE:
                return True
            if approvals is None:
                return False
            return approvals.is_approved(name, parameters, now_ms=now_ms)
        except (LookupError, TypeError, ValueError):
            return False


def _parameters_match_schema(parameters: dict[str, Any], schema: dict[str, Any]) -> bool:
    """Validate the deliberately small JSON-schema subset used by skill metadata."""
    if schema.get("type") != "object" or not isinstance(parameters, dict):
        return False
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        return False
    if any(not isinstance(name, str) or name not in parameters for name in required):
        return False
    if schema.get("additionalProperties") is False and any(
        key not in properties for key in parameters
    ):
        return False
    for name, value in parameters.items():
        rule = properties.get(name)
        if not isinstance(rule, dict):
            continue
        expected = rule.get("type")
        if expected == "string":
            if not isinstance(value, str):
                return False
            maximum = rule.get("maxLength")
            if isinstance(maximum, int) and len(value) > maximum:
                return False
        elif expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            return False
    return True


class SkillApprovalStore:
    """Persist approvals for exactly one skill and one normalized parameter set."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_approvals (
                    skill_name TEXT NOT NULL,
                    parameter_sha256 TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    approved_at_ms INTEGER NOT NULL,
                    expires_at_ms INTEGER,
                    revoked_at_ms INTEGER,
                    PRIMARY KEY(skill_name, parameter_sha256)
                )
                """
            )

    def approve(
        self,
        skill_name: str,
        parameters: dict[str, Any],
        *,
        approved_by: str,
        expires_at_ms: int | None = None,
        now_ms: int | None = None,
    ) -> str:
        digest = normalized_parameter_hash(parameters)
        now = int(time.time() * 1000) if now_ms is None else now_ms
        if expires_at_ms is not None and expires_at_ms <= now:
            raise ValueError("approval expiry must be in the future")
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO skill_approvals(
                    skill_name, parameter_sha256, approved_by, approved_at_ms,
                    expires_at_ms, revoked_at_ms
                ) VALUES (?, ?, ?, ?, ?, NULL)
                ON CONFLICT(skill_name, parameter_sha256) DO UPDATE SET
                    approved_by=excluded.approved_by,
                    approved_at_ms=excluded.approved_at_ms,
                    expires_at_ms=excluded.expires_at_ms,
                    revoked_at_ms=NULL
                """,
                (skill_name, digest, approved_by, now, expires_at_ms),
            )
        return digest

    def is_approved(
        self,
        skill_name: str,
        parameters: dict[str, Any],
        *,
        now_ms: int | None = None,
    ) -> bool:
        digest = normalized_parameter_hash(parameters)
        now = int(time.time() * 1000) if now_ms is None else now_ms
        try:
            with sqlite3.connect(self.path) as conn:
                row = conn.execute(
                    """
                    SELECT expires_at_ms, revoked_at_ms FROM skill_approvals
                    WHERE skill_name=? AND parameter_sha256=?
                    """,
                    (skill_name, digest),
                ).fetchone()
        except sqlite3.Error:
            return False
        if row is None or row[1] is not None:
            return False
        return row[0] is None or int(row[0]) > now

    def revoke(
        self, skill_name: str, parameters: dict[str, Any], *, now_ms: int | None = None
    ) -> bool:
        digest = normalized_parameter_hash(parameters)
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                """
                UPDATE skill_approvals SET revoked_at_ms=?
                WHERE skill_name=? AND parameter_sha256=? AND revoked_at_ms IS NULL
                """,
                (now, skill_name, digest),
            )
        return cursor.rowcount == 1


def default_skill_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(
        SkillDescriptor(
            name="reminder",
            description="Create and deliver an owner reminder after explicit confirmation.",
            input_schema={
                "type": "object",
                "required": ["content", "due_at_ms", "origin_conversation_id"],
                "properties": {
                    "content": {"type": "string", "maxLength": 500},
                    "due_at_ms": {"type": "integer"},
                    "origin_conversation_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            caller_roles=frozenset({"owner"}),
            surfaces=frozenset({"private", "group"}),
            external_side_effects=True,
            approval_mode=ApprovalMode.OWNER_CONFIRM,
            idempotency_strategy="reminder occurrence key (job UUID + attempt)",
            audit_policy="hash parameters; retain transitions and OneBot receipt",
            timeout_seconds=15,
            enabled=True,
        )
    )
    disabled = (
        ("server_alert", "Server and project health alerts."),
        ("group_summary", "Owner-approved group conversation summaries."),
        ("study_training_plan", "Study and training plan assistance."),
        ("furcolor_status", "Read-only FurColor task status."),
    )
    for name, description in disabled:
        registry.register(
            SkillDescriptor(
                name=name,
                description=description,
                input_schema={"type": "object", "additionalProperties": False},
                caller_roles=frozenset({"owner"}),
                surfaces=frozenset({"private"}),
                external_side_effects=False,
                approval_mode=ApprovalMode.OWNER_PREAUTHORIZED,
                idempotency_strategy="not implemented",
                audit_policy="metadata only; execution disabled",
                timeout_seconds=10,
                enabled=False,
            )
        )
    return registry
