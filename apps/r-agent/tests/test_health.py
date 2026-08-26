import json
import os
import time
from pathlib import Path

import pytest

from r_agent.health import HealthReporter, NapCatHealthReader, check_health


def test_health_requires_fresh_connected_heartbeat(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    reporter = HealthReporter(path, interval_seconds=5)

    reporter.set_connected(False)
    assert check_health(path) == (False, "onebot_disconnected")

    reporter.set_container_alive(True)
    reporter.set_connected(True)
    assert check_health(path) == (True, "ok")

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["updated_at_unix"] = time.time() - 120
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert check_health(path, max_age_seconds=90) == (False, "heartbeat_stale")


def test_shared_napcat_marker_is_fresh_regular_and_content_checked(tmp_path: Path) -> None:
    health_path = tmp_path / "health.json"
    marker_path = tmp_path / "napcat" / "heartbeat"
    reporter = HealthReporter(
        health_path,
        interval_seconds=5,
        napcat_health_path=marker_path,
        napcat_health_max_age_seconds=60,
    )

    reporter.set_connected(True)
    assert check_health(health_path) == (False, "napcat_container_not_alive")
    assert json.loads(health_path.read_text(encoding="utf-8"))["napcat_health_reason"] == (
        "missing"
    )

    marker_path.parent.mkdir()
    marker_path.write_text("ok", encoding="ascii")
    reporter.write()
    assert check_health(health_path) == (True, "ok")

    marker_path.write_text("not-ok", encoding="ascii")
    reporter.write()
    assert check_health(health_path) == (False, "napcat_container_not_alive")

    directory_marker = tmp_path / "directory-marker"
    directory_marker.mkdir()
    directory_reporter = HealthReporter(
        tmp_path / "directory-health.json",
        interval_seconds=5,
        napcat_health_path=directory_marker,
        napcat_health_max_age_seconds=60,
    )
    directory_reporter.set_connected(True)
    assert check_health(tmp_path / "directory-health.json") == (
        False,
        "napcat_container_not_alive",
    )


def test_shared_napcat_marker_stale_or_symlink_fails_closed(tmp_path: Path) -> None:
    health_path = tmp_path / "health.json"
    marker_path = tmp_path / "heartbeat"
    marker_path.write_text("ok", encoding="ascii")
    reporter = HealthReporter(
        health_path,
        interval_seconds=5,
        napcat_health_path=marker_path,
        napcat_health_max_age_seconds=60,
    )
    reporter.set_connected(True)

    old = time.time() - 120
    os.utime(marker_path, (old, old))
    reporter.write()
    assert check_health(health_path) == (False, "napcat_container_not_alive")

    target = tmp_path / "target"
    target.write_text("ok", encoding="ascii")
    symlink = tmp_path / "symlink"
    try:
        symlink.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    symlink_reporter = HealthReporter(
        tmp_path / "symlink-health.json",
        interval_seconds=5,
        napcat_health_path=symlink,
        napcat_health_max_age_seconds=60,
    )
    symlink_reporter.set_connected(True)
    assert check_health(tmp_path / "symlink-health.json") == (
        False,
        "napcat_container_not_alive",
    )


def test_napcat_marker_freshness_cannot_exceed_sixty_seconds(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 5 and 60"):
        NapCatHealthReader(tmp_path / "heartbeat", max_age_seconds=61)


def test_health_invalid_file_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    path.write_text("not-json", encoding="utf-8")
    assert check_health(path) == (False, "health_file_invalid")
