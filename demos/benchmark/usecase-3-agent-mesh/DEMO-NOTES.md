# Data Point 3 - agent-to-agent mesh control: demo notes

What DP3 proves, how to run it, and the honest scope. DP3 is DP2 generalized from two
control points to many: NOL8 at every hop of an agent workflow.

## What NOL8 actually does (read this first)

NOL8 does **deterministic literal replacement only** - text in, text out. That gives two
honest families of action, and the demo keeps them separate:

- **LIVE today (NOL8 transforms the data, oracle-verified):**
  - **redact** - replace a known value with a marker (`Project Maple Vault` -> `[REDACT]`)
  - **mask** - replace a known value with a usable stand-in (`4111 1111 1111 1111` -> `XXXX 1111`, last four kept)
  - **drop** - remove a known value entirely (a fraud-denylisted card -> gone). Drop is real; it is DP1's strip.
- **ROADMAP (NOL8 emits a signal; a control plane enforces; native enforcement later):**
  - **route** - flag for a controlled path (`Contoso Advisory` -> `[ROUTE]`)
  - **block** - flag to refuse (`Ignore prior safeguards` -> `[BLOCK]`)

**NOL8 does not route, block, or stop a message today.** It emits the signal and the
redacted text flows on. The report marks route and block `Roadmap`. Do not say NOL8
"routed" or "blocked" - say it emitted a signal a control plane acts on.

## The claim (from one clean run on live Themis, 13 tasks)

- **Least privilege at every hop.** NOL8 strips the known sensitive values from the
  message the next agent receives: **8 secrets redacted, masked, or dropped** (6 / 1 / 1),
  and **16% less content delivered downstream** (878 -> 737 tokens).
- **Verified.** `themis_api_mesh` reproduces an independent oracle **13 / 13 tasks, event
  for event** (`verify-oracle.py`).
- **Signals for the roadmap.** NOL8 emits **3 route and 3 block** signals a control plane
  can act on; native enforcement is on the roadmap.

The 16% reduction is from **redaction alone** - nothing is stopped today. Native route and
block enforcement (roadmap) would stop diverted and refused work and deliver far less;
that larger reduction is roadmap-projected, not claimed as today.

## How the oracle works

DP3's flow is stateful (redactions carry forward), so `verify-oracle.py` **re-simulates
the whole mesh flow** with the framework's Aho-Corasick matcher over `mesh.nol` and the
`mesh-actions.json` action map, then compares the engine's events to the oracle's one for
one. The orchestration is shared; the thing verified is the engine's literal matching and
replacement at each hop. Themis == oracle, 13/13.

## Honest scope (say this out loud)

- **listMatch only. Literal, case-insensitive.** No regex, no patterns. Regex is on the
  NOL8 roadmap; it is not in this demo.
- **Substring-exact, so it can over-trigger.** One task is a deliberate near-miss:
  "Contoso Advisory **Board**" contains the flagged literal "Contoso Advisory", so it is
  signalled. That is the honest boundary of listMatch. ("Project Maple **Syrup**" vs the
  protected "Project Maple Vault" correctly does not match - different words.)
- **Masks are capped at 15 characters (ISSUE-005),** our own documented truncation bug, so
  the card mask is compact (`XXXX 1111`), not a full 16-character PAN. Honest, and a live
  reminder we know our engine's limits.
- **Drop removes the value.** For "route while preserving the value," replace-only is
  lossy - which is exactly why native routing (that keeps the value) is roadmap.
- **The agents are deterministic stubs,** not real models. Not a model-quality or
  throughput test.

## Reproduce (SA-runnable, on EC2)

```bash
# 0. preflight - Themis :443 must be green
bash demos/check-engines.sh

# 1. regenerate the mesh policy + action map (safe: ISSUE-004/005 guards)
python demos/policies/build_mesh_policy.py    # -> demos/policies/mesh.nol, mesh-actions.json

# 2. deploy + run nocontrol and live Themis, combine, oracle-verify
bash demos/benchmark/usecase-3-agent-mesh/run-live.sh

# 3. (verify only) adjudicate the engine output against the oracle
python demos/benchmark/usecase-3-agent-mesh/verify-oracle.py \
  --policy demos/policies/mesh.nol \
  --actions demos/policies/mesh-actions.json \
  --results demos/benchmark/usecase-3-agent-mesh/results \
  themis_api_mesh
```

## The report

```bash
python demos/benchmark/make-report.py \
  demos/benchmark/usecase-3-agent-mesh/run.json \
  demos/benchmark/usecase-3-agent-mesh/agent-mesh-report.html
```

Self-contained HTML (fonts/logos inlined), web (dark) / deck (Export to PDF, light).
`run.json` (`kind: dp3`) carries the numbers; regenerate the HTML after any edit. Rendered
HTML is gitignored.

## Next

- **RE2 parity on the new action model** - update the in-process RE2 baseline (and the
  networked Aergia :444 baseline when it returns) to redact/mask/drop/route/block, to add
  the incumbent-comparison column.
- **Representative insurer mesh** - a DP3 representative dataset mirroring DP2's
  `representative/` set, the near-term bridge to the agentic insurance story. The full
  experience lives in Track B (agentic-mesh-lab), which consumes DP3's wiring and numbers.
- **Native route/block enforcement** - the roadmap items that turn today's signals into
  enforcement.
