#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACK_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GO_DIR="${PACK_ROOT}/go"
RESULTS_DIR="${PACK_ROOT}/results"
REPORT_DIR="${PACK_ROOT}/report"
INPUT_PATH="${PACK_ROOT}/data/prompts/sample_prompts.jsonl"
LIST_DIR="${PACK_ROOT}/data/reference_lists"
COMBINED_CSV="${RESULTS_DIR}/run_all.csv"

MODES=(
  "nocontrol"
  "re2_guard"
  "listguard"
  "nol8sim_infer"
)

mkdir -p "${RESULTS_DIR}" "${REPORT_DIR}"
rm -f "${COMBINED_CSV}"

for mode in "${MODES[@]}"; do
  echo "Running mode: ${mode}"
  cd "${GO_DIR}"
  if [[ "${mode}" == "listguard" ]]; then
    GOCACHE="${PACK_ROOT}/.gocache" go run . \
      --mode "${mode}" \
      --input "${INPUT_PATH}" \
      --list-dir "${LIST_DIR}" \
      --output-dir "${RESULTS_DIR}"
  else
    GOCACHE="${PACK_ROOT}/.gocache" go run . \
      --mode "${mode}" \
      --input "${INPUT_PATH}" \
      --output-dir "${RESULTS_DIR}"
  fi

  if [[ ! -f "${COMBINED_CSV}" ]]; then
    cp "${RESULTS_DIR}/run_01.csv" "${COMBINED_CSV}"
  else
    tail -n +2 "${RESULTS_DIR}/run_01.csv" >> "${COMBINED_CSV}"
  fi
done

cd "${PACK_ROOT}"
python3 report/generate_report.py \
  --results-csv "${COMBINED_CSV}" \
  --report-dir "${REPORT_DIR}" \
  --input-path "${INPUT_PATH}"

echo "Combined CSV: ${COMBINED_CSV}"
echo "Report HTML: ${REPORT_DIR}/report.html"
echo "Report JSON: ${REPORT_DIR}/report_data.json"
