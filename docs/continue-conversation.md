# Continue conversation — NOL8 validation / demos

Rewritten 2026-07-25 (evening — the Argus finding). **READ THIS FIRST.** The DP4
integrity picture changed materially today: the throughput numbers were **edge-limited**,
not engine-limited. Tests are **no longer paused** (Alon is done). Details below.

## 🟢 Current state

- **Tests are cleared.** Alon finished his Hydra work. We can drive load again.
- **Nothing is running.** Verified: no `dp4driver`, 0 engine connections, engines on the
  small starter policy, console down.
- **The big finding today:** the edge (Argus) was the throughput ceiling — see next section.

## 🔑 THE ARGUS FINDING (today's headline — this reframes DP4)

Alon revealed there had been only **a single Argus edge node per engine** during all our
DP4 runs. Argus is the SaaS front door (terminates TLS :443/:444 → PrivateLink → Iris QUIC
→ Apollo → engine); it does no matching, it's a proxy. The fleet was then scaled to **10
Argus**. We re-ran the exact `rulecount-live.sh` sweep (same tool + conditions as the
single-Argus CSVs) as a clean A/B. Result:

**Small payload, conc 256, 3 reps. 1 Argus → 10 Argus:**

| rules | Themis 1→10 Argus | Aergia 1→10 Argus | Themis/Aergia @10 |
|---|---|---|---|
| 2000 | 27.3k → **72.4k** (2.6×) | 26.0k → **58.9k** (2.3×) | 1.23× |
| 4000 | 27.9k → **72.9k** (2.6×) | 26.2k → **57.0k** (2.2×) | 1.28× |
| 8000 | 28.6k → **76.5k** (2.7×) | 26.4k → **55.6k** (2.1×) | **1.38×** |

(10-Argus figures are per-rule-count medians of 3 reps; raw in
`artifacts/evidence/rulecount-10argus-jul25-partial.csv`.)

**Four conclusions, all honest and all *good for us*:**

1. **The single Argus was the real throughput ceiling.** Both engines were pinned at
   ~26–28k with one front door; both jumped ~2.1–2.7× with ten. The suspiciously flat,
   rule-count-independent numbers were the *edge*, not the engines.
2. **The ~8.4k Aergia@8k "collapse" is explained and GONE.** With 10 Argus, Aergia@8k is a
   healthy 55.8k/54.5k/55.6k, p99 ~7.9ms, no crash. The collapse was a single edge node
   saturating intermittently (bistable), NOT an RE2/engine fault. **This closes integrity
   item 1** — the honest story is "edge-node saturation," provable by the A/B.
3. **The true engine gap is bigger than we reported and it WIDENS with rule count.**
   Edge-masked, the engines looked ~1.09× "close." Unmasked: 1.23× → 1.28× → 1.38× as rules
   climb. Themis holds flat; Aergia softens (RE2 DFA cost). This is the *original FPGA
   thesis* (`rulecount-live.sh`'s reason for existing) finally visible — the single Argus had
   been erasing exactly the effect we most wanted to show.
4. **Latency was edge queueing.** p99 dropped from ~17–19ms to ~5.7ms (Themis) / ~7.9ms
   (Aergia). This answers the founder's "no way 19ms P99 for SW" — the 19ms was the single
   front door queuing, and it's gone once the edge is scaled.

**Caveat / new confound — the driver box is now the next ceiling.** At 70k+ rps the single
driver host (`nol8-demo` / data-streamer, GOMAXPROCS=8) hit **ephemeral-port exhaustion**:
errors climbed *within* each rule-count's reps (Themis 48→75→261; resets each new rule
count) and the run ultimately died with **"Can't assign requested address"**. So the
10-Argus numbers are **floors** (engines may go higher) and the later-rep error counts are a
**driver artifact, not an engine fault**. Must be fixed before these numbers are publishable.

**Run status:** the sweep got 2000/4000/8000 complete for BOTH engines (3 reps each), then
died before 12000 — a **VPN flap on the Mac** dropped the ssh that held it (no PTY, so the
remote kept writing the CSV a while after stdout broke; that's why 8000 fully landed). Data
preserved to `artifacts/evidence/rulecount-10argus-jul25-partial.csv` (Mac + EC2).

## ☀️ PLAN FOR THE MORNING (start fresh, in order)

1. **Fix driver-side port exhaustion FIRST** (so error counts are clean and the ceiling is
   real, not artificial). On `nol8-demo`: widen `net.ipv4.ip_local_port_range`, lower
   `tcp_fin_timeout` / enable `tcp_tw_reuse`, `ulimit -n` already 65536. Confirm the driver
   reuses connections (HTTP/1.1 keep-alive — it does; the churn is from cap-* distinct
   bodies + high rps). Goal: drive 70k+ rps with ~0 errors.
2. **Use a durable run harness** — the ssh-foreground-held-by-background-task died on a VPN
   flap. Launch the sweep inside **tmux/screen on the box** (or nohup) so a laptop/VPN blip
   can't kill it. Reattach to read progress.
3. **Re-run the full clean sweep:** rule counts `2000 4000 8000 12000` (add 12000 — the
   missing point), **5 reps**, conc 256, save raw straight to `artifacts/evidence/` as
   `rulecount-10argus-clean.csv`. This is the definitive 10-Argus dataset.
4. **Confirm the collapse stays gone** across all 8k reps (item 1 fully closed with N≥5).
5. **Then the true-ceiling question:** with the port fix in, push concurrency (256 → 512 →
   1024) and/or add a second driver box to find where the *engines* actually top out (right
   now we only know they're ≥70k/≥55k). This tells us the real headroom.
6. **Rewrite the DP4 brief** with the corrected, stronger story:
   - throughput was edge-limited; with a scaled edge the engines do ~72k / ~57k+,
   - the real engine ratio is ~1.23–1.38× and **widens with rule count** (FPGA flat, RE2
     slopes) — lead with this, it's the product thesis,
   - the 8.4k "collapse" was single-edge-node saturation, now resolved,
   - the 19ms P99 was edge queueing, now ~6–8ms,
   - keep the efficiency story (below) as the durable spine.
   Then **Jamie re-renders the PDF** before any re-share. (Prior brief had a "no cliff,
   transient" claim that was wrong; this supersedes it with a *better* answer.)
7. **Items 2 & 4:** reconcile stale DEMO-NOTES.md (17,719→ correct fair numbers; 50k/5k→
   80k/4k).
8. **Item 3:** efficiency-demo.sh reps + spread + under-load variant (unaffected by the edge
   — it's measured on the engine hosts directly).

## What still holds regardless (the durable spine)

- **Efficiency is the robust story and is edge-independent.** Apollo poll-mode ~11.3 cores
  on both; Themis matches in silicon (0 host cores) vs Aergia ~8.2 RE2 lexer cores → ~8-core
  software tax, ~1.9× host CPU/req, constant under load. Measured on the engine hosts, so the
  Argus finding doesn't touch it. FPGA verified engaged (AFI, uio0, f2.6xlarge).
- **DP1–DP3 correctness** (oracle-verified replacement, parity, payload) — unaffected.

## What this is / topology

Demo/validation env: **Themis** (NOL8 FPGA literal matcher, `:443`) vs **Aergia** (Google
RE2 software incumbent, `:444`). NOL8 = **deterministic literal replacement only** (listMatch,
case-insensitive); NOT route/block/mask/enforce. Same policy + data + driver to every engine;
report divergence honestly, never rig. Path: **Argus** SaaS edge (`tenant001-v1demo.nol8.net`
`:443`/`:444`, now **10 nodes**) → Iris QUIC `:8443` → **Apollo** DPDK data plane → backend
(FPGA regexdev on themis / RE2 lexers on aergia). policyd/control `:8444`. 1 MB request cap.
Jamie has the Argus config URL/login + a troubleshooting doc.

## Hosts (SSH)

| host | what | reach |
|---|---|---|
| `nol8-demo` | driver/console box (aka data-streamer), m7a.2xlarge, 10.8.10.40 | reaches engines :443/:444; Go + venv + dp4driver. **Now the throughput ceiling (port exhaustion) at 70k+ rps.** |
| `themis-demo` | FPGA backend, f2.6xlarge, 24 cores, AFI loaded | Mac only |
| `aergia-demo` | RE2 backend, 32 cores | Mac only |
| `hydra-demo` | obs/fleet dashboard (Alon's box) | my key NOT authorized |

Repo: Mac `~/Code/nol8/nol8-validation`, EC2 `/opt/nol8/nol8-validation`. **results/ is
gitignored** (raw CSVs there don't sync/reach repo — copy evidence to `artifacts/evidence/`,
which IS tracked). Announce before git. Brand guide `~/Code/nol8/nol8-brand-guide` (charcoal
`#404040`, green `#33B046`, Google Sans, dark web mode).

## Operational lessons from today (don't repeat)

- **ssh-foreground held by a background task dies on a VPN/laptop flap** (no PTY → remote
  lingers then dies). Use **tmux/screen/nohup on the box** for any run > a minute.
- **`nohup … &` and `cat > file <<EOF` over ssh get blocked by the auto-mode classifier.**
  Write scripts locally + scp, or run via tmux; don't fight the classifier.
- **Copy raw CSVs to `artifacts/evidence/` immediately after a run**, not as a final step —
  today's run died before its copy step and the data was almost stranded on EC2.

## Demo console — BUILT, PARKED (resume after the brief rewrite)

`demos/showcase/console/` (stdlib server + on-brand dark UI on nol8-demo, `bash
console/run.sh`, tunnel `ssh -f -N -L 8770:localhost:8770 nol8-demo`). Catalog (18 prompts),
both-engines side-by-side redaction, corpus batch, scale mode, efficiency panel. **The scale
number should be re-based on the 10-Argus reality once the clean sweep is in.** Demo-flow the
UI should walk: generate data→show sample; generate policy→show slice; deploy→confirm applied;
run; results. Also `demos/showcase/` CLI tour (redact/usecases, oracle-verified) + RUNBOOK.

## Next-next (agenda, after DP4 is buttoned up)

- Shareable static dashboard (Artifact) of the DP4 story.
- Full agentic demo (mesh + pre-index repos) across the 3 use cases.

## Memories to respect

Substitution-not-enforcement; benchmark-integrity-no-rigging; announce-before-git;
demos-must-be-SA-runnable; avoid Hydra/Grafana dependency (self-contained tooling);
"update the project" = rewrite this file wholesale.
