#!/usr/bin/env bash
# Bring-Your-Own-Data POC runner. Sources the venv + engine endpoints, ensures
# the load driver is built, then runs the pipeline on a customer input dir.
#
#   bash demos/showcase/byo-poc/run-byo-poc.sh [BYO_DIR] [--skip-load] [--concurrency N] ...
#
# BYO_DIR defaults to the bundled sample. For a real customer, point it at a dir
# containing values/ (one <category>.txt per governed-value list) and documents/.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
set -a; source config/demo.env 2>/dev/null; source .env 2>/dev/null; set +a
export PATH="$HOME/.local/go/bin:$PATH"
ulimit -n 65536 2>/dev/null || true

# The correctness call + load driver both want the /v1/process URL per engine.
export THEMIS_ENDPOINT="${THEMIS_PROCESS_ENDPOINT:-${THEMIS_ENDPOINT:-}}"
export AERGIA_ENDPOINT="${AERGIA_PROCESS_ENDPOINT:-${AERGIA_ENDPOINT:-}}"

DRV="demos/benchmark/datapoint4/results/dp4driver"
if [ ! -x "$DRV" ]; then
  echo ">> building load driver"
  ( cd demos/benchmark/datapoint4/go && GOCACHE="$ROOT/demos/benchmark/datapoint4/.gocache" go build -o "$ROOT/$DRV" . )
fi

BYO_DIR="${1:-demos/showcase/byo-poc/sample}"
if [ "$#" -gt 0 ] && [[ "$1" != --* ]]; then shift; fi
python demos/showcase/byo-poc/byo_poc.py --byo-dir "$BYO_DIR" "$@"
