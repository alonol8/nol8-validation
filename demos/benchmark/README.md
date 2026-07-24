# NOL8 benchmark demos - run it yourself

Three data points that measure NOL8 (Themis, FPGA) against Aergia (our stand-up of Google
RE2, the incumbent), on the **identical literal policy**, adjudicated against an independent
oracle. Everything here is measured on the **live engines**, not simulated.

Each data point is self-contained: its own runner (`run-live.sh`), notes (`DEMO-NOTES.md`),
policy, and report. Start with the preflight, then run whichever data point you want.

## What NOL8 does (the honest action model)

NOL8 does **deterministic literal replacement only**. That gives two families of action,
and the reports keep them separate:

- **LIVE today (NOL8 transforms the data, oracle-verified):** **redact** (`value -> [REDACT]`),
  **mask** (`card -> XXXX <last4>`), **drop** (`value -> removed`).
- **ROADMAP (NOL8 emits a signal a control plane acts on; native enforcement later):**
  **route** (`-> [ROUTE]`), **block** (`-> [BLOCK]`).

NOL8 does not itself route, block, or stop a message today - it emits the signal and the
redacted text flows on. Reports mark route/block `Roadmap`. Scope is **listMatch (literal),
case-insensitive**; regex is on the roadmap, not in these demos.

## Two-host workflow

| | Mac | EC2 (`nol8-demo`, `/opt/nol8/nol8-validation`) |
|---|---|---|
| purpose | edit, commit, render reports | run against the live engines |
| why | no Go; can't reach the engines | has Go 1.22; reaches Themis :443 + Aergia :444 |

Edit + `git push` on the Mac, `git pull` + run on EC2. Reports render on either host.

## Step 0 - preflight (always run this first)

```bash
# on EC2
bash demos/check-engines.sh          # both engines must show all OK (6/6)
```

Deploys a harmless probe policy to each engine and confirms DNS + control-plane deploy +
data-plane round-trip. On failure it deep-probes and tells you whether it is the host, the
port, or a policy/propagation delay. (Tunables: `RELOAD_WAIT`, `ROUNDTRIP_TRIES`.)

## The three data points

| | Use case | Run (on EC2) | Notes |
|---|---|---|---|
| **DP1** | **Pre-index optimization** - clean text before it becomes embeddings | `bash demos/benchmark/run-live.sh` | [DEMO-NOTES.md](DEMO-NOTES.md) |
| **DP2** | **Pre/post-inference boundary** - keep secrets out of the model and the response | `bash demos/benchmark/datapoint2/run-live.sh` | [datapoint2/DEMO-NOTES.md](datapoint2/DEMO-NOTES.md) |
| **DP3** | **Agent-to-agent mesh** - strip secrets at every hop of an agent workflow | `bash demos/benchmark/datapoint3/run-live.sh` | [datapoint3/DEMO-NOTES.md](datapoint3/DEMO-NOTES.md) |
| **DP4** | **Throughput at load** - sustained req/s + latency tail as concurrency climbs | `bash demos/benchmark/datapoint4/run-live.sh` | [datapoint4/DEMO-NOTES.md](datapoint4/DEMO-NOTES.md) |

Each `run-live.sh` deploys the policy, runs the modes, prints a combined CSV, and (DP2/DP3)
adjudicates the engines against the oracle. DP2 and DP3 use the honest action model above;
DP1 is the pre-index optimization flow (redact/drop for embedding cost + governance). DP4 is
different in kind: it proves **capacity, not correctness** - a concurrency x payload sweep on
the same 5,000-rule literal policy, driving each engine to saturation and reporting the whole
throughput-latency curve (no pre-set win target). It is the run that shows where the FPGA
pulls ahead of RE2 under load - or, honestly, where the network still dominates. Expect ~24
min per engine for the full default sweep; dial it down with the `DP4_*` env knobs.

**Latest live results (2026-07-23):**
- **DP2:** Themis == Aergia == oracle, **53/53**; 25 secrets stripped (redact + last-4 mask).
- **DP3:** Themis == Aergia == oracle, **13/13**; 8 secrets stripped (redact/mask/drop); 878 -> 737 downstream tokens.

### Getting the Aergia/RE2 parity column

DP2's runner includes Aergia by default. DP3 defaults to Themis-only; add Aergia with:

```bash
MODES="nocontrol themis_api_mesh aergia_api_mesh" bash demos/benchmark/datapoint3/run-live.sh
```

### Regenerating a policy (optional - the committed `.nol` files are ready to run)

```bash
python demos/policies/build_boundary_policy.py   # DP2 -> boundary.nol + boundary-actions.json
python demos/policies/build_mesh_policy.py        # DP3 -> mesh.nol + mesh-actions.json
```

Both refuse an unsafe policy (over-length replacement = ISSUE-005; contained literals =
ISSUE-004). The `*-actions.json` sidecar is the action map the engine mode and oracle read.

## The reports

```bash
# render on either host (self-contained HTML: web = dark, deck = Export to PDF = light)
python demos/benchmark/make-report.py demos/benchmark/datapoint2/run.json demos/benchmark/datapoint2/pre-post-report.html
python demos/benchmark/make-report.py demos/benchmark/datapoint3/run.json demos/benchmark/datapoint3/agent-mesh-report.html
```

The shared renderer dispatches on `run.json`'s `kind` (default DP1, `dp2`, `dp3`). `run.json`,
`make-report.py`, and `brand/` are tracked; results and rendered HTML are gitignored.

## What's tracked vs generated

Tracked: source, corpus/reference lists, `.nol` policies + `*-actions.json`, `run.json`,
notes. Gitignored: everything under `**/results/`, the Go binaries and `.gocache/`, and the
rendered `*-report.html`.
