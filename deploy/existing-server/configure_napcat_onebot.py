#!/usr/bin/env python3
"""Create NapCat's forward OneBot WebSocket config without exposing secrets."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def empty_config() -> dict[str, object]:
    return {
        "network": {
            "httpServers": [],
            "httpSseServers": [],
            "httpClients": [],
            "websocketServers": [],
            "websocketClients": [],
            "plugins": [],
        },
        "musicSignUrl": "",
        "enableLocalFile2Url": False,
        "parseMultMsg": False,
        "imageDownloadProxy": "",
        "timeout": {
            "baseTimeout": 10000,
            "uploadSpeedKBps": 256,
            "downloadSpeedKBps": 256,
            "maxTimeout": 1800000,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stack-env", type=Path, default=Path("/srv/secrets/higgs/stack.env"))
    parser.add_argument("--data-root", type=Path, default=Path("/srv/data/higgs"))
    parser.add_argument("--trash-root", type=Path, default=Path("/srv/trash"))
    args = parser.parse_args()

    values = load_env(args.stack_env)
    account = values.get("NAPCAT_ACCOUNT", "")
    token = values.get("NAPCAT_ONEBOT_TOKEN", "")
    if re.fullmatch(r"[0-9]{5,12}", account) is None:
        raise ValueError("NAPCAT_ACCOUNT must contain 5-12 ASCII digits")
    if re.fullmatch(r"[0-9a-fA-F]{64}", token) is None:
        raise ValueError("NAPCAT_ONEBOT_TOKEN must be a 64-character hexadecimal token")

    config = args.data_root / "napcat" / "config" / f"onebot11_{account}.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(config.read_text(encoding="utf-8")) if config.exists() else empty_config()
    network = data.setdefault("network", {})
    if not isinstance(network, dict):
        raise ValueError("NapCat network configuration must be an object")
    network.update(
        {
            "httpServers": [],
            "httpSseServers": [],
            "httpClients": [],
            "websocketClients": [],
            "plugins": [],
            "websocketServers": [
                {
                    "enable": True,
                    "name": "higgs-internal",
                    "host": "0.0.0.0",
                    "port": 3001,
                    "reportSelfMessage": False,
                    "enableForcePushEvent": True,
                    "messagePostFormat": "array",
                    "token": token,
                    "debug": False,
                    "heartInterval": 30000,
                }
            ],
        }
    )

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    trash = args.trash_root / f"napcat-onebot-before-{timestamp}-{uuid4().hex[:8]}"
    trash.mkdir(parents=True, mode=0o700)
    os.chmod(trash, 0o700)
    temporary = config.parent / f".{config.name}.new-{uuid4().hex}"
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    parent_stat = config.parent.stat()
    os.chown(temporary, parent_stat.st_uid, parent_stat.st_gid)
    os.chmod(temporary, 0o660)

    previous: Path | None = None
    try:
        if config.exists():
            previous = trash / config.name
            shutil.move(config, previous)
        os.replace(temporary, config)
    except Exception:
        if temporary.exists():
            shutil.move(temporary, trash / temporary.name)
        if previous is not None and previous.exists() and not config.exists():
            shutil.move(previous, config)
        raise

    print(f"configured={config}")
    print(f"previous_config_trash={trash}")
    print("onebot_server=0.0.0.0:3001 (Docker internal network only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
