# Report

This folder contains Use Case 2 reporting artifacts.

Planned/generated files:
- `report_template.html`
- `generate_report.py`
- `report_data.json`
- `report.html`

The first-pass report is built from the combined benchmark CSV produced by:
- `scripts/run_all.sh`

The report now emphasizes mode divergence with:
- a top-line takeaway section that summarizes the benchmark result immediately
- contract-alignment metrics against the prompt-side expected action
- expected-action coverage by action type
- dedicated mixed-priority precedence visibility
- benchmark-group breakdown tables
- dedicated false-positive-pressure and output-control sections
- explicit near-miss precision visibility
- governance-risk metrics for missed governed prompts versus false positives
- token-reduction efficiency per avoided inference
- measured-vs-simulated caveat framing for `nol8sim_infer`
