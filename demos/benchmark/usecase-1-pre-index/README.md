# Data Point 1 — Pre-Index Optimization Benchmark Kit

## What this package is for

This package is meant to do **two jobs**:

1. **Deliver the pitch**
   - explain where Nol8 fits
   - explain why it matters
   - provide professional talking points
   - position the use case clearly in RAG / Agentic RAG

2. **Run the benchmark**
   - compare a no-filter baseline
   - compare a traditional software pipeline using Go `regexp` (RE2 syntax)
   - compare deterministic reference-list matching against known entities and indicators
   - compare a Nol8-style keep / mask / drop / route pipeline
   - generate a report artifact

---

## Package structure

- `docs/`
  - narrative documents, positioning, talking points, and benchmark methodology
- `diagram/`
  - editable draw.io diagrams
- `data/`
  - sample dataset and dataset generation helper
- `go/`
  - benchmark implementation
- `python/`
  - analysis helper
- `results/`
  - output location and templates
- `scripts/`
  - convenience scripts to run everything
- `report/`
  - simple HTML report generator

---

## Recommended benchmark environment

Use one machine type and keep it fixed for all runs.

Recommended:
- AWS `c6i.2xlarge`
- or equivalent:
  - GCP `n2-standard-8`
  - Azure `D8s v5`

Why:
- this is primarily a CPU-bound test
- string processing and deterministic control operations are the focus
- keeping a single instance type removes debate about environment drift

---

## Software requirements

- Go 1.22+
- Python 3.10+
- bash shell
- no external Python packages required

---

## Quick start

### 1. Run the benchmark and generate the report

```bash
bash scripts/run_all.sh
```

### 2. Open the report

Open:
- `report/report.html`

---

## Main documents to read first

1. `docs/01_use_case_pitch.md`
2. `docs/02_agentic_rag_overlay.md`
3. `docs/03_benchmark_methodology.md`
4. `docs/07_report_interpretation.md`
5. `docs/08_external_nol8_execution.md`
6. `docs/10_ai_summary_guidelines.md`

These documents are the core of the package.

---

## Dataset and test story

The benchmark runs against:
- `data/sample_chunks.jsonl`
- `data/reference_lists/`

The dataset is synthetic, but it is shaped like pre-index enterprise text from support, fraud, compliance, and customer-operations workflows.

Each line in `sample_chunks.jsonl` is one chunk:

```json
{"id":"chunk-0000003","category":"compromised_account","text":"Fraud operations escalated account ACC-7701-4432 after device telemetry and impossible-travel signals suggested compromise..."}
```

The test asks a simple question:

Which chunks should be embedded, and which chunks should be changed, withheld, or routed before they ever reach the embedding path?

The reference-list test is not about hiding random strings. It is about applying customer-owned business context before indexing.

Examples:
- If a chunk contains `ACC-7701-4432`, and that value is in `compromised_accounts.txt`, the chunk represents an active fraud/security case. The benchmark drops it from the general embedding path.
- If a chunk contains `192.0.2.90`, and that value is in `bad_ips.txt`, the chunk represents known hostile infrastructure. The benchmark drops it from the general embedding path.
- If a chunk contains `Atlas Rare Earth Trading`, and that value is in `denied_entities.txt`, the chunk may require compliance review. The benchmark routes it instead of embedding it into the general analyst index.
- If a chunk contains `Westbridge Merchant Services`, and that value is in `customers.txt`, the chunk may need customer-specific handling. The benchmark routes it rather than treating it as generic text.
- If a chunk contains `4111 1111 1111 1111`, and that value is in `payment_cards.txt`, the benchmark masks the listed value and forwards the remaining text.

That gives the benchmark a concrete enterprise story:
- reduce embedding work on content that should not enter the general index
- keep sensitive or governed material out of the wrong retrieval surface
- preserve useful text when masking is enough
- route higher-risk chunks to a controlled path instead of pretending they are ordinary text

This is intentionally a first-pass control test. It proves the benchmark contract with deterministic, explainable rules before any richer Nol8 product behavior is measured.

---

## Benchmark modes

### Mode A — `nofilter`
Traditional worst-case baseline:
- everything is forwarded to embedding

### Mode B — `re2`
Traditional software pipeline:
- deterministic filtering/masking using Go `regexp`
- Go `regexp` uses RE2 syntax

### Mode C — `listmatch`
Deterministic reference-list control:
- route known customers or denied entities
- drop bad IPs or compromised account IDs
- mask known payment-card values

What that means in practice:
- the benchmark loads plain-text reference lists from `data/reference_lists/`
- each chunk is checked against those known values
- if a bad IP or compromised account is found, the chunk is dropped
- if a customer or denied entity is found, the chunk is routed instead of embedded
- if a listed payment-card value is found, the chunk is masked and still forwarded
- if nothing matches, the chunk is kept

This is a deterministic first-pass enterprise control:
- it is not fuzzy matching
- it is not entity inference
- it is not the full long-term Nol8 vision
- it is the simplest real benchmark based on data customers already own

Action order matters:
1. `drop`
2. `route`
3. `mask`
4. `keep`

So each chunk ends with one effective outcome in the report.

### Mode D — `nol8sim`
Nol8-style data plane simulation:
- explicit keep / mask / drop / route decisions before embedding
- behavior placeholder only, not a measured production Nol8 result

---

## What success looks like

A strong result for this use case should show:

- lower forwarded tokens vs `nofilter`
- lower estimated embedding cost vs `nofilter`
- visible control over known entities and indicators using enterprise-owned lists
- credible throughput for incumbent software baselines
- clear explanation of what was dropped, masked, kept, or routed
- a narrative that ties the benchmark to CPU reduction, GPU protection, and privacy/compliance

For `listmatch` specifically, the numbers mean:
- `Dropped`: chunks containing listed bad IPs or compromised accounts
- `Routed`: chunks containing listed customers or denied entities
- `Masked`: chunks containing listed payment-card values
- `Kept`: chunks with no list hit
- `Prevented from embedding`: dropped plus routed chunks
- `Tokens forwarded` / `Chars forwarded`: only the text that still proceeds after those actions

## Important interpretation note

The current report contains measured software baselines and a simulated Nol8 behavior placeholder.

That means:
- `re2` and `listmatch` are measured software results
- `nol8sim` is useful for target control semantics
- `nol8sim` is not evidence of real Nol8 production efficiency

## External engineering handoff

When real Nol8 access is available, the engineering team should run the same benchmark contract through `nol8_api` and return the standard benchmark artifacts.

Start here:
- `docs/06_nol8_api_mode.md`
- `docs/08_external_nol8_execution.md`

The current repo is meant to establish:
- the workload
- the software baselines
- the report contract

The future `nol8_api` run is meant to establish:
- measured Nol8 behavior on the same workload
- measured product comparisons against the software baseline

## AWS execution

Use the shared AWS harness at the repo root when you want to run this pack on EC2:
- `../aws_benchmark_harness/`

---

## Notes

This package is intentionally focused on **Data Point 1 only**:
- Pre-Index Optimization

The same repo now includes additional benchmark packs:
- Data Point 2: Pre/Post-Inference Control
- Data Point 3: Agent-to-Agent Control

Use the shared AWS harness at the repo root when you want to run any use case on EC2:
- `../aws_benchmark_harness/`
