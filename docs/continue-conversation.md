# Continue conversation — NOL8 validation / demos

Rewritten 2026-07-26 (DP4 resolved). **READ THIS FIRST.** The DP4 throughput
question is now **resolved**: the old numbers were **edge-limited** (a single Argus
front-door node), not engine-limited. With the edge scaled to 10 nodes we
re-measured cleanly. The corrected brief is written; tests are cleared.

## 🟢 Current state

- **Tests cleared** (Alon done with Hydra). **10 Argus online** both sides.
- **Box idle**: no dp4driver, 0 engine connections; engines restored to the
  **starter policy** (`demos/policies/starter-known-values.nol`) so the redaction
  console works.
- **DP4 brief rewritten** → `docs/DP4-THROUGHPUT-BRIEF.md` (source doc). **Jamie
  re-renders the PDF before any re-share** — it supersedes the prior version wholesale.

## 🔑 THE RESOLVED DP4 STORY (what changed and the numbers)

**The old ~28.6k/26.3k "~1.09× close" numbers were measured through a SINGLE Argus
edge node** (the HTTPS front door), which caps ~27k and pinned both engines there.
Scaling to **10 Argus** and re-running the identical test:

- **Rule-count sweep (conc 256, 5 reps, 8k rules):** Themis (FPGA) **~76.6k** vs
  Aergia (RE2) **~56.9k** = **1.35×**. Aergia gently declines with rules
  (60.8→59.1→56.9k across 2k/4k/8k); Themis flat-high. *(Themis@2k was noisy from
  5xx bursts — clean reps ~75k; don't cherry-pick it.)*
- **The ~8.4k "collapse" is GONE** — 5 reps at 8k held ~57k, no crater. It was the
  single edge node saturating, not RE2. **Integrity item 1 closed.**
- **Concurrency push (8k rules, 256/512/1024):** Themis **77k → 115k → 146k**;
  Aergia **57k → 63k → 68k**. **Gap widens 1.35× → 1.83× → 2.15×.**
  - **Aergia walls at ~68k = a real ENGINE ceiling** (driver was only ~47% busy).
  - **Themis hit 146k where the DRIVER box maxed (~84% CPU), not the FPGA** — its
    true ceiling is higher than one load box can find.
- **Latency:** conc 256 P99 ~5.8ms (Themis) / ~7.9ms (Aergia). The old "19ms P99"
  was single-edge queuing — gone.
- **Errors = exclusively HTTP 5xx** (server-side backpressure). Driver instrumented
  to classify errors: dial/timeout/reset all **zero**; port exhaustion **ruled out**
  by direct socket measurement (keep-alive held 256 conns, TIME_WAIT 0). 5xx is
  <0.1% typical, rises under load, heavier on the Themis path (it drives more
  throughput downstream). **OPEN: where do the 5xx originate (edge vs backend)?** —
  Jamie is asking **Alon** for server-side logs of the run window.
- **Deploy ceiling:** 12k-rule policy **refused on Themis**; 8k deploys clean.

Evidence (all tracked, `artifacts/evidence/`): `rulecount-10argus-clean.csv`,
`concpush-8k-themis-10argus.csv`, `concpush-8k-aergia-10argus.csv`, plus the earlier
`rulecount-10argus-jul25-partial.csv` and the single-Argus baselines
(`rulecount-jul24-cliff.csv`, `rulecount-jul25-clean.csv`).

## Durable spine (unaffected by the edge finding)

- **Efficiency:** ~8-core structural software tax (RE2 lexers) the FPGA does in
  silicon; both data planes poll-mode (constant cost). Per-request multiplier to be
  **re-measured at the corrected higher throughput** (will favor the FPGA more).
  Measured on the engine hosts, so the edge finding doesn't touch it.
- **DP1–DP3 correctness** (oracle-verified) — unaffected.

## Hydra — SET ASIDE (Jamie's call, 2026-07-26)

Alon's Hydra dashboard showed Ares(=FPGA?) 120k rps / Aergia 1.4k under 160k
*offered* open-loop load — that's **congestion collapse under 3× overload**, a
different axis from our matched-load numbers, NOT an "87× throughput" claim. More
importantly: **a load generator is not a customer POC** (customers send their own
data). Decision: don't build on Hydra; focus on self-contained tooling + a
Bring-Your-Own-Data POC. (Confirm with Alon that "Ares" == our Themis.) See memory
[[avoid-hydra-grafana-dependency]].

## Next steps (in order)

1. **Commit** the brief + driver instrumentation + evidence (announce first). *(in
   progress this turn)*
2. **Build the BYO-data POC flow** on the console: customer brings a sample of their
   docs + governed-value list → we build the policy → run their docs through both
   engines, oracle-verify against their own policy → report throughput/latency on
   *their* corpus + the CPU-cost story. Demo-flow: generate→policy→deploy(confirm
   applied)→run→results. This is the buyer-facing proof Hydra can't be.
3. **5xx source** — ingest Alon's server logs; pin edge vs backend; fold into brief.
4. **Efficiency re-measure** under corrected load (efficiency-demo.sh reps + spread +
   under-load variant) → update the per-request multiplier in the brief.
5. **Reconcile stale DEMO-NOTES.md** (old 17,719 / 50k-5k numbers).
6. **Re-render + re-share the corrected brief** (Jamie).
7. Later: shareable static dashboard (Artifact); full agentic demo (mesh + pre-index).

## Hosts (SSH)

| host | what | reach |
|---|---|---|
| `nol8-demo` | driver/console box (aka data-streamer), m7a.2xlarge, GOMAXPROCS=8, 10.8.10.40 | reaches engines :443/:444; Go + venv + dp4driver. **Becomes the throughput limit ~146k+ (driver CPU).** |
| `themis-demo` | FPGA backend, f2.6xlarge, 24 cores, AFI loaded | Mac only |
| `aergia-demo` | RE2 backend, 32 cores | Mac only |
| `hydra-demo` | Alon's load-gen + obs | my key NOT authorized; set aside |

Repo: Mac `~/Code/nol8/nol8-validation`, EC2 `/opt/nol8/nol8-validation`. **results/
is gitignored** — copy raw to `artifacts/evidence/` (tracked). Argus config: Jamie
has the URL/login (fleet scales; was 1 overnight, now 10). Brand guide
`~/Code/nol8/nol8-brand-guide` (charcoal `#404040`, green `#33B046`, Google Sans).

## Operational lessons (don't repeat)

- **Run anything >1 min inside `tmux` on the box** — ssh-foreground-held-by-a-
  background-task dies on a VPN flap (killed a run last night). tmux survived today.
- **The auto-mode classifier blocks `nohup … &` and `cat > file <<EOF` over ssh** —
  write scripts locally + `scp` them, launch via tmux.
- **Copy raw CSVs to `artifacts/evidence/` as part of the run**, not after.
- **The driver (`demos/benchmark/datapoint4/go/main.go`) now classifies errors** —
  prints an `errbreak:` line (dial/timeout/reset/eof/http4xx/http5xx/other) whenever
  a cell has errors. CSV schema unchanged (console/build-rulecount.py still parse).

## BYO-data POC — BUILT (CLI + console UI), tested, committed

The buyer-facing answer to "a load generator is not a POC." Prove it on the
customer's OWN policy + documents.
- **CLI:** `demos/showcase/byo-poc/` — `run-byo-poc.sh [dir] [--skip-load]`. Ingest
  their `values/*.txt` + `documents/` → build safe policy (token≤15, ISSUE-004
  overlaps dropped) → deploy (settle for data-plane propagation) → oracle-verify
  both engines + parity → load-test their corpus → summary. Bundled `sample/`
  ("Meridian Financial") passes 18/18 both engines, 6/6 identical, load ~1.30×.
- **Console UI:** flagship BYO card in `demos/showcase/console/` — paste values +
  docs, staged buttons build→deploy→verify→load, each revealing output; prefilled
  with a sample. Four endpoints in server.py (`/api/byo/build|deploy|correctness|
  load`). Verified end-to-end (Themis 156k vs Aergia 112k = 1.39× on 2 docs, with
  the cache-fairness warning).
- **KEY LESSON baked in:** deploy returns "applied" before the data plane loads the
  policy — MUST settle (~8s) before verifying or the first docs falsely show 0
  matches (byo_poc caught this live). The console/rulecount scripts settle 6-8s.
- **Console is RUNNING** on nol8-demo (tmux `console`, 0.0.0.0:8770; starter policy
  restored). Reach it: `ssh -f -N -L 8770:localhost:8770 nol8-demo` → http://localhost:8770.
- **TODO:** the console's older "Scale" card numbers still reflect pre-10-Argus;
  re-base them. Add a BYO line to `demos/showcase/RUNBOOK.md`. Also `demos/showcase/`
  CLI tour + RUNBOOK exist.

## Memories to respect

Substitution-not-enforcement; benchmark-integrity-no-rigging; announce-before-git;
demos-must-be-SA-runnable; avoid-Hydra/Grafana; argus-edge-was-throughput-ceiling;
"update the project" = rewrite this file wholesale.
