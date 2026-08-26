#!/usr/bin/env python3
"""Generate the allowlisted, non-secret host snapshot consumed by Higgs.

This script intentionally uses Python's standard library only.  It never runs
Docker, a shell, or a command supplied by a caller.  The systemd unit invokes
it with the fixed output path below; the function-level ``output`` argument is
kept for isolated tests and local dry runs.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = Path("/srv/data/higgs/server-status/status.json")
DEFAULT_DISK_ROOT = Path("/srv")
SCHEMA = 1


def _proc_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="strict")


def _uptime_seconds() -> float:
    try:
        value = float(_proc_text(Path("/proc/uptime")).split()[0])
    except (OSError, ValueError, IndexError):
        value = 0.0
    return max(0.0, value) if math.isfinite(value) else 0.0


def _load_1m() -> float | None:
    try:
        value = float(_proc_text(Path("/proc/loadavg")).split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _memory_bytes() -> tuple[int, int]:
    values: dict[str, int] = {}
    try:
        for line in _proc_text(Path("/proc/meminfo")).splitlines():
            key, separator, raw = line.partition(":")
            if not separator:
                continue
            parts = raw.strip().split()
            if not parts or not parts[0].isdigit():
                continue
            # Linux meminfo reports kB.  Keep only the two fields required by
            # the schema and avoid exposing the full proc file.
            values[key] = int(parts[0]) * 1024
    except (OSError, ValueError):
        return 0, 0
    total = max(0, values.get("MemTotal", 0))
    available = max(0, min(total, values.get("MemAvailable", values.get("MemFree", 0))))
    return total, available


def collect(*, output: Path = DEFAULT_OUTPUT, disk_root: Path = DEFAULT_DISK_ROOT) -> dict[str, Any]:
    """Collect and atomically write one bounded snapshot."""

    output = Path(output)
    disk_root = Path(disk_root)
    if output.name != "status.json":
        raise ValueError("output must end in status.json")
    total_memory, available_memory = _memory_bytes()
    disk = shutil.disk_usage(disk_root)
    disk_total = max(0, int(disk.total))
    disk_free = max(0, min(disk_total, int(disk.free)))
    disk_used = 0.0 if disk_total == 0 else (disk_total - disk_free) * 100 / disk_total
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_unix": time.time(),
        "uptime_seconds": _uptime_seconds(),
        "load_1m": _load_1m(),
        "memory_total_bytes": total_memory,
        "memory_available_bytes": available_memory,
        "disk_total_bytes": disk_total,
        "disk_free_bytes": disk_free,
        "disk_used_percent": round(min(100.0, max(0.0, disk_used)), 3),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    # A rename from the same directory prevents the reader from seeing a
    # partially written document.  In case of an error, leave the temporary
    # file for the next privileged maintenance pass instead of deleting it.
    descriptor, temporary_name = tempfile.mkstemp(prefix=".status-", suffix=".tmp", dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, output)
        os.chmod(output, 0o644)
    except Exception:
        # Do not unlink a material file.  The leftover is non-secret and can be
        # moved to the host trash directory by an operator if necessary.
        raise
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--disk-root", type=Path, default=DEFAULT_DISK_ROOT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.output.expanduser().resolve() != DEFAULT_OUTPUT:
        raise SystemExit("--output is fixed to /srv/data/higgs/server-status/status.json")
    if args.disk_root.expanduser().resolve() != DEFAULT_DISK_ROOT:
        raise SystemExit("--disk-root is fixed to /srv")
    collect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
