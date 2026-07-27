#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACK_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GO_DIR="${PACK_ROOT}/go"
RESULTS_DIR="${PACK_ROOT}/results"
INPUT_PATH="${PACK_ROOT}/data/prompts/sample_prompts.jsonl"

if [[ -z "${NOL8_API_URL:-}" ]]; then
  echo "NOL8_API_URL is required for nol8_api_infer mode." >&2
  exit 1
fi

mkdir -p "${RESULTS_DIR}"

cd "${GO_DIR}"
GOCACHE="${PACK_ROOT}/.gocache" go run . \
  --mode nol8_api_infer \
  --input "${INPUT_PATH}" \
  --output-dir "${RESULTS_DIR}"
