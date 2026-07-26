import json
import os
from pathlib import Path

import pytest

from r_agent.conversation import ConversationStore
from r_agent.events import ConversationKind, InboundEvent
from r_agent.review_cli import main


def configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, owner: bool) -> Path:
    monkeypatch.chdir(tmp_path)
    for key in tuple(os.environ):
        if key.startswith("R_AGENT_"):
            monkeypatch.delenv(key)
    data_dir = tmp_path / "data"
    monkeypatch.setenv("R_AGENT_DATA_DIR", str(data_dir))
    if owner:
        monkeypatch.setenv("R_AGENT_OWNER_QQ", "800001")
    return data_dir


def event() -> InboundEvent:
    return InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id="800001",
        message_id="1",
        occurred_at_ms=1_767_225_600_000,
        conversation_kind=ConversationKind.PRIVATE,
        conversation_id="qq:private:900001:800001",
        group_id=None,
        text="hello",
        mentioned=False,
    )


def test_review_requires_configured_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch, tmp_path, owner=False)
    assert main([]) == 3
    assert json.loads(capsys.readouterr().out)["error"] == "authorization_error"


def test_owner_can_review_draft_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = configure(monkeypatch, tmp_path, owner=True)
    history = ConversationStore(data_dir / "conversation.sqlite")
    history.initialize()
    history.record(
        event(),
        principal_id="owner-principal",
        outcome="drafted",
        assistant_text="draft reply",
    )

    assert main(["--outcome", "drafted", "--limit", "5"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["count"] == 1
    assert output["turns"][0]["user_text"] == "hello"
    assert output["turns"][0]["assistant_text"] == "draft reply"
