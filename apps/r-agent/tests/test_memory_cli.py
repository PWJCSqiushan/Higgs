import json
import os
from pathlib import Path

import pytest

from r_agent.cli import main
from r_agent.memory import (
    MemoryKind,
    MemoryNotFoundError,
    MemoryScope,
    MemoryStore,
)


def configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    for key in tuple(os.environ):
        if key.startswith("R_AGENT_"):
            monkeypatch.delenv(key)
    data_dir = tmp_path / "data"
    monkeypatch.setenv("R_AGENT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("R_AGENT_OWNER_QQ", "12345678")
    return data_dir


def proposal(memory: MemoryStore):
    return memory.propose(
        scope=MemoryScope.PRINCIPAL,
        scope_id="alice",
        kind=MemoryKind.PREFERENCE,
        text="Alice prefers morning runs",
        source_channel="qq",
        source_account_id="900001",
        source_message_id="1",
        source_principal_id="alice",
        created_by="candidate-extractor-v1",
        confidence=0.8,
        now_ms=1_767_225_600_000,
    )


def test_cli_lists_and_shows_memory_with_source_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = configure(monkeypatch, tmp_path)
    memory = MemoryStore(data_dir / "memory.sqlite")
    memory.initialize()
    item = proposal(memory)

    assert main(["memory", "list", "--status", "candidate"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["count"] == 1
    assert listed["items"][0]["item_id"] == item.item_id

    assert main(["memory", "show", item.item_id]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["item"]["source_message_id"] == "1"
    assert [entry["action"] for entry in shown["audit"]] == ["proposed"]


def test_cli_requires_exact_confirmation_for_hard_delete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = configure(monkeypatch, tmp_path)
    memory = MemoryStore(data_dir / "memory.sqlite")
    memory.initialize()
    item = proposal(memory)

    assert (
        main(
            [
                "memory",
                "delete",
                item.item_id,
                "--reason",
                "privacy request",
                "--confirm",
                "wrong-id",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["error"] == "confirmation_error"
    assert memory.get(item.item_id).item_id == item.item_id

    assert (
        main(
            [
                "memory",
                "delete",
                item.item_id,
                "--reason",
                "privacy request",
                "--confirm",
                item.item_id,
            ]
        )
        == 0
    )
    capsys.readouterr()
    with pytest.raises(MemoryNotFoundError):
        memory.get(item.item_id)
