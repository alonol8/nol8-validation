# Nol8 API Overlay

## Purpose

This document defines the engineering-only overlay for running Use Case 2 against a real Nol8 API when it becomes available.

This overlay is intentionally separate from the customer-facing deterministic benchmark path.

## Current mode

The Go runner now supports:
- `nol8_api_infer`

This mode is intended for engineering use only until the real Nol8 endpoint contract is validated.

## Environment variables

Required:
- `NOL8_API_URL`

Optional:
- `NOL8_API_KEY`
- `NOL8_API_TIMEOUT_MS`
- `NOL8_API_MODE_LABEL`

Defaults:
- `NOL8_API_TIMEOUT_MS = 30000`
- `NOL8_API_MODE_LABEL = nol8_api_infer`

## Expected request shape

`POST {NOL8_API_URL}/infer-control`

Request body:

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

## Expected response shape

```json
{
  "pre_action": "mask",
  "pre_tags": [],
  "prompt_processed": "Summarize the account note for card [MASKED_CARD].",
  "inference_called": true,
  "raw_model_output": "Model response text",
  "post_action": "allow",
  "post_tags": [],
  "final_output": "Model response text"
}
```

Allowed actions:
- `allow`
- `mask`
- `block`
- `route`
- `tag`

Notes:
- if `inference_called` is omitted, the runner assumes `false` for `block` or `route`, otherwise `true`
- if `prompt_processed` is omitted, the runner falls back to the original prompt
- if `post_action` is omitted, the runner falls back to `allow`
- if `final_output` is omitted and `post_action = allow`, the runner falls back to `raw_model_output`
- if `final_output` is omitted and `post_action = block`, the runner falls back to `[BLOCKED_OUTPUT]`

## Expected engineering workflow

Run:

```bash
export NOL8_API_URL="https://example.internal"
export NOL8_API_KEY="..."
bash scripts/run_nol8_api_infer.sh
```

This writes:
- `results/nol8_api_infer_output.jsonl`
- `results/run_01.csv`

To include real Nol8 results in the HTML report, combine the resulting CSV row with the other benchmark rows and regenerate the report.

## Why this is an overlay

This mode exists so engineering can validate:
- real endpoint behavior
- auth and timeout handling
- measured versus simulated reporting
- report compatibility with live Nol8 decisions

It is not yet part of the default benchmark runner because:
- the endpoint is not available in this repo session
- the production contract is still expected to evolve
