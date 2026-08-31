# ruff: noqa: RUF001
"""Durable, principal-isolated daily plans with version-bound confirmation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from r_agent.skills import normalized_parameter_hash
from r_agent.task_scope import TaskScopeError
from r_agent.transport import DeliveryTarget


class AgendaError(RuntimeError):
    """A plan failed validation, authorization, or a state transition."""


@dataclass(frozen=True, slots=True)
class AgendaTask:
    task_id: str
    plan_id: str
    title: str
    duration_minutes: int
    duration_source: str
    location_text: str | None
    start_at_ms: int | None
    end_at_ms: int | None
    earliest_start_ms: int | None
    latest_finish_ms: int | None
    fixed_start_ms: int | None
    deadline_ms: int | None
    priority: int
    transport_mode: str | None
    status: str
    position: int


@dataclass(frozen=True, slots=True)
class DailyPlan:
    plan_id: str
    principal_id: str
    plan_date: str
    status: str
    version: int
    parameter_sha256: str
    parent_plan_id: str | None
    map_consent_sha256: str | None
    map_consent_expires_at_ms: int | None
    route_verified: bool
    created_at_ms: int
    updated_at_ms: int
    confirmed_at_ms: int | None
    delivery_channel: str | None = None
    delivery_surface: str | None = None
    delivery_account_id: str | None = None
    delivery_target_id: str | None = None
    delivery_binding_version: int = 1

    @property
    def delivery_target(self) -> DeliveryTarget | None:
        fields = (
            self.delivery_channel,
            self.delivery_surface,
            self.delivery_account_id,
            self.delivery_target_id,
        )
        if all(value is None for value in fields):
            return None
        if any(value is None for value in fields):
            raise AgendaError("计划投递目标无效")
        try:
            return DeliveryTarget(
                self.delivery_channel or "",
                self.delivery_account_id or "",
                self.delivery_target_id or "",
                self.delivery_surface or "",
            )
        except TaskScopeError as exc:
            raise AgendaError("计划投递目标无效") from exc


def _clean_title(value: str) -> str:
    return " ".join(value.split()).strip(" ，,。；;：:")


class AgendaStore:
    """SQLite store that never exposes one principal's plans to another."""

    PLAN_STATUSES = frozenset(
        {
            "draft",
            "awaiting_map_consent",
            "awaiting_confirmation",
            "active",
            "completed",
            "cancelled",
            "superseded",
            "expired",
        }
    )
    TASK_STATUSES = frozenset(
        {"draft", "scheduled", "in_progress", "completed", "skipped", "cancelled"}
    )

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    component TEXT PRIMARY KEY,
                    version INTEGER NOT NULL
                );
                INSERT INTO schema_meta(component, version) VALUES ('agenda', 1)
                ON CONFLICT(component) DO NOTHING;

                CREATE TABLE IF NOT EXISTS daily_plans (
                    plan_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    plan_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    parameter_sha256 TEXT NOT NULL,
                    parent_plan_id TEXT,
                    request_key TEXT,
                    map_consent_sha256 TEXT,
                    map_consent_expires_at_ms INTEGER,
                    route_verified INTEGER NOT NULL DEFAULT 0,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    confirmed_at_ms INTEGER
                    ,delivery_channel TEXT
                    ,delivery_surface TEXT
                    ,delivery_account_id TEXT
                    ,delivery_target_id TEXT
                    ,delivery_binding_version INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_agenda_owner_date
                    ON daily_plans(principal_id, plan_date, updated_at_ms DESC);

                CREATE TABLE IF NOT EXISTS agenda_tasks (
                    task_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL REFERENCES daily_plans(plan_id),
                    title TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    duration_source TEXT NOT NULL,
                    location_text TEXT,
                    start_at_ms INTEGER,
                    end_at_ms INTEGER,
                    earliest_start_ms INTEGER,
                    latest_finish_ms INTEGER,
                    fixed_start_ms INTEGER,
                    deadline_ms INTEGER,
                    priority INTEGER NOT NULL,
                    transport_mode TEXT,
                    hard_constraints_json TEXT NOT NULL DEFAULT '[]',
                    soft_preferences_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL,
                    position INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agenda_tasks_plan
                    ON agenda_tasks(plan_id, position);

                CREATE TABLE IF NOT EXISTS agenda_dependencies (
                    plan_id TEXT NOT NULL REFERENCES daily_plans(plan_id),
                    task_id TEXT NOT NULL REFERENCES agenda_tasks(task_id),
                    depends_on_task_id TEXT NOT NULL REFERENCES agenda_tasks(task_id),
                    PRIMARY KEY(plan_id, task_id, depends_on_task_id)
                );

                CREATE TABLE IF NOT EXISTS agenda_versions (
                    plan_id TEXT NOT NULL REFERENCES daily_plans(plan_id),
                    version INTEGER NOT NULL,
                    parameter_sha256 TEXT NOT NULL,
                    document_json TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    PRIMARY KEY(plan_id, version)
                );

                CREATE TABLE IF NOT EXISTS agenda_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id TEXT NOT NULL,
                    actor_principal_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    reason TEXT,
                    detail_sha256 TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agenda_events_plan
                    ON agenda_events(plan_id, created_at_ms);

                CREATE TABLE IF NOT EXISTS planner_profiles (
                    principal_id TEXT PRIMARY KEY,
                    origin_text TEXT,
                    transport_mode TEXT,
                    remember_origin INTEGER NOT NULL DEFAULT 0,
                    updated_at_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS route_cache (
                    cache_key TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    distance_meters INTEGER,
                    expires_at_ms INTEGER NOT NULL,
                    created_at_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agenda_reminder_links (
                    plan_id TEXT NOT NULL,
                    task_id TEXT,
                    reminder_job_id TEXT NOT NULL UNIQUE,
                    plan_version INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    PRIMARY KEY(plan_id, reminder_job_id)
                );
                """
            )
            columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(daily_plans)").fetchall()
            }
            if "request_key" not in columns:
                conn.execute("ALTER TABLE daily_plans ADD COLUMN request_key TEXT")
            for column, declaration in {
                "delivery_channel": "TEXT",
                "delivery_surface": "TEXT",
                "delivery_account_id": "TEXT",
                "delivery_target_id": "TEXT",
                "delivery_binding_version": "INTEGER NOT NULL DEFAULT 1",
            }.items():
                if column not in columns:
                    conn.execute(f"ALTER TABLE daily_plans ADD COLUMN {column} {declaration}")
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_agenda_request_key
                ON daily_plans(request_key) WHERE request_key IS NOT NULL
                """
            )

    @staticmethod
    def _plan(row: sqlite3.Row) -> DailyPlan:
        return DailyPlan(
            plan_id=str(row["plan_id"]),
            principal_id=str(row["principal_id"]),
            plan_date=str(row["plan_date"]),
            status=str(row["status"]),
            version=int(row["version"]),
            parameter_sha256=str(row["parameter_sha256"]),
            parent_plan_id=str(row["parent_plan_id"]) if row["parent_plan_id"] else None,
            map_consent_sha256=(
                str(row["map_consent_sha256"]) if row["map_consent_sha256"] else None
            ),
            map_consent_expires_at_ms=(
                int(row["map_consent_expires_at_ms"])
                if row["map_consent_expires_at_ms"] is not None
                else None
            ),
            route_verified=bool(row["route_verified"]),
            created_at_ms=int(row["created_at_ms"]),
            updated_at_ms=int(row["updated_at_ms"]),
            confirmed_at_ms=(
                int(row["confirmed_at_ms"]) if row["confirmed_at_ms"] is not None else None
            ),
            delivery_channel=(
                str(row["delivery_channel"]) if row["delivery_channel"] is not None else None
            ),
            delivery_surface=(
                str(row["delivery_surface"]) if row["delivery_surface"] is not None else None
            ),
            delivery_account_id=(
                str(row["delivery_account_id"]) if row["delivery_account_id"] is not None else None
            ),
            delivery_target_id=(
                str(row["delivery_target_id"]) if row["delivery_target_id"] is not None else None
            ),
            delivery_binding_version=int(row["delivery_binding_version"]),
        )

    @staticmethod
    def _task(row: sqlite3.Row) -> AgendaTask:
        def optional_int(name: str) -> int | None:
            return int(row[name]) if row[name] is not None else None

        return AgendaTask(
            task_id=str(row["task_id"]),
            plan_id=str(row["plan_id"]),
            title=str(row["title"]),
            duration_minutes=int(row["duration_minutes"]),
            duration_source=str(row["duration_source"]),
            location_text=str(row["location_text"]) if row["location_text"] else None,
            start_at_ms=optional_int("start_at_ms"),
            end_at_ms=optional_int("end_at_ms"),
            earliest_start_ms=optional_int("earliest_start_ms"),
            latest_finish_ms=optional_int("latest_finish_ms"),
            fixed_start_ms=optional_int("fixed_start_ms"),
            deadline_ms=optional_int("deadline_ms"),
            priority=int(row["priority"]),
            transport_mode=str(row["transport_mode"]) if row["transport_mode"] else None,
            status=str(row["status"]),
            position=int(row["position"]),
        )

    @staticmethod
    def _validate_document(document: dict[str, Any]) -> None:
        tasks = document.get("tasks")
        if not isinstance(tasks, list) or not 1 <= len(tasks) <= 20:
            raise AgendaError("每份计划必须包含 1 到 20 项任务")
        for item in tasks:
            if not isinstance(item, dict):
                raise AgendaError("任务格式无效")
            title = _clean_title(str(item.get("title", "")))
            duration = item.get("duration_minutes")
            priority = item.get("priority", 3)
            if not 1 <= len(title) <= 120:
                raise AgendaError("任务标题长度必须为 1 到 120 字")
            if (
                isinstance(duration, bool)
                or not isinstance(duration, int)
                or not 5 <= duration <= 480
            ):
                raise AgendaError("任务时长必须为 5 到 480 分钟")
            if (
                isinstance(priority, bool)
                or not isinstance(priority, int)
                or not 1 <= priority <= 5
            ):
                raise AgendaError("任务优先级必须为 1 到 5")

    def _append_event(
        self,
        conn: sqlite3.Connection,
        *,
        plan_id: str,
        actor_principal_id: str,
        event_type: str,
        reason: str | None,
        detail: dict[str, Any],
        now_ms: int,
    ) -> None:
        digest = normalized_parameter_hash(detail)
        conn.execute(
            """
            INSERT INTO agenda_events(
                plan_id, actor_principal_id, event_type, reason, detail_sha256, created_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (plan_id, actor_principal_id, event_type, reason, digest, now_ms),
        )

    def create_draft(
        self,
        *,
        principal_id: str,
        actor_principal_id: str,
        plan_date: date,
        document: dict[str, Any],
        parent_plan_id: str | None = None,
        needs_map_consent: bool = False,
        request_key: str | None = None,
        max_drafts_for_date: int | None = None,
        delivery_target: DeliveryTarget | None = None,
        now_ms: int | None = None,
    ) -> DailyPlan:
        self._validate_document(document)
        if request_key is not None and (
            len(request_key) != 64 or any(char not in "0123456789abcdef" for char in request_key)
        ):
            raise AgendaError("计划请求幂等键无效")
        if max_drafts_for_date is not None and not 1 <= max_drafts_for_date <= 50:
            raise AgendaError("计划草案限额无效")
        if delivery_target is not None and not isinstance(delivery_target, DeliveryTarget):
            raise AgendaError("计划投递目标无效")
        now = int(time.time() * 1000) if now_ms is None else now_ms
        digest_input: dict[str, Any] = document
        if delivery_target is not None:
            digest_input = {"document": document, "delivery_target": delivery_target.as_mapping()}
        digest = normalized_parameter_hash(digest_input)
        status = "awaiting_map_consent" if needs_map_consent else "awaiting_confirmation"
        encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if request_key is not None:
                prior = conn.execute(
                    "SELECT * FROM daily_plans WHERE request_key=?",
                    (request_key,),
                ).fetchone()
                if prior is not None:
                    expected = (
                        principal_id,
                        plan_date.isoformat(),
                        digest,
                        parent_plan_id,
                    )
                    actual = (
                        str(prior["principal_id"]),
                        str(prior["plan_date"]),
                        str(prior["parameter_sha256"]),
                        str(prior["parent_plan_id"]) if prior["parent_plan_id"] else None,
                    )
                    if actual != expected:
                        raise AgendaError("计划请求幂等键与既有参数冲突")
                    existing = self._plan(prior)
                    if delivery_target is not None:
                        self._assert_target(existing, delivery_target)
                    return existing
            if max_drafts_for_date is not None:
                count = conn.execute(
                    "SELECT COUNT(*) FROM daily_plans WHERE principal_id=? AND plan_date=?",
                    (principal_id, plan_date.isoformat()),
                ).fetchone()
                if count is not None and int(count[0]) >= max_drafts_for_date:
                    raise AgendaError("今天生成计划草案的次数已达到上限")
            plan_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO daily_plans(
                    plan_id, principal_id, plan_date, status, version, parameter_sha256,
                    parent_plan_id, request_key, created_at_ms, updated_at_ms,
                    delivery_channel, delivery_surface, delivery_account_id, delivery_target_id,
                    delivery_binding_version
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    principal_id,
                    plan_date.isoformat(),
                    status,
                    digest,
                    parent_plan_id,
                    request_key,
                    now,
                    now,
                    delivery_target.channel if delivery_target is not None else None,
                    delivery_target.surface if delivery_target is not None else None,
                    delivery_target.bot_account if delivery_target is not None else None,
                    delivery_target.target_id if delivery_target is not None else None,
                    2 if delivery_target is not None else 1,
                ),
            )
            task_ids: dict[str, str] = {}
            for position, item in enumerate(document["tasks"]):
                task_id = str(uuid.uuid4())
                client_id = str(item.get("client_id", position + 1))
                task_ids[client_id] = task_id
                conn.execute(
                    """
                    INSERT INTO agenda_tasks(
                        task_id, plan_id, title, duration_minutes, duration_source,
                        location_text, start_at_ms, end_at_ms, earliest_start_ms,
                        latest_finish_ms, fixed_start_ms, deadline_ms, priority,
                        transport_mode, hard_constraints_json, soft_preferences_json,
                        status, position
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)
                    """,
                    (
                        task_id,
                        plan_id,
                        _clean_title(str(item["title"])),
                        int(item["duration_minutes"]),
                        str(item.get("duration_source", "estimated")),
                        item.get("location_text"),
                        item.get("start_at_ms"),
                        item.get("end_at_ms"),
                        item.get("earliest_start_ms"),
                        item.get("latest_finish_ms"),
                        item.get("fixed_start_ms"),
                        item.get("deadline_ms"),
                        int(item.get("priority", 3)),
                        item.get("transport_mode"),
                        json.dumps(item.get("hard_constraints", []), ensure_ascii=False),
                        json.dumps(item.get("soft_preferences", []), ensure_ascii=False),
                        position,
                    ),
                )
            for position, item in enumerate(document["tasks"]):
                task_id = task_ids[str(item.get("client_id", position + 1))]
                for dependency in item.get("dependencies", []):
                    dependency_id = task_ids.get(str(dependency))
                    if dependency_id is None or dependency_id == task_id:
                        raise AgendaError("任务依赖关系无效")
                    conn.execute(
                        "INSERT INTO agenda_dependencies VALUES (?, ?, ?)",
                        (plan_id, task_id, dependency_id),
                    )
            conn.execute(
                "INSERT INTO agenda_versions VALUES (?, 1, ?, ?, ?)",
                (plan_id, digest, encoded, now),
            )
            self._append_event(
                conn,
                plan_id=plan_id,
                actor_principal_id=actor_principal_id,
                event_type="draft_created",
                reason=None,
                detail={"version": 1, "parameter_sha256": digest},
                now_ms=now,
            )
        return self.get(plan_id, principal_id=principal_id, delivery_target=delivery_target)

    def _resolve(self, short_id: str, *, principal_id: str | None) -> str:
        clean = short_id.strip().lower()
        if len(clean) < 6:
            raise AgendaError("计划或任务 ID 至少需要 6 位")
        query = "SELECT plan_id FROM daily_plans WHERE plan_id LIKE ?"
        params: list[object] = [f"{clean}%"]
        if principal_id is not None:
            query += " AND principal_id=?"
            params.append(principal_id)
        query += " LIMIT 2"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        if not rows:
            raise AgendaError("未找到计划")
        if len(rows) > 1:
            raise AgendaError("短 ID 不唯一，请输入更多位")
        return str(rows[0][0])

    @staticmethod
    def _assert_target(plan: DailyPlan, delivery_target: DeliveryTarget) -> DeliveryTarget:
        if not isinstance(delivery_target, DeliveryTarget):
            raise AgendaError("计划投递目标无效")
        try:
            stored = plan.delivery_target
        except AgendaError:
            raise
        if stored != delivery_target:
            raise AgendaError("计划不属于当前会话")
        return delivery_target

    def get(
        self,
        short_id: str,
        *,
        principal_id: str | None,
        delivery_target: DeliveryTarget | None = None,
    ) -> DailyPlan:
        plan_id = self._resolve(short_id, principal_id=principal_id)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM daily_plans WHERE plan_id=?", (plan_id,)).fetchone()
        if row is None:
            raise AgendaError("未找到计划")
        plan = self._plan(row)
        if delivery_target is not None:
            self._assert_target(plan, delivery_target)
        return plan

    def get_for_principal(
        self,
        short_id: str,
        *,
        principal_id: str,
        delivery_target: DeliveryTarget,
    ) -> DailyPlan:
        return self.get(
            short_id,
            principal_id=principal_id,
            delivery_target=delivery_target,
        )

    def get_by_request_key(
        self,
        request_key: str,
        *,
        principal_id: str,
        delivery_target: DeliveryTarget | None = None,
    ) -> DailyPlan | None:
        if len(request_key) != 64 or any(char not in "0123456789abcdef" for char in request_key):
            raise AgendaError("计划请求幂等键无效")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM daily_plans WHERE request_key=? AND principal_id=?",
                (request_key, principal_id),
            ).fetchone()
        if row is None:
            return None
        plan = self._plan(row)
        if delivery_target is not None:
            self._assert_target(plan, delivery_target)
        return plan

    def tasks(
        self,
        short_id: str,
        *,
        principal_id: str | None,
        delivery_target: DeliveryTarget | None = None,
    ) -> list[AgendaTask]:
        plan = self.get(short_id, principal_id=principal_id, delivery_target=delivery_target)
        plan_id = plan.plan_id
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agenda_tasks WHERE plan_id=? ORDER BY position", (plan_id,)
            ).fetchall()
        return [self._task(row) for row in rows]

    def latest_pending(
        self, principal_id: str, *, delivery_target: DeliveryTarget | None = None
    ) -> DailyPlan | None:
        target = delivery_target
        with self._connect() as conn:
            if target is None:
                row = conn.execute(
                    """
                    SELECT * FROM daily_plans
                    WHERE principal_id=? AND status IN (
                        'draft','awaiting_map_consent','awaiting_confirmation'
                    ) ORDER BY updated_at_ms DESC LIMIT 1
                    """,
                    (principal_id,),
                ).fetchone()
            else:
                if not isinstance(target, DeliveryTarget):
                    raise AgendaError("计划投递目标无效")
                row = conn.execute(
                    """
                    SELECT * FROM daily_plans
                    WHERE principal_id=? AND status IN (
                        'draft','awaiting_map_consent','awaiting_confirmation'
                    ) AND delivery_channel=? AND delivery_surface=?
                      AND delivery_account_id=? AND delivery_target_id=?
                    ORDER BY updated_at_ms DESC LIMIT 1
                    """,
                    (
                        principal_id,
                        target.channel,
                        target.surface,
                        target.bot_account,
                        target.target_id,
                    ),
                ).fetchone()
        if row is None:
            return None
        plan = self._plan(row)
        return plan

    def list_for_principal(
        self,
        principal_id: str,
        *,
        limit: int = 10,
        delivery_target: DeliveryTarget | None = None,
    ) -> list[DailyPlan]:
        if not 1 <= limit <= 50:
            raise AgendaError("计划列表数量必须在 1 到 50 之间")
        with self._connect() as conn:
            if delivery_target is None:
                rows = conn.execute(
                    """
                    SELECT * FROM daily_plans WHERE principal_id=?
                    ORDER BY updated_at_ms DESC LIMIT ?
                    """,
                    (principal_id, limit),
                ).fetchall()
            else:
                if not isinstance(delivery_target, DeliveryTarget):
                    raise AgendaError("计划投递目标无效")
                rows = conn.execute(
                    """
                    SELECT * FROM daily_plans
                    WHERE principal_id=? AND delivery_channel=? AND delivery_surface=?
                      AND delivery_account_id=? AND delivery_target_id=?
                    ORDER BY updated_at_ms DESC LIMIT ?
                    """,
                    (
                        principal_id,
                        delivery_target.channel,
                        delivery_target.surface,
                        delivery_target.bot_account,
                        delivery_target.target_id,
                        limit,
                    ),
                ).fetchall()
        return [self._plan(row) for row in rows]

    def count_for_date(self, principal_id: str, plan_date: date) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM daily_plans WHERE principal_id=? AND plan_date=?",
                (principal_id, plan_date.isoformat()),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def event_count_since(self, principal_id: str, event_type: str, *, since_ms: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM agenda_events e
                JOIN daily_plans p ON p.plan_id=e.plan_id
                WHERE p.principal_id=? AND e.event_type=? AND e.created_at_ms>=?
                """,
                (principal_id, event_type, since_ms),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def grant_map_consent(
        self,
        short_id: str,
        *,
        principal_id: str,
        actor_principal_id: str,
        consent_parameters: dict[str, Any],
        quota_since_ms: int | None = None,
        max_grants: int | None = None,
        delivery_target: DeliveryTarget | None = None,
        now_ms: int | None = None,
    ) -> DailyPlan:
        plan = self.get(short_id, principal_id=principal_id, delivery_target=delivery_target)
        now = int(time.time() * 1000) if now_ms is None else now_ms
        digest = normalized_parameter_hash(consent_parameters)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM daily_plans WHERE plan_id=?", (plan.plan_id,)
            ).fetchone()
            if row is None:
                raise AgendaError("未找到计划")
            if (
                str(row["status"]) == "awaiting_confirmation"
                and (str(row["map_consent_sha256"]) if row["map_consent_sha256"] else None)
                == digest
            ):
                return self._plan(row)
            if str(row["status"]) != "awaiting_map_consent":
                raise AgendaError("当前计划不等待地图授权")
            if (quota_since_ms is None) != (max_grants is None):
                raise AgendaError("地图授权限额参数不完整")
            if quota_since_ms is not None and max_grants is not None:
                if max_grants < 0:
                    raise AgendaError("地图授权限额无效")
                count = conn.execute(
                    """
                    SELECT COUNT(*) FROM agenda_events e
                    JOIN daily_plans p ON p.plan_id=e.plan_id
                    WHERE p.principal_id=? AND e.event_type='map_consent_granted'
                      AND e.created_at_ms>=?
                    """,
                    (principal_id, quota_since_ms),
                ).fetchone()
                if count is not None and int(count[0]) >= max_grants:
                    raise AgendaError("今天的地图优化次数已达到上限")
            conn.execute(
                """
                UPDATE daily_plans SET map_consent_sha256=?, map_consent_expires_at_ms=?,
                    status='awaiting_confirmation', updated_at_ms=? WHERE plan_id=?
                """,
                (digest, now + 10 * 60_000, now, plan.plan_id),
            )
            self._append_event(
                conn,
                plan_id=plan.plan_id,
                actor_principal_id=actor_principal_id,
                event_type="map_consent_granted",
                reason=None,
                detail={"consent_sha256": digest},
                now_ms=now,
            )
        return self.get(
            plan.plan_id,
            principal_id=principal_id,
            delivery_target=delivery_target,
        )

    def confirm_exact_version(
        self,
        short_id: str,
        *,
        principal_id: str,
        actor_principal_id: str,
        parameter_sha256: str,
        delivery_target: DeliveryTarget | None = None,
        now_ms: int | None = None,
    ) -> DailyPlan:
        plan = self.get(short_id, principal_id=principal_id, delivery_target=delivery_target)
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM daily_plans WHERE plan_id=?", (plan.plan_id,)
            ).fetchone()
            if row is None:
                raise AgendaError("未找到计划")
            current = self._plan(row)
            if not parameter_sha256 or parameter_sha256 != current.parameter_sha256:
                raise AgendaError("计划已经变化，请重新查看后确认")
            if current.status == "active":
                return current
            if current.status != "awaiting_confirmation":
                raise AgendaError("当前计划不能确认")
            cursor = conn.execute(
                """
                UPDATE daily_plans SET status='active', confirmed_at_ms=?, updated_at_ms=?
                WHERE plan_id=? AND status='awaiting_confirmation' AND parameter_sha256=?
                """,
                (now, now, plan.plan_id, parameter_sha256),
            )
            if cursor.rowcount != 1:
                raise AgendaError("计划确认发生并发冲突，请重新查看")
            conn.execute(
                "UPDATE agenda_tasks SET status='scheduled' WHERE plan_id=? AND status='draft'",
                (plan.plan_id,),
            )
            self._append_event(
                conn,
                plan_id=plan.plan_id,
                actor_principal_id=actor_principal_id,
                event_type="plan_confirmed",
                reason=None,
                detail={"version": current.version, "parameter_sha256": parameter_sha256},
                now_ms=now,
            )
        return self.get(
            plan.plan_id,
            principal_id=principal_id,
            delivery_target=delivery_target,
        )

    def supersede(
        self,
        short_id: str,
        *,
        principal_id: str,
        actor_principal_id: str,
        replacement_plan_id: str,
        delivery_target: DeliveryTarget | None = None,
    ) -> DailyPlan:
        plan = self.get(short_id, principal_id=principal_id, delivery_target=delivery_target)
        replacement = self.get(
            replacement_plan_id,
            principal_id=principal_id,
            delivery_target=delivery_target,
        )
        if plan.status == "superseded" and replacement.parent_plan_id == plan.plan_id:
            return plan
        if plan.status not in {
            "draft",
            "awaiting_map_consent",
            "awaiting_confirmation",
            "active",
        }:
            raise AgendaError("当前计划不能被新草案替换")
        if replacement.parent_plan_id != plan.plan_id:
            raise AgendaError("替换草案与原计划没有版本关系")
        now = int(time.time() * 1000)
        with self._connect() as conn:
            conn.execute(
                "UPDATE daily_plans SET status='superseded', updated_at_ms=? WHERE plan_id=?",
                (now, plan.plan_id),
            )
            self._append_event(
                conn,
                plan_id=plan.plan_id,
                actor_principal_id=actor_principal_id,
                event_type="plan_superseded",
                reason=None,
                detail={"replacement_plan_id": replacement.plan_id},
                now_ms=now,
            )
        return self.get(
            plan.plan_id,
            principal_id=principal_id,
            delivery_target=delivery_target,
        )

    def transition_task(
        self,
        short_id: str,
        *,
        principal_id: str,
        actor_principal_id: str,
        target: str,
        delivery_target: DeliveryTarget | None = None,
        now_ms: int | None = None,
    ) -> AgendaTask:
        if target not in {"completed", "skipped", "cancelled"}:
            raise AgendaError("任务目标状态无效")
        clean = short_id.strip().lower()
        if len(clean) < 6:
            raise AgendaError("任务 ID 至少需要 6 位")
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT t.* FROM agenda_tasks t
                JOIN daily_plans p ON p.plan_id=t.plan_id
                WHERE t.task_id LIKE ? AND p.principal_id=? LIMIT 2
                """,
                (f"{clean}%", principal_id),
            ).fetchall()
            if len(rows) != 1:
                raise AgendaError("未找到唯一任务")
            row = rows[0]
            if delivery_target is not None:
                plan_row = conn.execute(
                    "SELECT * FROM daily_plans WHERE plan_id=?", (str(row["plan_id"]),)
                ).fetchone()
                if plan_row is None:
                    raise AgendaError("未找到计划")
                self._assert_target(self._plan(plan_row), delivery_target)
            if str(row["status"]) == target:
                return self._task(row)
            if str(row["status"]) not in {"scheduled", "in_progress"}:
                raise AgendaError("当前任务状态不允许该操作")
            conn.execute(
                "UPDATE agenda_tasks SET status=? WHERE task_id=?",
                (target, str(row["task_id"])),
            )
            remaining = conn.execute(
                """
                SELECT COUNT(*) FROM agenda_tasks
                WHERE plan_id=? AND status IN ('draft','scheduled','in_progress')
                """,
                (str(row["plan_id"]),),
            ).fetchone()
            if remaining is not None and int(remaining[0]) == 0:
                conn.execute(
                    "UPDATE daily_plans SET status='completed', updated_at_ms=? WHERE plan_id=?",
                    (now, str(row["plan_id"])),
                )
            self._append_event(
                conn,
                plan_id=str(row["plan_id"]),
                actor_principal_id=actor_principal_id,
                event_type=f"task_{target}",
                reason=None,
                detail={"task_id": str(row["task_id"])},
                now_ms=now,
            )
            updated = conn.execute(
                "SELECT * FROM agenda_tasks WHERE task_id=?", (str(row["task_id"]),)
            ).fetchone()
        if updated is None:
            raise AgendaError("任务更新失败")
        return self._task(updated)

    def cancel_plan(
        self,
        short_id: str,
        *,
        principal_id: str | None,
        actor_principal_id: str,
        reason: str | None = None,
        delivery_target: DeliveryTarget | None = None,
    ) -> DailyPlan:
        plan = self.get(short_id, principal_id=principal_id, delivery_target=delivery_target)
        if plan.status == "cancelled":
            return plan
        if plan.status not in {
            "draft",
            "awaiting_map_consent",
            "awaiting_confirmation",
            "active",
        }:
            raise AgendaError("当前计划不能取消")
        if principal_id is None and not reason:
            raise AgendaError("主人跨用户操作必须填写原因")
        now = int(time.time() * 1000)
        with self._connect() as conn:
            conn.execute(
                "UPDATE daily_plans SET status='cancelled', updated_at_ms=? WHERE plan_id=?",
                (now, plan.plan_id),
            )
            conn.execute(
                """
                UPDATE agenda_tasks SET status='cancelled'
                WHERE plan_id=? AND status NOT IN ('completed','skipped')
                """,
                (plan.plan_id,),
            )
            self._append_event(
                conn,
                plan_id=plan.plan_id,
                actor_principal_id=actor_principal_id,
                event_type="plan_cancelled",
                reason=reason,
                detail={"admin": principal_id is None},
                now_ms=now,
            )
        return self.get(
            plan.plan_id,
            principal_id=None if principal_id is None else principal_id,
            delivery_target=delivery_target,
        )

    def link_reminder(
        self,
        *,
        plan_id: str,
        task_id: str | None,
        reminder_job_id: str,
        plan_version: int,
        kind: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO agenda_reminder_links(
                    plan_id, task_id, reminder_job_id, plan_version, kind
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (plan_id, task_id, reminder_job_id, plan_version, kind),
            )

    def audit(self, short_id: str, *, principal_id: str | None) -> list[dict[str, Any]]:
        plan_id = self._resolve(short_id, principal_id=principal_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT actor_principal_id,event_type,reason,detail_sha256,created_at_ms
                FROM agenda_events WHERE plan_id=? ORDER BY event_id DESC LIMIT 50
                """,
                (plan_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def anonymized_source(principal_id: str) -> str:
        return hashlib.sha256(principal_id.encode()).hexdigest()[:8]
