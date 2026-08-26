"""Operator entry point for an aggregate-only Memory V2.1 model evaluation."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from r_agent.config import ConfigError, load_env_file
from r_agent.model_client import ModelConfig, ModelError, OpenAICompatibleClient
from r_agent.model_memory_evaluation import MINIMUM_MODEL_RECALL, evaluate_model


class ModelEvaluationConfigurationError(ValueError):
    """The explicitly configured model is not available for an evaluation."""


def configured_model_client() -> OpenAICompatibleClient:
    """Build the existing OpenAI-compatible client without exposing credentials."""
    api_key = os.environ.get("R_AGENT_MODEL_API_KEY", "").strip()
    if not api_key:
        raise ModelEvaluationConfigurationError(
            "R_AGENT_MODEL_API_KEY is required; evaluation was not run"
        )
    thinking = os.environ.get("R_AGENT_MODEL_THINKING", "").strip().casefold() or None
    try:
        return OpenAICompatibleClient(
            ModelConfig(
                provider=os.environ.get("R_AGENT_MODEL_PROVIDER", "openai-compatible").strip(),
                base_url=os.environ.get(
                    "R_AGENT_MODEL_BASE_URL", "https://api.openai.com/v1"
                ).strip(),
                model=os.environ.get("R_AGENT_MODEL_NAME", "gpt-5-mini").strip(),
                api_key=api_key,
                thinking=thinking,
            )
        )
    except ModelError as exc:
        raise ModelEvaluationConfigurationError("model configuration is invalid") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="r-agent-memory-eval",
        description=(
            "Run the configured model against the redacted Memory V2.1 set. "
            "Only aggregate metrics are printed."
        ),
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="optional local R_AGENT_ environment file (default: .env)",
    )
    parser.add_argument(
        "--minimum-recall",
        type=float,
        default=0.90,
        help="minimum model recall threshold (default: 0.90)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not MINIMUM_MODEL_RECALL <= args.minimum_recall <= 1.0:
        print(
            "configuration_error: minimum recall must be between 0.90 and 1",
            file=sys.stderr,
        )
        return 2
    try:
        load_env_file(args.env_file)
        client = configured_model_client()
        metrics = asyncio.run(evaluate_model(client))
    except (ConfigError, ModelEvaluationConfigurationError):
        print(
            "configuration_error: configured model is unavailable; no metrics emitted",
            file=sys.stderr,
        )
        return 2
    except (ModelError, OSError, UnicodeError, ValueError):
        print("evaluation_error: model evaluation failed; no metrics emitted", file=sys.stderr)
        return 3

    print(
        json.dumps(
            metrics.aggregate_dict(minimum_recall=args.minimum_recall),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0 if metrics.passes_thresholds(minimum_recall=args.minimum_recall) else 1


if __name__ == "__main__":
    raise SystemExit(main())
