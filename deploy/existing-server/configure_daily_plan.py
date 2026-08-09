#!/usr/bin/env python3
"""Atomically enable a Higgs daily-plan release without printing secrets."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

IMAGE_RE = re.compile(r"higgs-agent:[0-9a-f]{40}")


def update_env(path: Path, values: dict[str, str]) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    original_stat = path.stat()
    original = path.read_text(encoding="utf-8")
    remaining = dict(values)
    lines: list[str] = []
    for line in original.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            lines.append(f"{key}={remaining.pop(key)}")
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    payload = "\n".join(lines) + "\n"
    mode = original_stat.st_mode & 0o777
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.chmod(temporary, mode)
    chown = getattr(os, "chown", None)
    if chown is not None:
        chown(temporary, original_stat.st_uid, original_stat.st_gid)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--mode", choices=("off", "shadow", "live"), default="shadow")
    parser.add_argument(
        "--stack-env", type=Path, default=Path("/srv/secrets/higgs/stack.env")
    )
    parser.add_argument(
        "--higgs-env", type=Path, default=Path("/srv/secrets/higgs/higgs.env")
    )
    parser.add_argument("--trash", type=Path, default=Path("/srv/trash"))
    args = parser.parse_args()
    if IMAGE_RE.fullmatch(args.image) is None:
        raise ValueError("image must use an immutable 40-character commit tag")
    args.trash.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for source in (args.stack_env, args.higgs_env):
        destination = args.trash / f"{source.name}.before-daily-plan-{stamp}"
        shutil.copy2(source, destination)
        os.chmod(destination, 0o600)
    update_env(args.stack_env, {"HIGGS_IMAGE": args.image})
    update_env(
        args.higgs_env,
        {
            "R_AGENT_DAILY_PLAN_MODE": args.mode,
            "R_AGENT_DAILY_PLAN_DRAFTS_PER_DAY": "10",
            "R_AGENT_DAILY_PLAN_MAP_OPTIMIZATIONS_PER_DAY": "3",
        },
    )
    print(
        f"Configured immutable image and daily-plan mode={args.mode}; secrets were not printed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
