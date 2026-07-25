# Continue conversation — NOL8 validation / demos

Rewritten 2026-07-25. Compaction-safe handoff: read it first every session.

## What this is

Demo/validation env for **Themis** (NOL8's FPGA literal-matching engine) benchmarked
against **Aergia** (a stand-up of Google RE2, the software incumbent). NOL8 does
**deterministic literal replacement only** (listMatch, case-insensitive); NOT
route/block/mask(true)/enforce — redact/mask/drop are LIVE (oracle-verified),
route/block are ROADMAP signals a downstream control plane acts on. Same policy +
data + driver to every engine; report divergence honestly, never rig.

## Two-host workflow (operational — don't fumble this)

| | Mac (`~/Code/nol8/nol8-validation`) | EC2 (`/opt/nol8/nol8-validation`) |
|---|---|---|
| role | edit, commit, render, analyze | run against live engines; has Go 1.22 |
| reach | no Go; can't reach engines | reaches Themis :443 + Aergia :444 |

- SSH host **`nol8-demo`** → `data-streamer.sales.nol8.cloud` (10.8.10.40), user `pground`.
  8 cores, 30 GB RAM, 174 GB disk. Go at `$HOME/.local/go/bin`. venv `.venv` (has
  `google-re2` installed). Endpoints from `config/demo.env`+`.env`:
  `THEMIS_PROCESS_ENDPOINT` `tenant001-v1demo.nol8.net:443/v1/process`, `AERGIA` `:444`.
  **Both engines share the tenant host** (argus edge 10.8.11.254) — drive one at a time
  for any per-engine host-CPU measurement.
- **Long runs:** `nohup bash <script> > /tmp/<log> 2>&1 </dev/null &`. Survives SSH/VPN
  drops (both happened; nohup carried runs to completion). Launch-ssh often times out
  locally at 2 min — fine, verify with `pgrep -f <script>`. Completion watcher pattern:
  background Bash `until ssh '... grep ">> done" || ! pgrep -f <script>'; do sleep 20; done`.
- VPN (Tailscale) to 10.8.x can drop on the Mac; runs continue on EC2. `check-engines.sh`
  must be 6/6 before driving. Announce before git; stage specific files; simple git cmds.

## DP1–DP3 (done, honest model, committed)

Oracle-verified on both engines. Reports render from each `run.json` via
`demos/benchmark/make-report.py` (kinds default/dp2/dp3/**dp4**). HTML gitignored,
run.json tracked. DP2 53/53, DP3 13/13 (Themis==Aergia==oracle).

## DP4 — throughput at load (active work, under `demos/benchmark/datapoint4/`)

**FPGA's win is capacity, not correctness.** Core: concurrent Go load driver (`go/main.go`
+ `histogram.go`) — closed-loop worker pool, HTTP/1.1 conn reuse, dependency-free
log-scaled latency histogram, per-band payload buckets with configurable distinct-body
caps (`--cap-small/-medium/-large`, the cache-defeat knob).

### CONFIRMED (all on the REAL enterprise-dlp generator, not filler)

1. **Throughput sweep** (`run-live.sh`): small Themis ~29k rps vs RE2 ~17k (at 5k rules);
   medium ~parity; **large bandwidth-bound on BOTH** (~150 MB/s, Themis higher ceiling,
   collapses at 2048 concurrency = Themis front-end large-transfer limit). First-sweep
   report committed (`datapoint4/run.json`). Fair re-run (80k/4k, ≥4000 unique/band) has
   NO committed report yet (pending).
2. **Matching is free (byte-bound):** `probe-size.py` — at concurrency 1, clean vs
   match-packed same-size text take identical time on Themis (~1.4 MB/s/conn); FPGA
   matcher adds ~nothing. ~1 MB bodies 413 on both (shared edge cap).

### ⚠️ RULE-COUNT "CLIFF" — MEASURED BUT NOT ROBUSTLY REPRODUCIBLE (integrity-critical)

- `rulecount-live.sh` (fixed small payload, conc 256, vary rule count; default corpus
  distribution, 15000 records, cap-small 4000): Aergia flat ~26k through 6k rules,
  **collapses to ~8.4k at 8k** (3 reps, <1% spread); Themis flat ~28k. Reported as
  **3.4× at 8k** in `docs/DP4-THROUGHPUT-BRIEF.md` — **which Jamie converted to PDF and
  shared externally.**
- **BUT `density-real-live.sh` (same generator, same 8k rules, forced small size +
  single match bucket, 12000 records, cap-small 12000) gives Aergia ~25–27k at 8k across
  light/moderate/heavy density — NO cliff.** Same engine + rule count, two real-data
  configs → **3× different Aergia result. The cliff does not reproduce across setups.**
- **DO NOT keep asserting the 3.4× cliff until the trigger is pinned.** Tell Jamie it
  needs qualification. Leading hypothesis (vindicates the founder's matches/KB point):
  the rulecount corpus used the DEFAULT match_distribution, which puts *heavy* match
  counts (up to 100) into *tiny* 512-byte docs = **~50–200 matches/KB (extreme)**, while
  density-real "heavy" only reached ~12/KB. So the cliff may require EXTREME density that
  the capped tests didn't hit. UNCONFIRMED.
- **NEXT TEST (do first):** push density-real to extreme (30/50/100 matches/KB) on real
  data at 8k rules; also compute actual matches/KB of the rulecount 8k small docs (the
  matches/KB label had a cosmetic bug — recompute from `generated/manifest.json`:
  `expected_total_matches/(payload_bytes_total/1024)`). Reconcile the two setups. If the
  cliff only appears at extreme density, say so precisely; if it can't be reproduced,
  retract/qualify the 3.4×.

### Other density findings (context)

Synthetic-filler sweeps (`make-dense-corpus.py`+`density-live.sh`) did NOT reproduce the
cliff — but that filler was low-entropy ("same sentence", a mistake) and capped ~12/KB;
superseded by the real-data approach. Deploy ceiling ~8k–10k rules (10k refused). 32k
gen refused (ISSUE-004 containment).

### INTEGRITY NOTE (preserve)

- **The numbers Jamie shared (brief PDF) are from the REAL YAML generator, NOT filler.**
  Filler was only in internal unshared diagnostics. Confirmed.
- The brief's *mechanism* paragraph ("cache cliff") is a HYPOTHESIS. AND now the cliff
  *number itself* is in question (see above). Both need fixing in the brief once resolved.

## Tooling (datapoint4/)

`go/` driver · `run-live.sh`+`build-run.py` (throughput) · `rulecount-live.sh`+
`build-rulecount.py` (rule-count) · `probe-size.py`+`probe-live.sh` (byte-vs-match) ·
`cpu-microbench.py` (RE2 Set CPU — google-re2) · `make-dense-corpus.py`+`density-live.sh`
(synthetic density×diversity, superseded) · `density-real-live.sh` (density on REAL
data — right approach; has a cosmetic empty-matches/KB-label bug) · `watch-load.sh`
(live ss/nstat backpressure) · `DEMO-NOTES.md`. Docs: `DP4-THROUGHPUT-BRIEF.md`
(shared), `DP4-THROUGHPUT-PLAN.md`, `THROUGHPUT-ISOLATION-REQUEST.md`,
`CPU-EFFICIENCY-REQUEST.md`. results/ + *-report.html gitignored.

## Next steps (in order, post-compaction)

1. **Resolve the cliff (integrity first):** extreme-density real-data test + recompute
   actual matches/KB of both setups; reconcile or qualify the 3.4×. Fix `make-dense-corpus`
   density label / `density-real-live.sh` manifest-key bug while at it.
2. **Redo CPU microbench on REAL dense docs** (not the sparse sample) — cores-per-GB.
3. **Build ONE full narrative report** (like DP2/DP3) on sound data; then correct the
   brief's cliff number + mechanism wording to match what's proven.
4. **380 MB/s bandwidth push** (founder ask, queued): parallel drivers on large payloads
   → is the byte ceiling one driver or the edge? Feeds `THROUGHPUT-ISOLATION-REQUEST.md`.

## Backlog

- `PYTHONUNBUFFERED=1` + periodic "N/total" line in generators (nohup logs look frozen
  during corpus gen). Choke-point instrumentation (Little's-Law knee column + `ss -tim`/
  `nstat` per cell). Compression A/B on large payloads (separate network-bytes from
  edge/FPGA processing).

## Engine quirks

ISSUE-004 (contained/overlapping literals corrupt output; generator refuses ~32k rules),
ISSUE-005 (replacements truncate at 15 chars), deploy ceiling ~8k–10k rules, shared
~1 MB request-size cap at the edge (413 on both engines).
