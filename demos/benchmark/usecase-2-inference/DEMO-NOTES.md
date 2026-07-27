# Data Point 2 - pre/post-inference control: demo notes

What DP2 proves, how to run it, and the honest scope. DP2 governs a model boundary: what
reaches the model, and what leaves it.

## What NOL8 actually does (read this first)

NOL8 does **deterministic literal replacement only** - text in, text out. Two honest
families of action, and the demo keeps them separate (same split as DP3):

- **LIVE today (NOL8 transforms the data, oracle-verified):**
  - **redact** - replace a known value with a marker (`Project Aurora Ledger` -> `[REDACT]`)
  - **mask** - replace a known value with a usable stand-in (`4111 1111 1111 1111` -> `XXXX 1111`, last four kept)
- **ROADMAP (NOL8 emits a signal; a control plane enforces; native enforcement later):**
  - **route** - flag for a controlled path (`Contoso Advisory` -> `[ROUTE]`)
  - **block** - flag to refuse / do not call the model (`Ignore prior safeguards` -> `[BLOCK]`)

**NOL8 does not stop a prompt reaching the model, or withhold an output, today.** It
redacts/masks the text and emits the signal; the model is always called, on the redacted
prompt. The report marks route/block `Roadmap`. Never say NOL8 "blocked" or "routed" a
prompt - say it redacted/masked the data and emitted a signal a control plane acts on.

## The claim (one clean run on live Themis AND Aergia, 53 prompts)

- **Secrets never reach the model, or the response.** NOL8 redacts and masks known values
  at both edges: **25 secrets stripped** (4 prompts redacted + 1 card masked before the
  model; 20 outputs redacted before the response). Prompt tokens to the model 613 -> 562;
  output tokens released 566 -> 537.
- **Byte-identical to the incumbent, verified.** **Themis == Aergia == oracle, 53 / 53.**
  Aergia is our stand-up of Google RE2 (the incumbent). Both engines produced identical
  output at both edges, and both match an independent oracle.
- **Signals for the roadmap.** NOL8 emits **12 route + 14 block** signals a control plane
  can act on; native enforcement is on the roadmap.

## How the oracle works

`verify-oracle.py` independently computes the correct leftmost-longest replacement of
`boundary.nol` with the framework's Aho-Corasick matcher at each edge (prompt, then model
output), derives the action from the same `boundary-actions.json` action map, and compares
to what each engine produced - action and processed text, both edges. The thing verified
is the engine's literal matching and replacement. Themis == Aergia == oracle, 53/53.

## Honest scope (say this out loud)

- **listMatch only. Literal, case-insensitive.** No regex, no patterns. Regex is on the
  roadmap; it is not in this demo.
- **Substring-exact, so it can over-trigger.** A value can match inside a longer phrase
  that contains it. Word-boundary regex and classification are the roadmap layer.
- **Masks are capped at 15 characters (ISSUE-005),** our own documented truncation bug, so
  the card mask is compact (`XXXX 1111`), not a full 16-character PAN.
- **Precedence is deterministic.** A prompt naming a flagged customer AND a card signals
  route (stronger control) rather than masking the card - route beats mask. That is
  defensible ordering, and one prompt in the set demonstrates it.
- **The model is a deterministic stub,** not a real model. Not a model-quality or
  throughput test.

## Reproduce (SA-runnable, on EC2)

```bash
# 0. preflight - both engines reachable (Themis :443, Aergia :444)
bash demos/check-engines.sh

# 1. regenerate the boundary policy + action map (safe: ISSUE-004/005 guards)
python demos/policies/build_boundary_policy.py   # -> boundary.nol, boundary-actions.json

# 2. deploy + run nocontrol, Themis, Aergia; combine; oracle-verify both engines
bash demos/benchmark/usecase-2-inference/run-live.sh

# 3. (verify only) adjudicate the engine output against the oracle
python demos/benchmark/usecase-2-inference/verify-oracle.py \
  --policy demos/policies/boundary.nol \
  --actions demos/policies/boundary-actions.json \
  --results demos/benchmark/usecase-2-inference/results \
  themis_api_infer aergia_api_infer
```

## The report

```bash
python demos/benchmark/make-report.py \
  demos/benchmark/usecase-2-inference/run.json \
  demos/benchmark/usecase-2-inference/pre-post-report.html
```

Self-contained HTML (fonts/logos inlined), web (dark) / deck (Export to PDF, light).
`run.json` (`kind: dp2`) reuses the mesh/mesh_flows sections; regenerate after any edit.
Rendered HTML is gitignored.

## Representative set

`representative/` (insurer "Northwind Mutual") is the realistic-policy companion to this
functional-test set. Its generator and run-live overrides still need updating to the new
action model (a pending follow-up), the same as the DP3 representative set.
