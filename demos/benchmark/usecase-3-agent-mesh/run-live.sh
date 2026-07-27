#!/usr/bin/env bash
# Run the Data Point 3 agent-to-agent mesh benchmark against the real engine(s).
#
# Deploys the same literal mesh policy to Themis (:443) (and Aergia :444 when it is up),
# then runs each mode through the Go harness. The themis_api_mesh / aergia_api_mesh modes
# call the engine directly at every control point of the agent workflow (each handoff, the
# tool call, the final output) and derive the action from the policy sentinels. Runs on
# EC2 (the box that reaches the engines).
#
# Aergia :444 is optional: leave it out of MODES until the networked RE2 baseline is back.
# The in-process RE2 baseline (re2_mesh) always runs and needs no engine.
#
# Scope note: listMatch (literal) only. No regex. All reference lists are literal.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"   # repo root
cd "$ROOT"

source .venv/bin/activate
set -a; source config/demo.env; source .env; set +a
export PATH="$HOME/.local/go/bin:$PATH"

POLICY="${POLICY:-demos/policies/mesh.nol}"
ACTIONS="${ACTIONS:-$ROOT/demos/policies/mesh-actions.json}"
# nocontrol is the payload baseline; themis_api_mesh is the live engine. Default omits
# aergia_api_mesh (its :444 data plane was down); add it once check-engines.sh is green.
MODES="${MODES:-nocontrol themis_api_mesh}"
export ENGINE_TIMEOUT_MS="${ENGINE_TIMEOUT_MS:-15000}"

echo ">> deploying the mesh policy to Themis"
validate policy --file "$POLICY" --target themis >/dev/null
if printf '%s' "$MODES" | grep -q aergia; then
  echo ">> deploying the mesh policy to Aergia"
  validate policy --file "$POLICY" --target aergia >/dev/null
  echo ">> waiting for Aergia reload to propagate"; sleep 6
else
  sleep 3
fi

PACK="demos/benchmark/usecase-3-agent-mesh"
# Overridable so the same runner drives either dataset (functional-test default, or a
# future representative-policy set).
RESULTS="${DP3_RESULTS:-$ROOT/$PACK/results}"
INPUT="${DP3_INPUT:-$ROOT/$PACK/data/tasks/sample_agent_tasks.jsonl}"
POLICYDIR="${DP3_POLICYDIR:-$ROOT/$PACK/data/policies}"
COMBINED="$RESULTS/run_all_combined.csv"
mkdir -p "$RESULTS"
rm -f "$COMBINED"

# The engine modes resolve their endpoint/token from these (data planes, valid certs).
export THEMIS_ENDPOINT="$THEMIS_PROCESS_ENDPOINT"
export AERGIA_ENDPOINT="$AERGIA_PROCESS_ENDPOINT"
# THEMIS_TOKEN / AERGIA_TOKEN come from .env already.

for mode in $MODES; do
  echo ">> mode: $mode"
  ( cd "$ROOT/$PACK/go" && GOCACHE="$ROOT/$PACK/.gocache" \
      go run . --mode "$mode" --input "$INPUT" --actions "$ACTIONS" --output-dir "$RESULTS" ) \
    | sed 's/^/   /'
  if [ ! -f "$COMBINED" ]; then head -n 1 "$RESULTS/run_all.csv" > "$COMBINED"; fi
  tail -n +2 "$RESULTS/run_all.csv" >> "$COMBINED"
done

echo ">> combined CSV: $COMBINED"
column -s, -t "$COMBINED" 2>/dev/null || cat "$COMBINED"

echo ">> adjudicating the engine(s) against the oracle"
ENGINES="$(printf '%s\n' $MODES | grep _api_mesh || true)"
if [ -n "$ENGINES" ]; then
  python "$PACK/verify-oracle.py" --policy "$POLICY" --results "$RESULTS" $ENGINES
else
  echo "   (no engine modes in MODES; skipping oracle adjudication)"
fi
