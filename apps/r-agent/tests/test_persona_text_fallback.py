import pytest

from r_agent.persona_bundle import PersonaV2Gate
from r_agent.phase2_cli import _DEFAULT_PERSONA, _persona_text


def test_explicitly_empty_legacy_persona_env_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R_AGENT_PERSONA_FILE", "")
    monkeypatch.setenv("R_AGENT_PERSONA", "")
    assert _persona_text() == _DEFAULT_PERSONA
    monkeypatch.setenv("R_AGENT_PERSONA", "   ")
    assert _persona_text() == _DEFAULT_PERSONA


def test_unset_and_inline_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("R_AGENT_PERSONA_FILE", raising=False)
    monkeypatch.delenv("R_AGENT_PERSONA", raising=False)
    assert _persona_text() == _DEFAULT_PERSONA
    monkeypatch.setenv("R_AGENT_PERSONA", "自定义人格")
    assert _persona_text() == "自定义人格"


def test_v2_gate_still_surface_scoped_with_empty_legacy_env() -> None:
    env = {"R_AGENT_PERSONA_V2_ENABLED": "true", "R_AGENT_PERSONA": "", "R_AGENT_PERSONA_FILE": ""}
    gate = PersonaV2Gate.from_env(env)
    assert gate.enabled and gate.napcat_enabled
    common = {"conversation_kind": "group", "sender_id": "1", "owner_id": None}
    assert gate.allows(channel="qq", principal_role="user", **common)
    assert not gate.allows(channel="qq_official", principal_role="user", **common)
    off = PersonaV2Gate.from_env({**env, "R_AGENT_PERSONA_V2_NAPCAT_ENABLED": "false"})
    assert not off.allows(channel="qq", principal_role="user", **common)
