import json
import time
from pathlib import Path

import pytest

from r_agent.identity import Principal
from r_agent.server_status import (
    SERVER_STATUS_FIELDS,
    ServerStatus,
    ServerStatusCommand,
    ServerStatusError,
    ServerStatusReader,
    format_server_status,
    register_server_status_tool,
)
from r_agent.tool_governance import ToolGovernance, ToolRequest, ToolRequestSource


def payload(*, generated_at_unix: float | None = None) -> dict:
    return {
        "schema": 1,
        "generated_at_unix": time.time() if generated_at_unix is None else generated_at_unix,
        "uptime_seconds": 3600.0,
        "load_1m": 0.25,
        "memory_total_bytes": 8 * 1024**3,
        "memory_available_bytes": 4 * 1024**3,
        "disk_total_bytes": 100 * 1024**3,
        "disk_free_bytes": 60 * 1024**3,
        "disk_used_percent": 40.0,
    }


def write_snapshot(root: Path, value: dict | str) -> Path:
    root.mkdir()
    path = root / "status.json"
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_reader_accepts_only_allowlisted_json_and_formats_safe_fields(tmp_path: Path) -> None:
    path = write_snapshot(tmp_path / "status", payload())
    reader = ServerStatusReader(path, allowed_root=path.parent)
    status = reader.read()
    assert isinstance(status, ServerStatus)
    assert set(status.as_payload()) == SERVER_STATUS_FIELDS
    assert "服务器状态" in format_server_status(status)


def test_reader_rejects_path_traversal_and_non_allowlisted_default(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ServerStatusError):
        ServerStatusReader(allowed / ".." / "outside" / "status.json", allowed_root=allowed)
    with pytest.raises(ServerStatusError):
        ServerStatusReader(tmp_path / "status.json")


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update({"unexpected": "ignore me"}),
        lambda value: value.update({"disk_used_percent": 101}),
        lambda value: value.update({"memory_available_bytes": 9 * 1024**3}),
        lambda value: value.update({"schema": 2}),
        lambda value: value.update({"load_1m": "1.0"}),
    ],
)
def test_reader_rejects_invalid_or_injection_shaped_snapshot(tmp_path: Path, mutator) -> None:
    value = payload()
    mutator(value)
    path = write_snapshot(tmp_path / "status", value)
    with pytest.raises(ServerStatusError):
        ServerStatusReader(path, allowed_root=path.parent).read()


def test_reader_rejects_stale_and_malformed_files(tmp_path: Path) -> None:
    root = tmp_path / "status"
    path = write_snapshot(root, payload(generated_at_unix=100.0))
    reader = ServerStatusReader(path, allowed_root=root, clock=lambda: 300.0, max_age_seconds=60)
    with pytest.raises(ServerStatusError, match="stale"):
        reader.read()
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ServerStatusError):
        reader.read()


def test_reader_rejects_symlink_without_following_it(tmp_path: Path) -> None:
    root = tmp_path / "status"
    root.mkdir()
    path = root / "status.json"
    target = root / "target.json"
    target.write_text(json.dumps(payload()), encoding="utf-8")
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this test filesystem")
    with pytest.raises(ServerStatusError):
        ServerStatusReader(path, allowed_root=root).read()


def test_server_status_command_is_owner_only_and_does_not_read_for_non_owner(
    tmp_path: Path,
) -> None:
    root = tmp_path / "status"
    path = write_snapshot(root, payload())
    governance = ToolGovernance(audit_path=tmp_path / "audit.sqlite")
    command = ServerStatusCommand(
        governance,
        ServerStatusReader(path, allowed_root=root),
    )
    assert "服务器状态" in command.handle(actor=Principal("owner", "owner"))
    user = command.handle(actor=Principal("user", "user"))
    assert "拒绝" in user


def test_model_shadow_request_cannot_execute_server_status(tmp_path: Path) -> None:
    root = tmp_path / "status"
    path = write_snapshot(root, payload())
    governance = ToolGovernance(audit_path=tmp_path / "audit.sqlite")
    reader = ServerStatusReader(path, allowed_root=root)
    register_server_status_tool(governance, reader)
    request = ToolRequest(
        tool_name="server_status",
        parameters={},
        actor_role="owner",
        actor_id="owner",
        source=ToolRequestSource.MODEL_SHADOW.value,
        surface="owner_command_private",
    )
    decision = governance.decide(request, approved=True, approved_by="owner")
    assert decision.reason == "model_shadow_only"
