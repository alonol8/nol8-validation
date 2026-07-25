#!/usr/bin/env bash
# Showcase: live deterministic redaction through the Argus Data API (/v1/process).
#
# SA-runnable, on the box that reaches the engines (EC2 `nol8-demo`). Deploys the
# known-governed-values policy to one engine, sends a single realistic message,
# and prints BEFORE / AFTER / ORACLE. The oracle is derived from the policy file,
# so a green result means the engine's output provably matches the policy.
#
#   bash demos/showcase/redact-demo.sh                 # default: Themis (FPGA, :443)
#   ENGINE=aergia bash demos/showcase/redact-demo.sh   # RE2 software (:444)
#   MSG_FILE=/path/to/your.txt bash demos/showcase/redact-demo.sh
#
# Scope: listMatch (literal) replacement only. No regex, no routing/blocking here.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
set -a; source config/demo.env; source .env; set +a

PACK="demos/showcase"
ENGINE="${ENGINE:-themis}"
POLICY="${POLICY:-demos/policies/starter-known-values.nol}"
MSG_FILE="${MSG_FILE:-$PACK/sample-message.txt}"

case "$ENGINE" in
  themis) EP="$THEMIS_PROCESS_ENDPOINT"; TOK="${THEMIS_TOKEN:-}"; LABEL="Themis (FPGA)";;
  aergia) EP="$AERGIA_PROCESS_ENDPOINT"; TOK="${AERGIA_TOKEN:-}"; LABEL="Aergia (RE2 software)";;
  *) echo "ENGINE must be 'themis' or 'aergia' (got '$ENGINE')" >&2; exit 2;;
esac

echo ">> deploying known-values policy to ${ENGINE} (${LABEL})"
echo "   policy: ${POLICY}  ($(grep -c -- '->' "$POLICY") literal rules)"
validate policy --file "$POLICY" --target "$ENGINE" >/dev/null
echo ">> letting the policy propagate"; sleep 6

python "$PACK/redact-demo.py" \
  --endpoint "$EP" --token "$TOK" \
  --policy "$POLICY" --message "$MSG_FILE" \
  --engine-label "$LABEL"
