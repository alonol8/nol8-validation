# File-By-File Action Map

## Report generation and rendering

### `report/generate_report.py`

Responsibility:
- orchestrate report generation from structured data

Should contain:
- loading of CSV, resource metrics, metadata
- construction of `report_data.json`
- optional loading of `ai_summary.json`
- rendering inputs for the HTML template

### `report/report_template.html`

Responsibility:
- present benchmark results clearly to humans

Should contain:
- environment section
- how-to-read section
- simulated-vs-measured caveat banner
- optional AI summary section
- deterministic summary cards
- derived metrics
- resource efficiency
- raw output
- metric definitions

### `report/report_data.json`

Responsibility:
- machine-readable source of truth for report interpretation

Should contain:
- benchmark metadata
- dataset metadata
- mode metadata
- raw results
- resource metrics
- derived metrics
- interpretation flags

## AI summary layer

### `report/summary_prompt.txt`

Responsibility:
- define exactly how an AI summary should be generated

### `report/summary_schema.json`

Responsibility:
- constrain AI summary output

### `report/generate_ai_summary.py`

Responsibility:
- optional AI-summary generation step

### `report/ai_summary.json`

Responsibility:
- store the AI-generated summary separately from deterministic report data

## Execution flow

### `scripts/run_all.sh`

Responsibility:
- benchmark execution orchestration

Should continue to:
- build benchmark binary once
- run each mode independently
- generate CSV
- generate resource metrics
- generate report

Should eventually also:
- ensure `report_data.json` is produced as part of the standard run
- optionally trigger AI summary generation if configured

### `python/collect_resource_metrics.py`

Responsibility:
- extract raw resource metrics from `/usr/bin/time -v` output

## Documentation

### `README.md`

Responsibility:
- explain package purpose and benchmark scope

Should explicitly cover:
- current first-pass use case is `listmatch`
- `re2` is a software baseline
- `nol8sim` is illustrative behavior, not measured production performance
- real Nol8 execution is expected later via the same suite

### `docs/03_benchmark_methodology.md`

Responsibility:
- define the measurement contract

### `docs/07_report_interpretation.md`

Responsibility:
- teach a reader how to interpret the artifact without talking to the project author

### `docs/08_external_nol8_execution.md`

Responsibility:
- define how the engineering team plugs in real Nol8

## Harness

### `aws_benchmark_harness/main.tf`

Responsibility:
- shared AWS deployment and execution wrapper for all benchmark packs

Should continue to:
- generate benchmark metadata
- copy benchmark pack
- run standard benchmark flow

Should not take on:
- report interpretation logic
- AI summary logic
- mode semantics

### `aws_benchmark_harness/README.md`

Responsibility:
- explain shared harness usage

Should mention:
- the benchmark pack produces structured report data
- the HTML report may include deterministic and AI-interpreted sections later
- measured vs simulated distinctions come from the pack, not the harness

## Recommended execution order

1. `report_data.json`
2. simulated/measured mode metadata
3. caveat banner in HTML
4. interpretation docs
5. AI summary prompt/schema
6. optional AI summary generation
