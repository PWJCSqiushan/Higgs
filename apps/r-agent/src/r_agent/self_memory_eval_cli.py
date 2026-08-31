"""Content-free CLI for the self-memory shadow evaluation gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from r_agent.self_memory_evaluation import (
    evaluate_raw_outputs,
    fixed_fixture_outputs,
    load_cases,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="r-agent-self-memory-eval")
    parser.add_argument("--cases", type=Path, help="optional versioned evaluation dataset")
    parser.add_argument(
        "--outputs",
        type=Path,
        help="optional JSON object mapping case IDs to raw extractor outputs",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        cases = load_cases(args.cases)
        if args.outputs is None:
            outputs = fixed_fixture_outputs(cases)
        else:
            payload = json.loads(args.outputs.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in payload.items()
            ):
                raise ValueError("extractor output fixture must be a string mapping")
            outputs = payload
        metrics = evaluate_raw_outputs(cases, outputs)
    except (KeyError, OSError, UnicodeError, ValueError, json.JSONDecodeError):
        print("evaluation_error: invalid offline evaluation input", file=sys.stderr)
        return 2
    print(json.dumps(metrics.report(), separators=(",", ":"), sort_keys=True))
    return 0 if metrics.passes() else 1


if __name__ == "__main__":
    raise SystemExit(main())
