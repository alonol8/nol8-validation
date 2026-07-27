# Repo Publish Checklist

Use this checklist before sharing the benchmark repo with engineering or publishing it more broadly.

## Benchmark integrity

- `bash scripts/run_all.sh` completes successfully
- `results/run_01.csv` is current
- `report/report_data.json` is current
- `report/report.html` renders successfully
- benchmark environment metadata is present

## Interpretation safety

- measured software modes are clearly labeled as measured
- `nol8sim` is clearly labeled as a behavior placeholder
- no document describes `nol8sim` as measured product performance
- the report caveat banner appears when no real Nol8 result exists
- `safe_for_product_claims` is false unless a measured Nol8 mode is present

## Documentation

- `README.md` explains what the repo proves now
- `README.md` explains what the repo does not prove yet
- `docs/03_benchmark_methodology.md` matches current benchmark behavior
- `docs/07_report_interpretation.md` explains measured versus simulated status
- `docs/08_external_nol8_execution.md` explains how engineering should run real Nol8

## External execution readiness

- `docs/06_nol8_api_mode.md` matches the current API contract
- environment variables for `nol8_api` are documented
- required returned artifacts are documented
- the repo does not require private local knowledge to run

## Narrative consistency

- `listmatch` is positioned as the first-pass enterprise use case
- `re2` is positioned as the incumbent software baseline
- the long-term Nol8 story still includes richer regex and policy behavior
- no doc overstates current evidence

## Handoff readiness

- the dataset and reference lists are included
- the harness instructions are current
- the current-state and planning docs are up to date
- next steps for engineering are explicit
