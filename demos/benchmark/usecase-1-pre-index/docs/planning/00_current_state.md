# Current State

## Purpose

This document is the quickest way to re-establish project state after time away from the repo.

It distinguishes between:
- what is already implemented in the benchmark pack
- what exists only as planning scaffolding
- what the immediate next task should be

## What is implemented now

### Benchmark modes

The benchmark pack currently supports these runnable modes:
- `nofilter`
- `re2`
- `listmatch`
- `nol8sim`

`nol8_api` is wired into the Go benchmark client, but it is not currently the main runnable path for benchmark results because real Nol8 access is not available yet.

### Data Point 1 benchmark story

The current first-pass enterprise benchmark story is:
- `listmatch` is the first practical use case
- `re2` is the incumbent software baseline
- `nol8sim` is a behavior placeholder, not a measured product result

The active dataset and report are designed to support that framing.

### Dataset and lists

Implemented:
- list-heavy enterprise-style sample dataset
- richer watchlists and indicators under `data/reference_lists/`
- dataset generator oriented toward the `listmatch` story

### Reporting

Implemented:
- improved HTML report
- benchmark environment block near the top
- clearer CPU/resource explanations
- reading guide in the report
- listmatch-first summary framing
- structured `report/report_data.json` as the report source of truth
- explicit measured-vs-simulated mode metadata
- interpretation flags and automatic caveat banner

### External handoff

Implemented:
- external Nol8 execution guide in `docs/08_external_nol8_execution.md`
- repo publish/readiness checklist in `docs/09_repo_publish_checklist.md`
- README and report wording that point readers toward a real `nol8_api` run when no measured Nol8 result exists

### Harness

Implemented:
- Terraform harness provisions the instance
- benchmark pack is copied and run remotely
- report server startup is verified
- benchmark metadata is written for report rendering

## What exists as planning only

The following work has been planned and written into `docs/planning/`, but is not yet implemented:

- real Nol8 measured-mode integration plan
- cross-data-point benchmark/report framework for Data Points 2 and 3

Milestone 3 scaffolding is now implemented:
- `report/summary_prompt.txt`
- `report/summary_schema.json`
- optional `ai_summary.json` rendering support in the HTML report
- AI summary guidelines in `docs/10_ai_summary_guidelines.md`

What is still not implemented for Milestone 3:
- actual AI-summary generation
- schema validation tooling for generated summaries

## Immediate next task

The recommended next implementation task is:

### Scope boundary

Use Case 1 remains isolated in this pack.

Use Case 2 planning and future implementation now live in the sibling folder:
- `../usecase-2-inference_pre_post_inference_pack_v1/`

## Recommended reading order for the next session

To get up to speed quickly next time, read these files in order:

1. `docs/planning/00_current_state.md`
2. `docs/planning/01_internal_planning_memo.md`
3. `docs/planning/03_milestones.md`
4. `docs/planning/04_implementation_checklist.md`
5. `docs/planning/05_file_by_file_action_map.md`

Then inspect the implemented benchmark/report files:

6. `report/report_template.html`
7. `report/generate_report.py`
8. `scripts/run_all.sh`
10. `go/benchmark.go`
11. `go/listmatch.go`
12. `data/generate_dataset.py`

## Practical reminder

If the next session starts with implementation work, the first question to answer should be:

"Are we working on Use Case 1 in this pack, or should we switch to the Use Case 2 pack?"

That will prevent mixing planning-only work with code changes again.
