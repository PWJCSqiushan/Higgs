"""Operator-only CLI for one-shot official QQ owner capture."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from r_agent.official_qq_owner_capture import (
    OfficialQQOwnerCapture,
    OwnerCaptureError,
    OwnerCaptureTimeout,
    SecureOwnerBinding,
)

CONFIRMATION = "ONLY_OWNER_IS_TEST_USER"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="r-agent-official-owner-capture")
    parser.add_argument("--env-file", type=Path, default=Path("/run/higgs-config/higgs.env"))
    parser.add_argument("--data-dir", type=Path, default=Path("/var/lib/higgs"))
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path("/run/higgs-config/owner-capture-backups"),
    )
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument(
        "--confirm-single-test-user",
        required=True,
        help=f"must be exactly {CONFIRMATION}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.confirm_single_test_user != CONFIRMATION:
        print(json.dumps({"status": "refused", "reason": "confirmation_mismatch"}))
        return 2
    binding = SecureOwnerBinding(args.env_file, backup_dir=args.backup_dir)
    capture = OfficialQQOwnerCapture(binding, data_dir=args.data_dir)
    try:
        asyncio.run(capture.run(timeout_seconds=args.timeout_seconds))
    except OwnerCaptureTimeout:
        print(json.dumps({"status": "timeout", "official_enabled": False}))
        return 4
    except (OwnerCaptureError, ValueError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": type(exc).__name__,
                    "official_enabled": False,
                }
            )
        )
        return 3
    print(json.dumps({"status": "captured", "official_enabled": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
