#!/usr/bin/env bash
# Data Point 4 - throughput at load, against the real engine(s).
#
# Generates a large enterprise-dlp scale corpus, deploys ITS policy (the same
# 5,000-rule literal policy) to each engine, then drives a concurrency x payload
# sweep against each and writes one CSV per engine plus a combined CSV. Run on
# EC2 (the box that has Go 1.22 and reaches Themis :443 + Aergia :444).
#
# Integrity: identical policy + corpus + driver to every engine. This is a
# throughput test on the same listMatch policy - not a new capability claim.
#
# Heads-up on runtime: the full default sweep is 6 concurrency x 3 payloads x
# (warm 10s + measure 30s) = ~24 min PER ENGINE. Dial it down for a quick read,
# e.g.  DP4_CONCURRENCY=1,32,256 DP4_DURATION=10 DP4_WARMUP=3
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"   # repo root
cd "$ROOT"

source .venv/bin/activate
set -a; source config/demo.env; source .env; set +a
export PATH="$HOME/.local/go/bin:$PATH"

PACK="demos/benchmark/datapoint4"
RESULTS="${DP4_RESULTS:-$ROOT/$PACK/results}"
mkdir -p "$RESULTS"

# Scale + load knobs (all overridable). 50k records / 5k rules is 5x the
# qualification floor; the sweep matches the plan's defaults.
RECORDS="${DP4_RECORDS:-50000}"
RULES="${DP4_RULES:-5000}"
CONCURRENCY="${DP4_CONCURRENCY:-1,8,32,128,512,1024}"
PAYLOADS="${DP4_PAYLOADS:-small,medium,large}"
WARMUP="${DP4_WARMUP:-10}"
DURATION="${DP4_DURATION:-30}"
INSECURE_FLAG=""
[ "${DP4_INSECURE:-0}" = "1" ] && INSECURE_FLAG="--insecure"
# Engines to drive. Default both; set DP4_ENGINES=themis if Aergia :444 is down.
ENGINES="${DP4_ENGINES:-themis aergia}"

# --- corpus: reuse a prepared one, or generate a fresh scale corpus ---
if [ -n "${DP4_CORPUS:-}" ]; then
  CORPUS_DIR="$DP4_CORPUS"
  echo ">> reusing corpus at $CORPUS_DIR"
else
  echo ">> generating enterprise-dlp scale corpus: $RECORDS records, $RULES rules"
  GEN_OUT="$(validate generate --config config/workloads/enterprise-dlp.yaml \
      --records "$RECORDS" --rules "$RULES")"
  echo "$GEN_OUT"
  RUN_DIR="$(printf '%s\n' "$GEN_OUT" | awk -F': +' '/Run directory:/{print $2}')"
  CORPUS_DIR="$RUN_DIR/generated"
fi
INPUT="$CORPUS_DIR/input.jsonl"
POLICY="$CORPUS_DIR/scale-policy.nol"
[ -f "$INPUT" ]  || { echo "missing corpus input: $INPUT" >&2; exit 1; }
[ -f "$POLICY" ] || { echo "missing corpus policy: $POLICY" >&2; exit 1; }
echo ">> corpus: $INPUT"

# The driver resolves its endpoint/token from these (data planes, valid certs).
export THEMIS_ENDPOINT="$THEMIS_PROCESS_ENDPOINT"
export AERGIA_ENDPOINT="$AERGIA_PROCESS_ENDPOINT"
# THEMIS_TOKEN / AERGIA_TOKEN come from .env already.

# --- build the driver once ---
echo ">> building the load driver"
( cd "$PACK/go" && GOCACHE="$ROOT/$PACK/.gocache" go build -o "$RESULTS/dp4driver" . )

for engine in $ENGINES; do
  echo ">> deploying the scale policy to $engine (replaces the active policy)"
  validate policy --file "$POLICY" --target "$engine" >/dev/null
  echo ">> letting the policy propagate"; sleep 6
  echo ">> driving $engine: concurrency [$CONCURRENCY] x payloads [$PAYLOADS]"
  "$RESULTS/dp4driver" \
    --engine "$engine" \
    --label "$engine" \
    --input "$INPUT" \
    --concurrency "$CONCURRENCY" \
    --payloads "$PAYLOADS" \
    --warmup "$WARMUP" \
    --duration "$DURATION" \
    $INSECURE_FLAG \
    --output "$RESULTS/throughput_$engine.csv"
done

echo ">> combining per-engine CSVs"
COMBINED="$RESULTS/throughput_combined.csv"
first=1
for engine in $ENGINES; do
  f="$RESULTS/throughput_$engine.csv"
  [ -f "$f" ] || continue
  if [ $first -eq 1 ]; then cat "$f" > "$COMBINED"; first=0; else tail -n +2 "$f" >> "$COMBINED"; fi
done
echo ">> combined CSV: $COMBINED"
column -s, -t "$COMBINED" 2>/dev/null || cat "$COMBINED"
echo ">> done. Build run.json from the combined CSV, then render with make-report.py."
