#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACK_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PACK_ROOT}/go"
GOCACHE="${PACK_ROOT}/.gocache" go run . \
  --mode nocontrol \
  --input ../data/prompts/sample_prompts.jsonl \
  --output-dir ../results
