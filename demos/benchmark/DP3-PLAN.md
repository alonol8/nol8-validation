# Data Point 3 - Agent-to-Agent Control, plan

Planning only. No DP3 code exists yet in this repo; this is the build spec for the
next real pass. DP3 is DP2 generalized from two control points to many: governance
at every hop in an agent workflow.

## Two tracks (keep them distinct)

1. **DP3 kit benchmark (Track A, our next build).** A deterministic, measured
   benchmark that proves governance survives an agent chain, run on the live engines,
   oracle-verifiable. Fits `demos/benchmark/` exactly like DP1 and DP2. This is what
   "DP3" means in our benchmark line.
2. **agentic-mesh-lab (Track B, separate, larger, user-driven).** A richer visual
   demo (`~/Code/nol8/agentic-mesh-lab`): side-by-side traditional-vs-Nol8 insurance-
   claim workflow with a UI, currently mostly PRD/architecture docs. It is the
   *experience*; DP3 is the *proof*. The lab consumes DP3's engine wiring, policy, and
   numbers. Do not conflate them: DP3 is a benchmark, the lab is a demo app.

The lab's framing should shape DP3 (see "What the lab tells us" below), but building
the lab is out of scope for the benchmark line and much bigger (frontend/backend/UI).

## The DP3 kit benchmark

Kit pack: `~/Code/nol8/preindex-benchmark-kit/usecase-3-agent-mesh_agent_mesh_pack_v1`
(copy OUT into `demos/benchmark/usecase-3-agent-mesh/`, non-destructive, when we start).

**Flow:** `User Task -> Triage -> Research -> Decision -> Action -> Final Response`.
Governance is applied at three kinds of control point:
- **handoff** - an agent-to-agent message (actions: allow, mask, tag, route, block_handoff)
- **tool** - a tool call (actions: allow, block_tool)
- **final** - the final output leaving the mesh (actions: allow, tag, block)

**Dataset:** `data/tasks/sample_agent_tasks.jsonl` (each task: user_task,
expected_mesh_action, expected_final_action, agent_stub_profile). `data/policies/`
holds literal reference lists: account_ids, payment_cards, denied_entities,
flagged_customers, internal_projects, blocked_tool_phrases, output_block_phrases,
output_tag_phrases. All literal, so listMatch-compatible (same as DP2, overlapping
lists).

**Kit modes:** `nocontrol`, `re2_mesh` (regex), `listmesh` (literal, our analog),
`nol8sim_agent` (expected-action oracle sim). No real-engine mode yet.

### The build (mirrors DP2 step-for-step)

1. **Mesh policy generator** - mirror `build_boundary_policy.py`. Read the DP3
   `data/policies/` lists, emit `demos/policies/mesh.nol` mapping each literal to a
   sentinel. Reuse the ISSUE-005 (<=15 char) / ISSUE-004 (containment) guards. Likely
   sentinels: `blocked_tool_phrases -> [BLOCK]`, `denied_entities`/`flagged_customers
   -> [ROUTE]`, `payment_cards -> [MASK_CARD]`, `account_ids -> [MASK_ACCT]`,
   `internal_projects -> [TAG_INT]`, `output_block_phrases -> [BLOCK_OUT]`,
   `output_tag_phrases -> [TAG_PRIV]`. The STAGE disambiguates: `[BLOCK]` at a tool
   call means block_tool; at a handoff it means block_handoff. (These lists overlap
   DP2's boundary lists heavily; a shared generator could serve both, but keep them
   separate files for clarity unless it gets unwieldy.)

2. **Real-engine modes** `themis_api_mesh` / `aergia_api_mesh` - copy the DP2 pattern
   (`engine_infer.go` -> `engine_mesh.go`): call the engine directly at each stage,
   derive the per-stage action from the sentinel. Same `callEngineProcess`
   (`{message}->{result.message}`), same THEMIS_ENDPOINT/AERGIA_ENDPOINT env, no
   adapter. Generalize the derive functions per stage (handoff/tool/final).

3. **run.json + report** - `kind: dp3`, reuse `make-report.py`. New "mesh flow"
   section: an agent chain (Triage->...->Action->Final) with a governance badge at
   each hop; a few example task flows (block_tool, mask-at-handoff, route, block-final)
   using the existing `flows`-style cards (badges already support these actions -
   extend the color map for block_handoff/block_tool). Reuse hero/stat-band/meaning/
   method/footer.

4. **Oracle-verify** - generalize `usecase-2-inference/verify-oracle.py`: framework Aho-Corasick
   matcher on `mesh.nol`, applied at each stage, derive expected per-stage actions,
   compare byte-for-byte. Expect the same result shape as DP2 (Themis == Aergia ==
   oracle, since mesh.nol also redacts-to-sentinel, not strip-to-empty).

5. **DEMO-NOTES + SA runbook** - model on DP2's. Same honesty guardrails carry over
   (listMatch scope, exact case-sensitive matching, tag=redact-to-marker, stub not a
   model).

### Metrics (what DP3 measures)

- Per-stage action counts: handoffs masked/routed/blocked, tool calls blocked, final
  outputs blocked/tagged. "Governance survives the whole chain."
- **Payload reduction across hops** - the lab's "reduction before delivery" principle.
  Measure the payload each downstream agent RECEIVES vs a no-control baseline: the mesh
  forwards less to each agent. This is DP1's ship-less story generalized to an agent
  chain and is likely the strongest DP3 headline. Decide with the user (see below).
- Parity + correctness: Themis == Aergia, both == oracle (the DP1/DP2 trust result).

## What the lab tells us (informs DP3's shape)

- **"Nol8 is an AI Data Plane that governs communication between agents"** - DP3's
  headline framing: govern every hop, inline, deterministically. Not an agent
  framework, a control plane in the path.
- **"Reduction before delivery: downstream agents receive only the context they
  need"** - push DP3 to measure payload reduction across hops, not just action counts.
- **Insurance-claim scenario** - the lab's narrative. DP3's kit tasks are generic
  enterprise agent tasks; keeping them is fine for the benchmark. Optionally reframe a
  few example task flows toward the claim scenario for continuity with the lab, but do
  not rebuild the dataset for it.

## Decisions (resolved 2026-07-23) and build progress

- **Headline: BOTH** - governance-survives-the-chain as the trust anchor PLUS
  payload-reduction-across-hops as the differentiator. Needs token instrumentation in
  the harness (downstream tokens delivered per hop; reduction vs the nocontrol row).
- **Scenario: keep the kit's generic enterprise tasks** for the DP3 benchmark. The
  insurance/agentic story is sequenced separately: (1) DP2 already plants it (the
  representative set is insurer "Northwind Mutual"); (2) near-term bridge = a DP3
  *representative* insurer-agent-mesh dataset mirroring DP2's representative set (reuses
  all wiring, no rewrite of the functional-test dataset); (3) flagship = Track B
  (agentic-mesh-lab), the full UI experience that consumes DP3's numbers, scheduled once
  DP1-3 are locked. Proof -> coherent insurer thread -> full experience.
- **ISSUE-004 curation:** our copy of `blocked_tool_phrases.txt` drops "external
  distribution" because it is a substring of the output-block phrase "external
  distribution package"; a single deployable policy cannot hold both (overlapping
  literals corrupt, ISSUE-004). No task outcome changes - it was never the decisive
  trigger. Documented in DEMO-NOTES.
- **Sentinel map:** `[BLOCK_TOOL]` (tool->block_tool), `[BLOCK_HAND]` (handoff->
  block_handoff), `[ROUTE]` (flagged+denied), `[MASK_CARD]`, `[MASK_ACCT]`,
  `[BLOCK_OUT]` (final->block), `[TAG_PRIV]` (final->tag). Unique per action, all <=15.
- **Three honest listMatch behaviours the oracle surfaced** (all are oracle-vs-dataset-
  label, NOT oracle-vs-engine - the engine reproduces the oracle, so engine==oracle
  still holds; these go in DEMO-NOTES as the deterministic guardrail's real edges):
  1. **Substring false-positive:** "Contoso Advisory Board" (task_0011) contains the
     flagged-customer literal "Contoso Advisory" -> routes when it shouldn't. (Contrast
     task_0012: "Project Maple Syrup" does NOT match "Project Maple Vault" - listMatch
     passes the different-words near-miss, trips the containment one. Word-boundary
     regex / classification, on the roadmap, is where this is solved.)
  2. **Precedence:** a task naming a flagged customer (task_0004) routes at the handoff
     before its tool-block phrase is evaluated - route wins over block_tool.
  3. **Sentinel carry-forward:** a value masked at a handoff stays `[MASK_CARD]` in the
     final text, so the final stage also reports "mask" (task_0002/0003) - honest, the
     output is masked, just not the "allow" the label expected.

**Build status (2026-07-23):** pack copied to `usecase-3-agent-mesh/`; lists curated;
`build_mesh_policy.py` -> `mesh.nol` (17 rules, guard passes); `engine_mesh.go` +
`main.go` dispatch written (needs EC2 to compile - no Go on Mac); `verify-oracle.py`
(full-flow re-simulation oracle) written and its flow logic validated on Mac. TODO:
token/payload instrumentation for the BOTH headline; run.json (`kind: dp3`) + the
make-report.py dp3 path; run-live.sh; DEMO-NOTES; then one EC2 pass (compile, live
Themis run - :443 is back, oracle-verify, render). Aergia parity column waits on :444.

## Open decisions for the user (before the build) [RESOLVED ABOVE]

1. **DP3 headline:** payload reduction across hops (reduction-before-delivery), or
   governance-survives-the-chain (block/mask/route/tag at every hop), or both.
2. **Scenario:** keep the kit's generic agent tasks, or reframe example flows toward
   the insurance-claim scenario to line up with the lab.
3. **The DP2 stats conversation** almost certainly applies to DP3 too (same metric
   families) - resolve it once, apply to both.
4. **Track B (the lab)** - is it a near-term deliverable, or does it wait until the
   benchmark line (DP1-3) is complete. It is a much larger build.

## Reuse vs new

- **Reuse:** policy-generator pattern, the engine-mode pattern (direct Go engine
  calls), the report renderer (add a dp3 path), the oracle-verify discipline, all the
  honesty guardrails.
- **New:** `mesh.nol`, the per-stage engine wiring (`engine_mesh.go`), a mesh flow
  report section, per-stage + payload-reduction metrics, DP3 report copy.
