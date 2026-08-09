# ruff: noqa: RUF001
"""Deterministic daily-plan parsing and bounded feasible scheduling."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


class PlannerError(RuntimeError):
    """The requested plan is invalid or has no feasible schedule."""


@dataclass(frozen=True, slots=True)
class PlanTask:
    client_id: str
    title: str
    duration_minutes: int
    duration_source: str = "estimated"
    location_text: str | None = None
    earliest_start_ms: int | None = None
    latest_finish_ms: int | None = None
    fixed_start_ms: int | None = None
    deadline_ms: int | None = None
    priority: int = 3
    dependencies: tuple[str, ...] = ()
    transport_mode: str | None = None
    hard_constraints: tuple[str, ...] = ()
    soft_preferences: tuple[str, ...] = ()
    start_at_ms: int | None = None
    end_at_ms: int | None = None

    def as_document(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "title": self.title,
            "duration_minutes": self.duration_minutes,
            "duration_source": self.duration_source,
            "location_text": self.location_text,
            "earliest_start_ms": self.earliest_start_ms,
            "latest_finish_ms": self.latest_finish_ms,
            "fixed_start_ms": self.fixed_start_ms,
            "deadline_ms": self.deadline_ms,
            "priority": self.priority,
            "dependencies": list(self.dependencies),
            "transport_mode": self.transport_mode,
            "hard_constraints": list(self.hard_constraints),
            "soft_preferences": list(self.soft_preferences),
            "start_at_ms": self.start_at_ms,
            "end_at_ms": self.end_at_ms,
        }


@dataclass(frozen=True, slots=True)
class PlanResult:
    tasks: tuple[PlanTask, ...]
    globally_optimized: bool
    route_verified: bool
    explanations: tuple[str, ...]


def _at(day: date, hour: int, minute: int) -> int:
    if hour > 23 or minute > 59:
        raise PlannerError("时间格式无效")
    return int(datetime.combine(day, time(hour, minute), SHANGHAI).timestamp() * 1000)


def _estimate_duration(title: str) -> int:
    estimates = (
        (("买菜", "菜市场"), 35),
        (("买水", "桶装水", "桶水", "一桶水"), 20),
        (("取快递", "拿快递", "快递"), 20),
        (("跑步", "训练"), 45),
        (("吃饭", "午饭", "晚饭"), 40),
        (("背单词",), 30),
        (("学习", "编程", "写代码"), 90),
    )
    for keywords, minutes in estimates:
        if any(keyword in title for keyword in keywords):
            return minutes
    return 30


def _soft_preferences(title: str) -> tuple[str, ...]:
    values: list[str] = []
    if any(word in title for word in ("买水", "桶装水", "桶水", "一桶水")):
        values.append("heavy_item_late")
    if any(word in title for word in ("买菜", "菜市场", "生鲜")):
        values.append("perishable_late")
    return tuple(values)


def _location_hint(title: str) -> str | None:
    if "快递" in title:
        return "快递站（待确认具体地点）"
    if any(word in title for word in ("买菜", "菜市场")):
        return "菜市场（待确认具体地点）"
    if any(word in title for word in ("买水", "桶装水", "桶水", "一桶水")):
        return "购水地点（待确认具体地点）"
    return None


def parse_simple_plan(text: str, *, now: datetime | None = None) -> tuple[date, list[PlanTask]]:
    """Parse common Chinese multi-task requests without trusting model output."""
    current = now.astimezone(SHANGHAI) if now else datetime.now(SHANGHAI)
    clean = " ".join(text.strip().split())
    clean = re.sub(r"(?i)(?:higgs|希格斯|gigas)[，,：:\s]*", "", clean)
    plan_day = current.date() + timedelta(days=1) if "明天" in clean else current.date()
    clean = re.sub(r"^(?:请|帮我|麻烦)?(?:安排|规划)?(?:一下)?(?:今天|明天)?(?:的)?", "", clean)
    clean = re.sub(r"(?:帮我)?(?:安排|规划)(?:一下)?$", "", clean)
    clauses = [part.strip(" ，,。；;") for part in re.split(r"[、，,；;]", clean)]
    clauses = [part for part in clauses if part]

    deadline_mentions: list[tuple[int, int, str]] = []
    task_texts: list[str] = []
    for clause in clauses:
        match = re.search(r"(?P<h>\d{1,2})[:：](?P<m>\d{2})(?P<before>前|之前)?", clause)
        if match:
            stamp = _at(plan_day, int(match.group("h")), int(match.group("m")))
            stripped = re.sub(r"\d{1,2}[:：]\d{2}(?:前|之前)?", "", clause).strip()
            stripped = re.sub(r"^(?:要|需要|必须)", "", stripped).strip()
            if stripped:
                deadline_mentions.append((stamp, 1 if match.group("before") else 0, stripped))
                if len(clauses) == 1:
                    task_texts.append(stripped)
            continue
        task_texts.append(clause)

    normalized: list[str] = []
    for item in task_texts:
        item = re.sub(r"^(?:待办|任务)\s*[:：]?\s*", "", item).strip()
        item = re.sub(r"^(?:我)?(?:今天|明天)?(?:有|要|需要|得|去)", "", item).strip()
        item = re.sub(r"(?:这几件事|这些事|这些待办)$", "", item).strip()
        if item and not re.fullmatch(r"(?:一|二|三|四|五)是?", item):
            normalized.append(item)
    if len(normalized) < 2 and not any(word in clean for word in ("待办", "计划", "安排", "规划")):
        raise PlannerError("没有识别到多项今日待办")
    if not normalized:
        raise PlannerError("没有识别到可安排的待办")
    if len(normalized) > 20:
        raise PlannerError("每份计划最多 20 项任务")

    tasks: list[PlanTask] = []
    for index, title in enumerate(normalized, start=1):
        deadline_ms = None
        fixed_start_ms = None
        hard: list[str] = []
        for stamp, is_deadline, mention in deadline_mentions:
            keywords = [word for word in re.split(r"[的要到完成取买]", mention) if len(word) >= 2]
            if mention in title or title in mention or any(word in title for word in keywords):
                if is_deadline:
                    deadline_ms = stamp
                    hard.append("deadline")
                else:
                    fixed_start_ms = stamp
                    hard.append("fixed_start")
                break
        tasks.append(
            PlanTask(
                client_id=str(index),
                title=title,
                duration_minutes=_estimate_duration(title),
                duration_source="estimated",
                location_text=_location_hint(title),
                fixed_start_ms=fixed_start_ms,
                deadline_ms=deadline_ms,
                priority=3,
                hard_constraints=tuple(hard),
                soft_preferences=_soft_preferences(title),
            )
        )
    if deadline_mentions and not any(task.deadline_ms or task.fixed_start_ms for task in tasks):
        stamp, is_deadline, _ = deadline_mentions[0]
        first = tasks[0]
        tasks[0] = replace(
            first,
            deadline_ms=stamp if is_deadline else None,
            fixed_start_ms=None if is_deadline else stamp,
            hard_constraints=("deadline",) if is_deadline else ("fixed_start",),
        )
    return plan_day, tasks


def validate_model_tasks(raw: Any, *, plan_day: date) -> list[PlanTask]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 20:
        raise PlannerError("模型任务数量无效")
    allowed = {
        "client_id",
        "title",
        "duration_minutes",
        "duration_source",
        "location_text",
        "earliest_start",
        "latest_finish",
        "fixed_start",
        "deadline",
        "priority",
        "dependencies",
        "transport_mode",
        "hard_constraints",
        "soft_preferences",
    }
    tasks: list[PlanTask] = []
    ids: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or any(key not in allowed for key in item):
            raise PlannerError("模型返回了未知任务字段")
        client_id = str(item.get("client_id", index)).strip()
        title = " ".join(str(item.get("title", "")).split())
        duration = item.get("duration_minutes")
        priority = item.get("priority", 3)
        if not client_id or client_id in ids or not 1 <= len(title) <= 120:
            raise PlannerError("模型任务标识或标题无效")
        if isinstance(duration, bool) or not isinstance(duration, int) or not 5 <= duration <= 480:
            raise PlannerError("模型任务时长无效")
        if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 5:
            raise PlannerError("模型任务优先级无效")
        ids.add(client_id)

        def parse_clock(name: str, source: dict[str, Any] = item) -> int | None:
            value = source.get(name)
            if value in {None, ""}:
                return None
            if not isinstance(value, str) or not re.fullmatch(r"\d{1,2}:\d{2}", value):
                raise PlannerError(f"模型任务 {name} 无效")
            hour, minute = (int(part) for part in value.split(":"))
            return _at(plan_day, hour, minute)

        dependencies = item.get("dependencies", [])
        if not isinstance(dependencies, list) or any(
            not isinstance(dep, str) for dep in dependencies
        ):
            raise PlannerError("模型任务依赖无效")
        tasks.append(
            PlanTask(
                client_id=client_id,
                title=title,
                duration_minutes=duration,
                duration_source=str(item.get("duration_source", "estimated")),
                location_text=(
                    str(item["location_text"]).strip() if item.get("location_text") else None
                ),
                earliest_start_ms=parse_clock("earliest_start"),
                latest_finish_ms=parse_clock("latest_finish"),
                fixed_start_ms=parse_clock("fixed_start"),
                deadline_ms=parse_clock("deadline"),
                priority=priority,
                dependencies=tuple(dependencies),
                transport_mode=(
                    str(item["transport_mode"]).strip() if item.get("transport_mode") else None
                ),
                hard_constraints=tuple(str(x) for x in item.get("hard_constraints", [])),
                soft_preferences=tuple(str(x) for x in item.get("soft_preferences", [])),
            )
        )
    if any(dep not in ids for task in tasks for dep in task.dependencies):
        raise PlannerError("模型任务引用了不存在的依赖")
    return tasks


def solve_plan(
    tasks: list[PlanTask],
    *,
    plan_day: date,
    start_at: datetime | None = None,
    travel_minutes: dict[tuple[str, str], int] | None = None,
    route_verified: bool = False,
) -> PlanResult:
    """Build a feasible schedule; hard constraints are never relaxed."""
    if not 1 <= len(tasks) <= 20:
        raise PlannerError("计划任务数量必须在 1 到 20 之间")
    identifiers = {task.client_id for task in tasks}
    if len(identifiers) != len(tasks):
        raise PlannerError("任务标识重复")
    if any(dep not in identifiers for task in tasks for dep in task.dependencies):
        raise PlannerError("任务依赖不存在")

    order: list[PlanTask] = []
    pending = list(tasks)
    completed_ids: set[str] = set()
    while pending:
        available = [task for task in pending if set(task.dependencies).issubset(completed_ids)]
        if not available:
            raise PlannerError("任务依赖形成了循环")

        def key(task: PlanTask) -> tuple[int, int, int, int, str]:
            anchor = task.fixed_start_ms or task.deadline_ms or 2**63 - 1
            heavy = 1 if "heavy_item_late" in task.soft_preferences else 0
            perishable = 1 if "perishable_late" in task.soft_preferences else 0
            return (
                anchor,
                heavy + perishable,
                -task.priority,
                task.duration_minutes,
                task.client_id,
            )

        chosen = min(available, key=key)
        order.append(chosen)
        completed_ids.add(chosen.client_id)
        pending.remove(chosen)

    if len(order) > 1:
        normal = [
            task
            for task in order
            if not ({"heavy_item_late", "perishable_late"} & set(task.soft_preferences))
            or task.fixed_start_ms
            or task.deadline_ms
        ]
        soft = [task for task in order if task not in normal]
        soft.sort(key=lambda item: "heavy_item_late" in item.soft_preferences)
        order = normal + soft

    current_dt = start_at.astimezone(SHANGHAI) if start_at else datetime.now(SHANGHAI)
    if current_dt.date() != plan_day:
        current_dt = datetime.combine(plan_day, time(9, 0), SHANGHAI)
    current_ms = int(current_dt.timestamp() * 1000)
    day_end_ms = _at(plan_day, 23, 59)
    scheduled: list[PlanTask] = []
    explanations: list[str] = []
    previous: PlanTask | None = None
    travel = travel_minutes or {}
    for task in order:
        travel_key = (previous.location_text or "", task.location_text or "") if previous else None
        if travel_key is not None:
            current_ms += max(0, travel.get(travel_key, 0)) * 60_000
        start_ms = max(current_ms, task.earliest_start_ms or current_ms)
        if task.fixed_start_ms is not None:
            if start_ms > task.fixed_start_ms:
                raise PlannerError(f"“{task.title}”的固定时间与其他任务冲突")
            start_ms = task.fixed_start_ms
        end_ms = start_ms + task.duration_minutes * 60_000
        if task.deadline_ms is not None and end_ms > task.deadline_ms:
            raise PlannerError(f"“{task.title}”无法在截止时间前完成")
        if task.latest_finish_ms is not None and end_ms > task.latest_finish_ms:
            raise PlannerError(f"“{task.title}”超出允许时间窗")
        if end_ms > day_end_ms:
            raise PlannerError("计划无法在当天完成")
        scheduled_task = replace(task, start_at_ms=start_ms, end_at_ms=end_ms)
        scheduled.append(scheduled_task)
        current_ms = end_ms
        previous = scheduled_task
        if task.duration_source == "estimated":
            explanations.append(f"“{task.title}”暂按 {task.duration_minutes} 分钟估计")
        if "heavy_item_late" in task.soft_preferences:
            explanations.append(f"“{task.title}”尽量靠后，减少携带重物的路程")
        if "perishable_late" in task.soft_preferences:
            explanations.append(f"“{task.title}”尽量靠后，减少生鲜等待时间")
    return PlanResult(
        tasks=tuple(scheduled),
        globally_optimized=False,
        route_verified=route_verified,
        explanations=tuple(dict.fromkeys(explanations)),
    )
