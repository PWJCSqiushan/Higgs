import json
import time
from pathlib import Path

from r_agent.health import HealthReporter, check_health


def test_health_requires_fresh_connected_heartbeat(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    reporter = HealthReporter(path, interval_seconds=5)

    reporter.set_connected(False)
    assert check_health(path) == (False, "onebot_disconnected")

    reporter.set_connected(True)
    assert check_health(path) == (True, "ok")

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["updated_at_unix"] = time.time() - 120
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert check_health(path, max_age_seconds=90) == (False, "heartbeat_stale")


def test_health_invalid_file_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    path.write_text("not-json", encoding="utf-8")
    assert check_health(path) == (False, "health_file_invalid")
