#!/usr/bin/env bash
# Showcase: one engine, one capability, at all three control points.
#
# NOL8 does the SAME deterministic literal redaction through /v1/process; what
# changes per use case is only WHERE it sits in the pipeline. This runs the three
# use cases back-to-back against a live engine, oracle-verifying each:
#
#   1. Pre-embedding      — redact before text enters a vector index   (depth: DP1)
#   2. Pre/post-inference — redact before/after the model boundary      (depth: DP2)
#   3. Agent-to-agent     — redact at every hop of an agent workflow    (depth: DP3)
#
# SA-runnable on the box that reaches the engines (EC2 `nol8-demo`).
#
#   bash demos/showcase/usecases-demo.sh                 # Themis (FPGA, :443)
#   ENGINE=aergia bash demos/showcase/usecases-demo.sh   # RE2 software (:444)
#
# Scope: listMatch (literal) replacement only — substitution, not enforcement.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
set -a; source config/demo.env; source .env; set +a

PACK="demos/showcase"
ENGINE="${ENGINE:-themis}"
POLICY="${POLICY:-demos/policies/starter-known-values.nol}"

case "$ENGINE" in
  themis) EP="$THEMIS_PROCESS_ENDPOINT"; TOK="${THEMIS_TOKEN:-}"; LABEL="Themis (FPGA)";;
  aergia) EP="$AERGIA_PROCESS_ENDPOINT"; TOK="${AERGIA_TOKEN:-}"; LABEL="Aergia (RE2 software)";;
  *) echo "ENGINE must be 'themis' or 'aergia' (got '$ENGINE')" >&2; exit 2;;
esac

# Parallel arrays: scenario file | use-case title | control point | depth datapoint
FILES=("$PACK/scenarios/01-pre-embedding.txt"
       "$PACK/scenarios/02-pre-post-inference.txt"
       "$PACK/scenarios/03-agent-to-agent.txt")
TITLES=("USE CASE 1 — PRE-EMBEDDING (RAG ingestion)"
        "USE CASE 2 — PRE / POST INFERENCE (model boundary)"
        "USE CASE 3 — AGENT-TO-AGENT (mesh hop)")
POINTS=("Redact BEFORE the text is chunked and embedded — sensitive values never enter the vector store."
        "Redact BEFORE the prompt reaches the model — the LLM, its provider, and its logs never see them."
        "Redact AT THE HOP between agents — the receiving agent acts only on cleaned data.")
DEPTH=("Benchmark-depth proof: DP1 (Pre-Index Optimization)"
       "Benchmark-depth proof: DP2 (pre/post-inference control)"
       "Benchmark-depth proof: DP3 (agent-to-agent mesh control)")

echo ">> deploying known-values policy to ${ENGINE} (${LABEL}) — $(grep -c -- '->' "$POLICY") literal rules"
validate policy --file "$POLICY" --target "$ENGINE" >/dev/null
echo ">> letting the policy propagate"; sleep 6

PASS=0
for i in 0 1 2; do
  echo
  echo "══════════════════════════════════════════════════════════════════════"
  echo "  ${TITLES[$i]}"
  echo "  Control point: ${POINTS[$i]}"
  echo "  ${DEPTH[$i]}"
  echo "══════════════════════════════════════════════════════════════════════"
  if python "$PACK/redact-demo.py" \
       --endpoint "$EP" --token "$TOK" \
       --policy "$POLICY" --message "${FILES[$i]}" \
       --engine-label "$LABEL"; then
    PASS=$((PASS+1))
  fi
done

echo
echo "══════════════════════════════════════════════════════════════════════"
echo "  TOUR COMPLETE — ${PASS}/3 use cases redacted and oracle-verified on ${LABEL}"
echo "  Same engine, same /v1/process call, three control points. Next: the CPU"
echo "  cost that separates the FPGA from software → demos/showcase/efficiency-demo.sh"
echo "══════════════════════════════════════════════════════════════════════"
[ "$PASS" -eq 3 ] || exit 1
