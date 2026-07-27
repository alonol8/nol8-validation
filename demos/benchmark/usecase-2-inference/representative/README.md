# DP2 representative-policy dataset

A **second** DP2 dataset that sits alongside the functional-test set in
`../data/`. They do different jobs; keep them distinct.

| dataset | job |
|---|---|
| `../data/` (functional-test) | known input, known expected action, oracle-verifiable. Proves the mechanism works and the engines agree. Its counts describe the TEST HARNESS, not a customer. |
| `representative/` (this) | a realistic customer policy and traffic. Shows what a real pre/post-inference deployment actually governs, so the demo is strategically honest, not self-fulfilling. |

## The scenario

A mid-size insurer's internal **claims-support assistant** ("Northwind Mutual").
The policy is the *known* things this customer has decided to govern at the model
boundary, which is exactly the listMatch sweet spot: **the deterministic guardrail
for known policy.**

Reference lists (`reference_lists/`, same filenames the harness reads):

| list | sentinel | what it is |
|---|---|---|
| `block_phrases` | `[BLOCK]` | curated exfil / jailbreak strings this team never allows |
| `route_phrases` | `[ROUTE]` | controlled-workflow triggers (legal hold, subpoena, regulatory) |
| `flagged_customers` | `[ROUTE]` | customers requiring controlled handling |
| `denied_entities` | `[ROUTE]` | denied / sanctioned parties |
| `payment_cards` | `[MASK_CARD]` | specific card numbers on file |
| `account_ids` | `[MASK_ACCT]` | specific claim / policy IDs |
| `internal_projects` | `[TAG_INT]` | internal project codenames |
| `output_block_phrases` | `[BLOCK_OUT]` | markers of an unsafe generation to stop on the way out |
| `output_tag_phrases` | `[TAG_PRIV]` | privileged-output markers |

Traffic (`prompts/prompts.jsonl`, 24 prompts) is shaped like real assistant
traffic: mostly benign, with a realistic minority hitting the policy, plus two
**false-pressure** rows (`rep_0011`, `rep_0012`) that look risky but must NOT fire
(they mention "previous instructions" and a "Harbor Point" name that are not the
exact governed literals). These test that deterministic matching does not
over-trigger.

## Honest scope

This is still **known values only** (listMatch). It does NOT cover novel prompt
injection, arbitrary card patterns, or classification. Those are a complementary
probabilistic layer, out of scope today (regex is on the NOL8 roadmap). The point
of this dataset is to show a *realistic known-value policy*, not to claim coverage
of the fuzzy problem.

## Run it (SA-runnable, on EC2)

```bash
# 1. build the representative policy from these lists
python demos/policies/build_boundary_policy.py \
  --list-dir demos/benchmark/usecase-2-inference/representative/reference_lists \
  --output demos/policies/boundary-representative.nol

# 2. deploy it to both engines and run all modes against the representative traffic
POLICY=demos/policies/boundary-representative.nol \
DP2_INPUT="$PWD/demos/benchmark/usecase-2-inference/representative/prompts/prompts.jsonl" \
DP2_LISTS="$PWD/demos/benchmark/usecase-2-inference/representative/reference_lists" \
DP2_RESULTS="$PWD/demos/benchmark/usecase-2-inference/representative/results" \
  bash demos/benchmark/usecase-2-inference/run-live.sh

# 3. adjudicate the engines against the oracle for THIS policy
python demos/benchmark/usecase-2-inference/verify-oracle.py \
  --policy demos/policies/boundary-representative.nol \
  --results demos/benchmark/usecase-2-inference/representative/results \
  themis_api_infer aergia_api_infer
```

Results (`representative/results/`) are gitignored. Expect the same shape as the
functional-test run: Themis and Aergia byte-for-byte identical, both matching the
oracle, because the boundary policy redacts to sentinels (no strip-to-empty).
