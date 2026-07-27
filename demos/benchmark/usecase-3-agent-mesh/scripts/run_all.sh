#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GOCACHE_DIR="${GOCACHE:-$ROOT/.gocache}"

mkdir -p "$ROOT/results"
mkdir -p "$GOCACHE_DIR"

echo "Running Data Point 3 agent-mesh benchmark..."
(
  cd "$ROOT/go"
  GOCACHE="$GOCACHE_DIR" go run . \
    --input "$ROOT/data/tasks/sample_agent_tasks.jsonl" \
    --policy-dir "$ROOT/data/policies" \
    --output-dir "$ROOT/results"
)

echo "Generating report..."
python3 "$ROOT/report/generate_report.py" \
  --results-csv "$ROOT/results/run_all.csv" \
  --report-dir "$ROOT/report" \
  --input-path "$ROOT/data/tasks/sample_agent_tasks.jsonl"

echo "Done."
echo "Results CSV: $ROOT/results/run_all.csv"
echo "HTML report: $ROOT/report/report.html"
