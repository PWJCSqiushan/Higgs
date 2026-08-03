import json
import sqlite3
from pathlib import Path

from r_agent.backup import BackupManager


def test_consistent_backup_excludes_secrets_and_prunes(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "memory.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE facts(value TEXT NOT NULL)")
        conn.execute("INSERT INTO facts(value) VALUES ('verified')")

    manager = BackupManager(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        interval_minutes=15,
        retention=3,
        config_snapshot=lambda: {"groups": ["700001"], "enabled": True},
    )
    for index in range(4):
        manager.create(f"test-{index}")

    status = manager.status()
    assert status["count"] == 3
    trashed = list((manager.backup_dir / ".trash").iterdir())
    assert len(trashed) == 1
    assert trashed[0].name.endswith("backup-" + trashed[0].name.split("backup-", 1)[1])
    latest = manager.backup_dir / str(status["latest"])
    manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["secrets_included"] is False
    assert manifest["safe_runtime_config"]["groups"] == ["700001"]
    assert "api_key" not in json.dumps(manifest).casefold()
    with sqlite3.connect(latest / "memory.sqlite") as conn:
        assert conn.execute("SELECT value FROM facts").fetchone()[0] == "verified"
