# Current State

## Purpose

This document captures the current state of **Use Case 2: Pre/Post-Inference Control**.

## What exists now

Planning is in place for:
- the benchmark objective
- the benchmark flow
- the prompt schema
- the deterministic model-stub contract
- the first-pass report fields

Initial prompt-side scaffolding exists in:
- `data/prompts/sample_prompts.jsonl`

Current prompt set:
- `52` prompts
- intentionally split across:
  - benign
  - regex-favoring
  - list-favoring
  - `nol8sim_infer`-favoring
  - mixed-priority
  - near-miss
  - false-positive pressure
  - output control

Initial runnable scaffold exists for:
- deterministic model stub
- `nocontrol` mode
- `re2_guard` mode
- `listguard` mode
- `nol8sim_infer` mode
- engineering-only `nol8_api_infer` overlay mode
- summary CSV output
- per-record JSONL output
- combined benchmark CSV output
- first-pass HTML report generation

## What is not implemented yet

- no AWS harness for Use Case 2
- no hosted report path yet
- no validated real Nol8 endpoint run in this repo yet

## Immediate next task

The next implementation task is:
- validate the engineering-only `nol8_api_infer` overlay against a real endpoint
- optionally add new datasets that stress:
  - mixed policy priority cases

Recently added dataset expansion:
- a small false-positive-pressure slice with customer-explainable near-match wording
- a small output-control slice showing why post-inference blocking and tagging still matter after prompt-side allow decisions
- an expanded mixed-priority slice showing explainable precedence rules such as block over route and route over tag or mask

The report now already includes:
- contract-alignment by mode
- benchmark-group breakdowns
- explicit near-miss precision
- governance-risk framing for missed versus over-governed prompts
- token-reduction efficiency per avoided inference

Dataset rule now in force:
- every benchmark row must be clearly explainable to customers, prospects, and internal stakeholders through a plain-English `intent_note`
- implementation-only edge cases should stay out of the main benchmark set unless they can be explained as a recognizable governance scenario

## Validated so far

- `nocontrol` runs end to end
- `re2_guard` runs end to end
- `listguard` runs end to end
- `nol8sim_infer` runs end to end
- `nol8_api_infer` code path now exists for engineering-only overlay use
- `scripts/run_all.sh` runs all four modes and generates:
  - `results/run_all.csv`
  - `report/report_data.json`
  - `report/report.html`
- the report now includes:
  - prompt-set composition
  - explicit mode-contrast framing
  - contract-alignment metrics against `expected_pre_action`
  - expected-action coverage by action type
  - dedicated mixed-priority precedence visibility
  - benchmark-group breakdowns showing where each mode matches or misses the prompt contract
  - dedicated false-positive-pressure visibility
  - dedicated output-control visibility
  - explicit near-miss precision visibility
  - governance-risk metrics for missed governed prompts versus false positives
  - token-reduction efficiency per avoided inference
  - measured-vs-simulated caveat handling
- the newest dataset slices now show:
  - `re2_guard` over-governs `1` of `4` false-positive-pressure rows
  - `listguard` over-governs all `4` false-positive-pressure rows in this dataset slice
  - all three guarded modes exercise output-side block/tag behavior on the new output-control rows
  - the expanded mixed-priority slice now contains `10` explainable precedence rows
  - `listguard` matches `9` of `10` mixed-priority rows in the current dataset
  - `re2_guard` matches `4` of `10` mixed-priority rows because it still lacks the stronger route/block precedence behavior captured in the contract
- the expanded prompt set now creates real divergence across guarded modes:
  - `re2_guard` is strongest on broad pattern matching
  - `listguard` is stronger on known-value and known-phrase controls
  - `nol8sim_infer` is broader because it follows target contract behavior
- `re2_guard` currently performs:
  - prompt-side regex masking for payment cards and account IDs
  - prompt-side blocking for explicit safeguard-bypass language
  - prompt-side routing for exact approval / denied-entity / flagged-customer phrases
  - prompt-side tagging for internal-only project references
  - output-side blocking for blocked-output phrases
  - output-side tagging for privileged-context phrases
- `listguard` currently performs:
  - prompt-side exact/list-based masking for known payment cards and account IDs
  - prompt-side exact/list-based routing for known customers, denied entities, and approval phrases
  - prompt-side exact/list-based blocking for disallowed request phrases
  - prompt-side exact/list-based tagging for internal project names
  - output-side exact/list-based blocking/tagging driven by reference-list phrases
- `nol8sim_infer` currently performs:
  - prompt-side actions from the benchmark contract (`expected_pre_action` and expected tags)
  - post-inference actions from deterministic model-stub output profiles
  - behavior-placeholder semantics only, not measured product execution
- `nol8_api_infer` currently provides:
  - environment-driven endpoint and auth configuration
  - request/response contract for a future real Nol8 `/infer-control` endpoint
  - measured-mode report compatibility once real API responses are available
  - no validated live endpoint execution yet

## Next session read order

1. `docs/planning/00_current_state.md`
2. `docs/planning/01_use_case_2_design.md`
3. `docs/planning/02_use_case_2_contract.md`
4. `docs/planning/03_nol8_api_overlay.md`
5. `data/prompts/sample_prompts.jsonl`
