# Preserved Evidence

Validation runs are not tracked in git — they are reproducible, large, and caused
the development and execution hosts to diverge. This directory holds the small
number of artifacts that must survive run cleanup. Everything here is tracked
deliberately; do not add whole run directories.

**Every measurement CSV has a paired `<basename>.manifest.json`** recording the
rig it was produced on (issuing host, instance type, vCPU, driver source commit,
engine hosts, Argus count). Read the manifest before comparing any two files:
absolute numbers are only comparable within one rig configuration.

---

## Provenance table — every file here

Status legend: **current** = the figure to use; **superseded** = kept for
history, do not quote; **caveat** = valid only within a stated scope;
**reference** = a fixed asset (policy/report), not a run.

### Current-config runs (2026-07-27, 32-vCPU `c6a.8xlarge` driver, 10 Argus, driver CPU recorded per cell)

| File | Status | What it is |
|---|---|---|
| `rulecount-2k4k6k8k-current-20260727.csv` | **current** | **The headline.** Rule-count trend, conc256, small, 5 reps. Themis flat ~77k; Aergia 58.4k→55.9k (−4.4%); ratios 1.31→1.39× widening. Driver ~22%, zero cells driver-limited. Reproduces the old-rig trend within 2% on independent hardware. |
| `efficiency-idle-20260727.csv` + `efficiency-under-load-20260727.csv` | **current** | Core sampling, 5 reps each, current config. Idle == under-load → poll-mode demonstrated. Themis apollo ~11.25; Aergia apollo 11.27 + lexers ~8.05 = 19.32; **~8.1-core tax**. Issued from the Mac (`/proc/<pid>/stat`, host-scoped); drive from the box (driver CPU 51.7%, not limited). |
| `efficiency-constants.json` | **current** | SINGLE SOURCE OF TRUTH for the efficiency claim. Measured cores + conc256 throughput → cores/1k 0.144/0.335, **ratio 2.33×**, `provisional: false` (poll-mode demonstrated, driver ≤51.7%). |
| `numapin-1024-2048-15s-20260727.csv` | **current** | Driver pinned to one NUMA node (`numactl --cpunodebind=0`). Themis recovers 129,890→**145,838** (conc1024) and 119,990→**160,292** (conc2048); Aergia unchanged. Proves the unpinned concurrency series was rig-contaminated (findings 014). Pinned busiest-core ~80% → 160k is a lower bound, not a ceiling. |
| `mediumlarge-8k-current-20260727.csv` | **current** | Medium/large, conc256. Near-parity (medium 1.03×, large 1.04×), both byte-bound ~310–320 MiB/s at 3–9% driver CPU. FPGA edge is small-payload/compute-bound only. |
| `density-sent-current-20260727.json` | **current** | Match density over the trend's sent small bodies: flat ~4.8/KB, ~11/req, ~74% hit → the Aergia decline is ruleset size, not density. |
| `concpush-8k-current-20260727.csv` | **caveat** | Concurrency 256–4096, UNPINNED. **Valid only at conc256.** Above it, cross-NUMA client latency depresses Themis; the peak-at-1024 and ratio collapse are RIG ARTIFACTS (see `numapin`, findings 014). Carries a `# CAVEAT` header. |
| `reconcile-1024-15s-20260727.csv` | **caveat** | Unpinned conc1024 reconciliation (Themis ~130k, 3 reps). Evidence OF the NUMA effect, not an engine ceiling; pinned recovers to ~146k. |

### Old-rig runs (8-vCPU driver — superseded absolutes, some still corroborate)

| File | Status | What it is |
|---|---|---|
| `rulecount-2k4k6k8k-clean-20260726.csv` | **corroborating** | Old-rig 4-point trend. Themis 76,169 / Aergia 55,939 at 8k conc256, ratio 1.362. Agrees with the current trend within 2% — two independent driver configs, the strongest form of the headline. Not superseded; kept as cross-rig corroboration. |
| `concpush-8k-themis-10argus.csv` + `concpush-8k-aergia-10argus.csv` | **superseded** | Old-rig concurrency series (8-vCPU, single-NUMA). Themis conc1024 ~145,795 — CORROBORATED by the pinned current run (145,838, 0.03% apart). Old-rig corroboration, not a current absolute. `# SUPERSEDED` header. |
| `rulecount-2k4k-clean-20260726.csv` | **superseded** | Old-rig clean 2k/4k re-run; superseded by the 4-point trend. |
| `mediumlarge-10edge-20260726.csv` | **superseded** | Old-rig medium/large; superseded by `mediumlarge-8k-current-20260727.csv` (same parity finding). |
| `large-rerun-4k-20260726.csv` | **superseded** | Old-rig large re-run (3 reps); superseded by the current medium/large. |
| `efficiency-idle-20260726.csv` | **superseded** | Idle cores on the pre-restart Aergia engine; superseded by the paired current-config efficiency. |
| `rulecount-10argus-clean.csv` | **superseded** | 10-edge trend, old driver; superseded as trend basis. `# SUPERSEDED` header. |
| `rulecount-jul24-cliff.csv` | **superseded** | Single-edge Jul24; contains the Aergia@8k cliff. `# SUPERSEDED` header. |
| `rulecount-jul25-clean.csv` | **superseded** | Single-edge Jul25; flatness is the edge ceiling, not parity. `# SUPERSEDED` header. |
| `rulecount-10argus-jul25-partial.csv` | **superseded** | Partial 10-edge Jul25. `# SUPERSEDED` header. |
| `throughput_combined-fairrun.csv` | **superseded** | Original DP4 fair run, single-edge; holds the disproven ~150 MB/s figure. `# SUPERSEDED` header. |

### Offline / analysis (no fleet)

| File | Status | What it is |
|---|---|---|
| `corpus-density-20260726.{json,md}` + `corpus-density-sent-20260726.json` | **context** | Density on the old-rig corpora. The `.md` explains SENT bodies (~4.8/KB, the right object) vs the source-doc 0.12/KB (wrong object — do not quote). Current-config equivalent is `density-sent-current-20260727.json`. |
| `issue-005-truncation-20260726.{json,md}` | **reference** | Controlled truncation reproduction (:443 full / :444 trunc-15), a dated observation raised as an engineering question. Alon's PR confirmed the mechanism (Aergia's fixed 15-byte `replacement[15]` field). |

### Reference assets (not runs)

| File | Status | What it is |
|---|---|---|
| `tenant-restore-policy.nol` | **reference** | The only copy of the deployed 5,000-rule Themis policy (SHA below). Restore instructions in the section that follows. |
| `issue-004-failure-sample.jsonl` | **reference** | 12 representative failures from the original qualification (corroborating; ISSUE-004 reproduces from `scripts/repro-issue-004-curl.sh`). Note: ISSUE-004's "corruption" characterisation is now known to be wrong — Themis every-match-fires and Aergia one-byte-one-match are two self-consistent contracts (Alon's ES-1). |
| `qualification-passing-report.html` | **reference** | The passing qualification report (`20260720T221534714262Z`, 10,000 PASS). |

### Manifests

`*.manifest.json` (18): one provenance sidecar per CSV — 12 retrofitted for pre-
existing runs (issuing host recorded as UNKNOWN/old-driver-box where it was never
captured) + `current-config.manifest.json` + today's per-run start manifests
(signature, rule-count, concpush, concpush-ext, numapin). Drift between runs is
**keyed on the driver's source commit + working-tree cleanliness**, not the binary
sha (Go builds are not reproducible without `-trimpath`, so the sha moves every
build from identical source; it is recorded but does not trigger a drift warning).

---

## tenant-restore-policy.nol

The 5,000 rule policy currently deployed on the `tenant001-v1demo` Themis tenant,
from the authoritative qualification run `20260720T221534714262Z`.

```
SHA256  27fe47dbcdffd8fc4e8a51f81b41673735161e72587f753c7c81f636ec1f854e
```

**This is the only copy.** Themis provides no way to read back the deployed policy
(THM-1), so if this file is lost the tenant's policy is unrecoverable. Deploying
any policy replaces the entire active ruleset (THM-2), so restore after any
deployment:

```bash
validate policy --file artifacts/evidence/tenant-restore-policy.nol --target themis
```

This catalog contains no overlapping literals, so the two transformation contracts
coincide on it and its replacement tokens stay distinct after the 15-character
truncation (THM-5). Both properties are enforced at generation time.

---

## Reproducing rather than retaining

Any run regenerates deterministically from its configuration and seed (post-FW-7,
independent of YAML key order). Prefer regenerating over keeping artifacts:

```bash
validate generate --config config/workloads/customer-record-csv.yaml \
  --rules 5000 --records 10000
```
