# Preserved Evidence

Validation runs are no longer tracked in git - they are reproducible, large,
and caused the development and execution hosts to diverge. This directory holds
the small number of artifacts that must survive run cleanup.

Everything here is tracked deliberately. Do not add whole run directories.

---

## tenant-restore-policy.nol

The 5,000 rule policy currently deployed on the `tenant001-v1demo` Themis
tenant, from the authoritative qualification run `20260720T221534714262Z`.

```
SHA256  27fe47dbcdffd8fc4e8a51f81b41673735161e72587f753c7c81f636ec1f854e
```

**This is the only copy.** Themis provides no way to read back the deployed
policy (THM-1), so if this file is lost the tenant's policy is unrecoverable.

Deploying any policy replaces the entire active ruleset (THM-2), so restore
after any deployment:

```bash
validate policy --file artifacts/evidence/tenant-restore-policy.nol --target themis
```

This catalog contains **no overlapping literals**, so it does not trigger
ISSUE-004, and its replacement tokens remain distinct after the runtime's
15-character truncation (THM-5), so a comparison can tell which rule fired.

Both properties are now enforced at generation time - a catalog lacking either
is refused rather than emitted.

> Superseded `20260720T193444152733Z` (SHA `c3b763aa...`), the prior
> authoritative policy. It was generated under the pre-FW-7 generator; after
> FW-7 canonicalised weighted-selection order, seed 42 produces this catalog
> instead. The old policy remains valid evidence but is no longer what
> `validate generate ... seed 42` yields. Earlier still,
> `20260719T161514709224Z` contained 31 overlapping literal pairs and three
> `[BUSINESS_TERMS:*]` tokens that collapsed under truncation. Kept in history
> only; do not deploy either.

## issue-004-failure-sample.jsonl

Twelve representative failures from the original qualification
(`20260719T161514709224Z`, 272 CONTENT_MISMATCH of 10,000).

Each row carries the record id, the byte offset where output diverged, the
byte delta, and trimmed excerpts of expected versus actual. The full 61 MB
comparison artifact is not retained - ISSUE-004 is reproducible from
`scripts/repro-issue-004-curl.sh` with no corpus at all, so this sample is
corroborating evidence rather than the primary proof.

## qualification-passing-report.html

The passing report from run `20260720T221534714262Z`:

```
5,000 rules / 10,000 records / customer-record-csv / seed 42
10,000 PASS · 0 CONTENT_MISMATCH · 0 EXECUTION_FAILURE · 0 INCONCLUSIVE
p50 12.643 ms · p95 14.358 ms · p99 16.814 ms
```

Retained as the reference for what a clean qualification looks like.

This supersedes the report from `20260720T193444152733Z`, the prior
authoritative run, which was equally airtight (10,000 PASS, 0 inconclusive) but
generated before FW-7 canonicalised weighted-selection order. It in turn
superseded `20260719T230452981053Z`, which predated collision detection and had
three `[BUSINESS_TERMS:*]` tokens that became identical under truncation across
4,755 transformations - records that under current logic would be INCONCLUSIVE.

---

## issue-005-truncation-20260726.{json,md}

Controlled reproduction of the token-truncation behaviour (ISSUE-005) across four
token lengths (15/16/20/29) against both engines, plus an ISSUE-004 engine-identity
confirmation. `.json` is the raw per-engine per-length data; `.md` is the analysis.
Repro: `demos/benchmark/datapoint4/truncation_repro.py`.

**Observation (not a conclusion):** in this run the `:443` engine emitted full tokens
and `:444` truncated to 15. It contradicts ISSUE-005's "Component: Themis" (and the
THM-5 line above), but a single experiment does not re-attribute a filed issue that was
raised with engineering under context the repo does not hold. ISSUE-005/THM-5 are
**unchanged**; the questions are appended to `docs/aergia-8k-collapse-question.md`.

## DP4 throughput CSVs — PROVISIONAL, under active review

These are the raw combined CSVs behind the DP4 throughput work. All are **provisional**:
the DP4 review is open, and rule-count numbers are being re-run with a fixed harness
(deploy probe, rep-1 basis, error accounting). Do not quote absolute numbers from these
without checking the review status. **Do not compare absolute numbers across files with
different edge topology** (single Argus vs 10) — only ratios within one run survive.

| File | Config | What it is |
|---|---|---|
| `rulecount-jul24-cliff.csv` | single edge, conc 256, small | Rule-count sweep, Jul 24. Contains the Aergia@8k collapse (~8.4k). |
| `rulecount-jul25-clean.csv` | **single edge**, conc 256, small | Rule-count sweep, Jul 25. Flat ~28.6k/~26.4k, ~1.09×, no collapse. **Single-edge — the flatness is the edge ceiling, NOT engine parity; do not read as "engines are equal."** |
| `rulecount-10argus-jul25-partial.csv` | 10 edge, conc 256, small | Partial 10-edge sweep (2k/4k/8k only), Jul 25. Corroborates the clean file. |
| `rulecount-10argus-clean.csv` | 10 edge, conc 256, small, 5 reps | The current rule-count sweep on the 10-node edge. Reps are a degrading series — use rep-1, not median (see review). |
| `concpush-8k-themis-10argus.csv` | 10 edge, 8k rules, conc 256/512/1024 | Concurrency push, Themis. |
| `concpush-8k-aergia-10argus.csv` | 10 edge, 8k rules, conc 256/512/1024 | Concurrency push, Aergia. |
| `throughput_combined-fairrun.csv` | **single edge**, 4k rules, payload×conc | The original DP4 fair run. **Superseded for absolute throughput** (single-edge ceiling; large-payload row shows the disproven ~150 MB/s figure). Kept as the pre-10-edge baseline. |

---

## Reproducing rather than retaining

Any run can be regenerated deterministically from its configuration and seed,
and - since FW-7 - independently of YAML key order. Verified: two generations
from seed 42 produce byte-identical policy, input, and expected artifacts. This
policy was generated under the current (post-FW-7) generator, so it regenerates
from seed 42; the superseded policies were not and do not. Prefer regenerating
over keeping artifacts:

```bash
validate generate --config config/workloads/customer-record-csv.yaml \
  --rules 5000 --records 10000
```
