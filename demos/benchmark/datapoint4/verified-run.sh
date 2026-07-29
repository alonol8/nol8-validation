#!/usr/bin/env bash
# One verified engine comparison: generate -> deploy -> verify -> measure.
#
# The sequence people run by hand, with the steps that are easy to forget built
# in. Two of them are not optional:
#
#   settle after deploy   the control plane returns before the data plane has
#                         loaded the policy, so requests sent immediately after
#                         a deploy can be evaluated against the previous one and
#                         nothing in the response says so
#
#   verify before quoting the driver checks HTTP status only. A 200 carrying
#                         wrong output counts as a success, and a 5,000-rule run
#                         once reported 674,893 successful responses of which
#                         every one was wrong. This computes the oracle's answer
#                         and checks every response against it
#
# A cell that returned wrong output is reported as such and the run exits
# non-zero, so a throughput figure is never printed for an engine that was doing
# the wrong job.
#
#   bash demos/benchmark/datapoint4/verified-run.sh
#   bash demos/benchmark/datapoint4/verified-run.sh --config config/workloads/database-export.yaml
#   bash demos/benchmark/datapoint4/verified-run.sh --rules 8000 --records 40000 --concurrency 2048
#   bash demos/benchmark/datapoint4/verified-run.sh --run 20260727T100911662509Z   # reuse a corpus
#
# Every flag also has a DP4_* environment variable, so it composes into a sweep.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

CONFIG="${DP4_CONFIG:-config/workloads/database-export.yaml}"
RULES="${DP4_RULES:-5000}"
RECORDS="${DP4_RECORDS:-20000}"
CONCURRENCY="${DP4_CONCURRENCY:-1024}"
PAYLOAD="${DP4_PAYLOAD:-small}"
CAP="${DP4_CAP:-20000}"
WARMUP="${DP4_WARMUP:-5}"
DURATION="${DP4_DURATION:-20}"
ENGINES="${DP4_ENGINES:-themis aergia}"
SETTLE="${DP4_SETTLE:-8}"
REUSE_RUN="${DP4_RUN:-}"
SKIP_VERIFY="${DP4_SKIP_VERIFY:-0}"

usage() {
  sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --config)      CONFIG="$2"; shift 2 ;;
    --rules)       RULES="$2"; shift 2 ;;
    --records)     RECORDS="$2"; shift 2 ;;
    --concurrency) CONCURRENCY="$2"; shift 2 ;;
    --payload)     PAYLOAD="$2"; shift 2 ;;
    --cap)         CAP="$2"; shift 2 ;;
    --warmup)      WARMUP="$2"; shift 2 ;;
    --duration)    DURATION="$2"; shift 2 ;;
    --engines)     ENGINES="$2"; shift 2 ;;
    --settle)      SETTLE="$2"; shift 2 ;;
    --run)         REUSE_RUN="$2"; shift 2 ;;
    --skip-verify) SKIP_VERIFY=1; shift ;;
    -h|--help)     usage 0 ;;
    *) echo "unknown option: $1" >&2; usage 2 ;;
  esac
done

# shellcheck disable=SC1091
source .venv/bin/activate
set -a; source config/demo.env; source .env; set +a
export THEMIS_ENDPOINT="$THEMIS_PROCESS_ENDPOINT"
export AERGIA_ENDPOINT="$AERGIA_PROCESS_ENDPOINT"
export PATH="$HOME/.local/go/bin:$PATH"
ulimit -n 200000 2>/dev/null || true

PACK="demos/benchmark/datapoint4"
RESULTS="${DP4_RESULTS:-$ROOT/$PACK/results}"
DRIVER="$RESULTS/dp4driver"
mkdir -p "$RESULTS"

echo ">> building the load driver"
( cd "$PACK/go" && GOCACHE="$ROOT/$PACK/.gocache" go build -o "$DRIVER" . ) || {
  echo "!! driver build failed"; exit 1; }

# ---------------------------------------------------------------- corpus

if [ -n "$REUSE_RUN" ]; then
  RUN_DIR="$ROOT/artifacts/runs/$REUSE_RUN"
  echo ">> reusing run $REUSE_RUN"
else
  echo ">> generating $RECORDS records / $RULES rules from $(basename "$CONFIG")"
  GEN_OUT="$(validate generate --config "$CONFIG" --rules "$RULES" --records "$RECORDS" 2>&1)"
  RUN_DIR="$(printf '%s\n' "$GEN_OUT" | awk -F': +' '/Run directory:/{print $2}')"
  if [ -z "$RUN_DIR" ]; then
    echo "!! generation failed"; printf '%s\n' "$GEN_OUT" | tail -5; exit 1
  fi
fi

POLICY="$RUN_DIR/generated/scale-policy.nol"
CORPUS="$RUN_DIR/generated/input.jsonl"
MANIFEST="$RUN_DIR/generated/generation-manifest.json"
for f in "$POLICY" "$CORPUS"; do
  [ -f "$f" ] || { echo "!! missing $f"; exit 1; }
done
echo "   run: $(basename "$RUN_DIR")"

# The regime the numbers were taken in. A throughput figure without it is not
# interpretable: match density and rule coverage move it more than concurrency does.
if [ -f "$MANIFEST" ]; then
  python - "$MANIFEST" <<'PY'
import json, sys
p = json.load(open(sys.argv[1])).get("input_profile", {})
if p:
    print(f"   corpus: {p.get('matches_per_kb')} matches/KB, "
          f"{p.get('near_misses_per_kb')} near-misses/KB, "
          f"rule coverage {p.get('rule_coverage')}")
PY
fi

# ---------------------------------------------------------------- deploy

for E in $ENGINES; do
  echo ">> deploying to $E"
  validate policy --file "$POLICY" --target "$E" >/dev/null 2>&1 || {
    echo "!! deploy to $E failed (the policy may exceed a size or rule limit)"
    exit 1; }
done

# Not optional. The deploy call returns on acceptance, not on convergence, so
# without this the first requests can be evaluated against the previous policy -
# which looks like an engine returning wrong output.
echo ">> settling ${SETTLE}s for the policy to reach both data planes"
sleep "$SETTLE"

# ---------------------------------------------------------------- verify

DIGESTS="$RESULTS/$(basename "$RUN_DIR").digests"
EXPECTED_ARG=()
if [ "$SKIP_VERIFY" = "1" ]; then
  echo ">> skipping verification (--skip-verify): throughput only, correctness unknown"
else
  echo ">> computing expected output for every record"
  python "$PACK/expected-digests.py" --policy "$POLICY" --corpus "$CORPUS" \
    --out "$DIGESTS" | sed 's/^/   /' || { echo "!! digest generation failed"; exit 1; }
  EXPECTED_ARG=(--expected "$DIGESTS")
fi

# ---------------------------------------------------------------- measure

WRONG=0
for E in $ENGINES; do
  echo ">> driving $E at concurrency $CONCURRENCY"
  # The run id is in the filename: a sweep drives several corpora through this
  # script, and a fixed name means each arm silently overwrites the last, leaving
  # one CSV and no way to tell which arm it came from.
  TAG="$(basename "$RUN_DIR")-c${CONCURRENCY}"
  OUT="$RESULTS/verified_${E}_${TAG}.csv"
  rm -f "$OUT"
  LOG="$RESULTS/verified_${E}_${TAG}.log"
  "$DRIVER" --engine "$E" --label "$E" --input "$CORPUS" \
    --concurrency "$CONCURRENCY" --payloads "$PAYLOAD" \
    "--cap-$PAYLOAD" "$CAP" --warmup "$WARMUP" --duration "$DURATION" \
    "${EXPECTED_ARG[@]}" --output "$OUT" | tee "$LOG" | sed 's/^/   /'
  # Parse the count, not the word: the driver's success line is "... 0 WRONG",
  # so grepping for the string reports failure on every verified run.
  N_WRONG="$(grep -oE '[0-9]+ WRONG' "$LOG" | awk '{s+=$1} END{print s+0}')"
  if [ "${N_WRONG:-0}" -gt 0 ]; then
    WRONG=1
  fi
done

echo
FIRST="$(echo "$ENGINES" | awk '{print $1}')"
{ head -1 "$RESULTS/verified_${FIRST}_${TAG}.csv"
  for E in $ENGINES; do tail -qn +2 "$RESULTS/verified_${E}_${TAG}.csv"; done
} | column -s, -t

if [ "$SKIP_VERIFY" = "1" ]; then
  echo
  echo "!! Nothing above is known to be correct - the driver checks HTTP status"
  echo "   only. Drop --skip-verify to check every response against the oracle."
  exit 0
fi

if [ "$WRONG" = "1" ]; then
  echo
  echo "!! At least one engine returned output that did not match the oracle."
  echo "   Do not quote these throughput figures: an engine doing the wrong job"
  echo "   is not comparable to one doing the right job. See the divergence with:"
  echo
  # The endpoints are exported inside this script's own process, so a command
  # pasted into a fresh shell needs them again or it reports "no endpoint
  # configured" and looks like a second failure.
  echo "   set -a; source config/demo.env; source .env; set +a"
  echo "   export THEMIS_ENDPOINT=\"\$THEMIS_PROCESS_ENDPOINT\""
  echo "   export AERGIA_ENDPOINT=\"\$AERGIA_PROCESS_ENDPOINT\""
  echo "   python demos/benchmark/verify-corpus.py --policy $POLICY \\"
  echo "     --corpus $CORPUS --engines ${ENGINES// /,} --limit 20"
  exit 1
fi

echo
echo ">> every response from every engine matched the oracle."
echo "   Verification costs driver CPU, so these figures are lower than an"
echo "   unverified run; the ratio between engines is unaffected."
