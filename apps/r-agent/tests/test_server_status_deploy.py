import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
COLLECTOR_PATH = REPO / "deploy" / "existing-server" / "collect_server_status.py"


def load_collector():
    spec = importlib.util.spec_from_file_location("higgs_status_collector", COLLECTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collector_writes_atomic_allowlisted_snapshot(tmp_path: Path) -> None:
    collector = load_collector()
    output = tmp_path / "status.json"
    payload = collector.collect(output=output, disk_root=tmp_path)
    assert output.is_file()
    on_disk = json.loads(output.read_text(encoding="utf-8"))
    assert on_disk == payload
    assert set(payload) == {
        "schema",
        "generated_at_unix",
        "uptime_seconds",
        "load_1m",
        "memory_total_bytes",
        "memory_available_bytes",
        "disk_total_bytes",
        "disk_free_bytes",
        "disk_used_percent",
    }


def test_collector_rejects_non_status_output_name(tmp_path: Path) -> None:
    collector = load_collector()
    try:
        collector.collect(output=tmp_path / "host.json", disk_root=tmp_path)
    except ValueError as exc:
        assert "status.json" in str(exc)
    else:  # pragma: no cover - assertion makes intent clear
        raise AssertionError("collector accepted a non-allowlisted output name")


def test_compose_mount_is_read_only_and_has_no_docker_socket() -> None:
    compose = (REPO / "deploy" / "existing-server" / "compose.yml").read_text(encoding="utf-8")
    assert "/run/higgs-server-status:ro" in compose
    assert "R_AGENT_SERVER_STATUS_FILE: /run/higgs-server-status/status.json" in compose
    assert "docker.sock" not in compose


def test_systemd_timer_uses_fixed_service_and_minute_refresh() -> None:
    service = (REPO / "deploy" / "existing-server" / "higgs-server-status.service").read_text(
        encoding="utf-8"
    )
    timer = (REPO / "deploy" / "existing-server" / "higgs-server-status.timer").read_text(
        encoding="utf-8"
    )
    assert "collect_server_status.py" in service
    assert "ReadWritePaths=/srv/data/higgs/server-status" in service
    assert "OnUnitActiveSec=1min" in timer
    assert "Unit=higgs-server-status.service" in timer
    assert "subprocess" not in (COLLECTOR_PATH.read_text(encoding="utf-8")).casefold()
