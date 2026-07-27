#!/usr/bin/env bash
# Run the usecase-1-pre-index benchmark against BOTH real engines, listMatch only.
#
# Deploys the same literal starter policy to Themis (:443) and Aergia (:444),
# starts one adapter per engine, runs the Go harness so `themis_api` and
# `aergia_api` are separate columns, then builds ONE combined report and cleans
# up. Both engines run identical listMatch rules, so the comparison is
# performance/behavior (Themis FPGA vs Aergia), alongside the local `nofilter`
# and `listmatch` software baselines. Runs on EC2 (the box that reaches Themis).
#
# Scope note: listMatch (literal) only. No regex. (Aergia can't do regex yet.)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # repo root
cd "$ROOT"

source .venv/bin/activate
set -a; source config/demo.env; source .env; set +a
export PATH="$HOME/.local/go/bin:$PATH"

POLICY="${POLICY:-demos/policies/starter-known-values.nol}"
MODES="${MODES:-nofilter listmatch themis_api aergia_api}"
export NOL8_TIMEOUT_MS="${NOL8_TIMEOUT_MS:-10000}"

echo ">> deploying the same starter policy to both engines"
validate policy --file "$POLICY" --target themis >/dev/null
validate policy --file "$POLICY" --target aergia >/dev/null
echo ">> waiting for Aergia reload to propagate"
sleep 6

start_adapter() {  # name port process_endpoint process_token
  PROCESS_ENDPOINT="$3" PROCESS_TOKEN="$4" ADAPTER_PORT="$2" \
    python demos/themis-adapter/adapter.py >"/tmp/adapter-$1.log" 2>&1 &
  echo "$!"
}

THEMIS_PID="$(start_adapter themis 8799 "$THEMIS_PROCESS_ENDPOINT" "$THEMIS_TOKEN")"
AERGIA_PID="$(start_adapter aergia 8800 "$AERGIA_PROCESS_ENDPOINT" "$AERGIA_TOKEN")"
trap 'kill "$THEMIS_PID" "$AERGIA_PID" 2>/dev/null || true' EXIT

wait_ready() {  # port
  for _ in $(seq 1 30); do
    if curl -sS -o /dev/null --max-time 5 -X POST "http://127.0.0.1:$1/" \
         -d '{"text":"ping"}' 2>/dev/null; then return 0; fi
    sleep 0.3
  done
  echo "!! adapter on :$1 did not become ready" >&2; return 1
}
wait_ready 8799
wait_ready 8800
echo ">> adapters ready: themis=8799 aergia=8800"

cd demos/benchmark/usecase-1-pre-index
export THEMIS_ENDPOINT="http://127.0.0.1:8799"
export AERGIA_ENDPOINT="http://127.0.0.1:8800"
export MODES
echo ">> MODES=$MODES"
bash scripts/run_all.sh
