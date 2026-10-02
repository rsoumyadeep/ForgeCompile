#!/usr/bin/env bash
# Run every check that CI runs: lint, format check, type check, tests.
# Usage: scripts/check.sh [extra pytest args]
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== ruff check";  uv run ruff check .
echo "== ruff format"; uv run ruff format --check .
echo "== mypy";        uv run mypy
echo "== pytest";      uv run pytest "$@"
