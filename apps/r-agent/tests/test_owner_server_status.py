import json
import time
from pathlib import Path

from r_agent.identity import Principal
from r_agent.memory import MemoryStore
from r_agent.owner_commands import OwnerCommandContext, OwnerCommandRouter
from r_agent.server_status import ServerStatusCommand, ServerStatusReader
from r_agent.tool_governance import ToolGovernance
from r_agent.vector_memory import MemoryVectorStore


def test_router_exposes_server_status_only_as_explicit_owner_command(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize()
    vectors = MemoryVectorStore(memory.path, memory=memory)
    root = tmp_path / "status"
    root.mkdir()
    (root / "status.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "generated_at_unix": time.time(),
                "uptime_seconds": 1,
                "load_1m": 0,
                "memory_total_bytes": 10,
                "memory_available_bytes": 5,
                "disk_total_bytes": 10,
                "disk_free_bytes": 5,
                "disk_used_percent": 50,
            }
        ),
        encoding="utf-8",
    )
    command = ServerStatusCommand(
        ToolGovernance(audit_path=tmp_path / "tool-audit.sqlite"),
        ServerStatusReader(root / "status.json", allowed_root=root),
    )
    router = OwnerCommandRouter(
        context=OwnerCommandContext("live", 0, 0, 0, True, False, True),
        vectors=vectors,
        server_status=command,
    )
    owner = Principal("owner-principal", "owner")
    assert "服务器状态" in (router.handle("/higgs server status", actor=owner) or "")
    assert "用法" in (router.handle("/higgs server now", actor=owner) or "")
