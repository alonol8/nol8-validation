#!/usr/bin/env bash
# DP4 density on REAL data - does denser realistic data widen the FPGA's lead?
#
# Uses the enterprise-dlp.yaml generator (real varied docs - customer records,
# tickets, emails, logs) and varies ONLY the match density by overriding the
# match_distribution (light ~1/KB -> moderate ~6/KB -> heavy ~12-15/KB), small
# docs, fixed rules, both engines. No hand-rolled filler; this is the honest test
# of the founder's matches/KB point on data we trust. Run on EC2.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
set -a; source config/demo.env; source .env; set +a
export PATH="$HOME/.local/go/bin:$PATH"
ulimit -n 65536 2>/dev/null || true

PACK="demos/benchmark/datapoint4"
RESULTS="${DP4_RESULTS:-$ROOT/$PACK/results}"
mkdir -p "$RESULTS"

RULES="${DP4_DR_RULES:-8000}"
RECORDS="${DP4_DR_RECORDS:-12000}"
CONC="${DP4_DR_CONC:-256}"
DUR="${DP4_DR_DURATION:-15}"
WARM="${DP4_DR_WARMUP:-5}"
PROFILES="${DP4_DR_PROFILES:-light moderate heavy}"

export THEMIS_ENDPOINT="$THEMIS_PROCESS_ENDPOINT"
export AERGIA_ENDPOINT="$AERGIA_PROCESS_ENDPOINT"

echo ">> building the load driver"
( cd "$PACK/go" && GOCACHE="$ROOT/$PACK/.gocache" go build -o "$RESULTS/dp4driver" . )

OUT="$RESULTS/density_real.csv"
rm -f "$OUT"
DEPLOYED=0

for prof in $PROFILES; do
  echo ">> ===== profile=${prof} (real enterprise-dlp data, rules=${RULES}) ====="
  # Override match density + force small docs; everything else is the real generator.
  python - "$prof" <<'PY'
import sys, yaml
prof = sys.argv[1]
ranges = {"light": (1, 3), "moderate": (8, 16), "heavy": (20, 45)}
lo, hi = ranges[prof]
c = yaml.safe_load(open("config/workloads/enterprise-dlp.yaml"))
c["documents"]["match_distribution"] = {prof: {"weight": 100,
    "matches_per_document": {"minimum": lo, "maximum": hi}}}
c["documents"]["size_distribution"] = {"small": {"weight": 100,
    "pad_to_target": True, "minimum_bytes": 512, "maximum_bytes": 4096}}
yaml.safe_dump(c, open(f"/tmp/edlp-{prof}.yaml", "w"), sort_keys=False)
PY
  GEN_OUT="$(validate generate --config /tmp/edlp-${prof}.yaml --rules "$RULES" --records "$RECORDS" 2>&1)"
  RUN_DIR="$(printf '%s\n' "$GEN_OUT" | awk -F': +' '/Run directory:/{print $2}')"
  POLICY="$RUN_DIR/generated/scale-policy.nol"
  INPUT="$RUN_DIR/generated/input.jsonl"
  MANIFEST="$RUN_DIR/generated/manifest.json"
  if [ -z "$RUN_DIR" ] || [ ! -f "$INPUT" ]; then
    echo "   !! generation failed for $prof"; printf '%s\n' "$GEN_OUT" | tail -3; continue
  fi
  DENS="$(python -c "import json;m=json.load(open('$MANIFEST'));print(round(m['expected_total_matches']/(m['payload_bytes_total']/1024),2))")"
  AVG="$(python -c "import json;m=json.load(open('$MANIFEST'));print(int(m['payload_bytes_average']))")"
  echo "   real corpus: ${RECORDS} docs, avg ${AVG} bytes, ~${DENS} matches/KB"

  if [ $DEPLOYED -eq 0 ]; then
    echo ">> deploying the ${RULES}-rule policy to both engines"
    validate policy --file "$POLICY" --target themis >/dev/null 2>&1 || { echo "themis deploy failed"; exit 1; }
    validate policy --file "$POLICY" --target aergia >/dev/null 2>&1 || { echo "aergia deploy failed"; exit 1; }
    echo ">> letting the policy propagate"; sleep 6
    DEPLOYED=1
  fi

  for engine in themis aergia; do
    rm -f "$RESULTS/dr_${engine}.csv"
    "$RESULTS/dp4driver" \
      --engine "$engine" --label "$engine" --input "$INPUT" \
      --concurrency "$CONC" --payloads small \
      --warmup "$WARM" --duration "$DUR" \
      --cap-small "$RECORDS" --cap-medium 4000 --cap-large 4000 \
      --output "$RESULTS/dr_${engine}.csv" | sed 's/^/      /'
    if [ ! -s "$RESULTS/dr_${engine}.csv" ] || [ "$(wc -l < "$RESULTS/dr_${engine}.csv")" -lt 2 ]; then
      echo "      !! no data row for $engine (docs may have missed the small band)"; continue
    fi
    if [ ! -f "$OUT" ]; then echo "profile,matches_per_kb,rules,$(head -1 "$RESULTS/dr_${engine}.csv")" > "$OUT"; fi
    tail -n +2 "$RESULTS/dr_${engine}.csv" | sed "s/^/$prof,$DENS,$RULES,/" >> "$OUT"
  done
  echo ">> profile=${prof} done"
done

echo ">> combined real-density CSV: $OUT"
column -s, -t "$OUT" 2>/dev/null || cat "$OUT"
echo ">> done."
