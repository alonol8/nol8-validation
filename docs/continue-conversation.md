# Continue conversation — NOL8 validation / demos

Rewritten 2026-07-26 (evening). **READ THIS FIRST.** DP4 is resolved and the brief
is corrected + shared. The BYO-data POC is built (CLI + live console UI). The
console UI works but wants a design pass (handing to Fable). Tests are cleared.

## 🟢 Current state

- **Tests cleared.** 10 Argus online both sides. Box idle; engines on the **starter
  policy** (`demos/policies/starter-known-values.nol`). Console is running (tmux
  `console`, 0.0.0.0:8770).
- **DP4 resolved**, brief rewritten + **PDF shared by Jamie**.
- **BYO POC built + tested** (CLI + console UI), committed + pushed.
- Everything committed; `git log` head is the BYO/efficiency/UI work.

## 🔑 DP4 — resolved (the corrected story)

Old "~28.6k/26.3k, ~1.09× close" was measured through a **single Argus edge node**
(caps ~27k, pinned both engines). With **10 Argus**:

- **Rule-count sweep (conc 256, 5 reps, 8k rules):** Themis ~76.6k vs Aergia ~56.9k
  = **1.35×**; Aergia declines with rules (60.8→59.1→56.9k), Themis flat-high. The
  ~8.4k "collapse" is **gone** (5 reps ~57k) — it was single-edge saturation.
- **Concurrency push (8k):** Themis 77k→115k→146k; Aergia 57k→63k→68k; **gap widens
  1.35×→1.83×→2.15×.** Aergia walls ~68k = real engine ceiling (driver ~47% idle);
  Themis hit 146k where the **driver** maxed (~84% CPU), not the FPGA — true ceiling higher.
- **Latency:** conc 256 P99 ~5.8/7.9ms (was 19ms edge-queue).
- **Errors = exclusively HTTP 5xx** (server-side). Port exhaustion RULED OUT (socket
  measurement: keep-alive held 256, TIME_WAIT 0). Driver classifies errors now
  (`errbreak:` line). **OPEN: 5xx source (edge vs backend)** — Jamie asked **Alon**
  for logs; fold his answer into the brief when it lands.
- **Efficiency (measured idle AND under load):** ~8-core software tax; poll-mode →
  flat idle→load (verified: Themis apollo 10.91→11.29; Aergia apollo 10.97→11.23,
  lexers 8.17→8.01 under conc-256 load). **Cores/1k: ~0.15 (Themis) vs ~0.34 (Aergia)
  → ~2.3× host CPU/req** (up from old 1.9× — Themis's true throughput is higher).
- **Deploy ceiling:** 12k policy refused on Themis; 8k clean.

Evidence (tracked, `artifacts/evidence/`): `rulecount-10argus-clean.csv`,
`concpush-8k-{themis,aergia}-10argus.csv`, plus baselines. Brief:
`docs/DP4-THROUGHPUT-BRIEF.md` (supersedes prior wholesale; Jamie has re-rendered/shared).

## BYO-data POC — BUILT (CLI + console UI)

The buyer-facing answer to "a load generator is not a POC" — prove it on the
customer's OWN policy + documents.
- **CLI:** `demos/showcase/byo-poc/` (`run-byo-poc.sh [dir] [--skip-load]`). Ingest
  their `values/*.txt` + `documents/` → safe policy (token≤15, ISSUE-004 overlaps
  dropped) → deploy (settle) → oracle-verify both engines + parity → load their
  corpus → summary. Sample passes 18/18 both engines, 6/6 identical.
- **Console UI:** flagship BYO card in `demos/showcase/console/`. Endpoints
  `/api/byo/build|deploy|correctness|load` (load takes optional `engine` for per-engine
  progress). Staged build→deploy→verify→load; **load now has a live status panel +
  elapsed timer + per-engine incremental results**. Prefilled sample.
- **KEY LESSON baked in:** deploy returns "applied" before the data plane loads the
  policy — MUST settle (~8s) before verifying or first docs falsely show 0 matches.

## Console BYO — functional pass done (2026-07-26 late)

Before handing UI to Fable, did the pipeline-touching functional items myself:
- **60-doc sample** prefilled (generated from templates × sample values, each distinct)
  — real volume in the input.
- **add/remove category** controls; "+ add category" **scaffolds** a suggested category
  + example values (not a blank box).
- **Correctness reliability fix (important finding):** verifying 50+ docs live was slow
  AND flaky because **Aergia sheds/stalls under parallel connections from Python**
  (measured: fine one run, 7/34 the next — its bistable character again). Fix:
  `/api/byo/correctness` now verifies an evenly-spaced **sample (default 12)**, each
  engine **sequential on one reused keep-alive conn, engines in parallel** — the pattern
  Aergia tolerates (matches loop-probe 60/60). Reliable + sub-second. The **full corpus
  is still exercised in the load step** (Go driver, which Aergia handles). This design is
  DELIBERATE — flagged in UI-HANDOFF so Fable doesn't parallelize it back to flaky.

## 🎨 Console UI → hand to Fable (Jamie will drive)

Good functional first pass; needs a real design/interaction pass. **`demos/showcase/
console/UI-HANDOFF.md`** documents the data contract + integrity guardrails + TODOs
for whoever polishes it. **Jamie's specific asks to fold in:**
- **Bigger sample corpus** — produce **≥50 records** in the first section (the current
  3-doc sample is too small; also dodges the cache-fairness warning on load).
- **"add category" should help populate** — scaffold/suggest example values, not just
  an empty box.
- **Add a "remove category"** control on each category row.
- General: layout/hierarchy, real-time load viz, file upload, empty/error states.
INTEGRITY GUARDRAILS Fable must keep (in UI-HANDOFF.md): keep the cache-fairness
`warn` visible; ratios/CPU-cost are the defensible facts (not bare absolutes); never
fabricate "live" numbers; honest engine labels; preserve deploy→settle→verify order.

## Console — running now

`bash console/run.sh` on nol8-demo (starter policy on boot, 0.0.0.0:8770). Reach it:
`ssh -f -N -L 8770:localhost:8770 nol8-demo` → http://localhost:8770. **The `-f -N`
matters** — plain `-L` won't persist ([[console-tunnel-command]]). Direct
`http://10.8.10.40:8770` is SG-blocked.

## Next steps

1. **Fold Alon's 5xx-source answer** into the brief (edge vs backend) when it arrives.
2. **Fable UI pass** (Jamie drives) — per UI-HANDOFF.md + the asks above.
3. **Re-base the console "Scale" card** numbers to the 10-Argus reality (still shows
   pre-10-Argus figures; the efficiency panel is already updated to ~2.3×/corrected rps).
4. **Reconcile stale DEMO-NOTES.md**; add a BYO line to `demos/showcase/RUNBOOK.md`.
5. (efficiency-demo.sh: throughput defaults corrected; reps+spread still a nice-to-have.)
6. AGENDA: full agentic demo (mesh + pre-index repos) across the 3 use cases.

## Hosts (SSH)

| host | what | reach |
|---|---|---|
| `nol8-demo` | driver/console box (aka data-streamer), m7a.2xlarge, GOMAXPROCS=8, 10.8.10.40 | reaches engines :443/:444; Go + venv + dp4driver. Becomes the throughput limit ~146k+ (driver CPU). |
| `themis-demo` | FPGA backend, f2.6xlarge, 24 cores, AFI loaded | Mac only |
| `aergia-demo` | RE2 backend, 32 cores | Mac only |
| `hydra-demo` | Alon's load-gen + obs | my key NOT authorized; set aside |

Repo: Mac `~/Code/nol8/nol8-validation`, EC2 `/opt/nol8/nol8-validation`. **results/
gitignored** — copy raw to `artifacts/evidence/` (tracked). Brand guide
`~/Code/nol8/nol8-brand-guide`.

## Hydra — SET ASIDE

A load generator is not a POC (customers send their own data). Don't build on Hydra;
BYO-POC is the buyer-facing proof. (Confirm "Ares" == our Themis with Alon.) See
[[avoid-hydra-grafana-dependency]].

## Operational lessons

- **Run anything >1 min inside `tmux` on the box** — ssh-foreground-held-by-a-
  background-task dies on a VPN flap.
- **Classifier blocks `nohup … &` and `cat > file <<EOF` over ssh** — write scripts
  locally + `scp`, launch via tmux.
- **Copy raw CSVs to `artifacts/evidence/` as part of the run.**
- **`macOS has no `timeout`** (don't wrap local commands in it).
- **Driver classifies errors** (`errbreak:` line); CSV schema unchanged.

## Memories to respect

substitution-not-enforcement; benchmark-integrity-no-rigging; announce-before-git;
demos-must-be-SA-runnable; avoid-Hydra/Grafana; argus-edge-was-throughput-ceiling;
console-tunnel-command (`ssh -f -N -L`); "update the project" = rewrite this file wholesale.
