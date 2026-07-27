# AI Summary Guidelines

## Purpose

This document defines how an optional AI-generated summary may be used in the benchmark report.

The AI summary is an interpretation layer on top of the deterministic benchmark artifact.

It is **not** the source of truth.

The source of truth remains:
- `report/report_data.json`
- `report/report.html`
- the benchmark CSV and resource metrics that feed them

## What the AI summary may do

The AI summary may:
- restate measured benchmark outcomes in plain language
- highlight the most important deltas and governance outcomes
- summarize the current benchmark state for leadership or engineering readers
- call out caveats that already exist in the report data

## What the AI summary may not do

The AI summary may not:
- invent numbers
- use outside knowledge
- claim measured Nol8 performance when only `nol8sim` is present
- blur simulated behavior and measured behavior
- replace the deterministic tables

## Required grounding

The AI summary must be generated only from:
- `report/report_data.json`

It must not depend on:
- the rendered HTML
- undocumented assumptions
- external model knowledge about Nol8

## Required caveat behavior

If:
- `contains_simulated_modes = true`
- and `contains_real_nol8_results = false`

then the AI summary must explicitly say that real Nol8 production efficiency is not measured in the report.

## Expected shape

The AI summary contract is defined by:
- `report/summary_prompt.txt`
- `report/summary_schema.json`

Expected fields:
- `headline`
- `executive_summary`
- `key_findings`
- `caveats`
- `mode_notes`

## Rendering behavior

The report should:
- render the AI summary only if `report/ai_summary.json` exists
- keep the deterministic report visible regardless
- present the AI summary as optional interpretation, not authoritative output

## Why this exists

Milestone 3 adds the AI summary layer because:
- the benchmark now has a structured report contract
- the repo is ready for external readers
- leadership and engineering may benefit from a concise interpretation layer

The AI summary is intentionally optional until the benchmark suite needs it.
