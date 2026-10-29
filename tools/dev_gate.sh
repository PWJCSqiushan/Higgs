#!/usr/bin/env bash
# Local quality gate mirroring the Python part of .github/workflows/ci.yml.
# Usage: bash tools/dev_gate.sh   (from the repository root)
# The virtualenv lives outside the repo (default /tmp/higgs-venv) so synced
# folders never receive thousands of site-packages files.
set -euo pipefail
# NB: callers should check the exit status; do not pipe this script into tail in && chains.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/tmp/higgs-venv}"
export UV_LINK_MODE=copy
export PYTHONDONTWRITEBYTECODE=1
export UV_PYTHON="${UV_PYTHON:-3.12}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/higgs-uv-cache}"

cd "$ROOT"
python3 tools/release_gate.py

cd "$ROOT/apps/r-agent"
uv sync --locked --extra dev -q
uv run ruff format --check .
uv run ruff check .
uv run pytest -q -p no:cacheprovider "$@"
echo "dev-gate=ok"
