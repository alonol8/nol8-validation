# Preserved Evidence

Validation runs are not tracked in git. This directory holds the artifacts that must survive
run cleanup. Everything here is tracked deliberately; do not add whole run directories.

**Every measurement CSV has a paired `<basename>.manifest.json`** recording the rig it was
produced on: issuing host, instance type, vCPU, driver source commit, engine hosts, Argus
count. Read the manifest before comparing any two files. Absolute numbers are only comparable
within one rig configuration.

## Layout

**`current/`** — the figures to use. Measured on the current rig with driver headroom recorded
per cell.

| | |
|---|---|
| `rulecount/` | throughput against policy size, 2k to 8k rules |
| `concurrency/` | the pinned series and the reconciliation cell |
| `efficiency/` | idle and under-load cores, plus the derived constants |
| `payload/` | medium and large |
| `density/` | corpus coordinates for the runs above |

**`superseded/`** — kept, not discarded. **Superseded is not the same as wrong.** Some of this
is valid measurement on hardware we no longer run and actively corroborates the current
figures. One directory is genuinely invalid above a stated concurrency. The status column below
says which is which; read it before quoting anything from here.

**`reference/`** — not measurements. Policies, issue samples, the qualification report, and the
current-rig config manifest.

## Three things true of every figure here

**Ratios are properties of the data, not the engines.** The same comparison has measured
anywhere from parity to five times depending on match density, payload size and concurrency.
The coordinates in `current/density/` are part of the result, not context for it.

**Absolutes belong to a rig.** Instance type, NUMA topology, edge count and driver headroom all
move them.

**Low driver CPU does not prove the rig was clean.** Cross-NUMA memory latency cost roughly a
millisecond per request at high connection counts while consuming no additional CPU. Anything
above conc 256 requires the driver pinned to one NUMA node.

---

## Provenance

Status: **current** = the figure to use; **corroborating** = older rig, still supports the
current figure; **superseded** = kept for history, do not quote; **caveat** = valid only within
a stated scope; **reference** = a fixed asset, not a run.

### `current/` — 2026-07-27, 32-vCPU `c6a.8xlarge` driver, 10 Argus

| File | Status | What it is |
|---|---|---|
| `rulecount/rulecount-2k4k6k8k-current-20260727.csv` | **current** | **The headline.** Rule-count trend, conc 256, small, 5 reps. Themis flat ~77k; Aergia 58.4k to 55.9k (−4.4%); ratios 1.31 to 1.39 widening. Driver ~22%, no cell driver-limited. Reproduces the old-rig trend within 2% on independent hardware. |
| `efficiency/efficiency-idle-20260727.csv` + `efficiency-under-load-20260727.csv` | **current** | Core sampling, 5 reps each. Idle equals under-load, so poll-mode is demonstrated rather than asserted. Themis apollo ~11.25; Aergia apollo 11.27 plus matching ~8.05 = 19.32. **~8.1-core tax.** Sampled from the Mac via `/proc/<pid>/stat`, which is host-scoped; drive from the box at 51.7% driver CPU, not limited. |
| `efficiency/efficiency-constants.json` | **current** | Single source of truth for the efficiency claim. Cores per 1k of 0.144 against 0.335, **ratio 2.33x**, `provisional: false`. |
| `concurrency/numapin-1024-2048-15s-20260727.csv` | **current** | Driver pinned to one NUMA node. Themis recovers 129,890 to **145,838** at conc 1024 and 119,990 to **160,292** at 2048; Aergia essentially unchanged. Pinned busiest core ~80%, so 160k is a lower bound rather than a ceiling. |
| `payload/mediumlarge-8k-current-20260727.csv` | **current** | Medium and large, conc 256. Near parity, both byte-bound at 310 to 320 MiB/s at 3 to 9% driver CPU. The throughput edge is small-payload only. |
| `density/density-sent-current-20260727.json` | **current** | Match density over the trend's sent bodies: flat ~4.8/KB, ~11 per request, ~74% carrying a match. The Aergia decline tracks ruleset size, not density. |
| `concurrency/reconcile-1024-15s-20260727.csv` | **caveat** | Unpinned conc 1024 reconciliation, Themis ~130k. Evidence *of* the NUMA effect rather than an engine figure. |

### `superseded/jul26-old-driver/` — 8-vCPU driver, single NUMA

| File | Status | What it is |
|---|---|---|
| `rulecount-2k4k6k8k-clean-20260726.csv` | **corroborating** | Old-rig 4-point trend. Themis 76,169 / Aergia 55,939 at 8k conc 256, ratio 1.362. Agrees with the current trend within 2%. Two independent driver configurations agreeing is the strongest form of the headline. **Not superseded** despite its location. |
| `concpush-8k-themis-10argus.csv` + `concpush-8k-aergia-10argus.csv` | **corroborating** | Old-rig concurrency series. Themis conc 1024 at 145,795, corroborated by the pinned current run at 145,838 — 0.03% apart on entirely different hardware. Single-NUMA, so not contaminated. |
| `rulecount-2k4k-clean-20260726.csv` | superseded | Old-rig 2k/4k re-run, superseded by the 4-point trend. |
| `rulecount-10argus-clean.csv` | superseded | 10-edge trend on the old driver. |
| `mediumlarge-10edge-20260726.csv`, `large-rerun-4k-20260726.csv` | superseded | Old-rig payload runs, same parity finding as the current one. |
| `efficiency-idle-20260726.csv` | superseded | Idle cores on the pre-restart Aergia engine. |
| `corpus-density-20260726.{json,md}`, `corpus-density-sent-20260726.json` | context | Density on the old corpora. The `.md` explains sent bodies at ~4.8/KB, the right object, against the source-document 0.12/KB, which is the wrong object and should not be quoted. |
| `throughput_combined-fairrun.csv` | superseded | Original DP4 fair run. Holds the disproven ~150 MB/s figure. |

### `superseded/jul24-single-edge/` and `jul25-single-edge/`

Both measured through a single Argus edge node capping around 27,000 req/s, so both engines
were pinned at the front door and the flatness is the edge rather than parity.

`rulecount-jul24-cliff.csv` contains the Aergia 8k collapse to 8,402 req/s. Real and
reproducible that day, gone the next on the same configuration, cause never established.

### `superseded/jul27-unpinned/` — current hardware, invalid configuration

| File | Status | What it is |
|---|---|---|
| `concpush-8k-current-20260727.csv` | **caveat** | Concurrency 256 to 4096, **unpinned**. Valid only at conc 256. Above it, cross-NUMA client latency depresses Themis; the apparent peak at 1024 and the ratio collapse are rig artifacts. Carries a `# CAVEAT` header. |
| `signature-8k-20260727.*`, `concpush-ext-*` | superseded | Signature gate and extension manifests from the same unpinned run. |

### `reference/`

| File | What it is |
|---|---|
| `tenant-restore-policy.nol` | The only copy of the deployed 5,000-rule Themis policy. See below. |
| `qualification-passing-report.html` | Passing qualification report, run `20260720T221534714262Z`, 10,000 PASS. |
| `issue-004-failure-sample.jsonl` | 12 representative failures from the original qualification. **ISSUE-004's "corruption" characterisation is now known to be wrong**: Themis every-match-fires and Aergia one-byte-one-match are two self-consistent transformation contracts. |
| `issue-005-truncation-20260726.{json,md}` | Controlled truncation reproduction. Confirmed since: Aergia's rule record has a fixed 15-byte replacement field. |
| `current-config.manifest.json` | Current rig snapshot, the baseline for drift checks. |

---

## Known gaps in the manifests

Being fixed. Worth knowing when reading one:

- **`corpus.dir` is null.** The manifest does not record which corpus produced the result.
- **`policy.sha256` records `UNKNOWN` with provenance `measured_now`**, which is
  self-contradictory: it claims to have measured and stored a placeholder.
- **`generator_version` reads `1` both before and after the generator changed** on 2026-07-27,
  so a manifest cannot distinguish a corpus built before that change from one built after.

Drift between runs is keyed on the driver's source commit and working-tree cleanliness rather
than the binary hash, because Go builds are not reproducible without `-trimpath` and the hash
moves on every build from identical source. It is recorded but does not trigger a warning.

---

## The corpora are not regenerable across 2026-07-27

**This corrects an earlier claim in this file.** Runs were previously described as regenerating
deterministically from configuration and seed. That holds only within a single generator
version.

The corpus-realism work merged on 2026-07-27 changed `framework/workload/` and
`framework/scenarios/`. Every corpus from before that date came from the previous generator and
regenerating from the current tree produces different bytes. `generator_version` was never
bumped, so the manifests cannot even tell you which side of the boundary a corpus is on.

Consequence: corpora built before 2026-07-27 are **the only byte-exact copies** of what the
weekend's results were measured against. They are archived to:

```
s3://nol8-validation-archive-455132698227/runs-pre-20260727/
```

Seven tarballs, `batch-00` through `batch-06`, covering 56 run directories.

Within one generator version, regeneration is still the right default:

```bash
validate generate --config config/workloads/customer-record-csv.yaml \
  --rules 5000 --records 10000
```

---

## tenant-restore-policy.nol

The 5,000 rule policy deployed on the `tenant001-v1demo` Themis tenant, from qualification run
`20260720T221534714262Z`.

```
SHA256  27fe47dbcdffd8fc4e8a51f81b41673735161e72587f753c7c81f636ec1f854e
```

**This is the only copy.** Themis provides no way to read back a deployed policy, so if this
file is lost the tenant's policy is unrecoverable. Deploying any policy replaces the entire
active ruleset, so restore after any deployment:

```bash
validate policy --file artifacts/evidence/reference/tenant-restore-policy.nol --target themis
```

This catalog contains no overlapping literals, so the two transformation contracts coincide on
it, and its replacement tokens stay distinct after the 15-character truncation. Both properties
are enforced at generation time.
