#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "$ROOT/python/mock_nol8_server.py" >/tmp/mock_nol8_server.log 2>&1 &
MOCK_PID=$!
trap 'kill $MOCK_PID >/dev/null 2>&1 || true' EXIT

sleep 1

export NOL8_ENDPOINT="http://127.0.0.1:8787/process"
export MODES="nofilter re2 nol8_api"

bash "$ROOT/scripts/run_all.sh"
