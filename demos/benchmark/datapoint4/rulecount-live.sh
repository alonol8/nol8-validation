#!/usr/bin/env bash
# DP4 rule-count sweep - does the FPGA's edge scale with POLICY SIZE?
#
# The fair run suggested the real advantage axis is rule count, not payload or
# request-uniqueness: software RE2 gets slower as the pattern set grows, while a
# fixed FPGA pipeline is ~constant in rule count. This isolates that: FIXED
# payload (small) at a FIXED concurrency, varying ONLY the deployed rule count.
# Expect Themis flat, RE2 sloping down as rules climb.
#
# Run on EC2 (Go + reaches the engines). Deploys a fresh policy per rule count
# to BOTH engines.
#
# CORPUS CAVEAT (do not read the cross-cell trend naively): a fresh corpus is
# generated PER rule count, so avg_body_bytes co-varies slightly with rule count
# (observed ~2624/2611/2580 across 2k/6k/8k, ~1.7%). The WITHIN-cell A/B is fair —
# both engines get the identical corpus in a cell — so the engine RATIO per cell is
# clean. The cross-cell rule-count TREND is mildly confounded by that body-size
# drift; read it alongside the per-cell avg_body_bytes column, which the driver
# records.
#
# Why regenerate rather than fix one corpus: fixing the corpus would make MATCH
# DENSITY co-vary with rule count (the catalog is nested, so a 2k policy matches
# fewer literals in the same document than an 8k policy), which blends automaton
# size with match count — the worse confound for "RE2 slows as the pattern set
# grows." Regenerating is intended to hold match density ~constant and isolate rule
# count. ASSUMPTION, not yet verified: that the generator actually holds match
# density roughly constant across rule counts. Treat the trend accordingly.
#
#   bash demos/benchmark/datapoint4/rulecount-live.sh
#   DP4_RULE_COUNTS="1000 4000 16000" DP4_RC_DURATION=10 bash .../rulecount-live.sh
set -uo pipefail   # NOT -e: a failed deploy at a huge rule count must not abort the sweep

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
set -a; source config/demo.env; source .env; set +a
export PATH="$HOME/.local/go/bin:$PATH"
ulimit -n 65536 2>/dev/null || true

PACK="demos/benchmark/datapoint4"
RESULTS="${DP4_RESULTS:-$ROOT/$PACK/results}"
mkdir -p "$RESULTS"

# Denser points under the ~16k deploy ceiling; a huge count that fails to deploy
# or generate just skips. REPS re-drives the SAME corpus so we can median out
# transient shared-host noise without regenerating.
RULE_COUNTS="${DP4_RULE_COUNTS:-1000 2000 4000 6000 8000 10000 12000}"
REPS="${DP4_RC_REPS:-3}"
RECORDS="${DP4_RC_RECORDS:-15000}"    # ~40% small band -> >=4,000 distinct small bodies
CONC="${DP4_RC_CONC:-256}"            # fixed, near Themis small peak and well-parallelized
PAYLOAD="${DP4_RC_PAYLOAD:-small}"
DURATION="${DP4_RC_DURATION:-15}"
WARMUP="${DP4_RC_WARMUP:-5}"

export THEMIS_ENDPOINT="$THEMIS_PROCESS_ENDPOINT"
export AERGIA_ENDPOINT="$AERGIA_PROCESS_ENDPOINT"

echo ">> building the load driver"
( cd "$PACK/go" && GOCACHE="$ROOT/$PACK/.gocache" go build -o "$RESULTS/dp4driver" . )

OUT="$RESULTS/rulecount.csv"
rm -f "$OUT"

# The policy we last confirmed live on the engines (for the deploy probe's
# set-difference). Empty on the first cell.
PREV_POLICY=""

for R in $RULE_COUNTS; do
  echo ">> ===== rule_count=$R ====="
  GEN_OUT="$(validate generate --config config/workloads/enterprise-dlp.yaml --records "$RECORDS" --rules "$R" 2>&1)"
  RUN_DIR="$(printf '%s\n' "$GEN_OUT" | awk -F': +' '/Run directory:/{print $2}')"
  POLICY="$RUN_DIR/generated/scale-policy.nol"
  INPUT="$RUN_DIR/generated/input.jsonl"
  if [ -z "$RUN_DIR" ] || [ ! -f "$POLICY" ]; then
    echo "   !! generation failed at rule_count=$R -- skipping"; printf '%s\n' "$GEN_OUT" | tail -3; continue
  fi
  if ! validate policy --file "$POLICY" --target themis >/dev/null 2>&1; then
    echo "   !! themis deploy failed at rule_count=$R -- skipping (policy may exceed a limit)"; continue
  fi
  if ! validate policy --file "$POLICY" --target aergia >/dev/null 2>&1; then
    echo "   !! aergia deploy failed at rule_count=$R -- skipping"; continue
  fi
  sleep 6
  # Deploy verification (ISSUE-003 fire-and-forget, ISSUE-007 no health signal):
  # prove the NEW ruleset actually landed on BOTH engines before we trust this
  # cell. Probes with a literal unique to this policy vs the last one confirmed
  # live, and prints |set(N)-set(prev)| (an empty diff = the sweep isn't varying
  # the ruleset here, a finding in itself). A stale policy cannot pass.
  if ! python "$PACK/deploy_probe.py" --policy "$POLICY" --prev "$PREV_POLICY" --engines themis,aergia; then
    echo "   !! deploy probe FAILED at rule_count=$R -- aborting this cell (policy did not land)"; continue
  fi
  PREV_POLICY="$POLICY"
  # Alternate which engine is driven first each rep (item 7: run-order confound).
  # The old order ran all Themis reps then all Aergia, so Themis was ALWAYS the one
  # measured immediately after deploy — which could account for the ~180x 5xx
  # asymmetry all on its own. Alternating removes that as an explanation.
  for rep in $(seq 1 "$REPS"); do
    if [ $((rep % 2)) -eq 1 ]; then ORDER="themis aergia"; else ORDER="aergia themis"; fi
    for engine in $ORDER; do
      echo "   -- $engine rule_count=$R rep $rep/$REPS (order: $ORDER)"
      # Per-cell driver-host CPU headroom (findings 011 step 2): the check that
      # stops the load generator being the answer again. The probe tails the
      # driver's MEASURE window (robust to variable corpus-load time) and is
      # stopped the instant the driver returns; the two numbers land in the CSV
      # beside errors and stall. Read-only /proc/stat -> zero test impact.
      CPUTMP="$(mktemp)"
      bash "$PACK/driver-cpu-probe.sh" --tail "$DURATION" > "$CPUTMP" & CPUPID=$!
      "$RESULTS/dp4driver" \
        --engine "$engine" --label "$engine" --input "$INPUT" \
        --concurrency "$CONC" --payloads "$PAYLOAD" \
        --warmup "$WARMUP" --duration "$DURATION" \
        --cap-small 4000 --cap-medium 4000 --cap-large 4000 \
        --output "$RESULTS/rc_${engine}.csv" | sed 's/^/      /'
      kill -TERM "$CPUPID" 2>/dev/null; wait "$CPUPID" 2>/dev/null || true
      read -r DCPU DMAXCORE < "$CPUTMP" 2>/dev/null || { DCPU=NA; DMAXCORE=NA; }
      rm -f "$CPUTMP"
      # Driver-limited if the box is broadly hot (>70%) OR a single core is pinned
      # (>90%) — the two shapes of "the load generator was the limit". Flag it AT
      # THE TIME so a suspect cell is visible during the run, not months later.
      DFLAG=no
      awk "BEGIN{exit !((${DCPU:-0}+0)>70 || (${DMAXCORE:-0}+0)>90)}" 2>/dev/null && DFLAG=yes
      [ "$DFLAG" = yes ] && echo "      !! DRIVER CPU ${DCPU}% (busiest core ${DMAXCORE}%) > threshold -- cell may be DRIVER-LIMITED; read this engine rps with suspicion"
      [ -f "$RESULTS/rc_${engine}.csv" ] || continue
      if [ ! -f "$OUT" ]; then echo "rule_count,rep,$(head -1 "$RESULTS/rc_${engine}.csv"),driver_cpu_pct,driver_busiest_core_pct,driver_limited" > "$OUT"; fi
      tail -n +2 "$RESULTS/rc_${engine}.csv" | sed "s/^/$R,$rep,/;s/\$/,$DCPU,$DMAXCORE,$DFLAG/" >> "$OUT"
    done
  done
  echo ">> rule_count=$R done"
done

echo ">> combined rule-count CSV: $OUT"
column -s, -t "$OUT" 2>/dev/null || cat "$OUT"
echo ">> done. Build the rule-count chart with build-rulecount.py."
