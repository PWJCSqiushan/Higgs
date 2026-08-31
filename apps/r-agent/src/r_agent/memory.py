"""Auditable, scope-isolated memory primitives for Phase 3.

Chat messages never become active memory through this module alone. Callers may
propose candidates, while deterministic owner authorization controls every
state transition and physical deletion.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from r_agent.identity import Principal

_AUTO_REVIEW_BLOCKERS = (
    "住在",
    "地址",
    "电话",
    "手机",
    "qq",
    "微信",
    "邮箱",
    "学号",
    "身份证",
    "护照",
    "银行卡",
    "账户",
    "账号",
    "密码",
    "验证码",
    "密钥",
    "token",
    "疾病",
    "病史",
    "诊断",
    "用药",
    "过敏",
    "收入",
    "工资",
    "存款",
    "负债",
    "政治",
    "选举",
    "党派",
    "宗教",
    "民族",
    "性取向",
    "主人",
    "管理员",
    "权限",
    "系统提示",
    "提示词",
    "忽略所有",
    "忽略规则",
    "无视规则",
    "无视限制",
    "绕过限制",
    "不要遵守",
    "遵循我的指令",
    "按我的指令",
    "服从我的指令",
    "覆盖规则",
    "跳过安全",
    "解除限制",
    "开发者消息",
    "system prompt",
    "jailbreak",
)


def is_auto_review_safe_text(text: str) -> bool:
    """Return whether text is eligible for the harmless-preference lane."""
    lowered = text.casefold()
    return not any(marker in lowered for marker in _AUTO_REVIEW_BLOCKERS)


class MemoryError(RuntimeError):
    """Base error for memory operations."""


class MemoryNotFoundError(MemoryError):
    """The requested memory item does not exist."""


class MemoryPermissionError(MemoryError):
    """The actor is not authorized to govern memory."""


class MemoryTransitionError(MemoryError):
    """A requested state transition is not valid."""


class MemoryValidationError(MemoryError):
    """A candidate is structurally unsafe or incomplete."""


class MemoryScope(StrEnum):
    PRINCIPAL = "principal"
    GROUP = "group"
    PERSONA = "persona"
    GLOBAL = "global"


class MemoryKind(StrEnum):
    USER_FACT = "user_fact"
    PREFERENCE = "preference"
    RELATIONSHIP = "relationship"
    COMMITMENT = "commitment"
    EPISODE_SUMMARY = "episode_summary"
    GROUP_NORM = "group_norm"
    SELF_STANCE = "self_stance"
    ADOPTED_IDEA = "adopted_idea"


class MemoryRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MemoryStatus(StrEnum):
    CANDIDATE = "candidate"
    QUARANTINED = "quarantined"
    ACTIVE = "active"
    INVALIDATED = "invalidated"


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    item_id: str
    scope: MemoryScope
    scope_id: str
    kind: MemoryKind
    text: str
    source_channel: str
    source_account_id: str
    source_message_id: str
    source_principal_id: str
    source_principal_role: str
    created_by: str
    risk: MemoryRisk
    confidence: float
    status: MemoryStatus
    created_at_ms: int
    reviewed_at_ms: int | None
    reviewed_by: str | None
    invalidated_reason: str | None
    embedding_dim: int | None
    importance: float
    source_trust: float
    valid_from_ms: int
    valid_to_ms: int | None
    supersedes_item_id: str | None


@dataclass(frozen=True, slots=True)
class MemoryAuditRecord:
    audit_id: int
    item_id: str
    action: str
    actor_principal_id: str
    actor_role: str
    details_sha256: str
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class MemoryAutoReviewOutcome:
    """Result of the narrow, deterministic automatic-review gate."""

    record: MemoryRecord
    decision: str
    evidence_count: int


class MemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(
        self,
        *,
        self_memory_v4: bool = False,
        personal_memory_v5: bool = False,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            # Keep all schema changes in one transaction.  In particular, the
            # v4 kind expansion requires rebuilding the old CHECK-constrained
            # table on SQLite (SQLite cannot ALTER a CHECK constraint).  A
            # failed rebuild therefore leaves the pre-migration table intact.
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    item_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    scope_type TEXT NOT NULL
                        CHECK(scope_type IN ('principal','group','persona','global')),
                    scope_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN (
                        'user_fact','preference','relationship','commitment',
                        'episode_summary','group_norm'
                    )),
                    text TEXT NOT NULL,
                    source_channel TEXT NOT NULL,
                    source_account_id TEXT NOT NULL,
                    source_message_id TEXT NOT NULL,
                    source_principal_id TEXT NOT NULL,
                    source_principal_role TEXT NOT NULL DEFAULT 'user',
                    created_by TEXT NOT NULL,
                    risk TEXT NOT NULL CHECK(risk IN ('low','medium','high')),
                    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
                    status TEXT NOT NULL CHECK(status IN (
                        'candidate','quarantined','active','invalidated'
                    )),
                    created_at_ms INTEGER NOT NULL,
                    reviewed_at_ms INTEGER,
                    reviewed_by TEXT,
                    invalidated_reason TEXT,
                    embedding BLOB,
                    embedding_dim INTEGER,
                    importance REAL NOT NULL DEFAULT 0.5,
                    source_trust REAL NOT NULL DEFAULT 0.5,
                    valid_from_ms INTEGER NOT NULL DEFAULT 0,
                    valid_to_ms INTEGER,
                    supersedes_item_id TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_schema_versions (
                    version INTEGER PRIMARY KEY,
                    applied_at_ms INTEGER NOT NULL
                )
                """
            )
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(memory_items)")}
            for name, definition in (
                ("importance", "REAL NOT NULL DEFAULT 0.5"),
                ("source_trust", "REAL NOT NULL DEFAULT 0.5"),
                ("valid_from_ms", "INTEGER NOT NULL DEFAULT 0"),
                ("valid_to_ms", "INTEGER"),
                ("supersedes_item_id", "TEXT"),
                ("source_principal_role", "TEXT NOT NULL DEFAULT 'user'"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE memory_items ADD COLUMN {name} {definition}")
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_schema_versions(version, applied_at_ms)
                VALUES (2, ?)
                """,
                (int(time.time() * 1000),),
            )
            applied_versions = {
                int(row[0]) for row in conn.execute("SELECT version FROM memory_schema_versions")
            }
            if 3 not in applied_versions:
                # Older SQLite builds can retain pre-ALTER records without materializing
                # newly added NOT NULL defaults.  Reads still expose the defaults, but
                # PRAGMA integrity_check reports the underlying fields as NULL.  Rewrite
                # each row once so verified backups cannot inherit that legacy encoding.
                conn.execute(
                    """
                    UPDATE memory_items
                    SET importance = COALESCE(importance, 0.5),
                        source_trust = COALESCE(source_trust, 0.5),
                        valid_from_ms = COALESCE(valid_from_ms, 0),
                        source_principal_role = COALESCE(source_principal_role, 'user')
                    """
                )
                conn.execute(
                    """
                    INSERT INTO memory_schema_versions(version, applied_at_ms)
                    VALUES (3, ?)
                    """,
                    (int(time.time() * 1000),),
                )

            # v4 extends the kind constraint while preserving every legacy
            # row.  Rebuild only when the existing table definition does not
            # already contain the two new kinds; fresh databases are created
            # with the expanded definition above.
            table_sql_row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_items'"
            ).fetchone()
            table_sql = str(table_sql_row[0] or "").casefold() if table_sql_row else ""
            applied_versions = {
                int(row[0]) for row in conn.execute("SELECT version FROM memory_schema_versions")
            }
            if self_memory_v4 and 4 not in applied_versions:
                if "self_stance" not in table_sql or "adopted_idea" not in table_sql:
                    legacy_name = "memory_items_v3_legacy"
                    conn.execute(f"DROP TABLE IF EXISTS {legacy_name}")
                    # The index belongs to the old table and would otherwise
                    # collide with the replacement index name.
                    conn.execute("DROP INDEX IF EXISTS idx_memory_scope_status")
                    conn.execute(f"ALTER TABLE memory_items RENAME TO {legacy_name}")
                    conn.execute(
                        """
                        CREATE TABLE memory_items (
                            item_id TEXT PRIMARY KEY,
                            fingerprint TEXT NOT NULL UNIQUE,
                            scope_type TEXT NOT NULL
                                CHECK(scope_type IN ('principal','group','persona','global')),
                            scope_id TEXT NOT NULL,
                            kind TEXT NOT NULL CHECK(kind IN (
                                'user_fact','preference','relationship','commitment',
                                'episode_summary','group_norm','self_stance','adopted_idea'
                            )),
                            text TEXT NOT NULL,
                            source_channel TEXT NOT NULL,
                            source_account_id TEXT NOT NULL,
                            source_message_id TEXT NOT NULL,
                            source_principal_id TEXT NOT NULL,
                            source_principal_role TEXT NOT NULL DEFAULT 'user',
                            created_by TEXT NOT NULL,
                            risk TEXT NOT NULL CHECK(risk IN ('low','medium','high')),
                            confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
                            status TEXT NOT NULL CHECK(status IN (
                                'candidate','quarantined','active','invalidated'
                            )),
                            created_at_ms INTEGER NOT NULL,
                            reviewed_at_ms INTEGER,
                            reviewed_by TEXT,
                            invalidated_reason TEXT,
                            embedding BLOB,
                            embedding_dim INTEGER,
                            importance REAL NOT NULL DEFAULT 0.5,
                            source_trust REAL NOT NULL DEFAULT 0.5,
                            valid_from_ms INTEGER NOT NULL DEFAULT 0,
                            valid_to_ms INTEGER,
                            supersedes_item_id TEXT
                        )
                        """
                    )
                    legacy_columns = {
                        str(row[1]) for row in conn.execute(f"PRAGMA table_info({legacy_name})")
                    }
                    ordered_columns = (
                        "item_id",
                        "fingerprint",
                        "scope_type",
                        "scope_id",
                        "kind",
                        "text",
                        "source_channel",
                        "source_account_id",
                        "source_message_id",
                        "source_principal_id",
                        "source_principal_role",
                        "created_by",
                        "risk",
                        "confidence",
                        "status",
                        "created_at_ms",
                        "reviewed_at_ms",
                        "reviewed_by",
                        "invalidated_reason",
                        "embedding",
                        "embedding_dim",
                        "importance",
                        "source_trust",
                        "valid_from_ms",
                        "valid_to_ms",
                        "supersedes_item_id",
                    )
                    expressions = {
                        name: (
                            name
                            if name in legacy_columns
                            else {
                                "source_principal_role": "'user'",
                                "importance": "0.5",
                                "source_trust": "0.5",
                                "valid_from_ms": "0",
                                "valid_to_ms": "NULL",
                                "supersedes_item_id": "NULL",
                            }.get(name, "NULL")
                        )
                        for name in ordered_columns
                    }
                    columns_sql = ", ".join(ordered_columns)
                    values_sql = ", ".join(expressions[name] for name in ordered_columns)
                    conn.execute(
                        f"INSERT INTO memory_items ({columns_sql}) "
                        f"SELECT {values_sql} FROM {legacy_name}"
                    )
                    conn.execute(f"DROP TABLE {legacy_name}")

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS self_memory_observations (
                        observation_id TEXT PRIMARY KEY,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        reply_message_id TEXT NOT NULL,
                        reply_fingerprint TEXT NOT NULL,
                        reply_text TEXT NOT NULL,
                        delivery_status TEXT NOT NULL CHECK(delivery_status = 'SENT'),
                        channel TEXT NOT NULL,
                        account_id TEXT NOT NULL,
                        conversation_id TEXT,
                        principal_id TEXT,
                        created_at_ms INTEGER NOT NULL,
                        UNIQUE(channel, account_id, reply_message_id)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS self_memory_metadata (
                        item_id TEXT PRIMARY KEY,
                        memory_kind TEXT NOT NULL CHECK(
                            memory_kind IN ('self_stance','adopted_idea')
                        ),
                        canonical_content TEXT NOT NULL,
                        original_quote TEXT,
                        origin TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN (
                            'adopted','partial','considering','rejected',
                            'quarantined','supersedes','withdrawn'
                        )),
                        previous_state TEXT,
                        adoption_reason TEXT,
                        created_at_ms INTEGER NOT NULL,
                        withdrawn_at_ms INTEGER,
                        restored_at_ms INTEGER
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS self_memory_evidence (
                        evidence_id TEXT PRIMARY KEY,
                        item_id TEXT NOT NULL,
                        observation_id TEXT,
                        evidence_kind TEXT NOT NULL CHECK(
                            evidence_kind IN ('self_reply','support','opposition')
                        ),
                        source_message_id TEXT NOT NULL,
                        source_principal_id TEXT NOT NULL,
                        quote TEXT,
                        quote_sha256 TEXT,
                        created_at_ms INTEGER NOT NULL,
                        UNIQUE(item_id, evidence_kind, source_message_id)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS self_memory_evolution_observations (
                        evolution_id TEXT PRIMARY KEY,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        item_id TEXT,
                        observation_id TEXT,
                        source_message_id TEXT NOT NULL,
                        source_principal_id TEXT NOT NULL,
                        source_principal_role TEXT NOT NULL
                            CHECK(source_principal_role IN ('owner','user','blocked')),
                        memory_kind TEXT NOT NULL CHECK(
                            memory_kind IN ('self_stance','adopted_idea')
                        ),
                        normalized_content TEXT NOT NULL,
                        original_quote TEXT,
                        confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
                        risk TEXT NOT NULL CHECK(risk IN ('low','medium','high')),
                        sensitive_level TEXT NOT NULL CHECK(
                            sensitive_level IN ('low','medium','high')
                        ),
                        decision TEXT NOT NULL CHECK(decision IN (
                            'adopted','partial','considering','rejected',
                            'quarantined','supersedes'
                        )),
                        requires_fact_check INTEGER NOT NULL DEFAULT 0
                            CHECK(requires_fact_check IN (0,1)),
                        core_impact INTEGER NOT NULL DEFAULT 0
                            CHECK(core_impact IN (0,1)),
                        reason TEXT NOT NULL,
                        supersedes_item_id TEXT,
                        created_at_ms INTEGER NOT NULL,
                        updated_at_ms INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_self_memory_evidence_item "
                    "ON self_memory_evidence(item_id, evidence_kind, created_at_ms DESC)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_self_memory_evolution_decision "
                    "ON self_memory_evolution_observations(decision, created_at_ms DESC)"
                )
                conn.execute(
                    """
                    INSERT INTO memory_schema_versions(version, applied_at_ms)
                    VALUES (4, ?)
                    """,
                    (int(time.time() * 1000),),
                )
            # Personal-memory v5 is deliberately independent from the
            # self-memory v4 migration above.  In particular, a deployment
            # may opt into v5 on a v2/v3 database without expanding the
            # memory_items kind CHECK constraint or creating any self-memory
            # tables.  The feature flag is owned by the caller; leaving it
            # false must not create these tables or record version 5.
            if personal_memory_v5:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS personal_memory_intents (
                        intent_id TEXT PRIMARY KEY,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        request_sha256 TEXT NOT NULL,
                        observation_id TEXT UNIQUE,
                        principal_id TEXT NOT NULL,
                        principal_role TEXT NOT NULL
                            CHECK(principal_role IN ('owner','user','blocked')),
                        source_channel TEXT NOT NULL,
                        source_account_id TEXT NOT NULL,
                        source_message_id TEXT NOT NULL,
                        intent TEXT NOT NULL CHECK(intent IN (
                            'explicit_remember','repeated_observation',
                            'correction','forget_request'
                        )),
                        kind TEXT NOT NULL CHECK(kind IN (
                            'user_fact','preference','relationship','commitment',
                            'episode_summary'
                        )),
                        semantic_sha256 TEXT NOT NULL,
                        confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
                        risk TEXT NOT NULL CHECK(risk IN ('low','medium','high')),
                        sensitive_level TEXT NOT NULL CHECK(
                            sensitive_level IN ('low','medium','high')
                        ),
                        decision TEXT NOT NULL CHECK(decision IN (
                            'pending','candidate','activated','superseded',
                            'forgotten','quarantined','rejected','no_match',
                            'ambiguous','shadow'
                        )),
                        reason_code TEXT NOT NULL,
                        result_item_id TEXT,
                        created_at_ms INTEGER NOT NULL,
                        updated_at_ms INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS personal_memory_evidence (
                        evidence_id TEXT PRIMARY KEY,
                        item_id TEXT NOT NULL,
                        intent_id TEXT NOT NULL UNIQUE,
                        source_observation_id TEXT NOT NULL,
                        principal_id TEXT NOT NULL,
                        source_channel TEXT NOT NULL,
                        source_account_id TEXT NOT NULL,
                        source_message_id TEXT NOT NULL,
                        evidence_kind TEXT NOT NULL CHECK(
                            evidence_kind IN (
                                'explicit_remember','observation','correction','forget_request'
                            )
                        ),
                        content_sha256 TEXT NOT NULL,
                        confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
                        created_at_ms INTEGER NOT NULL,
                        UNIQUE(item_id, source_observation_id)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_personal_memory_intents_semantic
                    ON personal_memory_intents(
                        principal_id, source_channel, source_account_id,
                        kind, semantic_sha256, created_at_ms DESC
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_personal_memory_evidence_source
                    ON personal_memory_evidence(
                        principal_id, source_channel, source_account_id,
                        item_id, source_message_id
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO memory_schema_versions(version, applied_at_ms)
                    VALUES (5, ?)
                    ON CONFLICT(version) DO NOTHING
                    """,
                    (int(time.time() * 1000),),
                )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_scope_status
                ON memory_items(scope_type, scope_id, status, created_at_ms DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor_principal_id TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    details_sha256 TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL
                )
                """
            )

    @staticmethod
    def _require_owner(actor: Principal) -> None:
        if actor.role != "owner":
            raise MemoryPermissionError("memory governance requires owner role")

    @staticmethod
    def _clean_required(value: str, *, field: str, limit: int) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise MemoryValidationError(f"{field} is required")
        if len(cleaned) > limit:
            raise MemoryValidationError(f"{field} exceeds {limit} characters")
        return cleaned

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            item_id=str(row["item_id"]),
            scope=MemoryScope(row["scope_type"]),
            scope_id=str(row["scope_id"]),
            kind=MemoryKind(row["kind"]),
            text=str(row["text"]),
            source_channel=str(row["source_channel"]),
            source_account_id=str(row["source_account_id"]),
            source_message_id=str(row["source_message_id"]),
            source_principal_id=str(row["source_principal_id"]),
            source_principal_role=str(row["source_principal_role"]),
            created_by=str(row["created_by"]),
            risk=MemoryRisk(row["risk"]),
            confidence=float(row["confidence"]),
            status=MemoryStatus(row["status"]),
            created_at_ms=int(row["created_at_ms"]),
            reviewed_at_ms=(
                int(row["reviewed_at_ms"]) if row["reviewed_at_ms"] is not None else None
            ),
            reviewed_by=str(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
            invalidated_reason=(
                str(row["invalidated_reason"]) if row["invalidated_reason"] is not None else None
            ),
            embedding_dim=(int(row["embedding_dim"]) if row["embedding_dim"] is not None else None),
            importance=float(row["importance"]),
            source_trust=float(row["source_trust"]),
            valid_from_ms=int(row["valid_from_ms"]),
            valid_to_ms=(int(row["valid_to_ms"]) if row["valid_to_ms"] is not None else None),
            supersedes_item_id=(
                str(row["supersedes_item_id"]) if row["supersedes_item_id"] is not None else None
            ),
        )

    @staticmethod
    def _audit(
        conn: sqlite3.Connection,
        *,
        item_id: str,
        action: str,
        actor_principal_id: str,
        actor_role: str,
        details: str,
        now_ms: int,
    ) -> None:
        digest = hashlib.sha256(details.encode("utf-8")).hexdigest()
        conn.execute(
            """
            INSERT INTO memory_audit(
                item_id, action, actor_principal_id, actor_role,
                details_sha256, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (item_id, action, actor_principal_id, actor_role, digest, now_ms),
        )

    def propose(
        self,
        *,
        scope: MemoryScope,
        scope_id: str,
        kind: MemoryKind,
        text: str,
        source_channel: str,
        source_account_id: str,
        source_message_id: str,
        source_principal_id: str,
        source_principal_role: str = "user",
        created_by: str = "unknown",
        risk: MemoryRisk = MemoryRisk.LOW,
        confidence: float = 0.5,
        importance: float = 0.5,
        source_trust: float = 0.5,
        valid_from_ms: int | None = None,
        valid_to_ms: int | None = None,
        supersedes_item_id: str | None = None,
        now_ms: int | None = None,
    ) -> MemoryRecord:
        if not isinstance(scope, MemoryScope):
            raise MemoryValidationError("scope must be a MemoryScope")
        if not isinstance(kind, MemoryKind):
            raise MemoryValidationError("kind must be a MemoryKind")
        if not isinstance(risk, MemoryRisk):
            raise MemoryValidationError("risk must be a MemoryRisk")
        if not 0 <= confidence <= 1:
            raise MemoryValidationError("confidence must be between 0 and 1")
        if not 0 <= importance <= 1 or not 0 <= source_trust <= 1:
            raise MemoryValidationError("importance and source_trust must be between 0 and 1")

        clean_scope_id = self._clean_required(scope_id, field="scope_id", limit=256)
        if scope is MemoryScope.GLOBAL and clean_scope_id != "*":
            raise MemoryValidationError("global scope_id must be '*'")
        clean_text = self._clean_required(text, field="text", limit=4000)
        clean_source_channel = self._clean_required(
            source_channel, field="source_channel", limit=32
        )
        clean_source_account = self._clean_required(
            source_account_id, field="source_account_id", limit=64
        )
        clean_source_message = self._clean_required(
            source_message_id, field="source_message_id", limit=128
        )
        clean_source_principal = self._clean_required(
            source_principal_id, field="source_principal_id", limit=128
        )
        if source_principal_role not in {"owner", "user", "blocked"}:
            raise MemoryValidationError("source_principal_role is invalid")
        clean_created_by = self._clean_required(created_by, field="created_by", limit=128)
        timestamp = int(time.time() * 1000) if now_ms is None else now_ms
        valid_from = timestamp if valid_from_ms is None else int(valid_from_ms)
        if valid_to_ms is not None and int(valid_to_ms) <= valid_from:
            raise MemoryValidationError("valid_to_ms must be after valid_from_ms")
        clean_supersedes = None
        if supersedes_item_id is not None:
            clean_supersedes = self._resolve_item_id(supersedes_item_id)
        initial_status = (
            MemoryStatus.QUARANTINED if risk is MemoryRisk.HIGH else MemoryStatus.CANDIDATE
        )
        fingerprint_payload = json.dumps(
            {
                "scope": scope.value,
                "scope_id": clean_scope_id,
                "kind": kind.value,
                "text": clean_text,
                "source_channel": clean_source_channel,
                "source_account_id": clean_source_account,
                "source_message_id": clean_source_message,
                "source_principal_id": clean_source_principal,
                "valid_from_ms": valid_from,
                "supersedes_item_id": clean_supersedes,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        fingerprint = hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()
        item_id = str(uuid.uuid4())

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO memory_items(
                    item_id, fingerprint, scope_type, scope_id, kind, text,
                    source_channel, source_account_id, source_message_id,
                    source_principal_id, source_principal_role, created_by, risk, confidence,
                    status, created_at_ms, importance, source_trust,
                    valid_from_ms, valid_to_ms, supersedes_item_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    fingerprint,
                    scope.value,
                    clean_scope_id,
                    kind.value,
                    clean_text,
                    clean_source_channel,
                    clean_source_account,
                    clean_source_message,
                    clean_source_principal,
                    source_principal_role,
                    clean_created_by,
                    risk.value,
                    confidence,
                    initial_status.value,
                    timestamp,
                    importance,
                    source_trust,
                    valid_from,
                    valid_to_ms,
                    clean_supersedes,
                ),
            )
            if cursor.rowcount == 1:
                self._audit(
                    conn,
                    item_id=item_id,
                    action="proposed",
                    actor_principal_id=clean_created_by,
                    actor_role="extractor",
                    details=f"{initial_status.value}:{risk.value}",
                    now_ms=timestamp,
                )
            row = conn.execute(
                "SELECT * FROM memory_items WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        if row is None:
            raise MemoryError("memory proposal could not be persisted")
        return self._row_to_record(row)

    def _resolve_item_id(self, item_id: str) -> str:
        clean = self._clean_required(item_id, field="item_id", limit=128)
        with self._connect() as conn:
            exact = conn.execute(
                "SELECT item_id FROM memory_items WHERE item_id = ?",
                (clean,),
            ).fetchone()
            if exact is not None:
                return str(exact["item_id"])
            if len(clean) < 6:
                raise MemoryValidationError("memory id prefix must contain at least 6 characters")
            rows = conn.execute(
                "SELECT item_id FROM memory_items WHERE item_id LIKE ? ORDER BY item_id LIMIT 2",
                (f"{clean}%",),
            ).fetchall()
        if not rows:
            raise MemoryNotFoundError("memory item not found")
        if len(rows) > 1:
            raise MemoryValidationError("memory id prefix is ambiguous; use more characters")
        return str(rows[0]["item_id"])

    def get(self, item_id: str) -> MemoryRecord:
        resolved_id = self._resolve_item_id(item_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE item_id = ?",
                (resolved_id,),
            ).fetchone()
        if row is None:
            raise MemoryNotFoundError("memory item not found")
        return self._row_to_record(row)

    def get_for_review(self, item_id: str, *, actor: Principal) -> MemoryRecord:
        """Return one complete record to an authenticated memory governor."""
        self._require_owner(actor)
        return self.get(item_id)

    def list_items(
        self,
        *,
        actor: Principal,
        status: MemoryStatus | None = None,
        scope: MemoryScope | None = None,
        scope_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """List review records without allowing chat-controlled authorization."""
        self._require_owner(actor)
        if status is not None and not isinstance(status, MemoryStatus):
            raise MemoryValidationError("status must be a MemoryStatus")
        if scope is not None and not isinstance(scope, MemoryScope):
            raise MemoryValidationError("scope must be a MemoryScope")
        if scope_id is not None and scope is None:
            raise MemoryValidationError("scope_id requires scope")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise MemoryValidationError("limit must be between 1 and 200")
        if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= 100_000:
            raise MemoryValidationError("offset must be between 0 and 100000")

        clauses: list[str] = []
        params: list[str | int] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if scope is not None:
            clauses.append("scope_type = ?")
            params.append(scope.value)
        if scope_id is not None:
            clauses.append("scope_id = ?")
            params.append(self._clean_required(scope_id, field="scope_id", limit=256))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend((limit, offset))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM memory_items
                {where}
                ORDER BY created_at_ms DESC, item_id ASC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def status_counts(self, *, actor: Principal) -> dict[str, int]:
        """Return governance counts without abusing the bounded review page API."""
        self._require_owner(actor)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM memory_items GROUP BY status"
            ).fetchall()
        counts = {status.value: 0 for status in MemoryStatus}
        counts.update({str(row["status"]): int(row["count"]) for row in rows})
        return counts

    def auto_review_candidate(
        self,
        item_id: str,
        *,
        min_confidence: float,
        min_evidence: int,
        now_ms: int | None = None,
    ) -> MemoryAutoReviewOutcome:
        """Activate only repeated, low-risk self-preferences from the passive extractor.

        This path cannot govern owner identity, persona, global/group memory,
        medium/high-risk content, or candidates created by another source.
        """
        if not 0.8 <= min_confidence <= 0.99:
            raise MemoryValidationError("auto-review confidence must be between 0.8 and 0.99")
        if not 2 <= min_evidence <= 5:
            raise MemoryValidationError("auto-review evidence must be between 2 and 5")
        resolved_id = self._resolve_item_id(item_id)
        timestamp = int(time.time() * 1000) if now_ms is None else now_ms
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE item_id = ?",
                (resolved_id,),
            ).fetchone()
            if row is None:
                raise MemoryNotFoundError("memory item not found")
            record = self._row_to_record(row)
            eligible = (
                record.status is MemoryStatus.CANDIDATE
                and record.scope is MemoryScope.PRINCIPAL
                and record.scope_id == record.source_principal_id
                and record.source_principal_role == "owner"
                and record.kind is MemoryKind.PREFERENCE
                and record.risk is MemoryRisk.LOW
                and record.created_by in {"passive-observer-v2", "memory-reconciler-v2"}
                and record.confidence >= min_confidence
                and is_auto_review_safe_text(record.text)
            )
            if not eligible:
                return MemoryAutoReviewOutcome(record, "manual_review_required", 0)

            evidence_count = int(
                conn.execute(
                    """
                    SELECT COUNT(DISTINCT source_message_id)
                    FROM memory_items
                    WHERE scope_type = 'principal' AND scope_id = ?
                      AND source_principal_id = ? AND source_principal_role = 'owner'
                      AND kind = 'preference'
                      AND text = ? AND created_by IN ('passive-observer-v2','memory-reconciler-v2')
                      AND risk = 'low' AND confidence >= ?
                      AND status IN ('candidate','active')
                    """,
                    (
                        record.scope_id,
                        record.source_principal_id,
                        record.text,
                        min_confidence,
                    ),
                ).fetchone()[0]
            )
            if evidence_count < min_evidence:
                return MemoryAutoReviewOutcome(record, "awaiting_corroboration", evidence_count)

            active = conn.execute(
                """
                SELECT item_id FROM memory_items
                WHERE item_id <> ? AND scope_type = 'principal' AND scope_id = ?
                  AND kind = 'preference' AND text = ? AND status = 'active'
                ORDER BY reviewed_at_ms DESC LIMIT 1
                """,
                (record.item_id, record.scope_id, record.text),
            ).fetchone()
            if active is not None:
                reason = f"auto-review duplicate of {active['item_id']}"
                conn.execute(
                    """
                    UPDATE memory_items
                    SET status = 'invalidated', reviewed_at_ms = ?,
                        reviewed_by = 'system:auto-reviewer', invalidated_reason = ?
                    WHERE item_id = ? AND status = 'candidate'
                    """,
                    (timestamp, reason, record.item_id),
                )
                self._audit(
                    conn,
                    item_id=record.item_id,
                    action="auto_duplicate_invalidated",
                    actor_principal_id="system:auto-reviewer",
                    actor_role="system-reviewer",
                    details=reason,
                    now_ms=timestamp,
                )
                updated = conn.execute(
                    "SELECT * FROM memory_items WHERE item_id = ?",
                    (record.item_id,),
                ).fetchone()
                if updated is None:
                    raise MemoryError("auto-review result could not be read back")
                return MemoryAutoReviewOutcome(
                    self._row_to_record(updated),
                    "duplicate_invalidated",
                    evidence_count,
                )

            reason = f"deterministic auto-review with {evidence_count} matching self-reports"
            cursor = conn.execute(
                """
                UPDATE memory_items
                SET status = 'active', reviewed_at_ms = ?,
                    reviewed_by = 'system:auto-reviewer', invalidated_reason = NULL
                WHERE item_id = ? AND status = 'candidate'
                """,
                (timestamp, record.item_id),
            )
            if cursor.rowcount != 1:
                raise MemoryTransitionError("memory changed during automatic review")
            self._audit(
                conn,
                item_id=record.item_id,
                action="auto_activated",
                actor_principal_id="system:auto-reviewer",
                actor_role="system-reviewer",
                details=reason,
                now_ms=timestamp,
            )
            updated = conn.execute(
                "SELECT * FROM memory_items WHERE item_id = ?",
                (record.item_id,),
            ).fetchone()
        if updated is None:
            raise MemoryError("auto-review result could not be read back")
        return MemoryAutoReviewOutcome(
            self._row_to_record(updated),
            "activated",
            evidence_count,
        )

    def audit_log(
        self,
        item_id: str,
        *,
        actor: Principal,
        limit: int = 100,
    ) -> list[MemoryAuditRecord]:
        """Return content-free governance history, including after hard deletion."""
        self._require_owner(actor)
        clean_item_id = self._clean_required(item_id, field="item_id", limit=128)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise MemoryValidationError("limit must be between 1 and 500")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT audit_id, item_id, action, actor_principal_id, actor_role,
                       details_sha256, created_at_ms
                FROM memory_audit
                WHERE item_id = ?
                ORDER BY audit_id ASC
                LIMIT ?
                """,
                (clean_item_id, limit),
            ).fetchall()
        return [
            MemoryAuditRecord(
                audit_id=int(row["audit_id"]),
                item_id=str(row["item_id"]),
                action=str(row["action"]),
                actor_principal_id=str(row["actor_principal_id"]),
                actor_role=str(row["actor_role"]),
                details_sha256=str(row["details_sha256"]),
                created_at_ms=int(row["created_at_ms"]),
            )
            for row in rows
        ]

    def _transition(
        self,
        item_id: str,
        *,
        actor: Principal,
        target: MemoryStatus,
        allowed_from: frozenset[MemoryStatus],
        reason: str,
        now_ms: int | None = None,
    ) -> MemoryRecord:
        self._require_owner(actor)
        item_id = self._resolve_item_id(item_id)
        timestamp = int(time.time() * 1000) if now_ms is None else now_ms
        clean_reason = self._clean_required(reason, field="reason", limit=500)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise MemoryNotFoundError("memory item not found")
            current = MemoryStatus(row["status"])
            if current not in allowed_from:
                raise MemoryTransitionError(
                    f"cannot transition memory from {current.value} to {target.value}"
                )
            # Restoring a predecessor while its successor is active would
            # expose two contradictory memories to recall.  Corrections in
            # the personal-memory service create the successor and invalidate
            # this row atomically; owner restore must preserve that invariant.
            if target is MemoryStatus.ACTIVE and current is MemoryStatus.INVALIDATED:
                successor = conn.execute(
                    """
                    WITH RECURSIVE successors(item_id) AS (
                        SELECT item_id FROM memory_items WHERE supersedes_item_id = ?
                        UNION
                        SELECT child.item_id FROM memory_items child
                        JOIN successors parent ON child.supersedes_item_id = parent.item_id
                    )
                    SELECT memory_items.item_id FROM memory_items
                    JOIN successors ON successors.item_id = memory_items.item_id
                    WHERE memory_items.status = 'active'
                    LIMIT 1
                    """,
                    (item_id,),
                ).fetchone()
                if successor is not None:
                    raise MemoryTransitionError(
                        "cannot restore memory while an active successor exists"
                    )
            invalidated_reason = clean_reason if target is MemoryStatus.INVALIDATED else None
            cursor = conn.execute(
                """
                UPDATE memory_items
                SET status = ?, reviewed_at_ms = ?, reviewed_by = ?,
                    invalidated_reason = ?, valid_to_ms = ?
                WHERE item_id = ? AND status = ?
                """,
                (
                    target.value,
                    timestamp,
                    actor.principal_id,
                    invalidated_reason,
                    None if target is MemoryStatus.ACTIVE else timestamp,
                    item_id,
                    current.value,
                ),
            )
            if cursor.rowcount != 1:
                raise MemoryTransitionError("memory changed during review; retry from fresh state")
            if target is MemoryStatus.ACTIVE and row["supersedes_item_id"] is not None:
                superseded_id = str(row["supersedes_item_id"])
                previous = conn.execute(
                    "SELECT * FROM memory_items WHERE item_id = ?",
                    (superseded_id,),
                ).fetchone()
                if previous is None:
                    raise MemoryTransitionError("superseded memory no longer exists")
                if (
                    str(previous["scope_type"]) != str(row["scope_type"])
                    or str(previous["scope_id"]) != str(row["scope_id"])
                    or str(previous["kind"]) != str(row["kind"])
                ):
                    raise MemoryTransitionError("superseded memory must share scope and kind")
                conn.execute(
                    """
                    UPDATE memory_items
                    SET status='invalidated', valid_to_ms=?, reviewed_at_ms=?,
                        reviewed_by=?, invalidated_reason=?
                    WHERE item_id=? AND status='active'
                    """,
                    (
                        timestamp,
                        timestamp,
                        actor.principal_id,
                        f"superseded by {item_id}",
                        superseded_id,
                    ),
                )
                self._audit(
                    conn,
                    item_id=superseded_id,
                    action="superseded",
                    actor_principal_id=actor.principal_id,
                    actor_role=actor.role,
                    details=item_id,
                    now_ms=timestamp,
                )
            self._audit(
                conn,
                item_id=item_id,
                action=target.value,
                actor_principal_id=actor.principal_id,
                actor_role=actor.role,
                details=clean_reason,
                now_ms=timestamp,
            )
            updated = conn.execute(
                "SELECT * FROM memory_items WHERE item_id = ?",
                (item_id,),
            ).fetchone()
        if updated is None:
            raise MemoryError("memory transition could not be read back")
        return self._row_to_record(updated)

    def activate(self, item_id: str, *, actor: Principal, reason: str) -> MemoryRecord:
        return self._transition(
            item_id,
            actor=actor,
            target=MemoryStatus.ACTIVE,
            allowed_from=frozenset({MemoryStatus.CANDIDATE, MemoryStatus.QUARANTINED}),
            reason=reason,
        )

    def quarantine(self, item_id: str, *, actor: Principal, reason: str) -> MemoryRecord:
        return self._transition(
            item_id,
            actor=actor,
            target=MemoryStatus.QUARANTINED,
            allowed_from=frozenset({MemoryStatus.CANDIDATE, MemoryStatus.ACTIVE}),
            reason=reason,
        )

    def invalidate(self, item_id: str, *, actor: Principal, reason: str) -> MemoryRecord:
        return self._transition(
            item_id,
            actor=actor,
            target=MemoryStatus.INVALIDATED,
            allowed_from=frozenset(
                {MemoryStatus.CANDIDATE, MemoryStatus.QUARANTINED, MemoryStatus.ACTIVE}
            ),
            reason=reason,
        )

    def restore(self, item_id: str, *, actor: Principal, reason: str) -> MemoryRecord:
        record = self.get(item_id)
        target = MemoryStatus.QUARANTINED if record.risk is MemoryRisk.HIGH else MemoryStatus.ACTIVE
        return self._transition(
            item_id,
            actor=actor,
            target=target,
            allowed_from=frozenset({MemoryStatus.INVALIDATED}),
            reason=reason,
        )

    def hard_delete(self, item_id: str, *, actor: Principal, reason: str) -> None:
        self._require_owner(actor)
        clean_reason = self._clean_required(reason, field="reason", limit=500)
        timestamp = int(time.time() * 1000)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT text FROM memory_items WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise MemoryNotFoundError("memory item not found")
            content_digest = hashlib.sha256(str(row["text"]).encode("utf-8")).hexdigest()
            self._audit(
                conn,
                item_id=item_id,
                action="hard_deleted",
                actor_principal_id=actor.principal_id,
                actor_role=actor.role,
                details=f"{clean_reason}:{content_digest}",
                now_ms=timestamp,
            )
            tables = {
                str(table_row["name"])
                for table_row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if {
                "self_memory_metadata",
                "self_memory_evidence",
                "self_memory_evolution_observations",
                "self_memory_observations",
            } <= tables:
                observation_ids = {
                    str(observation_row["observation_id"])
                    for observation_row in conn.execute(
                        """
                        SELECT observation_id FROM self_memory_evidence
                        WHERE item_id = ? AND observation_id IS NOT NULL
                        UNION
                        SELECT observation_id FROM self_memory_evolution_observations
                        WHERE item_id = ? AND observation_id IS NOT NULL
                        """,
                        (item_id, item_id),
                    ).fetchall()
                }
                conn.execute("DELETE FROM self_memory_evidence WHERE item_id = ?", (item_id,))
                conn.execute(
                    "DELETE FROM self_memory_evolution_observations WHERE item_id = ?",
                    (item_id,),
                )
                conn.execute("DELETE FROM self_memory_metadata WHERE item_id = ?", (item_id,))
                for observation_id in observation_ids:
                    still_referenced = conn.execute(
                        """
                        SELECT 1 FROM self_memory_evidence
                        WHERE observation_id = ?
                        UNION ALL
                        SELECT 1 FROM self_memory_evolution_observations
                        WHERE observation_id = ?
                        LIMIT 1
                        """,
                        (observation_id, observation_id),
                    ).fetchone()
                    if still_referenced is None:
                        conn.execute(
                            "DELETE FROM self_memory_observations WHERE observation_id = ?",
                            (observation_id,),
                        )
            if {"personal_memory_intents", "personal_memory_evidence"} <= tables:
                intent_ids = {
                    str(intent_row["intent_id"])
                    for intent_row in conn.execute(
                        "SELECT intent_id FROM personal_memory_intents WHERE result_item_id = ?",
                        (item_id,),
                    ).fetchall()
                }
                conn.execute("DELETE FROM personal_memory_evidence WHERE item_id = ?", (item_id,))
                for intent_id in intent_ids:
                    conn.execute(
                        "DELETE FROM personal_memory_evidence WHERE intent_id = ?",
                        (intent_id,),
                    )
                    conn.execute(
                        "DELETE FROM personal_memory_intents WHERE intent_id = ?",
                        (intent_id,),
                    )
            conn.execute("DELETE FROM memory_items WHERE item_id = ?", (item_id,))

    def search_active(
        self,
        *,
        scope: MemoryScope,
        scope_id: str,
        query: str,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        if not isinstance(scope, MemoryScope):
            raise MemoryValidationError("scope must be a MemoryScope")
        clean_scope_id = self._clean_required(scope_id, field="scope_id", limit=256)
        clean_query = self._clean_required(query, field="query", limit=500)
        bounded_limit = max(1, min(limit, 50))
        now_ms = int(time.time() * 1000)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_items
                WHERE scope_type = ? AND scope_id = ? AND status = 'active'
                  AND valid_from_ms <= ?
                  AND (
                    valid_to_ms IS NULL
                    OR valid_to_ms > ?
                  )
                  AND instr(lower(text), lower(?)) > 0
                ORDER BY confidence DESC, created_at_ms DESC
                LIMIT ?
                """,
                (scope.value, clean_scope_id, now_ms, now_ms, clean_query, bounded_limit),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_active_for_scope(
        self,
        *,
        scope: MemoryScope,
        scope_id: str,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        """Return only owner-approved memory from one exact scope."""
        if not isinstance(scope, MemoryScope):
            raise MemoryValidationError("scope must be a MemoryScope")
        clean_scope_id = self._clean_required(scope_id, field="scope_id", limit=256)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise MemoryValidationError("limit must be between 1 and 20")
        now_ms = int(time.time() * 1000)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM memory_items
                WHERE scope_type = ? AND scope_id = ? AND status = 'active'
                  AND valid_from_ms <= ?
                  AND (
                    valid_to_ms IS NULL
                    OR valid_to_ms > ?
                  )
                ORDER BY importance DESC, source_trust DESC, confidence DESC,
                         created_at_ms DESC, item_id ASC
                LIMIT ?
                """,
                (scope.value, clean_scope_id, now_ms, now_ms, limit),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def audit_count(self, item_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM memory_audit WHERE item_id = ?",
                (item_id,),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    # Compatibility facade: vector storage is implemented in a separate module
    # so the core memory state machine remains easy to audit.
    def set_embedding(
        self,
        item_id: str,
        embedding: tuple[float, ...] | list[float],
    ) -> MemoryRecord:
        from r_agent.vector_memory import MemoryVectorStore

        return MemoryVectorStore(self.path, memory=self).set(item_id, embedding)

    def search_active_by_vector(
        self,
        *,
        scope: MemoryScope,
        scope_id: str,
        query_embedding: tuple[float, ...] | list[float],
        limit: int = 10,
    ) -> list[MemoryRecord]:
        from r_agent.vector_memory import MemoryVectorStore

        return MemoryVectorStore(self.path, memory=self).search_active(
            scope=scope,
            scope_id=scope_id,
            query_embedding=query_embedding,
            limit=limit,
        )

    def vector_status(self) -> dict[str, int]:
        from r_agent.vector_memory import MemoryVectorStore

        return MemoryVectorStore(self.path, memory=self).status()
