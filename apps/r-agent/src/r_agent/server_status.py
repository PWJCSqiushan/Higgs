"""Read-only, allowlisted host status tool.

The agent never receives a Docker socket, a shell, or a general filesystem
reader.  A host-side timer writes one small JSON document to the fixed
``/run/higgs-server-status/status.json`` path.  ``ServerStatusReader`` accepts
that exact path in production (and an explicitly supplied test root in tests),
checks the document's schema and age, and exposes only typed, bounded fields.
"""

from __future__ import annotations

import json
import math
import os
import stat
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from r_agent.identity import Principal
from r_agent.tool_governance import (
    ToolDecision,
    ToolGovernance,
    ToolReceipt,
    ToolReceiptState,
    ToolRequest,
    ToolRequestSource,
    ToolSpec,
)

DEFAULT_SERVER_STATUS_PATH = Path("/run/higgs-server-status/status.json")
SERVER_STATUS_SCHEMA = 1
SERVER_STATUS_FIELDS = frozenset(
    {
        "schema",
        "generated_at_unix",
        "uptime_seconds",
        "load_1m",
        "memory_total_bytes",
        "memory_available_bytes",
        "disk_total_bytes",
        "disk_free_bytes",
        "disk_used_percent",
    }
)


class ServerStatusError(ValueError):
    """The fixed status document is unavailable or fails validation."""


@dataclass(frozen=True, slots=True)
class ServerStatus:
    schema: int
    generated_at_unix: float
    uptime_seconds: float
    load_1m: float | None
    memory_total_bytes: int
    memory_available_bytes: int
    disk_total_bytes: int
    disk_free_bytes: int
    disk_used_percent: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ServerStatus:
        if not isinstance(payload, Mapping):
            raise ServerStatusError("status document must be an object")
        if set(payload) != SERVER_STATUS_FIELDS:
            raise ServerStatusError("status document fields are not allowlisted")
        schema = payload.get("schema")
        if isinstance(schema, bool) or schema != SERVER_STATUS_SCHEMA:
            raise ServerStatusError("status document schema is unsupported")

        def finite_number(name: str, *, minimum: float = 0.0) -> float:
            value = payload.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ServerStatusError(f"status field {name} is invalid")
            result = float(value)
            if not math.isfinite(result) or result < minimum:
                raise ServerStatusError(f"status field {name} is invalid")
            return result

        def nonnegative_int(name: str) -> int:
            value = payload.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ServerStatusError(f"status field {name} is invalid")
            return value

        generated = finite_number("generated_at_unix")
        uptime = finite_number("uptime_seconds")
        raw_load = payload.get("load_1m")
        if raw_load is not None:
            if isinstance(raw_load, bool) or not isinstance(raw_load, (int, float)):
                raise ServerStatusError("status field load_1m is invalid")
            load = float(raw_load)
            if not math.isfinite(load) or load < 0:
                raise ServerStatusError("status field load_1m is invalid")
        else:
            load = None
        disk_used = finite_number("disk_used_percent")
        if disk_used > 100:
            raise ServerStatusError("status field disk_used_percent is invalid")
        total = nonnegative_int("memory_total_bytes")
        available = nonnegative_int("memory_available_bytes")
        if available > total:
            raise ServerStatusError("memory available bytes exceed total bytes")
        disk_total = nonnegative_int("disk_total_bytes")
        disk_free = nonnegative_int("disk_free_bytes")
        if disk_free > disk_total:
            raise ServerStatusError("disk free bytes exceed total bytes")
        return cls(
            schema=schema,
            generated_at_unix=generated,
            uptime_seconds=uptime,
            load_1m=load,
            memory_total_bytes=total,
            memory_available_bytes=available,
            disk_total_bytes=disk_total,
            disk_free_bytes=disk_free,
            disk_used_percent=disk_used,
        )

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


class ServerStatusReader:
    """Read exactly one regular file under one explicitly allowlisted directory."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        allowed_root: Path | None = None,
        max_age_seconds: float = 180.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        raw_path = Path(path) if path is not None else DEFAULT_SERVER_STATUS_PATH
        root = Path(allowed_root) if allowed_root is not None else DEFAULT_SERVER_STATUS_PATH.parent
        if ".." in raw_path.parts or ".." in root.parts:
            raise ServerStatusError("server status path must not contain traversal components")
        # Keep lexical absolute paths for lstat/O_NOFOLLOW checks.  ``resolve``
        # here would follow an in-root symlink and make it invisible to the
        # later regular-file check.
        absolute_root = Path(os.path.abspath(root.expanduser()))
        absolute_path = Path(os.path.abspath(raw_path.expanduser()))
        if absolute_path.name != "status.json":
            raise ServerStatusError("server status path must end with status.json")
        fixed_default = Path(os.path.abspath(DEFAULT_SERVER_STATUS_PATH))
        if allowed_root is None and absolute_path != fixed_default:
            raise ServerStatusError("server status path is outside the fixed allowlist")
        if absolute_path.parent != absolute_root:
            raise ServerStatusError("server status path is outside the allowlisted directory")
        if isinstance(max_age_seconds, bool) or not 5 <= max_age_seconds <= 3_600:
            raise ServerStatusError("server status max age is invalid")
        self.path = absolute_path
        self.allowed_root = absolute_root
        self.max_age_seconds = float(max_age_seconds)
        self._clock = clock or time.time

    def _read_bytes(self) -> bytes:
        try:
            parent_stat = self.allowed_root.lstat()
            if stat.S_ISLNK(parent_stat.st_mode):
                raise ServerStatusError("server status directory must not be a symlink")
            file_stat = self.path.lstat()
            if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
                raise ServerStatusError("server status file must be a regular file")
            if file_stat.st_size > 64 * 1024:
                raise ServerStatusError("server status file is too large")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self.path, flags)
            try:
                return os.read(descriptor, 64 * 1024 + 1)
            finally:
                os.close(descriptor)
        except ServerStatusError:
            raise
        except (OSError, UnicodeError) as exc:
            raise ServerStatusError("server status file is unavailable") from exc

    def read(self) -> ServerStatus:
        try:
            raw = self._read_bytes()
            if len(raw) > 64 * 1024:
                raise ServerStatusError("server status file is too large")
            payload = json.loads(raw.decode("utf-8"))
        except ServerStatusError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ServerStatusError("server status file is not valid UTF-8 JSON") from exc
        status = ServerStatus.from_mapping(payload)
        age = self._clock() - status.generated_at_unix
        if age < -60:
            raise ServerStatusError("server status timestamp is in the future")
        if age > self.max_age_seconds:
            raise ServerStatusError("server status file is stale")
        return status


def server_status_spec() -> ToolSpec:
    """Return the only currently executable phase-3 tool descriptor."""

    return ToolSpec(
        name="server_status",
        description="Read a bounded host status snapshot generated by a system timer.",
        input_schema={"type": "object", "additionalProperties": False},
        caller_roles=frozenset({"owner"}),
        surfaces=frozenset({"owner_command_private"}),
        enabled=True,
        requires_explicit_approval=True,
        allow_model_execution=False,
        timeout_seconds=3.0,
        rate_limit_per_minute=6,
        persist_result=False,
    )


def register_server_status_tool(governance: ToolGovernance, reader: ServerStatusReader) -> None:
    """Register the bounded reader exactly once on a governance instance."""

    if governance.registry.has("server_status"):
        return

    def handler(parameters: Mapping[str, Any]) -> dict[str, Any]:
        if parameters:
            raise ServerStatusError("server_status does not accept parameters")
        return reader.read().as_payload()

    governance.register(server_status_spec(), handler)


def format_server_status(status: ServerStatus) -> str:
    """Format only allowlisted values for an owner command response."""

    generated = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(status.generated_at_unix))
    load = "不可用" if status.load_1m is None else f"{status.load_1m:.2f}"
    memory_used = max(0, status.memory_total_bytes - status.memory_available_bytes)
    return (
        "服务器状态(只读快照)\n"
        f"采集时间：{generated}\n"
        f"运行时间：{status.uptime_seconds / 3600:.1f}小时\n"
        f"1分钟负载：{load}\n"
        f"内存：{memory_used / 1024**3:.1f}/{status.memory_total_bytes / 1024**3:.1f}GiB\n"
        f"磁盘：已用{status.disk_used_percent:.1f}%"
    )


class ServerStatusCommand:
    """Owner-command facade that keeps authorization before file access."""

    def __init__(self, governance: ToolGovernance, reader: ServerStatusReader) -> None:
        self.governance = governance
        self.reader = reader
        register_server_status_tool(governance, reader)

    def handle(self, *, actor: Principal) -> str:
        request = ToolRequest(
            tool_name="server_status",
            parameters={},
            actor_role=actor.role,
            actor_id=actor.principal_id,
            source=ToolRequestSource.OWNER_COMMAND.value,
            surface="owner_command_private",
        )
        decision: ToolDecision = self.governance.decide(
            request,
            approved=actor.role == "owner",
            approved_by=actor.principal_id if actor.role == "owner" else None,
        )
        receipt: ToolReceipt = self.governance.execute_sync(request, decision=decision)
        if receipt.state is ToolReceiptState.SUCCEEDED:
            try:
                return format_server_status(ServerStatus.from_mapping(receipt.result))
            except ServerStatusError:
                return "服务器状态暂不可用：快照格式无效。"
        messages = {
            ToolReceiptState.DENIED: "服务器状态工具拒绝执行。",
            ToolReceiptState.RATE_LIMITED: "服务器状态查询过于频繁，请稍后再试。",
            ToolReceiptState.TIMED_OUT: "服务器状态查询超时。",
            ToolReceiptState.UNKNOWN: "服务器状态查询结果未知，未重试。",
            ToolReceiptState.DUPLICATE: "服务器状态查询已处理。",
            ToolReceiptState.FAILED: "服务器状态暂不可用。",
        }
        return messages.get(receipt.state, "服务器状态暂不可用。")
