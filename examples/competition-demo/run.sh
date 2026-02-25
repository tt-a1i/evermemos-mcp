#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATE="${DATE:-$(date +%F)}"
ARTIFACT_DIR="${ARTIFACT_DIR:-$ROOT/artifacts/competition/${DATE}-formal-real}"
QUERIES="${QUERIES:-$ROOT/examples/competition-demo/query_set_real_template.jsonl}"
PREFIX="${PREFIX:-}"

cd "$ROOT"

cmd=(
  uv run python examples/competition-demo/run_demo.py
  --queries "$QUERIES"
  --artifact-dir "$ARTIFACT_DIR"
)

if [[ -n "$PREFIX" ]]; then
  cmd+=(--prefix "$PREFIX")
fi

if [[ "$#" -gt 0 ]]; then
  cmd+=("$@")
fi

"${cmd[@]}"
