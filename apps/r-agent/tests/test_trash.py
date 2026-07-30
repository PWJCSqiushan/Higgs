from pathlib import Path

from r_agent.trash import move_to_trash


def test_move_to_trash_preserves_file_and_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "obsolete.txt"
    source.write_text("recoverable", encoding="utf-8")

    destination = move_to_trash(source)

    assert destination is not None
    assert not source.exists()
    assert destination.parent == tmp_path / ".trash"
    assert destination.read_text(encoding="utf-8") == "recoverable"
    assert move_to_trash(source) is None
