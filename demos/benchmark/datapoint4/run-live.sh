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

# High concurrency needs one file descriptor per open connection; the default
# soft limit (often 1024) would turn real throughput into spurious "too many
# open files" errors. Raise it as high as the hard limit allows.
ulimit -n 65536 2>/dev/null || ulimit -n "$(ulimit -Hn)" 2>/dev/null || true
echo ">> fd limit (ulimit -n): $(ulimit -n)"

PACK="demos/benchmark/datapoint4"
RESULTS="${DP4_RESULTS:-$ROOT/$PACK/results}"
mkdir -p "$RESULTS"

# Scale + load knobs (all overridable). 80k records supplies >=4,000 DISTINCT
# bodies in every size band so neither engine gets a warm-cache free ride (a
# small repeated working set silently favors software RE2, which the FPGA can't
# exploit); 4,000 rules per the qualification target.
RECORDS="${DP4_RECORDS:-80000}"
RULES="${DP4_RULES:-4000}"
CONCURRENCY="${DP4_CONCURRENCY:-1,8,32,128,512,1024}"
PAYLOADS="${DP4_PAYLOADS:-small,medium,large}"
WARMUP="${DP4_WARMUP:-10}"
DURATION="${DP4_DURATION:-30}"
# Distinct bodies held per band (the fair-comparison / cache-defeat knob).
CAP_SMALL="${DP4_CAP_SMALL:-20000}"
CAP_MEDIUM="${DP4_CAP_MEDIUM:-8000}"
CAP_LARGE="${DP4_CAP_LARGE:-4000}"
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
  # Deploy verification (ISSUE-003/007, no policy read-back): confirm the policy
  # actually landed on this engine before we drive it — otherwise a silent stale
  # deploy would be reported as a real throughput number. Single policy, so no
  # set-difference; any literal must redact.
  if ! python "$PACK/deploy_probe.py" --policy "$POLICY" --engines "$engine"; then
    echo ">> !! deploy probe FAILED for $engine -- skipping (policy did not land)"; continue
  fi
  echo ">> driving $engine: concurrency [$CONCURRENCY] x payloads [$PAYLOADS], ONE CELL PER INVOCATION"
  # Single-cell invocation (findings 011 step 2): per-cell driver-host CPU is
  # meaningless if one dp4driver call spans a concurrency list, so we drive one
  # (payload, concurrency) at a time and sample the driver box for exactly that
  # cell. driver_cpu_pct/busiest/limited land in the CSV beside errors and stall,
  # and a >70% overall or >90% single-core cell is flagged AT THE TIME.
  ENGINE_CSV="$RESULTS/throughput_$engine.csv"
  CELL_CSV="$RESULTS/cell_${engine}.csv"
  first_cell=1
  for payload in ${PAYLOADS//,/ }; do
    for conc in ${CONCURRENCY//,/ }; do
      echo ">> -- $engine payload=$payload concurrency=$conc"
      CPUTMP="$(mktemp)"
      bash "$PACK/driver-cpu-probe.sh" --tail "$DURATION" > "$CPUTMP" & CPUPID=$!
      "$RESULTS/dp4driver" \
        --engine "$engine" --label "$engine" --input "$INPUT" \
        --concurrency "$conc" --payloads "$payload" \
        --warmup "$WARMUP" --duration "$DURATION" \
        --cap-small "$CAP_SMALL" --cap-medium "$CAP_MEDIUM" --cap-large "$CAP_LARGE" \
        $INSECURE_FLAG \
        --output "$CELL_CSV" | sed 's/^/     /'
      kill -TERM "$CPUPID" 2>/dev/null || true; wait "$CPUPID" 2>/dev/null || true
      read -r DCPU DMAXCORE < "$CPUTMP" 2>/dev/null || { DCPU=NA; DMAXCORE=NA; }
      rm -f "$CPUTMP"
      DFLAG=no
      awk "BEGIN{exit !((${DCPU:-0}+0)>70 || (${DMAXCORE:-0}+0)>90)}" 2>/dev/null && DFLAG=yes
      [ "$DFLAG" = yes ] && echo "     !! DRIVER CPU ${DCPU}% (busiest core ${DMAXCORE}%) > threshold -- cell may be DRIVER-LIMITED; read this engine rps with suspicion"
      [ -f "$CELL_CSV" ] || { echo "     !! no CSV for this cell -- skipping"; continue; }
      if [ "$first_cell" -eq 1 ]; then
        echo "$(head -1 "$CELL_CSV"),driver_cpu_pct,driver_busiest_core_pct,driver_limited" > "$ENGINE_CSV"
        first_cell=0
      fi
      tail -n +2 "$CELL_CSV" | sed "s/\$/,$DCPU,$DMAXCORE,$DFLAG/" >> "$ENGINE_CSV"
    done
  done
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
