# Milestones

## Milestone 1: Honest deterministic report

Goal:
Make the report contract honest, structured, and unambiguous before anything else.

Core outputs:
- `report_data.json` generated on every run
- explicit mode metadata for measured vs simulated
- interpretation flags in structured output
- report caveat banner when simulated modes are present
- updated docs explaining what claims are and are not supported

## Milestone 2: GitHub-ready external execution

Goal:
Make the repo clean enough to hand to the engineering team so they can run the same benchmark against a real Nol8 implementation and return comparable results.

Core outputs:
- external execution instructions
- explicit instructions for plugging in real Nol8
- required output contract for returned results
- clear report labeling for real Nol8 vs baseline modes

## Milestone 3: Optional AI summary layer

Goal:
Add an optional AI-generated interpretation layer on top of the deterministic benchmark artifact without weakening factual rigor.

Core outputs:
- `summary_prompt.txt`
- `summary_schema.json`
- optional `ai_summary.json`
- report support for rendering AI summary if present
- strong factual guardrails

## Milestone 4: Real Nol8 integration path

Goal:
Prepare the benchmark suite for the day real Nol8 measurements are available, so the report can transition from behavioral placeholders to measured product comparisons without a redesign.

Core outputs:
- measured product mode labeling
- real Nol8 comparison rules
- real execution contract
- claims policy
- result ingestion rules

## Milestone 5: Cross-data-point / agentic-mesh extension

Goal:
Extend the reporting and interpretation framework so it becomes the common benchmark layer for:
- Data Point 1: pre-index optimization
- Data Point 2: pre/post-inference control
- Data Point 3: agentic mesh / retrieval-loop control

Core outputs:
- reusable schema
- reusable control outcome vocabulary
- reusable AI summary layer
- shared benchmark vocabulary

## Recommended order

1. Milestone 1
2. Milestone 2
3. Milestone 3
4. Milestone 4
5. Milestone 5

## Why this order

This sequence keeps the repo honest first, publishable second, interpretable third, product-comparative later, and framework-ready after that.
