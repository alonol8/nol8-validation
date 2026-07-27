#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="$ROOT/results"
GOCACHE_DIR="${GOCACHE:-$ROOT/.gocache}"
BENCHMARK_BIN="$ROOT/go/benchmark_runner"
mkdir -p "$RESULTS_DIR"
mkdir -p "$GOCACHE_DIR"

COMBINED_CSV="$RESULTS_DIR/run_01.csv"
RESOURCE_JSON="$RESULTS_DIR/resource_metrics.json"

rm -f "$COMBINED_CSV" "$RESOURCE_JSON"
rm -f "$BENCHMARK_BIN"

echo "Building benchmark binary..."
(
  cd "$ROOT/go"
  GOCACHE="$GOCACHE_DIR" go build -o "$BENCHMARK_BIN" .
)

MODES="${MODES:-nofilter re2 listmatch nol8sim}"
first=1

for mode in $MODES; do
  echo "Running Go benchmark for mode: $mode"
  tmp_csv="$RESULTS_DIR/${mode}.csv"
  tmp_stdout="$RESULTS_DIR/${mode}_stdout.txt"
  tmp_time="$RESULTS_DIR/${mode}_time.txt"

  if /usr/bin/time -v true >/dev/null 2>&1; then
    TIME_CMD="/usr/bin/time -v"
  else
    TIME_CMD="/usr/bin/time"
  fi

  $TIME_CMD bash -c '"$1" "$2/data/sample_chunks.jsonl" "$3" "$4"' _ "$BENCHMARK_BIN" "$ROOT" "$tmp_csv" "$mode" >"$tmp_stdout" 2>"$tmp_time"
  
  if [ "$first" -eq 1 ]; then
    head -n 1 "$tmp_csv" > "$COMBINED_CSV"
    first=0
  fi
  tail -n +2 "$tmp_csv" >> "$COMBINED_CSV"
done

echo
echo "Collecting resource metrics..."
cmd=(python3 "$ROOT/python/collect_resource_metrics.py" "$RESOURCE_JSON")
for mode in $MODES; do
  cmd+=("${mode}=$RESULTS_DIR/${mode}_time.txt")
done
"${cmd[@]}"

echo
echo "Analyzing results..."
python3 "$ROOT/python/analyze_results.py" "$COMBINED_CSV"

echo
echo "Generating HTML report..."
python3 "$ROOT/report/generate_report.py" "$COMBINED_CSV" "$ROOT/report/report.html" "$RESOURCE_JSON"

echo
echo "Done."
echo "Modes: $MODES"
echo "Results CSV: $COMBINED_CSV"
echo "Resource metrics JSON: $RESOURCE_JSON"
echo "HTML report: $ROOT/report/report.html"
