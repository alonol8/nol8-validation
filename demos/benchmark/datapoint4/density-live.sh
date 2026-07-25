#!/usr/bin/env bash
# DP4 match density x diversity sweep - what actually makes software degrade?
#
# Fixed policy (default 8,000 rules) and fixed concurrency; vary two things about
# the INPUT independently:
#   - density   = matches per KB (the founder's point: SW is cheap at ~1/KB, works
#                 at 10-20/KB like real enterprise data, not sparse like DPI).
#   - diversity = how many DISTINCT rules actually get hit (--lit-pool). The real
#                 corpus hits matches across the whole rule set; a naive synthetic
#                 corpus hits only a few, which keeps a software DFA cache-friendly.
# Drives BOTH engines on the SAME policy and same-size small docs. Run on EC2.
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

RULES="${DP4_DENSE_RULES:-8000}"
DENSITIES="${DP4_DENSITIES:-1 6 12}"          # matches/KB; keep <=~15 so docs stay in the small band
LITPOOLS="${DP4_LITPOOLS:-1000 $RULES}"       # diversity: few distinct rules vs the whole set
CONC="${DP4_DENSE_CONC:-256}"
DUR="${DP4_DENSE_DURATION:-15}"
WARM="${DP4_DENSE_WARMUP:-5}"
DOCS="${DP4_DENSE_DOCS:-6000}"
DOCB="${DP4_DENSE_DOCBYTES:-4000}"

echo ">> generating the ${RULES}-rule policy"
GEN_OUT="$(validate generate --config config/workloads/enterprise-dlp.yaml --records 500 --rules "$RULES" 2>&1)"
RUN_DIR="$(printf '%s\n' "$GEN_OUT" | awk -F': +' '/Run directory:/{print $2}')"
POLICY="$RUN_DIR/generated/scale-policy.nol"
[ -f "$POLICY" ] || { echo "policy generation failed:"; printf '%s\n' "$GEN_OUT" | tail -3; exit 1; }

echo ">> deploying the ${RULES}-rule policy to both engines"
validate policy --file "$POLICY" --target themis >/dev/null 2>&1 || { echo "themis deploy failed"; exit 1; }
validate policy --file "$POLICY" --target aergia >/dev/null 2>&1 || { echo "aergia deploy failed"; exit 1; }
echo ">> letting the policy propagate"; sleep 6

export THEMIS_ENDPOINT="$THEMIS_PROCESS_ENDPOINT"
export AERGIA_ENDPOINT="$AERGIA_PROCESS_ENDPOINT"

echo ">> building the load driver"
( cd "$PACK/go" && GOCACHE="$ROOT/$PACK/.gocache" go build -o "$RESULTS/dp4driver" . )

OUT="$RESULTS/density.csv"
rm -f "$OUT"

for POOL in $LITPOOLS; do
  for D in $DENSITIES; do
    echo ">> ===== diversity(lit-pool)=${POOL}  density=${D}/KB  rules=${RULES} ====="
    IN="$RESULTS/dense_p${POOL}_d${D}.jsonl"
    python "$PACK/make-dense-corpus.py" --policy "$POLICY" --matches-per-kb "$D" \
      --lit-pool "$POOL" --doc-bytes "$DOCB" --docs "$DOCS" --out "$IN" | sed 's/^/   /'
    for engine in themis aergia; do
      rm -f "$RESULTS/dn_${engine}.csv"        # never re-append a stale cell
      "$RESULTS/dp4driver" \
        --engine "$engine" --label "$engine" --input "$IN" \
        --concurrency "$CONC" --payloads small \
        --warmup "$WARM" --duration "$DUR" \
        --cap-small "$DOCS" --cap-medium 4000 --cap-large 4000 \
        --output "$RESULTS/dn_${engine}.csv" | sed 's/^/      /'
      if [ ! -s "$RESULTS/dn_${engine}.csv" ] || [ "$(wc -l < "$RESULTS/dn_${engine}.csv")" -lt 2 ]; then
        echo "      !! no data row for $engine (docs may have missed the small band) - skipping"; continue
      fi
      if [ ! -f "$OUT" ]; then echo "lit_pool,matches_per_kb,rules,$(head -1 "$RESULTS/dn_${engine}.csv")" > "$OUT"; fi
      tail -n +2 "$RESULTS/dn_${engine}.csv" | sed "s/^/$POOL,$D,$RULES,/" >> "$OUT"
    done
    echo ">> diversity=${POOL} density=${D} done"
  done
done

echo ">> combined density x diversity CSV: $OUT"
column -s, -t "$OUT" 2>/dev/null || cat "$OUT"
echo ">> done."
