# Prompt Data

This folder holds prompt-side benchmark inputs for **Use Case 2: Pre/Post-Inference Control**.

First-pass file:
- `sample_prompts.jsonl`

Current prompt-set intent:
- create meaningful divergence between `re2_guard`, `listguard`, and `nol8sim_infer`
- preserve near-miss rows so the benchmark tests precision, not just aggressive filtering
- include:
  - benign prompts
  - regex-favoring prompts
  - list-favoring prompts
  - target-semantics prompts for `nol8sim_infer`
  - mixed-content priority tests
  - precedence tests where one explainable control should outrank another
  - near-miss controls
  - false-positive-pressure prompts
  - output-control prompts

Required fields:
- `prompt_id`
- `category`
- `prompt_text`
- `expected_pre_action`
- `model_stub_profile`
- `intent_note`

Optional fields:
- `expected_pre_tags`
- `benchmark_group`

Paired contract:
- `docs/planning/02_use_case_2_contract.md`

## Explainability rule

Every prompt in this folder must be understandable to external and internal audiences.

That means each row should be explainable in plain English:
- what the row is trying to prove
- why the expected action is reasonable
- why the result matters in a real customer or governance workflow

Use `intent_note` for that explanation.

Good benchmark rows are:
- easy to describe in a sales or engineering walkthrough
- tied to a recognizable control problem
- free of repo-only or code-path-only rationale

If a row exists only because it is convenient for implementation, it does not belong in the benchmark set as written.
