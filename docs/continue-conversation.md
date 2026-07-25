# Continue conversation — NOL8 validation / demos

Rewritten 2026-07-25 (updated same day: cliff RESOLVED/retracted, brief corrected,
efficiency + instrumentation + demo-system are the forward path). Read it first every session.

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

### ✅ RULE-COUNT "CLIFF" — RESOLVED: IT WAS A TRANSIENT, RETRACTED (2026-07-25)

- The original `rulecount-live.sh` run reported Aergia **8.4k at 8k rules (3.4× cliff)**
  and that number went into `docs/DP4-THROUGHPUT-BRIEF.md`, which Jamie shared externally.
- **It does not reproduce.** Re-ran the *identical* rulecount 8k cell (same seed=42 corpus,
  same flags, same host): Aergia **26.36k / 26.42k**, Themis ~28.7k. Then a full clean
  1k→8k sweep (3 reps, <1% spread): **BOTH engines dead flat** — Themis ~28.6k, Aergia
  ~26.3k, steady **1.09×** at every rule count. No cliff, and no gradual slope either.
- **Root cause:** the 8.4k was a **transient depression of the shared host**; the 3 reps
  agreed only because they ran back-to-back inside the same bad window. Density was NOT
  the trigger — measured the rulecount 8k small-band at **4.8 matches/KB** (join
  `input.jsonl.message` size ⋈ `expected.jsonl.expected_match_count`), LOWER than the
  density-real runs. Founder's matches/KB mechanism is real in principle but not what
  produced this number.
- **Brief is CORRECTED** (rewritten 2026-07-25): visible Correction Notice retracting the
  3.4×, honest flat table, latency corrected (p99 ~16 vs ~19ms, ~15% tighter, not "half"),
  large-ceiling caveated, pivots positioning to EFFICIENCY (unmeasured) + predictability.
- **Falsified hypotheses (all dead):** the 3.4× cliff; "RE2 slopes down with rule count";
  "rule count is the FPGA's advantage axis." Deploy ceiling ~8k–10k (10k refused) means
  >8k is UNTESTABLE (policy won't load), not "flat forever."

### Other density findings (context)

`density-real-live.sh` (light/mod/heavy) and `density-live.sh` (density×diversity) both
gave Aergia 22–27k at 8k — all consistent with the corrected ~26k, all disagree with the
retracted 8.4k. Synthetic filler was low-entropy ("same sentence", a mistake); superseded.
32k gen refused (ISSUE-004 containment).

### THE REAL STORY IS EFFICIENCY (unmeasured) + instrumentation direction

- At req/s level the engines are CLOSE (FPGA ~1.09× small, parity medium). The FPGA's
  decisive win is expected to be **cores/power/cost per unit throughput** — NOT yet
  measured. This is the founder's cores ask and now the #1 priority.
- **GATE:** efficiency lives on the *engine* host. Themis FPGA = black box. Aergia (our
  RE2) CPU story needs monitoring/exec access on whatever host runs the RE2 process
  (engines sit behind argus edge, NOT on the driver EC2). **Confirm Aergia-host access.**
- **Network finding (driver host m7a.2xlarge):** ENA `bw_out_allowance_exceeded` is LARGE
  and non-zero — EC2 has been throttling our EGRESS. Reframes the ~150 MB/s large-payload
  ceiling (may be our host's cloud cap, not the engine) and the 380 MB/s push (need
  MULTI-host, one host can't beat a per-host cap). `ss -tim`/`nstat`/`ethtool -S $NIC`.
- **PMU boundary:** virtualized (not .metal) → core `cpu` PMU present (perf cache-misses/
  IPC works → can settle cache-cliff on Aergia) but NO `uncore_imc` (no true DRAM bytes/s
  membw). PSI (`/proc/pressure/*`) is the always-works stall proxy.
- **Instrumentation plan:** Prometheus + node_exporter + Grafana, out-of-band host CPU/net
  (~0 request overhead) → the "software pegs N cores vs FPGA idle" panel = efficiency proof
  AND live demo asset AND host-health canary that would've caught the 8.4k. Skip Elastic.
  Keep driver lean; NO per-request tracing in the hot path (corrupts the number at 28k rps).
- **Metrics gaps to add:** per-cell rep-variance + canary guard; correctness-under-load
  (sample 1% vs oracle during load); soak (minutes) for drift; error taxonomy; per-cell
  backpressure (ENA delta / ss / nstat).

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

Cliff is RESOLVED and brief is CORRECTED (see above). Remaining, in priority:

1. **Confirm Aergia-host access**, then capture **cores-per-throughput** (efficiency —
   the number the whole story now hinges on; founder's ask). Themis stays a black box.
2. **Settle the large-payload ceiling:** snapshot ENA `bw_out_allowance_exceeded` delta
   around large-payload cells — separate "engine limit" from "our EC2 egress cap." Feeds
   `THROUGHPUT-ISOLATION-REQUEST.md` and reframes the 380 MB/s push (likely multi-host).
3. **Stand up Prometheus + node_exporter + Grafana** (out-of-band host CPU/net) — the
   efficiency panel doubles as a demo asset + host-health canary.
4. **BUILD THE DEMO SYSTEM** (the real deliverable — Jamie's explicit reminder). SA-runnable
   end-to-end env; the Grafana panel is part of it. Stop rabbit-holing on benchmarking once
   the efficiency number is in hand. See demo memories (SA-runnable, positioning, assets).
5. **REPO CLEANUP** (after testing): keep needed + reusable one-off scripts (probe-*,
   density-*, reproduce, watch-load, rulecount-*), remove cruft, organize. Note made.

**Known small bug:** density scripts reference `generated/manifest.json`; actual file is
`generated/generation-manifest.json` (that's why matches/KB labels printed empty). Per-doc
density = join `input.jsonl.message` byte-len ⋈ `expected.jsonl.expected_match_count`.

## Backlog

- `PYTHONUNBUFFERED=1` + periodic "N/total" line in generators (nohup logs look frozen
  during corpus gen). Choke-point instrumentation (Little's-Law knee column + `ss -tim`/
  `nstat` per cell). Compression A/B on large payloads (separate network-bytes from
  edge/FPGA processing).

## Engine quirks

ISSUE-004 (contained/overlapping literals corrupt output; generator refuses ~32k rules),
ISSUE-005 (replacements truncate at 15 chars), deploy ceiling ~8k–10k rules, shared
~1 MB request-size cap at the edge (413 on both engines).
