# ruff: noqa: E501, RUF001
"""Owner-only durable reminders with explicit confirmation and idempotent sends."""

from __future__ import annotations

import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from r_agent.skills import normalized_parameter_hash

SHANGHAI = ZoneInfo("Asia/Shanghai")
_RETRY_OFFSETS_MS = (0, 5 * 60_000, 15 * 60_000, 30 * 60_000)
_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


class ReminderError(RuntimeError):
    """Reminder validation or transition error."""


@dataclass(frozen=True, slots=True)
class ReminderJob:
    job_id: str
    owner_principal_id: str
    owner_qq: str
    content: str
    due_at_ms: int
    status: str
    created_at_ms: int
    confirmed_at_ms: int | None
    acknowledged_at_ms: int | None
    origin_channel: str
    origin_surface: str
    origin_conversation_id: str
    source_message_id: str | None
    approved_parameter_sha256: str | None


@dataclass(frozen=True, slots=True)
class DueOccurrence:
    occurrence_key: str
    job_id: str
    owner_qq: str
    content: str
    attempt: int
    scheduled_at_ms: int
    origin_channel: str
    origin_surface: str
    origin_conversation_id: str


def _number(value: str) -> int | None:
    """Parse the small Chinese/Arabic number vocabulary useful for reminders."""
    if value.isdigit():
        return int(value)
    if not value or any(char not in _CN_DIGITS and char != "十" for char in value):
        return None
    if len(value) == 1:
        return _CN_DIGITS.get(value)
    if value == "十":
        return 10
    if "十" in value:
        tens, _, ones = value.partition("十")
        return (_CN_DIGITS.get(tens, 1) * 10) + (_CN_DIGITS.get(ones, 0) if ones else 0)
    return None


def _clean_reminder_content(value: str) -> str:
    value = value.strip(" \t\r\n，,。！？!?：:；;")
    value = re.sub(r"(?i)(?:^|[\s，,])(?:higgs|希格斯)(?:$|[\s，,])", " ", value)
    return " ".join(value.split()).strip(" \t\r\n，,。！？!?：:；;")


def parse_reminder_intent(text: str, *, now: datetime | None = None) -> tuple[int, str] | None:
    """Parse natural owner reminder requests without requiring one rigid sentence."""
    clean = " ".join(text.strip().split()).replace("：", ":")
    clean = re.sub(r"(?i)(?:^|[\s，,])(?:higgs|希格斯)(?=$|[\s，,])", " ", clean)
    clean = " ".join(clean.split()).strip(" ，,。！？!?")
    clean = re.sub(r"^(?:再)?过(?=[0-9零〇一二两三四五六七八九十])", "", clean)
    if not clean:
        return None
    current = now.astimezone(SHANGHAI) if now is not None else datetime.now(SHANGHAI)
    generic_suffix = "\u7ed9\u6211\u53d1\u4e00\u6761\u6d88\u606f"
    if clean.endswith(generic_suffix):
        generic_head = clean[: -len(generic_suffix)]
        generic_match = re.fullmatch(
            r"\d{1,4}(?:\u5206\u949f|\u5c0f\u65f6|\u5206|\u65f6)", generic_head
        )
        if generic_match:
            amount = int(re.match(r"\d+", generic_head).group())
            minutes = generic_head.endswith(("\u5206", "\u5206\u949f"))
            delta = timedelta(minutes=amount if minutes else amount * 60)
            due = current + delta
            return int(due.timestamp() * 1000), "\u63d0\u9192\u4e8b\u9879"
    relative_patterns = (
        r"^(?:请)?(?:(?:再)?过)?(?P<n>[0-9零〇一二两三四五六七八九十]+)\s*"
        r"(?P<unit>分钟?|分|小时?|时)(?:之后|以后|后)"
        r"(?:给我(?:发(?:一条)?消息)?|提醒我|提示我|叫我|通知我)?(?P<content>.*)$",
        r"^(?:请)?(?:在)?(?P<n>[0-9零〇一二两三四五六七八九十]+)\s*"
        r"(?P<unit>分钟?|分|小时?|时)(?:之后|以后|后)"
        r"(?:给我(?:发(?:一条)?消息)?|提醒我|提示我|叫我|通知我)?(?P<content>.*)$",
    )
    for pattern in relative_patterns:
        relative = re.match(pattern, clean)
        if relative:
            amount = _number(relative.group("n"))
            content = _clean_reminder_content(relative.group("content"))
            if not content and ("给我发" in clean or "发一条消息" in clean):
                content = "提醒事项"
            if amount is None or amount <= 0 or not content:
                return None
            unit = relative.group("unit")
            delta = timedelta(minutes=amount if unit in {"分", "分钟"} else 60 * amount)
            due = current + delta
            return int(due.timestamp() * 1000), content

    absolute = re.search(
        r"(?P<day>今天|明天|今晚)?\s*(?P<h>\d{1,2})(?::|点)(?P<m>\d{1,2})?分?"
        r"\s*(?:的时候)?(?:提醒我|提示我|叫我|通知我|给我发(?:一条)?消息)"
        r"(?P<content>.+)$",
        clean,
    )
    if absolute:
        hour = int(absolute.group("h"))
        minute = int(absolute.group("m") or 0)
        if hour > 23 or minute > 59:
            return None
        day = absolute.group("day")
        base = current + timedelta(days=1) if day == "明天" else current
        due = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day == "今晚" and due <= current:
            due += timedelta(days=1)
        if due <= current:
            return None
        content = _clean_reminder_content(absolute.group("content"))
        return (int(due.timestamp() * 1000), content) if content else None

    dated = re.search(
        r"(?P<date>\d{4}-\d{1,2}-\d{1,2})\s+(?P<h>\d{1,2}):(?P<m>\d{2})"
        r"\s*(?:提醒我|提示我|叫我|通知我|给我发(?:一条)?消息)(?P<content>.+)$",
        clean,
    )
    if dated:
        try:
            due = datetime.strptime(
                f"{dated.group('date')} {dated.group('h')}:{dated.group('m')}",
                "%Y-%m-%d %H:%M",
            ).replace(tzinfo=SHANGHAI)
        except ValueError:
            return None
        content = _clean_reminder_content(dated.group("content"))
        if due <= current or not content:
            return None
        return int(due.timestamp() * 1000), content
    return None


class ReminderStore:
    STATUSES = frozenset(
        {
            "pending_confirmation",
            "scheduled",
            "awaiting_ack",
            "completed",
            "cancelled",
            "missed",
            "failed",
        }
    )

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _approved_parameters(row: sqlite3.Row) -> dict[str, object]:
        """Return the exact side-effect parameters covered by owner confirmation."""
        return {
            "content": str(row["content"]),
            "due_at_ms": int(row["due_at_ms"]),
            "origin_conversation_id": str(row["origin_conversation_id"]),
        }

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminder_jobs (
                    job_id TEXT PRIMARY KEY,
                    owner_principal_id TEXT NOT NULL,
                    owner_qq TEXT NOT NULL,
                    content TEXT NOT NULL,
                    due_at_ms INTEGER NOT NULL,
                    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                    status TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    confirmed_at_ms INTEGER,
                    acknowledged_at_ms INTEGER,
                    cancelled_at_ms INTEGER,
                    updated_at_ms INTEGER NOT NULL,
                    origin_channel TEXT NOT NULL DEFAULT 'qq',
                    origin_surface TEXT NOT NULL DEFAULT 'private',
                    origin_conversation_id TEXT NOT NULL DEFAULT 'legacy',
                    source_message_id TEXT,
                    approved_parameter_sha256 TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminder_occurrences (
                    occurrence_key TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES reminder_jobs(job_id),
                    attempt INTEGER NOT NULL,
                    scheduled_at_ms INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('prepared','sent','failed','unknown')),
                    message_id TEXT,
                    prepared_at_ms INTEGER NOT NULL,
                    finished_at_ms INTEGER,
                    UNIQUE(job_id, attempt)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminder_effects (
                    effect_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurrence_key TEXT NOT NULL,
                    state TEXT NOT NULL,
                    detail_sha256 TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminder_due ON reminder_jobs(status, due_at_ms)"
            )
            existing = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(reminder_jobs)").fetchall()
            }
            migrations = {
                "origin_channel": "TEXT NOT NULL DEFAULT 'qq'",
                "origin_surface": "TEXT NOT NULL DEFAULT 'private'",
                "origin_conversation_id": "TEXT NOT NULL DEFAULT 'legacy'",
                "source_message_id": "TEXT",
                "approved_parameter_sha256": "TEXT",
            }
            for column, declaration in migrations.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE reminder_jobs ADD COLUMN {column} {declaration}")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reminder_origin
                ON reminder_jobs(owner_principal_id, origin_conversation_id, status)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reminder_occurrence_message
                ON reminder_occurrences(message_id)
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row) -> ReminderJob:
        return ReminderJob(
            str(row["job_id"]),
            str(row["owner_principal_id"]),
            str(row["owner_qq"]),
            str(row["content"]),
            int(row["due_at_ms"]),
            str(row["status"]),
            int(row["created_at_ms"]),
            int(row["confirmed_at_ms"]) if row["confirmed_at_ms"] is not None else None,
            int(row["acknowledged_at_ms"]) if row["acknowledged_at_ms"] is not None else None,
            str(row["origin_channel"]),
            str(row["origin_surface"]),
            str(row["origin_conversation_id"]),
            str(row["source_message_id"]) if row["source_message_id"] is not None else None,
            str(row["approved_parameter_sha256"])
            if row["approved_parameter_sha256"] is not None
            else None,
        )

    def _resolve(self, short_id: str) -> str:
        clean = short_id.strip().lower()
        if len(clean) < 6:
            raise ReminderError("提醒ID至少需要6位")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT job_id FROM reminder_jobs WHERE job_id LIKE ? LIMIT 2", (f"{clean}%",)
            ).fetchall()
        if not rows:
            raise ReminderError("未找到提醒")
        if len(rows) > 1:
            raise ReminderError("提醒ID不唯一，请输入更多位")
        return str(rows[0][0])

    def create_pending(
        self,
        *,
        owner_principal_id: str,
        owner_qq: str,
        content: str,
        due_at_ms: int,
        origin_channel: str = "qq",
        origin_surface: str = "private",
        origin_conversation_id: str = "legacy",
        source_message_id: str | None = None,
        now_ms: int | None = None,
    ) -> ReminderJob:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        clean = " ".join(content.split())
        if not 1 <= len(clean) <= 500:
            raise ReminderError("提醒内容长度必须为1到500字")
        if not now + 5_000 <= due_at_ms <= now + 366 * 86_400_000:
            raise ReminderError("提醒时间必须在5秒后到366天内")
        if origin_surface not in {"private", "group"}:
            raise ReminderError("invalid reminder origin surface")
        if not origin_channel.strip() or not origin_conversation_id.strip():
            raise ReminderError("invalid reminder origin conversation")
        job_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reminder_jobs(
                    job_id, owner_principal_id, owner_qq, content, due_at_ms,
                    status, created_at_ms, updated_at_ms, origin_channel,
                    origin_surface, origin_conversation_id, source_message_id
                ) VALUES (?, ?, ?, ?, ?, 'pending_confirmation', ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    owner_principal_id,
                    owner_qq,
                    clean,
                    due_at_ms,
                    now,
                    now,
                    origin_channel.strip(),
                    origin_surface,
                    origin_conversation_id.strip(),
                    source_message_id,
                ),
            )
        return self.get(job_id)

    def get(self, short_id: str) -> ReminderJob:
        job_id = self._resolve(short_id)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM reminder_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise ReminderError("未找到提醒")
        return self._row(row)

    def latest_pending(self, owner_principal_id: str) -> ReminderJob | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM reminder_jobs WHERE owner_principal_id=?
                  AND status='pending_confirmation' ORDER BY created_at_ms DESC LIMIT 1
                """,
                (owner_principal_id,),
            ).fetchone()
        return self._row(row) if row is not None else None

    def latest_awaiting_ack(self, owner_principal_id: str) -> ReminderJob | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM reminder_jobs WHERE owner_principal_id=?
                  AND status='awaiting_ack' ORDER BY due_at_ms DESC LIMIT 1
                """,
                (owner_principal_id,),
            ).fetchone()
        return self._row(row) if row is not None else None

    def resolve_contextual(
        self,
        *,
        owner_principal_id: str,
        statuses: frozenset[str],
        conversation_id: str,
        reply_message_id: str | None = None,
    ) -> ReminderJob | None:
        """Resolve only an explicitly quoted or single same-conversation job."""
        if not statuses or not statuses.issubset(self.STATUSES):
            raise ReminderError("invalid reminder status filter")
        placeholders = ",".join("?" for _ in statuses)
        ordered_statuses = tuple(sorted(statuses))
        with self._connect() as conn:
            if reply_message_id:
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT j.* FROM reminder_jobs j
                    LEFT JOIN reminder_occurrences o ON o.job_id=j.job_id
                    WHERE j.owner_principal_id=? AND j.status IN ({placeholders})
                      AND j.origin_conversation_id=?
                      AND (j.source_message_id=? OR o.message_id=?)
                    LIMIT 2
                    """,
                    (
                        owner_principal_id,
                        *ordered_statuses,
                        conversation_id,
                        reply_message_id,
                        reply_message_id,
                    ),
                ).fetchall()
                if len(rows) == 1:
                    return self._row(rows[0])
                if len(rows) > 1:
                    return None
            rows = conn.execute(
                f"""
                SELECT * FROM reminder_jobs
                WHERE owner_principal_id=? AND status IN ({placeholders})
                  AND origin_conversation_id=?
                ORDER BY created_at_ms DESC LIMIT 2
                """,
                (owner_principal_id, *ordered_statuses, conversation_id),
            ).fetchall()
        return self._row(rows[0]) if len(rows) == 1 else None

    def _transition(self, short_id: str, *, allowed: set[str], target: str) -> ReminderJob:
        job_id = self._resolve(short_id)
        now = int(time.time() * 1000)
        marks = {
            "scheduled": "confirmed_at_ms",
            "completed": "acknowledged_at_ms",
            "cancelled": "cancelled_at_ms",
        }
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM reminder_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None or str(row[0]) not in allowed:
                raise ReminderError("当前提醒状态不允许该操作")
            column = marks.get(target)
            if column:
                conn.execute(
                    f"UPDATE reminder_jobs SET status=?, {column}=?, updated_at_ms=? WHERE job_id=?",
                    (target, now, now, job_id),
                )
            else:
                conn.execute(
                    "UPDATE reminder_jobs SET status=?, updated_at_ms=? WHERE job_id=?",
                    (target, now, job_id),
                )
        return self.get(job_id)

    def confirm(self, short_id: str) -> ReminderJob:
        job_id = self._resolve(short_id)
        now = int(time.time() * 1000)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM reminder_jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None or str(row["status"]) != "pending_confirmation":
                raise ReminderError("reminder state does not allow confirmation")
            digest = normalized_parameter_hash(self._approved_parameters(row))
            conn.execute(
                """
                UPDATE reminder_jobs SET status='scheduled', confirmed_at_ms=?,
                    approved_parameter_sha256=?, updated_at_ms=? WHERE job_id=?
                """,
                (now, digest, now, job_id),
            )
        return self.get(job_id)

    def acknowledge(self, short_id: str) -> ReminderJob:
        return self._transition(short_id, allowed={"awaiting_ack", "scheduled"}, target="completed")

    def cancel(self, short_id: str) -> ReminderJob:
        return self._transition(
            short_id,
            allowed={"pending_confirmation", "scheduled", "awaiting_ack"},
            target="cancelled",
        )

    def snooze(self, short_id: str, minutes: int) -> ReminderJob:
        if not 1 <= minutes <= 1440:
            raise ReminderError("延后时间必须为1到1440分钟")
        job_id = self._resolve(short_id)
        now = int(time.time() * 1000)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM reminder_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None or str(row[0]) not in {"scheduled", "awaiting_ack"}:
                raise ReminderError("当前提醒不能延后")
            conn.execute(
                """
                UPDATE reminder_jobs SET due_at_ms=?, status='pending_confirmation',
                    confirmed_at_ms=NULL, approved_parameter_sha256=NULL, updated_at_ms=?
                WHERE job_id=?
                """,
                (now + minutes * 60_000, now, job_id),
            )
            conn.execute(
                "UPDATE reminder_occurrences SET state='failed' WHERE job_id=? AND state='prepared'",
                (job_id,),
            )
        return self.get(job_id)

    def list(self, *, limit: int = 10) -> list[ReminderJob]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reminder_jobs ORDER BY created_at_ms DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row(row) for row in rows]

    def prepare_due(self, *, now_ms: int | None = None) -> list[DueOccurrence]:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        due: list[DueOccurrence] = []
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            jobs = conn.execute(
                """
                SELECT * FROM reminder_jobs
                WHERE status IN ('scheduled','awaiting_ack') AND due_at_ms <= ?
                ORDER BY due_at_ms LIMIT 50
                """,
                (now,),
            ).fetchall()
            for row in jobs:
                job_id = str(row["job_id"])
                approved_digest = row["approved_parameter_sha256"]
                actual_digest = normalized_parameter_hash(self._approved_parameters(row))
                if approved_digest is None or str(approved_digest) != actual_digest:
                    # Fail closed if a confirmed job was altered in storage or came
                    # from a legacy path that never captured parameter approval.
                    conn.execute(
                        "UPDATE reminder_jobs SET status='failed', updated_at_ms=? WHERE job_id=?",
                        (now, job_id),
                    )
                    continue
                due_at = int(row["due_at_ms"])
                if now > due_at + _RETRY_OFFSETS_MS[-1] + 60_000:
                    conn.execute(
                        "UPDATE reminder_jobs SET status='missed', updated_at_ms=? WHERE job_id=?",
                        (now, job_id),
                    )
                    continue
                eligible = [
                    attempt
                    for attempt, offset in enumerate(_RETRY_OFFSETS_MS)
                    if due_at + offset <= now
                ]
                target_attempt = max(eligible)
                existing = {
                    int(item[0])
                    for item in conn.execute(
                        "SELECT attempt FROM reminder_occurrences WHERE job_id=?", (job_id,)
                    ).fetchall()
                }
                if target_attempt in existing:
                    continue
                scheduled = due_at + _RETRY_OFFSETS_MS[target_attempt]
                key = f"{job_id}:{target_attempt}"
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO reminder_occurrences(
                        occurrence_key, job_id, attempt, scheduled_at_ms,
                        state, prepared_at_ms
                    ) VALUES (?, ?, ?, ?, 'prepared', ?)
                    """,
                    (key, job_id, target_attempt, scheduled, now),
                )
                if cursor.rowcount == 1:
                    due.append(
                        DueOccurrence(
                            key,
                            job_id,
                            str(row["owner_qq"]),
                            str(row["content"]),
                            target_attempt,
                            scheduled,
                            str(row["origin_channel"]),
                            str(row["origin_surface"]),
                            str(row["origin_conversation_id"]),
                        )
                    )
        return due

    def finish_occurrence(
        self, occurrence_key: str, *, state: str, message_id: str | None = None
    ) -> None:
        if state not in {"sent", "failed", "unknown"}:
            raise ReminderError("无效发送状态")
        now = int(time.time() * 1000)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT job_id FROM reminder_occurrences WHERE occurrence_key=? AND state='prepared'",
                (occurrence_key,),
            ).fetchone()
            if row is None:
                return
            conn.execute(
                """
                UPDATE reminder_occurrences SET state=?, message_id=?, finished_at_ms=?
                WHERE occurrence_key=? AND state='prepared'
                """,
                (state, message_id, now, occurrence_key),
            )
            if state == "sent":
                conn.execute(
                    "UPDATE reminder_jobs SET status='awaiting_ack', updated_at_ms=? WHERE job_id=?",
                    (now, str(row["job_id"])),
                )
            digest = (
                __import__("hashlib").sha256(f"{state}:{message_id or ''}".encode()).hexdigest()
            )
            conn.execute(
                "INSERT INTO reminder_effects(occurrence_key,state,detail_sha256,created_at_ms) VALUES (?,?,?,?)",
                (occurrence_key, state, digest, now),
            )

    def recover_stale_prepared(
        self, *, now_ms: int | None = None, stale_after_ms: int = 60_000
    ) -> int:
        """Mark crash-interrupted sends unknown instead of risking a duplicate send."""
        if stale_after_ms < 1_000:
            raise ReminderError("stale threshold is too short")
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE reminder_occurrences
                SET state='unknown', finished_at_ms=?
                WHERE state='prepared' AND prepared_at_ms <= ?
                """,
                (now, now - stale_after_ms),
            )
        return cursor.rowcount


def format_job(job: ReminderJob) -> str:
    due = datetime.fromtimestamp(job.due_at_ms / 1000, SHANGHAI)
    return (
        f"提醒ID：{job.job_id[:8]}\n"
        f"内容：{job.content}\n"
        f"时间：{due:%Y-%m-%d %H:%M:%S}（北京时间）\n"
        f"状态：{job.status}\n"
        "追发：到点、+5、+15、+30分钟；明确确认收到后停止。"
    )
