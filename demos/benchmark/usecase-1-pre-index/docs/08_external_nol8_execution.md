# External Nol8 Execution

## Purpose

This document explains how another engineering team should run this benchmark pack against a real Nol8 implementation.

The goal is simple:
- keep the same workload
- keep the same control semantics
- keep the same output artifact shape
- replace the local behavior placeholder with a real Nol8-backed run

This lets the benchmark move from:
- measured software baselines plus a behavior placeholder

to:
- measured software baselines plus measured Nol8 results

## What this repo proves today

Today, this repo provides:
- a runnable benchmark workload for Data Point 1
- measured software baselines for `re2` and `listmatch`
- a simulated `nol8sim` mode used only to represent Nol8-style control semantics
- an API-wired `nol8_api` mode that can call a real Nol8-compatible endpoint

It does **not** yet provide measured production Nol8 efficiency.

## Modes and how to interpret them

### `nofilter`

Measured baseline.

Use:
- establish the do-nothing reference point

### `re2`

Measured software baseline.

Use:
- represent incumbent software pattern-matching behavior

### `listmatch`

Measured software baseline.

Use:
- represent first-pass enterprise reference-list control behavior

### `nol8sim`

Behavior placeholder only.

Use:
- validate target action semantics
- demonstrate keep / mask / drop / route logic

Do not use it to claim:
- real Nol8 throughput
- real Nol8 CPU efficiency
- real product advantage

### `nol8_api`

External Nol8 execution path.

Use:
- run the same benchmark against a real Nol8-compatible endpoint
- return measured results in the same artifact format

## Required execution contract

The engineering team should preserve:
- the same dataset
- the same mode semantics for baseline modes
- the same action vocabulary
- the same benchmark output columns
- the same report structure

Action vocabulary for the current benchmark:
- `keep`
- `mask`
- `drop`
- `route`

Semantics:
- `keep`: forward original text
- `mask`: forward modified text
- `drop`: do not forward the chunk
- `route`: treat the chunk as diverted away from embedding in this benchmark

## Nol8 API contract

The benchmark expects this request shape:

```json
{
  "text": "chunk text"
}
```

The benchmark expects this response shape:

```json
{
  "action": "keep | mask | drop | route",
  "text": "processed text"
}
```

Notes:
- `text` may be empty when `action=drop`
- `route` is treated as not forwarded to embedding for Data Point 1
- extra response metadata is optional, but the benchmark currently relies on `action` and `text`

## Environment variables for a real Nol8 run

Required:
- `NOL8_ENDPOINT`

Optional:
- `NOL8_API_KEY`
- `NOL8_TIMEOUT_MS`

Example:

```bash
export NOL8_ENDPOINT="https://nol8.example/process"
export NOL8_API_KEY="replace-me"
export NOL8_TIMEOUT_MS=2000
export MODES="nofilter re2 listmatch nol8_api"
bash scripts/run_all.sh
```

## Expected returned artifacts

At minimum, a real Nol8 execution should return:
- `results/run_01.csv`
- `results/resource_metrics.json`
- `benchmark_run_metadata.json`
- `report/report_data.json`
- `report/report.html`

Optional but useful:
- action trace output for debugging or semantic validation
- endpoint-specific metadata captured separately from the main report

## Artifact expectations

### `results/run_01.csv`

Must preserve the benchmark columns used by the current report generator.

That includes:
- mode
- chunk counts
- chars in / forwarded
- token estimates in / forwarded
- preprocess time
- chunks per second
- embedding-cost proxy

### `results/resource_metrics.json`

Should capture the same per-mode resource fields already used by the report:
- user CPU seconds
- system CPU seconds
- total CPU seconds
- elapsed seconds
- CPU cores used estimate
- max RSS KB

Important:
- for `nol8_api`, these numbers are client-observed benchmark-process numbers unless a richer server-side measurement contract is added later
- if server-side Nol8 metrics are available, keep them separate from the current benchmark resource file unless the contract is explicitly expanded

### `benchmark_run_metadata.json`

Should continue to identify:
- instance type
- region
- Go version
- any run metadata needed to interpret the environment

### `report/report_data.json`

This is the structured report source of truth.

A real Nol8 run should populate:
- measured mode metadata for the Nol8 row
- interpretation flags reflecting that real Nol8 results are now present
- the same derived metrics used by the HTML report

## Labeling rules for real Nol8 results

When a real Nol8 run is present:
- the Nol8 mode should be marked as a measured product mode
- it must not be labeled as simulated
- it becomes eligible for performance claims within the scope of the benchmark

Until then:
- `nol8sim` remains a behavioral placeholder only

## Minimal recommended run sequence

1. Validate the contract with the mock server if needed.
2. Point `nol8_api` at the real Nol8 endpoint.
3. Run the benchmark with the intended comparison modes.
4. Return the generated artifacts without changing the report format.

Example:

```bash
export NOL8_ENDPOINT="https://nol8.example/process"
export NOL8_API_KEY="replace-me"
export MODES="nofilter re2 listmatch nol8_api"
bash scripts/run_all.sh
```

## What this unlocks

Once engineering returns a real Nol8 run using this contract, the report can support measured statements about:
- software baseline versus real Nol8 behavior
- software CPU cost versus observed Nol8 path cost
- workload reduction achieved before embedding

That is the point at which the benchmark becomes a measured product-comparison artifact rather than a baseline-and-placeholder artifact.
