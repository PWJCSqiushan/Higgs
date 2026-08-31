import json
import sqlite3
from pathlib import Path

import pytest

from r_agent.memory import MemoryStore
from r_agent.persona_evolution import PHOTOGRAPHY_SEED_CONFIRMATION, SelfMemoryService
from r_agent.self_memory_seed_cli import SeedSafetyError, import_photography_seed, main


def _v4_database(path: Path) -> Path:
    MemoryStore(path).initialize(self_memory_v4=True)
    return path


def _seed_counts(path: Path) -> tuple[int, int]:
    with sqlite3.connect(path) as conn:
        items = conn.execute(
            "SELECT COUNT(*) FROM memory_items WHERE source_message_id='seed:photography-stance-v1'"
        ).fetchone()[0]
        evolution = conn.execute(
            "SELECT COUNT(*) FROM self_memory_evolution_observations "
            "WHERE idempotency_key='seed:photography-stance-v1'"
        ).fetchone()[0]
    return int(items), int(evolution)


def test_preview_never_touches_database_or_creates_backup(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "does-not-exist.sqlite"

    assert main(["--db", str(missing)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry_run"
    assert payload["written"] is False
    assert not missing.exists()
    assert list(tmp_path.iterdir()) == []


def test_wrong_confirmation_refuses_before_touching_database(tmp_path: Path, capsys) -> None:
    path = tmp_path / "memory.sqlite"

    assert main(["--db", str(path), "--confirm", "--confirmation", "wrong"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "mode": "refused",
        "reason": "confirmation_mismatch",
        "written": False,
    }
    assert not path.exists()


def test_missing_verified_backup_refuses_without_database_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _v4_database(tmp_path / "memory.sqlite")

    def fail_backup(*args, **kwargs):
        raise SeedSafetyError("consistent_backup_failed")

    monkeypatch.setattr("r_agent.self_memory_seed_cli._create_consistent_backup", fail_backup)
    with pytest.raises(SeedSafetyError, match="consistent_backup_failed"):
        import_photography_seed(path, confirmation=PHOTOGRAPHY_SEED_CONFIRMATION, now_ms=100)

    assert _seed_counts(path) == (0, 0)
    assert not list(tmp_path.glob("*.photography-seed-*.sqlite"))


def test_confirmed_import_creates_same_directory_consistent_backup(tmp_path: Path) -> None:
    path = _v4_database(tmp_path / "memory.sqlite")

    receipt = import_photography_seed(
        path,
        confirmation=PHOTOGRAPHY_SEED_CONFIRMATION,
        now_ms=1_700_000_000_000,
    )

    backups = list(tmp_path.glob(".*.photography-seed-*.sqlite"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert conn.execute(
            "SELECT COUNT(*) FROM self_memory_evolution_observations"
        ).fetchone() == (0,)
    assert _seed_counts(path) == (1, 1)
    assert receipt["mode"] == "confirmed"
    assert receipt["written"] is True
    assert receipt["recoverable"] is True
    assert len(str(receipt["backup_sha256"])) == 64
    encoded = json.dumps(receipt, ensure_ascii=False)
    assert str(path) not in encoded
    assert str(backups[0]) not in encoded
    assert "都不重要" not in encoded


def test_seed_import_is_idempotent_but_each_confirmed_run_is_backed_up(tmp_path: Path) -> None:
    path = _v4_database(tmp_path / "memory.sqlite")
    first = import_photography_seed(
        path,
        confirmation=PHOTOGRAPHY_SEED_CONFIRMATION,
        now_ms=100,
    )
    second = import_photography_seed(
        path,
        confirmation=PHOTOGRAPHY_SEED_CONFIRMATION,
        now_ms=200,
    )

    assert first["written"] is True
    assert second["written"] is False
    assert second["idempotent_replay"] is True
    assert _seed_counts(path) == (1, 1)
    assert len(list(tmp_path.glob(".*.photography-seed-*.sqlite"))) == 2


def test_import_failure_keeps_verified_backup_for_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _v4_database(tmp_path / "memory.sqlite")

    def fail_import(*args, **kwargs):
        raise RuntimeError("simulated seed failure with private content")

    monkeypatch.setattr(SelfMemoryService, "seed_photography_stance", fail_import)
    with pytest.raises(SeedSafetyError) as captured:
        import_photography_seed(
            path,
            confirmation=PHOTOGRAPHY_SEED_CONFIRMATION,
            now_ms=300,
        )

    assert captured.value.reason == "seed_import_failed"
    assert captured.value.receipt is not None
    assert captured.value.receipt["recoverable"] is True
    assert "private content" not in json.dumps(captured.value.receipt)
    assert len(list(tmp_path.glob(".*.photography-seed-*.sqlite"))) == 1
    assert _seed_counts(path) == (0, 0)


def test_confirmed_import_requires_preapproved_v4_schema(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite"
    MemoryStore(path).initialize()

    with pytest.raises(SeedSafetyError, match="self_memory_schema_v4_required"):
        import_photography_seed(path, confirmation=PHOTOGRAPHY_SEED_CONFIRMATION)

    assert _seed_counts_without_v4(path) == 0
    assert not list(tmp_path.glob(".*.photography-seed-*.sqlite"))


def test_confirmed_import_rejects_database_symlink(tmp_path: Path) -> None:
    target = _v4_database(tmp_path / "real-memory.sqlite")
    link = tmp_path / "memory.sqlite"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this test host")

    with pytest.raises(SeedSafetyError, match="database_must_be_regular_file"):
        import_photography_seed(link, confirmation=PHOTOGRAPHY_SEED_CONFIRMATION)

    assert _seed_counts(target) == (0, 0)
    assert not list(tmp_path.glob(".*.photography-seed-*.sqlite"))


def _seed_counts_without_v4(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM memory_items "
                "WHERE source_message_id='seed:photography-stance-v1'"
            ).fetchone()[0]
        )
