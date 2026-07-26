from pathlib import Path

import pytest

from r_agent.safety import OutboundSafetyPolicy, SafetyDecision, SafetyError


def test_builtin_terms_are_blocked_after_obfuscation_normalization() -> None:
    policy = OutboundSafetyPolicy()
    assert policy.evaluate("这是普通的跑步建议").decision is SafetyDecision.ALLOW
    assert policy.evaluate("刷 单 返 利").decision is SafetyDecision.BLOCKED_TERM


def test_optional_terms_file_is_bounded(tmp_path: Path) -> None:
    path = tmp_path / "terms.txt"
    path.write_text("# comment\ncustom-risk\n", encoding="utf-8")
    policy = OutboundSafetyPolicy.with_optional_file(path)
    assert policy.evaluate("CUSTOM risk").decision is SafetyDecision.BLOCKED_TERM

    path.write_text("x" * 129, encoding="utf-8")
    with pytest.raises(SafetyError, match="128"):
        OutboundSafetyPolicy.with_optional_file(path)
