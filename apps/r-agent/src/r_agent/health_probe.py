"""Container healthcheck entry point."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from r_agent.health import check_health


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--path",
        type=Path,
        default=Path(os.environ.get("R_AGENT_HEALTH_FILE", "./data/health.json")),
    )
    parser.add_argument("--max-age", type=float, default=90.0)
    args = parser.parse_args()
    healthy, reason = check_health(args.path, max_age_seconds=args.max_age)
    print(reason)
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
