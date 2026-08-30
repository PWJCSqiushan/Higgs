"""Governed, privacy-minimized public memory for official QQ groups.

Group memory is deliberately a separate lane from principal memory.  It only
accepts normalized public norms, never stores a message quote or a platform
identifier, and requires either an explicit owner approval or corroboration
from two different non-owner members.  The member identifier is used only for
an in-database one-way HMAC token so a process restart can still distinguish a
second member; the raw identifier and the token are never returned to callers.

The service is opt-in.  Constructing it with ``enabled=False`` performs no
schema work and all context callers must keep the group scope out of their
allowlist.  Production enables it only as a separately reviewed migration.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import time
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from r_agent.events import ConversationKind, InboundEvent
from r_agent.identity import Principal
from r_agent.memory import (
    MemoryKind,
    MemoryRecord,
    MemoryRisk,
    MemoryScope,
    MemoryStatus,
    MemoryStore,
    MemoryTransitionError,
)

GROUP_MEMORY_SCHEMA = "group-memory-v1"
GROUP_MEMORY_SOURCE = "group-memory-v1"
GROUP_MEMORY_MIN_CONFIDENCE = 0.80
GROUP_MEMORY_MEMBER_QUORUM = 2


class GroupMemoryError(RuntimeError):
    """Base error for the isolated public-group memory lane."""


class GroupMemoryDisabledError(GroupMemoryError):
    """The optional feature was not enabled by configuration."""


class GroupMemoryPermissionError(GroupMemoryError):
    """The operation requires the owner or a permitted group event."""


class GroupMemoryValidationError(GroupMemoryError):
    """A candidate or source event failed the public-memory contract."""


class GroupMemoryTransitionError(GroupMemoryError):
    """A candidate cannot be moved to the requested state."""


class GroupMemoryDecision(StrEnum):
    ACTIVATED = "activated"
    WAITING_CORROBORATION = "waiting_corroboration"
    ALREADY_ACTIVE = "already_active"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class GroupEvidenceKind(StrEnum):
    SUPPORT = "support"
    OPPOSITION = "opposition"


@dataclass(frozen=True, slots=True)
class GroupMemoryCandidate:
    """A normalized group norm; no original quote is part of this type."""

    normalized_content: str
    confidence: float
    sensitive_level: str = "low"
    evidence_message_id: str | None = None


@dataclass(frozen=True, slots=True)
class GroupMemoryOutcome:
    """Content-free governance result for one candidate/evidence submission."""

    item: MemoryRecord | None
    decision: GroupMemoryDecision
    support_count: int
    reason: str


@dataclass(frozen=True, slots=True)
class GroupMemorySource:
    """Untrusted source supplied to the strict model extractor."""

    group_id: str
    message_id: str
    principal_role: str
    text: str


@dataclass(frozen=True, slots=True)
class GroupCandidateParseResult:
    decision: GroupMemoryDecision
    reason: str
    candidate: GroupMemoryCandidate | None = None


class GroupMemoryModelClient(Protocol):
    async def complete_messages(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        max_tokens: int = 400,
    ) -> str: ...


_CANDIDATE_KEYS = frozenset(
    {"type", "evidence_message_id", "confidence", "sensitive_level", "normalized_content"}
)
_TOP_LEVEL_KEYS = frozenset({"version", "candidates"})
_ALLOWED_LEVELS = frozenset({"low", "medium", "high"})

# A group norm must not carry a personal fact, private exchange, platform
# identifier, authority request, or prompt injection into the shared scope.
# Deliberately conservative matching is preferable to leaking one member's
# information to everyone in the group.
_BLOCKED_MARKERS = (
    "私聊",
    "私信",
    "聊天记录",
    "原句",
    "原话",
    "qq",
    "openid",
    "用户id",
    "成员id",
    "账号",
    "密码",
    "验证码",
    "token",
    "密钥",
    "api key",
    "地址",
    "住在",
    "电话",
    "手机号",
    "微信",
    "邮箱",
    "身份证",
    "病史",
    "诊断",
    "收入",
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
    "忽略之前",
    "忽略系统",
    "绕过安全",
    "最高权限",
)
_PERSONAL_PRONOUN = re.compile(r"(?<!\w)(?:我(?:的)?|你(?:的)?|他(?!人)|她)(?!们)")
_SOURCE_UNSAFE_MARKERS = (
    "私聊",
    "私信",
    "聊天记录",
    "密码",
    "验证码",
    "token",
    "密钥",
    "api key",
    "qq号",
    "openid",
    "用户id",
    "成员id",
    "地址",
    "住在",
    "电话",
    "手机号",
    "微信",
    "邮箱",
    "身份证",
    "病史",
    "诊断",
    "收入",
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
    "忽略之前",
    "忽略系统",
    "绕过安全",
    "最高权限",
)


def _clean_text(value: object, *, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise GroupMemoryValidationError(f"{field} must be a string")
    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.split()).strip()
    if not normalized:
        raise GroupMemoryValidationError(f"{field} is required")
    if len(normalized) > limit:
        raise GroupMemoryValidationError(f"{field} exceeds {limit} characters")
    if any(ord(char) < 32 for char in normalized):
        raise GroupMemoryValidationError(f"{field} contains control characters")
    return normalized


def _clean_group_id(value: object) -> str:
    clean = _clean_text(value, field="group_id", limit=256)
    if any(char in clean for char in "\r\n\x00"):
        raise GroupMemoryValidationError("group_id contains invalid characters")
    return clean


def _blocked_marker(text: str) -> str | None:
    lowered = text.casefold()
    if _PERSONAL_PRONOUN.search(text):
        return "personal_pronoun"
    for marker in _BLOCKED_MARKERS:
        if marker.casefold() in lowered:
            return marker
    if "@" in text or re.search(r"(?<!\w)\d{5,}(?!\w)", text):
        return "platform_identifier"
    return None


def normalize_group_norm(text: object) -> str:
    """Normalize and validate content allowed in the shared group scope."""

    clean = _clean_text(text, field="normalized_content", limit=600)
    if len(clean) < 4:
        raise GroupMemoryValidationError("normalized_content must contain at least 4 characters")
    marker = _blocked_marker(clean)
    if marker is not None:
        raise GroupMemoryValidationError("group content contains private or authority material")
    return clean


def _risk_level(source: str, normalized: str, declared: str) -> str:
    lowered_source = source.casefold()
    if any(marker.casefold() in lowered_source for marker in _SOURCE_UNSAFE_MARKERS):
        return "high"
    if _blocked_marker(normalized) is not None:
        return "high"
    level = declared.casefold()
    return level if level in _ALLOWED_LEVELS else "high"


def parse_group_candidate_response(
    raw: str,
    source: GroupMemorySource,
) -> tuple[GroupCandidateParseResult, ...]:
    """Parse a closed JSON group-candidate response fail-closed."""

    try:
        clean_message = _clean_text(source.message_id, field="message_id", limit=256)
        _clean_group_id(source.group_id)
        _clean_text(source.text, field="source_text", limit=4_000)
    except GroupMemoryValidationError:
        return (GroupCandidateParseResult(GroupMemoryDecision.REJECTED, "invalid_source"),)
    if source.principal_role not in {"owner", "user", "blocked"}:
        return (GroupCandidateParseResult(GroupMemoryDecision.REJECTED, "invalid_source_role"),)
    if not isinstance(raw, str) or not raw or len(raw) > 12_000:
        return (GroupCandidateParseResult(GroupMemoryDecision.REJECTED, "invalid_json_envelope"),)
    if raw.lstrip().startswith("```"):
        return (GroupCandidateParseResult(GroupMemoryDecision.REJECTED, "markdown_not_allowed"),)
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        return (GroupCandidateParseResult(GroupMemoryDecision.REJECTED, "invalid_json"),)
    if not isinstance(payload, Mapping) or frozenset(payload) != _TOP_LEVEL_KEYS:
        return (
            GroupCandidateParseResult(GroupMemoryDecision.REJECTED, "invalid_top_level_schema"),
        )
    if payload.get("version") != GROUP_MEMORY_SCHEMA:
        return (
            GroupCandidateParseResult(GroupMemoryDecision.REJECTED, "unsupported_schema_version"),
        )
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > 3:
        return (GroupCandidateParseResult(GroupMemoryDecision.REJECTED, "invalid_candidate_count"),)
    results: list[GroupCandidateParseResult] = []
    for raw_candidate in candidates:
        if not isinstance(raw_candidate, Mapping) or frozenset(raw_candidate) != _CANDIDATE_KEYS:
            results.append(
                GroupCandidateParseResult(GroupMemoryDecision.REJECTED, "invalid_candidate_schema")
            )
            continue
        if raw_candidate.get("type") != "group_norm":
            results.append(GroupCandidateParseResult(GroupMemoryDecision.REJECTED, "invalid_type"))
            continue
        if raw_candidate.get("evidence_message_id") != clean_message:
            results.append(
                GroupCandidateParseResult(GroupMemoryDecision.REJECTED, "evidence_mismatch")
            )
            continue
        confidence = raw_candidate.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            results.append(
                GroupCandidateParseResult(GroupMemoryDecision.REJECTED, "invalid_confidence")
            )
            continue
        confidence_value = float(confidence)
        if not math.isfinite(confidence_value) or not 0 <= confidence_value <= 1:
            results.append(
                GroupCandidateParseResult(GroupMemoryDecision.REJECTED, "invalid_confidence")
            )
            continue
        level = raw_candidate.get("sensitive_level")
        if not isinstance(level, str) or level.casefold() not in _ALLOWED_LEVELS:
            results.append(
                GroupCandidateParseResult(GroupMemoryDecision.REJECTED, "invalid_sensitive_level")
            )
            continue
        try:
            normalized = normalize_group_norm(raw_candidate.get("normalized_content"))
        except GroupMemoryValidationError:
            results.append(
                GroupCandidateParseResult(
                    GroupMemoryDecision.QUARANTINED, "private_or_unsafe_content"
                )
            )
            continue
        effective = _risk_level(source.text, normalized, level)
        candidate = GroupMemoryCandidate(
            normalized_content=normalized,
            confidence=confidence_value,
            sensitive_level=effective,
            evidence_message_id=clean_message,
        )
        if effective != "low" or confidence_value < GROUP_MEMORY_MIN_CONFIDENCE:
            results.append(
                GroupCandidateParseResult(
                    GroupMemoryDecision.QUARANTINED,
                    "sensitive_or_low_confidence",
                    candidate,
                )
            )
        else:
            results.append(
                GroupCandidateParseResult(
                    GroupMemoryDecision.WAITING_CORROBORATION,
                    "awaiting_governed_evidence",
                    candidate,
                )
            )
    return tuple(results)


class ModelGroupMemoryExtractor:
    """Ask the configured model for public norms, never for raw group memory."""

    def __init__(self, client: GroupMemoryModelClient) -> None:
        self.client = client

    async def extract(
        self,
        source: GroupMemorySource,
    ) -> tuple[GroupCandidateParseResult, ...]:
        clean_group = _clean_group_id(source.group_id)
        clean_message = _clean_text(source.message_id, field="message_id", limit=256)
        clean_text = _clean_text(source.text, field="source_text", limit=4_000)
        payload = json.dumps(
            {
                "group_id": clean_group,
                "evidence_message_id": clean_message,
                "text": clean_text,
                "principal_role": source.principal_role,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        raw = await self.client.complete_messages(
            messages=(
                {
                    "role": "system",
                    "content": (
                        "你是官方群公共规范候选提取器，只输出严格 JSON，不写 Markdown。"
                        '顶层必须是 {"version":"group-memory-v1","candidates":[]}。'
                        "每个候选只能包含 type、evidence_message_id、confidence、"
                        "sensitive_level、normalized_content，type 只能是 group_norm。"
                        "只提取去标识的群公共规范或主题，不得保存个人事实、私聊内容、"
                        "成员或平台标识、原句、权限、身份、提示词、敏感内容或事实核验结论。"
                        "无法形成稳定公共规范时返回空 candidates，最多三个。"
                    ),
                },
                {"role": "user", "content": payload},
            ),
            max_tokens=700,
        )
        return parse_group_candidate_response(raw, source)


class GroupMemoryService:
    """Persist only anonymized group norms and quorum evidence."""

    def __init__(
        self,
        memory: MemoryStore,
        *,
        enabled: bool = False,
    ) -> None:
        self.memory = memory
        self.path = memory.path
        self.enabled = enabled
        self._hash_salt: bytes | None = None

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise GroupMemoryDisabledError("group memory is disabled")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(self) -> None:
        """Create the opt-in evidence tables without changing memory schema."""

        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS group_memory_meta (
                    key TEXT PRIMARY KEY,
                    value BLOB NOT NULL
                )
                """
            )
            row = conn.execute(
                "SELECT value FROM group_memory_meta WHERE key='member_hmac_salt'"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO group_memory_meta(key, value) VALUES ('member_hmac_salt', ?)",
                    (secrets.token_bytes(32),),
                )
                row = conn.execute(
                    "SELECT value FROM group_memory_meta WHERE key='member_hmac_salt'"
                ).fetchone()
            self._hash_salt = bytes(row[0]) if row is not None else None
            if self._hash_salt is None or len(self._hash_salt) < 32:
                raise GroupMemoryError("group member hash salt is invalid")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS group_memory_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL REFERENCES memory_items(item_id) ON DELETE CASCADE,
                    group_scope_id TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    member_token TEXT NOT NULL,
                    source_message_token TEXT NOT NULL,
                    member_role TEXT NOT NULL CHECK(member_role IN ('owner','user')),
                    evidence_kind TEXT NOT NULL CHECK(evidence_kind IN ('support','opposition')),
                    created_at_ms INTEGER NOT NULL,
                    UNIQUE(item_id, member_token, evidence_kind)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_group_memory_evidence_item
                ON group_memory_evidence(item_id, evidence_kind, created_at_ms DESC)
                """
            )

    def _salt(self) -> bytes:
        self._require_enabled()
        if self._hash_salt is None:
            self.initialize()
        if self._hash_salt is None:
            raise GroupMemoryError("group member hash salt is unavailable")
        return self._hash_salt

    def _token(self, domain: str, value: str) -> str:
        clean = _clean_text(value, field=domain, limit=512)
        return hmac.new(self._salt(), f"{domain}\0{clean}".encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _content_digest(normalized: str) -> str:
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _find_or_create_item(
        self,
        *,
        group_id: str,
        candidate: GroupMemoryCandidate,
        now_ms: int,
    ) -> MemoryRecord:
        normalized = normalize_group_norm(candidate.normalized_content)
        if candidate.confidence < GROUP_MEMORY_MIN_CONFIDENCE:
            raise GroupMemoryValidationError(
                "group candidate confidence is below the public-memory threshold"
            )
        if candidate.sensitive_level.casefold() != "low":
            raise GroupMemoryValidationError("sensitive group content cannot enter shared memory")
        digest = self._content_digest(normalized)
        # The source fields are fixed, content-free sentinels.  The actual
        # platform message/member identifiers are held only transiently by
        # submit_evidence and represented in the evidence table by HMACs.
        return self.memory.propose(
            scope=MemoryScope.GROUP,
            scope_id=group_id,
            kind=MemoryKind.GROUP_NORM,
            text=normalized,
            source_channel="qq_official",
            source_account_id=GROUP_MEMORY_SOURCE,
            source_message_id=f"group-candidate:{digest}",
            source_principal_id=GROUP_MEMORY_SOURCE,
            source_principal_role="user",
            created_by=GROUP_MEMORY_SOURCE,
            risk=MemoryRisk.LOW,
            confidence=candidate.confidence,
            valid_from_ms=0,
            now_ms=now_ms,
        )

    @staticmethod
    def _validate_member_role(role: str) -> str:
        if role not in {"owner", "user"}:
            raise GroupMemoryPermissionError("blocked members cannot contribute group memory")
        return role

    @staticmethod
    def _validate_evidence_kind(kind: GroupEvidenceKind | str) -> GroupEvidenceKind:
        try:
            result = kind if isinstance(kind, GroupEvidenceKind) else GroupEvidenceKind(str(kind))
        except ValueError as exc:
            raise GroupMemoryValidationError("evidence_kind is invalid") from exc
        return result

    def _support_count(self, item_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT member_token)
                FROM group_memory_evidence
                WHERE item_id=? AND evidence_kind='support' AND member_role='user'
                """,
                (item_id,),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def _activate_by_quorum(self, item_id: str, *, count: int, now_ms: int) -> MemoryRecord:
        reason = f"group public norm corroborated by {count} distinct non-owner members"
        digest = hashlib.sha256(reason.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM memory_items WHERE item_id=?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise GroupMemoryError("group candidate disappeared")
            if (
                str(row["scope_type"]) != MemoryScope.GROUP.value
                or str(row["kind"]) != MemoryKind.GROUP_NORM.value
            ):
                raise GroupMemoryTransitionError("only group_norm records may use group quorum")
            if str(row["status"]) == MemoryStatus.ACTIVE.value:
                return self.memory.get(item_id)
            if str(row["status"]) != MemoryStatus.CANDIDATE.value:
                raise GroupMemoryTransitionError("group candidate is not awaiting activation")
            current_count = int(
                conn.execute(
                    """
                    SELECT COUNT(DISTINCT member_token)
                    FROM group_memory_evidence
                    WHERE item_id=? AND evidence_kind='support' AND member_role='user'
                    """,
                    (item_id,),
                ).fetchone()[0]
            )
            if current_count < GROUP_MEMORY_MEMBER_QUORUM:
                raise GroupMemoryTransitionError("group candidate quorum is no longer satisfied")
            conn.execute(
                """
                UPDATE memory_items
                SET status='active', reviewed_at_ms=?, reviewed_by='group-memory-v1',
                    invalidated_reason=NULL
                WHERE item_id=? AND status='candidate'
                """,
                (now_ms, item_id),
            )
            conn.execute(
                """
                INSERT INTO memory_audit(
                    item_id, action, actor_principal_id, actor_role,
                    details_sha256, created_at_ms
                ) VALUES (?, 'group_quorum_activated', 'group-memory-v1', 'system-reviewer', ?, ?)
                """,
                (item_id, digest, now_ms),
            )
            updated = conn.execute(
                "SELECT * FROM memory_items WHERE item_id=?",
                (item_id,),
            ).fetchone()
        if updated is None:
            raise GroupMemoryError("group activation could not be read back")
        return self.memory.get(item_id)

    def submit_evidence(
        self,
        *,
        group_id: str,
        candidate: GroupMemoryCandidate,
        member_id: str,
        member_role: str,
        source_message_id: str,
        evidence_kind: GroupEvidenceKind | str = GroupEvidenceKind.SUPPORT,
        now_ms: int | None = None,
    ) -> GroupMemoryOutcome:
        """Add one public evidence item while persisting no raw identifiers."""

        self._require_enabled()
        clean_group = _clean_group_id(group_id)
        role = self._validate_member_role(member_role)
        clean_message = _clean_text(source_message_id, field="source_message_id", limit=256)
        kind = self._validate_evidence_kind(evidence_kind)
        if not isinstance(member_id, str) or not member_id.strip():
            raise GroupMemoryValidationError(
                "member_id is required transiently for quorum accounting"
            )
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        try:
            item = self._find_or_create_item(group_id=clean_group, candidate=candidate, now_ms=now)
        except GroupMemoryValidationError as exc:
            # Do not quarantine sensitive text in the shared memory table: the
            # caller receives only a content-free rejection.
            return GroupMemoryOutcome(None, GroupMemoryDecision.REJECTED, 0, str(exc))
        if item.scope is not MemoryScope.GROUP or item.kind is not MemoryKind.GROUP_NORM:
            raise GroupMemoryTransitionError("group candidate scope or kind is invalid")
        if item.status is MemoryStatus.INVALIDATED:
            return GroupMemoryOutcome(
                item, GroupMemoryDecision.REJECTED, 0, "candidate was invalidated"
            )
        member_token = self._token("group-member", member_id)
        message_token = self._token("group-message", clean_message)
        content_digest = self._content_digest(item.text)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO group_memory_evidence(
                    evidence_id, item_id, group_scope_id, content_sha256,
                    member_token, source_message_token, member_role, evidence_kind,
                    created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    item.item_id,
                    clean_group,
                    content_digest,
                    member_token,
                    message_token,
                    role,
                    kind.value,
                    now,
                ),
            )
        count = self._support_count(item.item_id)
        if item.status is MemoryStatus.ACTIVE:
            return GroupMemoryOutcome(
                item, GroupMemoryDecision.ALREADY_ACTIVE, count, "already active"
            )
        if kind is not GroupEvidenceKind.SUPPORT or count < GROUP_MEMORY_MEMBER_QUORUM:
            decision = (
                GroupMemoryDecision.DUPLICATE
                if cursor.rowcount == 0
                else GroupMemoryDecision.WAITING_CORROBORATION
            )
            return GroupMemoryOutcome(
                item, decision, count, "requires two distinct non-owner supports"
            )
        activated = self._activate_by_quorum(item.item_id, count=count, now_ms=now)
        return GroupMemoryOutcome(
            activated, GroupMemoryDecision.ACTIVATED, count, "two distinct non-owner supports"
        )

    def submit_event_evidence(
        self,
        event: InboundEvent,
        *,
        candidate: GroupMemoryCandidate,
        member_role: str,
        evidence_kind: GroupEvidenceKind | str = GroupEvidenceKind.SUPPORT,
        now_ms: int | None = None,
    ) -> GroupMemoryOutcome:
        """Accept evidence only from an official, actually-mentioned group event."""

        self._require_enabled()
        if (
            event.channel.casefold() != "qq_official"
            or event.conversation_kind is not ConversationKind.GROUP
            or not event.group_id
            or not event.mentioned
        ):
            raise GroupMemoryPermissionError(
                "group public memory requires an official @ group event"
            )
        return self.submit_evidence(
            group_id=event.group_id,
            candidate=candidate,
            member_id=event.sender_id,
            member_role=member_role,
            source_message_id=event.message_id,
            evidence_kind=evidence_kind,
            now_ms=event.occurred_at_ms if now_ms is None else now_ms,
        )

    def approve(
        self,
        item_id: str,
        *,
        actor: Principal,
        reason: str,
    ) -> MemoryRecord:
        """Explicitly activate one safe group norm as the owner."""

        self._require_enabled()
        if actor.role != "owner":
            raise GroupMemoryPermissionError("only the owner may approve group memory")
        item = self.memory.get(item_id)
        if item.scope is not MemoryScope.GROUP or item.kind is not MemoryKind.GROUP_NORM:
            raise GroupMemoryValidationError("item is not a group public norm")
        if item.risk is not MemoryRisk.LOW or _blocked_marker(item.text) is not None:
            raise GroupMemoryValidationError("sensitive group memory cannot be activated")
        if item.status is MemoryStatus.ACTIVE:
            return item
        if item.status is not MemoryStatus.CANDIDATE:
            raise MemoryTransitionError("group item is not awaiting owner approval")
        clean_reason = _clean_text(reason, field="reason", limit=500)
        return self.memory.activate(item.item_id, actor=actor, reason=clean_reason)

    def list_active(self, *, group_id: str, limit: int = 10) -> list[MemoryRecord]:
        if not self.enabled:
            return []
        return self.memory.list_active_for_scope(
            scope=MemoryScope.GROUP,
            scope_id=_clean_group_id(group_id),
            limit=limit,
        )

    def search(self, *, group_id: str, query: str, limit: int = 5) -> list[MemoryRecord]:
        if not self.enabled:
            return []
        clean_group = _clean_group_id(group_id)
        clean_query = _clean_text(query, field="query", limit=500)
        matches = self.memory.search_active(
            scope=MemoryScope.GROUP,
            scope_id=clean_group,
            query=clean_query,
            limit=limit,
        )
        seen = {item.item_id for item in matches}
        if len(matches) < limit:
            for item in self.list_active(group_id=clean_group, limit=limit):
                if item.item_id not in seen:
                    matches.append(item)
                    seen.add(item.item_id)
                if len(matches) >= limit:
                    break
        return matches

    def support_count(self, item_id: str) -> int:
        if not self.enabled:
            return 0
        item = self.memory.get(item_id)
        if item.scope is not MemoryScope.GROUP or item.kind is not MemoryKind.GROUP_NORM:
            raise GroupMemoryValidationError("item is not a group public norm")
        return self._support_count(item.item_id)


__all__ = [
    "GROUP_MEMORY_MEMBER_QUORUM",
    "GROUP_MEMORY_MIN_CONFIDENCE",
    "GroupCandidateParseResult",
    "GroupEvidenceKind",
    "GroupMemoryCandidate",
    "GroupMemoryDecision",
    "GroupMemoryDisabledError",
    "GroupMemoryError",
    "GroupMemoryModelClient",
    "GroupMemoryOutcome",
    "GroupMemoryPermissionError",
    "GroupMemoryService",
    "GroupMemorySource",
    "GroupMemoryTransitionError",
    "GroupMemoryValidationError",
    "ModelGroupMemoryExtractor",
    "normalize_group_norm",
    "parse_group_candidate_response",
]
