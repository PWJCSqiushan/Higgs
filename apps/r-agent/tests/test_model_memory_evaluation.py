from __future__ import annotations

from pathlib import Path

import pytest

from r_agent.model_memory_eval_cli import main
from r_agent.model_memory_evaluation import MINIMUM_MODEL_RECALL, MemoryEvalMetrics


def test_real_model_eval_fails_closed_without_credentials(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.delenv("R_AGENT_MODEL_API_KEY", raising=False)
    result = main(["--env-file", str(tmp_path / "missing.env")])
    captured = capsys.readouterr()
    assert result == 2
    assert "no metrics emitted" in captured.err
    assert captured.out == ""
    assert "API_KEY" not in captured.err


def test_real_model_eval_cannot_lower_recall_gate() -> None:
    metrics = MemoryEvalMetrics(1, 1, 0, 1, 0, 1, 0, 0)
    with pytest.raises(ValueError, match=f"{MINIMUM_MODEL_RECALL:.2f}"):
        metrics.passes_thresholds(minimum_recall=0.80)
