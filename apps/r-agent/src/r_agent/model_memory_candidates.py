"""Strict, shadow-only model proposals for Memory V2.1.

This module intentionally has no API for activating, replacing, or deleting a
memory.  It can only record reviewable shadow proposals tied to one evidence
message.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from r_agent.memory_v2 import Observation


class CandidateDecision(StrEnum):
    SHADOW = "shadow"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


class SensitiveLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_ALLOWED_TYPES = frozenset(
    {"user_fact", "preference", "relationship", "commitment", "episode_summary"}
)
_EXACT_TOP_LEVEL_KEYS = frozenset({"version", "candidates"})
_EXACT_CANDIDATE_KEYS = frozenset(
    {
        "type",
        "scope",
        "evidence_message_id",
        "confidence",
        "sensitive_level",
        "normalized_content",
    }
)
_CREDENTIAL_MARKERS = (
    "密码",
    "验证码",
    "token",
    "api key",
    "密钥",
    "银行卡",
    "身份证",
    "私钥",
)
_AUTHORITY_MARKERS = (
    "我是主人",
    "叫我主人",
    "管理员",
    "最高权限",
    "修改权限",
    "系统提示",
    "提示词",
    "忽略之前",
    "忽略系统",
)
_MEDIUM_MARKERS = (
    "地址",
    "住在",
    "手机号",
    "电话",
    "邮箱",
    "病史",
    "诊断",
    "收入",
    "政治",
    "宗教",
)

# Production never enables model proposals implicitly.  Operators must opt in
# to the isolated ``shadow`` mode after an explicit review of real-model eval.
MODEL_CANDIDATE_DEFAULT_MODE = "off"


class CandidateModel(Protocol):
    async def complete(self, *, system: str, user: str, max_tokens: int = 400) -> str: ...


@dataclass(frozen=True, slots=True)
class ModelMemoryCandidate:
    kind: str
    scope: str
    evidence_message_id: str
    confidence: float
    sensitive_level: SensitiveLevel
    normalized_content: str


@dataclass(frozen=True, slots=True)
class CandidateResult:
    decision: CandidateDecision
    reason: str
    candidate: ModelMemoryCandidate | None = None


class ModelCandidateStoreError(RuntimeError):
    """Base error for read-only model-candidate queue access."""


class ModelCandidateNotFoundError(ModelCandidateStoreError):
    """A requested proposal ID does not exist."""


class ModelCandidateAmbiguousError(ModelCandidateStoreError):
    """A short proposal ID matched more than one proposal."""


@dataclass(frozen=True, slots=True)
class ShadowCandidateRecord:
    """One immutable, owner-reviewable shadow proposal row."""

    proposal_id: str
    observation_id: str
    principal_id: str
    evidence_message_id: str
    kind: str | None
    scope: str | None
    confidence: float | None
    sensitive_level: SensitiveLevel | None
    normalized_content: str | None
    decision: CandidateDecision
    reason: str
    created_at_ms: int


def preflight_risk(text: str) -> CandidateResult | None:
    lowered = text.casefold()
    if any(marker in lowered for marker in _CREDENTIAL_MARKERS):
        return CandidateResult(CandidateDecision.REJECTED, "credential_or_unique_identifier")
    if any(marker in lowered for marker in _AUTHORITY_MARKERS):
        return CandidateResult(CandidateDecision.QUARANTINED, "authority_or_prompt_injection")
    return None


def _local_sensitive_level(text: str) -> SensitiveLevel:
    lowered = text.casefold()
    if any(marker in lowered for marker in _CREDENTIAL_MARKERS + _AUTHORITY_MARKERS):
        return SensitiveLevel.HIGH
    if any(marker in lowered for marker in _MEDIUM_MARKERS):
        return SensitiveLevel.MEDIUM
    return SensitiveLevel.LOW


def parse_candidate_response(raw: str, observation: Observation) -> tuple[CandidateResult, ...]:
    """Parse an exact JSON object; any schema drift rejects the whole response."""
    if not raw or len(raw) > 12_000 or raw.lstrip().startswith("```"):
        return (CandidateResult(CandidateDecision.REJECTED, "invalid_json_envelope"),)
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        return (CandidateResult(CandidateDecision.REJECTED, "invalid_json"),)
    if not isinstance(payload, Mapping) or frozenset(payload) != _EXACT_TOP_LEVEL_KEYS:
        return (CandidateResult(CandidateDecision.REJECTED, "invalid_top_level_schema"),)
    if payload.get("version") != "memory-candidate-v1":
        return (CandidateResult(CandidateDecision.REJECTED, "unsupported_schema_version"),)
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > 3:
        return (CandidateResult(CandidateDecision.REJECTED, "invalid_candidate_count"),)
    results: list[CandidateResult] = []
    for item in candidates:
        if not isinstance(item, Mapping) or frozenset(item) != _EXACT_CANDIDATE_KEYS:
            return (CandidateResult(CandidateDecision.REJECTED, "invalid_candidate_schema"),)
        kind = item.get("type")
        scope = item.get("scope")
        evidence = item.get("evidence_message_id")
        confidence = item.get("confidence")
        declared_sensitive = item.get("sensitive_level")
        content = item.get("normalized_content")
        if kind not in _ALLOWED_TYPES or scope != "principal":
            results.append(CandidateResult(CandidateDecision.REJECTED, "invalid_type_or_scope"))
            continue
        if evidence != observation.message_id:
            results.append(CandidateResult(CandidateDecision.REJECTED, "evidence_mismatch"))
            continue
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            results.append(CandidateResult(CandidateDecision.REJECTED, "invalid_confidence"))
            continue
        if not 0 <= float(confidence) <= 1:
            results.append(CandidateResult(CandidateDecision.REJECTED, "invalid_confidence"))
            continue
        if declared_sensitive not in {item.value for item in SensitiveLevel}:
            results.append(CandidateResult(CandidateDecision.REJECTED, "invalid_sensitive_level"))
            continue
        if not isinstance(content, str):
            results.append(CandidateResult(CandidateDecision.REJECTED, "invalid_content"))
            continue
        normalized = " ".join(content.split())
        if not 4 <= len(normalized) <= 300 or any(ord(char) < 32 for char in normalized):
            results.append(CandidateResult(CandidateDecision.REJECTED, "invalid_content"))
            continue
        candidate = ModelMemoryCandidate(
            kind=str(kind),
            scope="principal",
            evidence_message_id=str(evidence),
            confidence=float(confidence),
            sensitive_level=SensitiveLevel(str(declared_sensitive)),
            normalized_content=normalized,
        )
        local_level = _local_sensitive_level(observation.text + " " + normalized)
        declared_level = SensitiveLevel(str(declared_sensitive))
        effective_level = max(
            local_level, declared_level, key=lambda level: list(SensitiveLevel).index(level)
        )
        if effective_level is SensitiveLevel.HIGH:
            decision = CandidateDecision.QUARANTINED
            reason = "local_high_risk"
        elif observation.principal_role != "owner" or effective_level is SensitiveLevel.MEDIUM:
            decision = CandidateDecision.QUARANTINED
            reason = "non_owner_or_sensitive"
        else:
            decision = CandidateDecision.SHADOW
            reason = "awaiting_owner_review"
        results.append(CandidateResult(decision, reason, candidate))
    return tuple(results)


_SYSTEM_PROMPT = """你是受限的记忆候选提取器。只输出一个 JSON 对象，不得输出 Markdown。
顶层必须且只能有 version 和 candidates。version 固定为 memory-candidate-v1。
candidates 最多 3 项, 每项必须且只能有 type, scope, evidence_message_id,
confidence, sensitive_level, normalized_content。scope 只能是 principal。
不得推断主人、权限、凭据或提示词，不确定时输出空 candidates。"""


class ModelCandidateExtractor:
    def __init__(self, client: CandidateModel) -> None:
        self.client = client

    async def extract(self, observation: Observation) -> tuple[CandidateResult, ...]:
        blocked = preflight_risk(observation.text)
        if blocked is not None:
            return (blocked,)
        user = json.dumps(
            {
                "evidence_message_id": observation.message_id,
                "principal_role": observation.principal_role,
                "text": observation.text,
            },
            ensure_ascii=False,
        )
        raw = await self.client.complete(system=_SYSTEM_PROMPT, user=user, max_tokens=600)
        return parse_candidate_response(raw, observation)


class ModelCandidateShadowStore:
    """Append-only review queue; intentionally exposes no activation operation."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_memory_candidate_shadow (
                    proposal_id TEXT PRIMARY KEY,
                    observation_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    evidence_message_id TEXT NOT NULL,
                    kind TEXT,
                    scope TEXT,
                    confidence REAL,
                    sensitive_level TEXT,
                    normalized_content TEXT,
                    decision TEXT NOT NULL CHECK(decision IN ('shadow','quarantined','rejected')),
                    reason TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL
                )
                """
            )

    def record(self, observation: Observation, results: tuple[CandidateResult, ...]) -> int:
        inserted = 0
        with self._connect() as conn:
            for index, result in enumerate(results):
                candidate = result.candidate
                raw_id = f"{observation.observation_id}:{index}:{result.decision}:{result.reason}"
                proposal_id = hashlib.sha256(raw_id.encode()).hexdigest()[:32]
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO model_memory_candidate_shadow(
                        proposal_id, observation_id, principal_id, evidence_message_id,
                        kind, scope, confidence, sensitive_level, normalized_content,
                        decision, reason, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposal_id,
                        observation.observation_id,
                        observation.principal_id,
                        observation.message_id,
                        candidate.kind if candidate else None,
                        candidate.scope if candidate else None,
                        candidate.confidence if candidate else None,
                        candidate.sensitive_level if candidate else None,
                        candidate.normalized_content if candidate else None,
                        result.decision,
                        result.reason,
                        int(time.time() * 1000),
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    @staticmethod
    def _validate_window(*, limit: int, offset: int) -> None:
        if not 1 <= limit <= 50:
            raise ModelCandidateStoreError("limit must be between 1 and 50")
        if offset < 0:
            raise ModelCandidateStoreError("offset must not be negative")

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> ShadowCandidateRecord:
        return ShadowCandidateRecord(
            proposal_id=str(row["proposal_id"]),
            observation_id=str(row["observation_id"]),
            principal_id=str(row["principal_id"]),
            evidence_message_id=str(row["evidence_message_id"]),
            kind=str(row["kind"]) if row["kind"] is not None else None,
            scope=str(row["scope"]) if row["scope"] is not None else None,
            confidence=(float(row["confidence"]) if row["confidence"] is not None else None),
            sensitive_level=(
                SensitiveLevel(str(row["sensitive_level"]))
                if row["sensitive_level"] is not None
                else None
            ),
            normalized_content=(
                str(row["normalized_content"]) if row["normalized_content"] is not None else None
            ),
            decision=CandidateDecision(str(row["decision"])),
            reason=str(row["reason"]),
            created_at_ms=int(row["created_at_ms"]),
        )

    def list_candidates(
        self,
        *,
        decision: CandidateDecision | None = None,
        limit: int = 8,
        offset: int = 0,
    ) -> tuple[ShadowCandidateRecord, ...]:
        """List immutable queue rows; this method cannot change proposal state."""
        self._validate_window(limit=limit, offset=offset)
        clauses: list[str] = []
        parameters: list[object] = []
        if decision is not None:
            clauses.append("decision = ?")
            parameters.append(decision.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.extend((limit, offset))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT proposal_id, observation_id, principal_id, evidence_message_id,
                       kind, scope, confidence, sensitive_level, normalized_content,
                       decision, reason, created_at_ms
                FROM model_memory_candidate_shadow
                {where}
                ORDER BY created_at_ms DESC, proposal_id DESC
                LIMIT ? OFFSET ?
                """,
                parameters,
            ).fetchall()
        return tuple(self._record_from_row(row) for row in rows)

    # The explicit review name makes the read-only intent clear to callers.
    list_for_review = list_candidates

    def get_for_review(self, proposal_id: str) -> ShadowCandidateRecord:
        """Return one exact or unambiguous short-ID match for owner review."""
        clean = proposal_id.strip().casefold()
        if not clean or len(clean) > 32 or any(char not in "0123456789abcdef" for char in clean):
            raise ModelCandidateNotFoundError("model candidate ID is invalid")
        if len(clean) < 6:
            raise ModelCandidateNotFoundError(
                "model candidate ID prefix must contain at least 6 characters"
            )
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT proposal_id, observation_id, principal_id, evidence_message_id,
                       kind, scope, confidence, sensitive_level, normalized_content,
                       decision, reason, created_at_ms
                FROM model_memory_candidate_shadow
                WHERE proposal_id LIKE ?
                ORDER BY proposal_id
                LIMIT 2
                """,
                (f"{clean}%",),
            ).fetchall()
        if not rows:
            raise ModelCandidateNotFoundError("model candidate ID was not found")
        if len(rows) > 1:
            raise ModelCandidateAmbiguousError("model candidate short ID is ambiguous")
        return self._record_from_row(rows[0])

    async def extract_and_record(
        self,
        extractor: ModelCandidateExtractor,
        observation: Observation,
    ) -> tuple[CandidateResult, ...]:
        results = await extractor.extract(observation)
        await asyncio.to_thread(self.record, observation, results)
        return results
