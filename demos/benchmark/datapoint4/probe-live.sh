#!/usr/bin/env bash
# DP4 diagnostic: per-request latency vs payload size at concurrency 1.
#
# Generates a small scale policy, deploys it to BOTH engines, and runs
# probe-size.py to separate byte-cost from match-cost (see probe-size.py).
# Run on EC2. This is a diagnostic, not part of the headline benchmark.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

source .venv/bin/activate
set -a; source config/demo.env; source .env; set +a

RESULTS="${DP4_RESULTS:-$ROOT/demos/benchmark/datapoint4/results}"
mkdir -p "$RESULTS"
RECORDS="${DP4_PROBE_RECORDS:-200}"
RULES="${DP4_RULES:-3000}"

if [ -n "${DP4_CORPUS:-}" ]; then
  CORPUS_DIR="$DP4_CORPUS"
else
  echo ">> generating a small policy corpus ($RECORDS records, $RULES rules)"
  GEN_OUT="$(validate generate --config config/workloads/enterprise-dlp.yaml \
      --records "$RECORDS" --rules "$RULES")"
  echo "$GEN_OUT"
  RUN_DIR="$(printf '%s\n' "$GEN_OUT" | awk -F': +' '/Run directory:/{print $2}')"
  CORPUS_DIR="$RUN_DIR/generated"
fi
POLICY="$CORPUS_DIR/scale-policy.nol"
[ -f "$POLICY" ] || { echo "missing policy: $POLICY" >&2; exit 1; }

echo ">> deploying the probe policy to both engines"
validate policy --file "$POLICY" --target themis >/dev/null
validate policy --file "$POLICY" --target aergia >/dev/null
echo ">> letting the policy propagate"; sleep 6

export THEMIS_ENDPOINT="$THEMIS_PROCESS_ENDPOINT"
export AERGIA_ENDPOINT="$AERGIA_PROCESS_ENDPOINT"

python demos/benchmark/datapoint4/probe-size.py \
  --policy "$POLICY" --out "$RESULTS/size-probe.csv" "$@"
