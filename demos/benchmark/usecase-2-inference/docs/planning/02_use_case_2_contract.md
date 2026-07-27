# Use Case 2 — Implementation Contract

## Purpose

This document converts the Use Case 2 concept into an implementation-ready contract.

It should answer:
- what the input records look like
- what the model stub should return
- how pre/post actions are computed
- what rows and metrics the report must carry

This is the document to use before writing code.

## Benchmark flow contract

```text
Prompt Record
  -> pre-inference control
  -> model stub (only if not blocked/routed before inference)
  -> post-inference control
  -> final benchmark output row
```

## Prompt record schema

First-pass input file format:
- JSONL

Suggested file:
- `data/prompts/sample_prompts.jsonl`

Each record should contain:

```json
{
  "prompt_id": "prompt_0001",
  "category": "payment_card_prompt",
  "prompt_text": "Summarize the account note for card 4111 1111 1111 1111.",
  "expected_pre_action": "mask",
  "expected_pre_tags": [],
  "model_stub_profile": "returns_maskable_output",
  "intent_note": "This row is easy to explain: a payment card should be masked before reaching the model."
}
```

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

## Explainability requirement

Every prompt row must be explainable in plain language to:
- customers and prospects
- internal product and engineering teams
- non-specialist stakeholders reviewing the benchmark

This is a benchmark-design constraint, not just a documentation preference.

Each row must therefore include an `intent_note` that:
- explains why the row exists
- explains why the expected action is reasonable
- uses stakeholder-readable language rather than implementation jargon
- can be read aloud in a demo or benchmark review without extra decoding

Rows should avoid explanations like:
- "tests branch coverage"
- "exercises regex path 3"
- "covers edge case for internal implementation detail"

Rows should prefer explanations like:
- "unknown payment card format should still be masked before inference"
- "known flagged customer should route to a controlled workflow"
- "similar-looking benign text should remain allowed to show precision"

If a test cannot be explained clearly in one or two sentences, it should not be added to the customer-facing benchmark set without revision.

## Allowed prompt categories

- `benign_prompt`
- `payment_card_prompt`
- `account_id_prompt`
- `flagged_customer_prompt`
- `denied_entity_prompt`
- `internal_only_prompt`
- `approval_required_prompt`
- `near_miss_prompt`

## Allowed pre-inference actions

- `allow`
- `mask`
- `block`
- `route`
- `tag`

## First-pass fixed decisions

- denied-entity output is tagged, not blocked
- prompt-side `tag` counts separately and contributes to governed share
- `route` counts as an avoided inference call in the first pass
- first prompt input path is `data/prompts/sample_prompts.jsonl`

## Recommended next coding step

Implement in this order:
1. deterministic model stub
2. `nocontrol` end to end
3. `re2_guard`
4. `listguard`
5. `nol8sim_infer`
