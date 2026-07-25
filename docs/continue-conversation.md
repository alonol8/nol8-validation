# Continue conversation — NOL8 validation / demos

Rewritten 2026-07-25 (updated same day: cliff RESOLVED/retracted + brief corrected;
efficiency MEASURED (~8-core software tax); demo system BUILT in `demos/showcase/`).
Read it first every session.

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

### ✅ THE REAL STORY IS EFFICIENCY — MEASURED (2026-07-25)

- **Measured on the engine hosts** (SSH `themis-demo` = FPGA box ip-10-10-1-254
  f2.6xlarge 24c; `aergia-demo` = RE2 box 32c; both `pground`, my key works there —
  NOT on hydra). Both engines share the **Apollo** DPDK poll-mode data plane, so it
  subtracts out fairly:
  - **Themis:** Apollo ~11.3 cores + FPGA matching in silicon (**0 host cores**, no
    matcher proc) = **~11.3 total** → ~28,600 rps. FPGA verified: AFI
    `agfi-057af19e...` loaded/OK, `/dev/uio0`, apollo `-l 2-13` regexdev; DP1-3 correct.
  - **Aergia:** Apollo ~11.3 + **aergia.real `--num-lexers 8` = ~8.2 RE2 lexer cores**
    = **~19.4 total** → ~26,300 rps.
  - **Software tax ~8 cores; ~0.39 vs ~0.74 cores/krps → ~1.9× host CPU/request.**
    Poll-mode = cores burn continuously (idle == load; measured at rest is representative).
- **Coherent testable hypothesis:** Aergia's ~26k plateau may be the 8-lexer saturation
  (FPGA isn't lexer-bound → 28.6k). Falsifiable via `--num-lexers`. Not run.
- **Topology:** Argus SaaS edge (tenant001-v1demo.nol8.net :443/:444) → Iris QUIC :8443 →
  Apollo → backend (FPGA regexdev on themis / RE2 lexers on aergia). `nolctl backend set`
  (IaC) flips Apollo's backend. policyd :8444 control. 1MB request cap is a product limit.

### Instrumentation = SELF-CONTAINED (no Grafana — user steer)

- **Hydra (`hydra-obs`, `:8088` custom "orchestrator" Basic-auth) is NOT a dependency.**
  It hosts the eng team's (turned-OFF, expensive) load-gen + a Grafana OBS the user
  dislikes/may have offline; my SSH key isn't even authorized there. See memory
  [[avoid-hydra-grafana-dependency]]. Use our own on-box `/proc` sampling + the Go driver.
- **Network finding (driver host m7a.2xlarge):** ENA `bw_out_allowance_exceeded` LARGE —
  EC2 throttles our EGRESS. Reframes the ~150 MB/s ceiling (may be our cloud cap) + the
  380 MB/s push (need MULTI-host). PMU: core `cpu` present (perf works), no `uncore_imc`.
- **Metrics gaps still worth adding:** per-cell rep-variance + canary guard; correctness-
  under-load (sample 1% vs oracle); soak; error taxonomy; ENA-delta per large cell.

### ✅ DEMO SYSTEM BUILT — `demos/showcase/` (SA-runnable, self-contained, covers 3 use cases)

- **Act 1 = the 3 use cases `usecases-demo.sh`** (run on `nol8-demo`): one capability
  (`/v1/process` literal redaction) at three control points, each oracle-verified —
  **pre-embedding (DP1), pre/post-inference (DP2), agent-to-agent (DP3)**. Scenarios in
  `scenarios/*.txt` (real governed values). **Tested live on Themis: 3/3 use cases, 3/3
  values each.** `ENGINE=aergia` → identical output (parity). Single-message variant:
  `redact-demo.sh` (`MSG_FILE=` any file); `redact-demo.py` has the oracle (policy-derived:
  raw gone + token present) + a near-miss guard (warns when a value is split by a line-break
  so literal match correctly can't catch it — found on the agent scenario during testing).
- **Act 2 `efficiency-demo.sh`** (run on laptop; SSHes themis-demo+aergia-demo): on-box
  core sampling, prints the ~8-core tax / ~1.9× contrast. **Tested: 11.3 vs 19.4 cores.**
- `RUNBOOK.md` (two-host, copy-paste, what-to-say) + `README.md`. **EC2 synced to HEAD**
  (was scp scratch; now runs from committed code). Story: same customer-verifiable result
  from FPGA & software, at ~half the host CPU/req.
- **AGENDA (later, Jamie):** need MORE than one demo story; build a full **agentic demo**
  using the mesh + pre-index asset repos ([[demo-asset-repos]]); this showcase covers the
  3 use cases at the redaction level, the agentic build is the richer live version.

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

Cliff RESOLVED + brief CORRECTED; efficiency MEASURED; demo system BUILT (all above).
Remaining, in priority:

1. **REPO CLEANUP** (Jamie asked, do after testing): keep needed + reusable one-off scripts
   (probe-*, density-*, reproduce, watch-load, rulecount-*), remove cruft, organize. The new
   `demos/showcase/` is the keeper demo. Announce before git.
2. **Settle the large-payload ceiling:** snapshot ENA `bw_out_allowance_exceeded` delta
   around large-payload cells — separate "engine limit" from "our EC2 egress cap." Feeds
   `THROUGHPUT-ISOLATION-REQUEST.md` and reframes the 380 MB/s push (likely multi-host).
3. **(Optional) lexer-count test:** vary `--num-lexers` on aergia to confirm the ~26k
   plateau is lexer-bound.
4. **Metrics guards** (nice-to-have): per-cell rep-variance + host-health canary (would've
   caught the 8.4k); correctness-under-load sampling.

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
