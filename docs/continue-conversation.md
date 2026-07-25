# Continue conversation — NOL8 validation / demos

Rewritten 2026-07-25 (integrity review). **READ THIS FIRST.** Two things override
everything below: (1) **TESTS ARE PAUSED** — Alon is testing with Hydra; run NOTHING
against the engines until Jamie gives the word. (2) An **integrity review is open** on
DP4; the rule-count "cliff" is NOT settled (see below).

## ⛔ Current directive: tests paused

- Jamie said cease all tests while **Alon runs his own testing with Hydra**. Do not drive
  load, deploy policies, or run the console's scale/corpus against the live engines until
  Jamie explicitly clears it. Everything is currently stopped (no dp4driver, 0 engine
  connections, console down, engines on the small starter policy).
- Doc edits, local analysis, and reading committed files are fine. Engine calls are not.
- **Alon will hand Jamie RAW numbers from Hydra runs.** When they arrive: assess honestly,
  compare his methodology to ours, and especially check **whether Hydra reproduces the
  ~8.4k Aergia@8k collapse** — if he can trigger it on demand, that's the trigger we've been
  missing (see integrity item 1). Don't assume our numbers or his are "the" truth; reconcile.
- **Interrogate the Hydra code (read-only review, when Jamie clears it).** Jamie wants to
  understand what Hydra's load generator actually does under the hood (how it drives load,
  concurrency model, what it measures, connection reuse, warmup) — this directly affects how
  to reconcile his numbers with ours. CONSTRAINT: my SSH key is NOT authorized on
  `hydra-demo`, and we must not step on Alon — so this is a **pure read/review**, needs Jamie
  to grant read access or point me at the Hydra source. Do NOT run Hydra or touch his setup.

## What this is

Demo/validation env for **Themis** (NOL8's FPGA literal-matching engine, `:443`) vs
**Aergia** (a stand-up of Google RE2, the software incumbent, `:444`). NOL8 does
**deterministic literal replacement only** (listMatch, case-insensitive); NOT
route/block/mask/enforce. Same policy + data + driver to every engine; report divergence
honestly, never rig. Product/topology: Argus SaaS edge (`tenant001-v1demo.nol8.net`
`:443`/`:444`, PrivateLink) → Iris QUIC `:8443` → **Apollo** DPDK data plane → backend
(FPGA regexdev on themis / RE2 lexers on aergia). policyd `:8444` control. 1 MB request cap.

## Hosts (SSH)

| host | what | reach |
|---|---|---|
| `nol8-demo` | driver/console box, data-streamer, m7a.2xlarge, 10.8.10.40 | reaches engines :443/:444; has Go + venv + dp4driver |
| `themis-demo` | FPGA backend, ip-10-10-1-254, **f2.6xlarge, 24 cores**, AFI loaded | Mac only (NOT nol8-demo) |
| `aergia-demo` | RE2 backend, 32 cores | Mac only (NOT nol8-demo) |
| `hydra-demo` | obs/fleet dashboard `http://hydra-obs.sales.nol8.cloud:8088/` (Basic auth) | my key NOT authorized; Alon's testing box now |

Repo: Mac `~/Code/nol8/nol8-validation`, EC2 `/opt/nol8/nol8-validation`. **results/ is
gitignored** — raw CSVs there DO NOT sync between hosts or reach the repo (this caused the
integrity gap below). Long runs: `nohup … </dev/null &`; launch-ssh often times out at 2min
(fine). Announce before git. Brand guide at `~/Code/nol8/nol8-brand-guide` (charcoal
`#404040`, green `#33B046`, Google Sans, dark web mode).

## 🔴 OPEN INTEGRITY REVIEW (do first, once tests are cleared)

External reviewer + founder flagged DP4. All four confirmed on disk:

1. **Rule-count "cliff" is NOT a settled retraction — it's BISTABLE.** Jul-24 sweep
   (`results/rulecount.csv`, the file the reviewer/founder saw): Aergia at 8k rules
   **collapses to ~8,400 rps WITH errors (5/54/24), p50 29ms / p99 79ms, ⅓ completions**,
   while **Themis in the same run is fine (28,800, 0 err)** — so it's **Aergia-specific, NOT
   a shared-host transient** (a host blip would hit both). Jul-25 re-run got a clean ~26k
   (also reproduces). So Aergia@8k is **bistable: usually ~26k, sometimes a real ~8.4k
   collapse; trigger UNKNOWN.** The brief's current "transient, no cliff, flat" claim is
   **OVERCONFIDENT and must be fixed.** The founder likely saw the 8.4k himself.
   - **Procedural gap:** the Jul-25 clean re-run's raw CSV only lived on EC2 (gitignored),
     never reached the repo — so persisted evidence contradicted the brief.
   - **TO DO:** run MANY reps at 8k (matched policy, conc 256), save raw to
     `artifacts/evidence/` (NOT gitignored), characterize how often it collapses + hunt the
     trigger (deploy state? lexer memory? warmup? errors→timeouts?). Then rewrite the brief
     to the honest bistable story. A `rulecount-8k-stability.csv` run was started then killed
     for Alon (never wrote rows).
2. **DEMO-NOTES.md stale (throughput):** its `17,719` / "1.7×" small-payload figure is in NO
   csv; `throughput_combined.csv` shows Aergia **25,826** (~1.11×, matches brief). Update
   DEMO-NOTES to the fair-re-run numbers.
3. **Efficiency measurement weakest:** `efficiency-demo.sh` = single 4s idle sample +
   hardcoded throughput. TO DO: 3–5 reps + report spread; add an under-load sampling variant
   (I validated flat-under-load this session — F2 held 11.28/11.32/11.23/11.28 cores at ~27k
   req/s — but it's not in the committed script). Numbers to fold in once solid.
4. **DEMO-NOTES.md stale (corpus):** says "50,000 records / 5,000 rules"; `run-live.sh`
   defaults to **80,000 / 4,000**. Reconcile.

**Reviewer's rule: verify on disk, don't fix code before reporting. Be willing to find we
were wrong — on item 1 we partly were.**

## Measurement soundness notes (context for the review)

- **Huge shared-host variance:** same 8k config gave Themis 28.6k (swept, Jul-25) vs ~76k
  (fresh burst, later Jul-25) — ~2.7×. Absolute throughput is NOT stable on this env; only
  RATIOS and CPU cost are defensible. Any absolute number must be labeled point-in-time.
- **Mismatched policy inverts results:** driving an 8k-rule corpus against a 40-rule policy
  makes RE2 "win" (clean text, trivial DFA). Apples-to-apples REQUIRES matched policy+corpus.
- **ENA egress:** driver-host NIC bandwidth allowance caps large-payload throughput (~4000
  allowance-exceeded events in 20s under load, 0 idle; same-VPC, per-instance-NIC cap). Not
  an engine limit.
- **Latency ~19ms P99 = 256-concurrency queue, not matching** (conc 1 = ~2ms P99, ~1ms floor;
  Little's Law holds to 3 decimals). This one is solid.

## What still holds (probably — but re-verify under the review)

- FPGA matching is byte-bound/free (probe-size, conc 1). Small-payload FPGA edge modest.
- **Efficiency (the real story):** Apollo poll-mode ~11.3 cores both; Themis matches in
  silicon (0 host cores) vs Aergia ~8.2 RE2 lexer cores → ~8-core software tax, ~1.9× host
  CPU/req. Poll-mode = constant under load (validated). FPGA verified engaged (AFI, uio0,
  f2.6xlarge, DP1-3 correct). **This is robust regardless of the throughput question.**

## Demo console — BUILT, then PARKED pending the review

`demos/showcase/console/` (server.py stdlib + on-brand dark web UI, runs on nol8-demo,
`bash console/run.sh`, tunnel `ssh -f -N -L 8770:localhost:8770 nol8-demo` → localhost:8770,
or direct `http://10.8.10.40:8770` if SG allows — it doesn't). Features: catalog (18 prompts),
both-engines side-by-side redaction + per-req stats, corpus batch run, **scale** (matched 8k
policy deploy→drive conc256→restore; Themis ~1.28× live; absolute varies), efficiency panel
(cores + %-of-box + flat-under-load). Jamie liked it. **PARKED** — do not run its
load features during Alon's testing, and the scale number inherits the item-1 caveat.

Also built earlier: `demos/showcase/` CLI tour (redact-demo, usecases-demo across the 3 use
cases, oracle-verified, matches/KB reported) + RUNBOOK. DP1-3 (correctness) and DP4 brief
(`docs/DP4-THROUGHPUT-BRIEF.md`, shared as PDF — **needs the item-1 correction before reshare;
Jamie must re-render the PDF**).

## Demo-flow the user wants (UI target, for when we resume)

The console should walk the full pipeline visibly, each step showing its output:
1. **Generate data → show a sample** (a few records of the corpus).
2. **Generate the policy → show some of it** (a slice of the .nol rules).
3. **Deploy the policy → confirm it applied** (a real "applied" return from the control plane).
4. **Execute the test** (the load/corpus run).
5. **See the data** (results — done well already).
This makes the demo self-evident (generate→policy→deploy→run→results), not a black box.

## Next steps (in order, AFTER Alon clears + tests resume)

0. **Ingest Alon's raw Hydra numbers** (arrive via Jamie): reconcile with ours; does Hydra
   reproduce the 8.4k collapse? **Review Hydra's code** (read-only, needs access from Jamie)
   to understand its load model — this may explain any divergence and reveal the trigger.
1. **Resolve item 1:** multi-rep 8k stability characterization, raw saved to
   `artifacts/evidence/`, find the collapse trigger, then honestly rewrite the brief
   (bistable, not "no cliff"). This gates any external re-share.
2. **Fix items 2 & 4:** reconcile DEMO-NOTES (17,719→25,826; 50k/5k→80k/4k).
3. **Fix item 3:** efficiency-demo.sh reps + spread + under-load variant.
4. **Re-render + re-share the corrected brief** (Jamie).
5. **Resume UI:** build the generate→policy→deploy→run→results flow above; then the shareable
   static dashboard (Artifact). Full agentic demo (mesh + pre-index repos) still on the agenda.

## Memories to respect

Substitution-not-enforcement; benchmark-integrity-no-rigging; announce-before-git;
demos-must-be-SA-runnable; avoid Hydra/Grafana dependency (self-contained tooling);
"update the project" = rewrite this file wholesale.
