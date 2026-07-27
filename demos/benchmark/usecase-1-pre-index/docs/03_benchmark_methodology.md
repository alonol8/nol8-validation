# Benchmark Methodology — Data Point 1

## Objective

Measure the value of pre-index optimization before embedding.

The current benchmark compares four modes:

1. `nofilter`
2. `re2`
3. `listmatch`
4. `nol8sim`

Mode roles:
- `nofilter`: measured baseline
- `re2`: measured software baseline
- `listmatch`: measured software baseline
- `nol8sim`: simulated behavioral placeholder

## What we are testing

We are testing whether a deterministic pre-index layer can reduce:
- forwarded token volume
- forwarded payload size
- estimated embedding cost

while preserving:
- useful content
- credible throughput
- bounded resource usage

The first pass is intentionally centered on the `listmatch` use case.

Why:
- it is simple to explain
- it uses enterprise inputs customers already have
- it shows a realistic incumbent software path that consumes CPU before embedding
- it creates a clear bridge to future Nol8 support for richer regex and policy behavior

## Environment

Recommended fixed instance:
- AWS `c6i.2xlarge`

Equivalent options:
- GCP `n2-standard-8`
- Azure `D8s v5`

OS recommendation:
- Ubuntu 22.04 LTS

Software:
- Go 1.22+
- Python 3.10+

## Dataset

Included file:
- `data/sample_chunks.jsonl`

The dataset mixes:
- keepable technical and operational content
- fraud investigation notes
- compliance review notes
- support and onboarding summaries
- regex-detectable sensitive patterns
- known customer and entity watchlist hits
- bad-IP indicators
- compromised account identifiers
- payment-card values
- mixed-content chunks and near-misses

For larger runs, use:
- `data/generate_dataset.py`

Suggested sizes:
- 1K chunks: smoke test
- 10K chunks: functional benchmark
- 100K chunks: throughput / stress

## Rules under test

The benchmark uses explicit deterministic rules.

### RE2 masking rules
- mask email username but preserve domain
- mask SSN except last 4
- mask phone number except last 4
- mask account identifiers

### RE2 drop rules
- remove welcome/header lines
- remove navigation lines
- remove footer lines
- remove legal disclaimer lines
- remove cookie notice lines

### Reference-list rules

The `listmatch` mode loads exact-match watchlists from `data/reference_lists/`.

Current action mapping:
- known customers: `route`
- denied entities: `route`
- bad IPs: `drop`
- compromised account IDs: `drop`
- payment-card values: `mask`

Per-chunk evaluation order:
1. check bad IPs and compromised account IDs
2. if matched, `drop`
3. otherwise check customers and denied entities
4. if matched, `route`
5. otherwise check payment-card values
6. if matched, `mask`
7. otherwise `keep`

This means:
- each chunk gets one effective outcome
- `drop` overrides `route`
- `route` overrides `mask`
- `mask` only happens if the chunk was not already dropped or routed

Matching behavior:
- case-insensitive
- deterministic
- based on plain-text lists packaged with the benchmark
- intended to reduce near-miss substring matches for word-like terms

### Nol8-specific control model

The `nol8sim` mode uses:
- `keep`
- `mask`
- `drop`
- `route`

The routing decision is intentionally simple in this MVP, but it demonstrates data-plane behavior beyond plain regex replacement.

Longer term, Nol8 is expected to absorb richer deterministic matching as well, including harder regex-style control. The current benchmark starts with list-driven enterprise controls because that is the cleanest first-pass benchmark.

## Interpretation rule

The current benchmark may be used to discuss:
- measured software baseline behavior
- workload shape
- CPU cost of software control
- governance outcomes before embedding

The current benchmark may not be used to make product-performance claims for Nol8 because `nol8sim` is simulated behavior, not measured production execution.

When real Nol8 access is available, the expected next step is to run the same benchmark contract through `nol8_api` and return the standard artifacts described in:
- `docs/06_nol8_api_mode.md`
- `docs/08_external_nol8_execution.md`

## Run plan

### Warm-up

Run once and discard the result.

### Recorded runs

Run at least 3 recorded passes on the same dataset size.

### Keep fixed

- instance type
- dataset
- Go version
- no competing workloads

## Metrics

### Core benchmark metrics

- `tokens_forwarded_est`
- `chars_forwarded`
- `chunks_per_sec`
- `chunks_dropped`
- `chunks_masked`
- `chunks_routed`

For `listmatch`, interpret these as:
- `chunks_dropped`: chunks containing listed bad IPs or compromised accounts
- `chunks_routed`: chunks containing listed customers or denied entities
- `chunks_masked`: chunks containing listed payment-card values and still forwarded after masking
- `tokens_forwarded_est` / `chars_forwarded`: only the payload that still reaches embedding after list-driven actions

### Resource metrics

Collected per mode using `/usr/bin/time -v` where available, with a BSD `/usr/bin/time` fallback on macOS:
- user CPU seconds
- system CPU seconds
- CPU percentage
- elapsed wall time
- max RSS (KB)

On macOS fallback runs, CPU percentage and max RSS may be unavailable and reported as blank or zero.

### Derived metrics

- token reduction vs baseline
- payload reduction vs baseline
- estimated embedding cost delta vs baseline
- tokens reduced per CPU second
- route rate
- drop rate

## Command model

The updated harness runs each mode separately so resource metrics can be captured per mode.

That is important because a single "run everything at once" benchmark cannot attribute CPU or memory usage cleanly to each mode.

## How to interpret the benchmark

- `nofilter` is the do-nothing baseline.
- `re2` is the incumbent software pattern-matching baseline.
- `listmatch` is the first-pass enterprise control benchmark using known watchlists and indicators.
- `nol8sim` is the target control-behavior model, not the long-term implementation boundary.

For `listmatch`, the easiest plain-English explanation is:

"Take a chunk of text, compare it against known enterprise lists, and deterministically decide whether to drop it, route it, mask part of it, or keep it."

That is the current first-pass use case being benchmarked.

For leadership discussions, the important comparison is not "can software do this?" It can.

The important comparison is:
- how much content software can suppress or reroute before embedding
- how much CPU that software path consumes
- why that class of work is a candidate for a more efficient Nol8 execution plane
