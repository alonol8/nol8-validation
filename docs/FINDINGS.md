# Findings Register

Date: 2026-07-20
Status: living document - the single index of everything we have found

**Start here.** Every finding has a stable ID, a one-paragraph explanation, and
a pointer to the detail. Nothing is duplicated: this file says *what* and *why
it matters*; the linked documents carry evidence and reproduction.

Findings are split by who owns the fix.

- **THM-n** - the Themis runtime and its APIs. Engineering owns these.
- **OPS-n** - the operator tooling shipped with it (`nolctl`, service units,
  the troubleshooting guide). Engineering owns these too, but they are a
  different component and a different fix.
- **FW-n** - our validation framework. We own these.
- **OBS-n** - observations deliberately *not* raised as findings, recorded so
  they are not rediscovered and re-escalated.

---

## Summary

### Themis runtime - THM

These are the internal IDs. Each maps to an engineering-facing, sendable report
in `docs/issues/` (`ISSUE-NNN`), aligned 1:1 — **ISSUE-N = THM-N**.

| ID | Ext. | Finding | Severity | Status |
|---|---|---|---|---|
| THM-1 | ISSUE-001 | A deployed policy has no identity | High | Open, not reported |
| THM-2 | ISSUE-002 | Deployment replaces the entire ruleset | High | Open, not reported |
| THM-3 | ISSUE-003 | Deployment is fire and forget | Medium | Open, not reported |
| THM-4 | ISSUE-004 | Overlapping matches corrupt output | **High** | Open, **eng doc ready** |
| THM-5 | ISSUE-005 | Replacements truncate at 15 characters (KB-001) | Medium | Open, worked around |
| THM-6 | ISSUE-006 | Evaluation environment unreachable externally | High | Open, not reported |
| THM-7 | ISSUE-007 | No way to check whether the runtime is healthy | Medium | Open, not reported |
| THM-8 | - | The engines disagree on overlapping-match semantics | **High** | Open, needs an engineering answer |
| THM-9 | - | Themis: 2 divergent responses in 2.14M under load | Unknown | Open, uncharacterised |

### Operator tooling - OPS

| ID | Finding | Severity | Status |
|---|---|---|---|
| OPS-1 | `nolctl doctor` false-fails on kernel parameters | Medium | Open, found 2026-07-20 |
| OPS-2 | Service status string never updates after startup | Medium | Open, found 2026-07-20 |
| OPS-3 | Troubleshooting guide omits "paused awaiting policy" | Medium | Open, found 2026-07-20 |

### Our framework - FW

| ID | Finding | Severity | Status |
|---|---|---|---|
| FW-1 | Could report success it had not verified (Tier 0) | Critical | **Fixed** |
| FW-2 | Blamed Themis for its own expected-output bugs (Tier 1) | Critical | **Fixed** |
| FW-3 | `compare` scored unverifiable records as PASS | High | **Fixed** |
| FW-4 | Transports source a committed config file (Tier 2) | Medium | **Fixed** |
| FW-5 | Caller environment silently overridden by config | Medium | **Fixed** |
| FW-6 | Failing reports are unusable at scale (Tier 4) | Medium | Fixed |
| FW-7 | Generation depends on YAML key order (T1-6) | Low | Fixed |
| FW-8 | Policy tests polluted the real deployment ledger | Low | **Fixed** |
| FW-9 | Bearer token exposed on the command line (T2-3) | Medium | **Fixed** |
| FW-10 | Dead transport scripts had unauthenticated/plaintext paths (T2-4/T2-5) | Low | **Fixed** |
| FW-11 | Scattered atomic writes + crash-prone JSONL reader (T5-1) | Low | **Fixed** (layer-split deferred) |

### Observations - OBS

| ID | Observation | Disposition |
|---|---|---|
| OBS-1 | Control plane TLS is self-signed | **Not a finding.** Do not re-promote |
| OBS-2 | Processed payload returns to the caller | **Open question**, not a defect |
| OBS-3 | Run artifacts are plaintext (T2-4) | **Accepted residual.** Synthetic data only |

---

# THM - Themis runtime

Full detail: `docs/product/themis-product-limitations.md` (numbered 1-7 there,
matching THM-1 to THM-7).

## THM-1 - A deployed policy has no identity

You can post a policy. You cannot ask what policy is loaded. No identifier, no
version, no content hash, no deployed-at, no way to read the body back.

**Why it matters:** during an incident the first question is "what rules were
active?" That is unanswerable from the product. It also means a deployed policy
cannot be exported, diffed, or restored - if the source file is lost, the
enforcing ruleset is unrecoverable.

**Felt in practice 2026-07-20:** restoring the environment after an outage
required the copy we had kept ourselves, because the product could not tell us
what had been there.

## THM-2 - Deployment replaces the entire ruleset

Posting a policy replaces everything (`persisted, REPLACE`). No namespace, no
partial update, no rollback, no dry run.

**Why it matters:** multi-tenancy is unsafe on shared credentials; every change
is a full redeploy, which is exactly the operation most likely to introduce the
overlapping literals that trigger THM-4; a bad policy is either a DLP outage or
silent under-redaction.

## THM-3 - Deployment is fire and forget

The deploy call returns on acceptance. `command_id` and `stage: apollo` imply
asynchronous distribution, but nothing reports convergence and nothing can be
polled.

**Why it matters:** records sent immediately after deployment may be evaluated
against the previous policy. Results can look correct while being produced by
the wrong rules - the dangerous case, because nothing indicates it.

## THM-4 - Overlapping matches corrupt output

**The headline finding.** When two rules match overlapping regions of the
input, the runtime computes the wrong match start offset and destroys content
preceding the match. Silent. HTTP 200 every time.

```
rules   "ABCD" -> "[P]"  and  "DEFG" -> "[Q]"
input    x ABCDEFG y
correct  x [P]EFG y
actual   x [P[Q] y
```

**Why it matters:** this is ordinary policy authoring, not an exotic edge case.
Redacting both `"Acme Corp"` and `"Acme Corporation"` triggers it. Reproduces
with curl alone - two rules and one record.

- **Ready to send:** `docs/issues/ISSUE-004-overlapping-matches-corrupt-output.md`
  (self-contained, inline curl, safe to attach to an email)
- Detail and evidence: `docs/issues/internal/ISSUE-004-corruption-investigation.md`
- Authoring constraint: `docs/issues/internal/KNOWN_BEHAVIORS.md`

## THM-5 - Replacements truncate at 15 characters

Replacement strings longer than 15 characters are truncated at runtime.
`[FINANCIAL:CREDIT_CARD_NUMBER]` is emitted as `[FINANCIAL:CRED`.

**Why it matters:** tokens sharing a 15-character prefix become
indistinguishable in output, so a reader cannot tell which rule fired. That
silently degrades auditability, and it is what made FW-3 possible.

Detail: `docs/issues/internal/KNOWN_BEHAVIORS.md` (KB-001).

## THM-6 - Evaluation environment unreachable externally

Reachable only inside the VPC, via VPN and in practice an SSH session.

**Why it matters:** an agent, CI pipeline, customer sandbox, or partner
integration cannot establish a VPN or drive SSH. Agent-mediated integration is
the fastest-growing category of buyer interest for a product sitting in front
of models, and it currently cannot be demonstrated at all.

Framed as demonstrability, not as criticism of the security posture.

## THM-7 - No way to check whether the runtime is healthy

No health, readiness, or status endpoint. Verified, not assumed: the data plane
host publishes one port, and `/v1/process` is the only route on it - 16
candidate health paths all 404 while `GET /v1/process` returns 405.

**Why it matters:** the only way to learn the engine is not serving is to send
real traffic and have it fail. A long run starts normally and produces nothing
but execution failures.

**The 2026-07-20 outage is the case study.** Apollo boots with its data plane
paused and un-pauses only when a policy commits. None had been deployed since
the last restart, so every request 503'd for an hour. The system was **one API
call from working**, and no signal said so - see OPS-1 to OPS-3 for why the
tooling actively misled. A health endpoint reporting *policy-load state*, not
just liveness, would have made it a thirty-second fix.

**Mitigated our side:** `validate run` now pre-flights with one throwaway
record and aborts with the remedy rather than generating a full run of
failures. It cannot distinguish paused from dead - nothing client-side can - so
it names both and leads with the cheap fix.

## THM-8 - The engines disagree on overlapping-match semantics

When two matches share a byte there are two self-consistent answers, and the two
engines pick different ones. On 500 real business emails under a policy of
space-delimited common words, Aergia reproduced one-byte-one-match 500/500 and
Themis reproduced every-match-fires instead.

```
rules " to " " me " " be " -> removed;  input "There seem to me to be two questions"
one-byte-one-match   "There seem me be two questions"
every-match-fires    "There seem    two questions"    <- Themis, byte for byte
```

**Why it matters:** neither engine is corrupting anything, so this is a
specification question rather than a defect - but until it is answered, a
validation framework cannot score an overlapping policy without choosing sides,
and the two engines cannot be claimed to produce identical output.

It stayed hidden because the identifier catalogs exclude overlapping literals by
construction. A policy of words overlaps in nearly every sentence.

Detail and reproduction: `docs/issues/internal/ENGINE-SEMANTICS.md` (ES-1).

## THM-9 - Themis: 2 divergent responses in 2.14 million under load

A verified load run found 2 responses out of 2,144,853 that did not match the
oracle; a repeat of the same cell found none. Only visible with full-coverage
verification - a sample of a few hundred would never see it.

**Why it matters:** possibly nothing, possibly a rare load-dependent fault. It is
recorded rather than reported because it is uncharacterised: nobody has yet
established whether it reproduces, whether it is load-dependent, or what the
divergent bytes were. Do not raise it until that is done.

Detail: `docs/issues/internal/ENGINE-SEMANTICS.md` (ES-3).

---

# OPS - Operator tooling

All three found while diagnosing the 2026-07-20 outage. Written up inside
THM-7 in `docs/product/themis-product-limitations.md`.

## OPS-1 - `nolctl doctor` false-fails on kernel parameters

Reports `FAIL preflight: missing hugepages=4, isolcpus=0-11, nohz_full=0-11,
rcu_nocbs=0-11` on a host correctly configured with `hugepages=16,
isolcpus=2-13, nohz_full=2-13, rcu_nocbs=2-13`.

It is string-matching one expected topology rather than checking the parameters
are present and sane.

**Why it matters:** it fails on a correct machine and points the operator at
GRUB and a reboot - expensive, disruptive, and wrong. It also trains people to
ignore doctor output, which defeats the tool.

## OPS-2 - Service status string never updates after startup

`systemctl show ares-apollo -p StatusText` still read `data plane PAUSED` after
the data plane was verified working. The orchestrator sets the string once at
startup and never revises it.

**Why it matters:** an operator trusting it would restart a healthy service.
Combined with OPS-1, the two tools most likely to be consulted both lie.

## OPS-3 - Troubleshooting guide omits "paused awaiting policy"

The guide attributes `ARGUS_UPSTREAM_UNAVAILABLE` to "most probably Apollo
encountered a severe bug" and prescribes restarting services. For this cause
that is wrong: the journal shows apollo restarted three times, each returning
to the same paused state.

**Why it matters:** this is the failure a *new evaluator* hits first, because a
fresh or restarted host has no policy yet. Following the guide produces the
same 503 and the reasonable conclusion that the product is broken.

**The actual fix**, worth adding to the guide verbatim:

```bash
printf '%s\n' '"SSN" -> "[REDACTED]";' > /tmp/minimal.nol
curl -sS --insecure -X POST "$THEMIS_POLICY_ENDPOINT" \
  -H "Authorization: Bearer $THEMIS_TOKEN" --data-binary @/tmp/minimal.nol
```

---

# FW - Our framework

Detail: `docs/CODE_REVIEW_PLAN.md`, tiered by risk.

## FW-1 - Could report success it had not verified (FIXED)

A 2xx response was treated as success regardless of content, and an empty
comparison rendered a green PASS. The framework could certify a product it had
never exercised.

Now: success requires a string message in the response; transport exit codes
map to categories; an empty comparison renders INCONCLUSIVE.

## FW-2 - Blamed Themis for its own bugs (FIXED)

Expected output was computed by scanning only the injected rules, not the full
catalog, so 415 of 10,000 documents contained literals the expectation missed -
recorded as Themis failures.

Now: full-catalog scanning via Aho-Corasick (`framework/policy/matching.py`),
and generation refuses catalogs containing nested literals.

## FW-3 - `compare` scored unverifiable records as PASS (FIXED)

Consequence of THM-5. Normalizing expected replacements to 15 characters is
what lets a comparison succeed against a truncating product - but where two
replacements share a prefix within that limit, truncation maps them onto the
same token, so a record where the *wrong* rule fired compared equal to one
where the right rule fired.

Now: colliding tokens are detected, affected would-be passes become
`INCONCLUSIVE`, and the report withholds an overall PASS while any exist.
Mismatches are deliberately untouched - truncation can only make messages look
more alike, so an inequality is still genuine evidence. Commit `ca5c377`.

**Proven closed end to end (2026-07-20).** Generation now refuses a catalog
whose tokens collapse under truncation, and qualification run
`20260720T193444152733Z` (5,000 rules / 10,000 records) returned 10,000 PASS
with **0 inconclusive** - verified against the manifest and by an independent
recount. The prior authoritative run had 4,755 transformations behind collapsed
tokens; this one has none.

## FW-4 - Transports sourced a committed config file (FIXED)

Both transports `source`d `config/demo.env`, which is tracked. Anyone who could
land a change to it got code execution plus the tokens loaded on the next line.

Now: `scripts/lib/env-config.sh` parses the file as `KEY=VALUE` rather than
executing it, so it can only set variables - never run commands - and rejects
any key outside an allowlist, so a tampered file cannot smuggle in `LD_PRELOAD`
or similar. Sourcing that library is fine: it is code we commit deliberately;
the distinction is data versus code. Commit `e7bdac5`.

## FW-5 - Caller environment silently overridden (FIXED)

Scripts sourced the config *after* the caller's environment, so
`THEMIS_ALLOW_INSECURE_TLS=0` on the command line had no effect.

Now: the loader leaves an already-set variable untouched - the file supplies
defaults, the caller wins. Verified live: overriding the endpoint on the
command line reaches the override, not the config value. Commit `e7bdac5`.

Fixing this exposed a latent bash 3.2 crash (an empty array expanded under
`set -u`) in `load-policy.sh`, since the `=0` path was previously unreachable;
the single `--insecure` flag is now a `${VAR:+"$VAR"}` string, safe on every
bash.

## FW-6 - Failing reports unusable at scale (FIXED)

Failing reports were 2.6 MB of undifferentiated blocks - one full-document
`<article>` per failing row, no diff, no grouping, no classification.

Now `framework/reporting/generate_report.py` classifies each failure by an
explainable diff-shape signature (`classify_failure`), groups by signature
(`group_failures`), and renders a summary table (signature | count | first
example) followed by at most three compact representatives per group
(`render_failure_section`). Each representative shows a windowed diff anchored
on the first divergence byte - short shared prefix, then capped expected/actual
tails - with the full messages kept only inside a collapsed `<details>`. Dropped
records are never silent: the group states "Showing 3 of N" and lists every
remaining record ID so traceability is complete.

Signatures describe the observed shape ("actual is a prefix of expected
(consistent with truncation)", "actual longer than expected", "execution
failure (HTTP 503)", ...), not a diagnosed cause - the reader infers the cause.

On a 252-failure / 3-signature render the failure section is ~15 KB with 9 full
examples, versus 252 full-document dumps before. INCONCLUSIVE records are still
excluded from failure details (neither pass nor product failure). Tests in
`tests/test_report_failure_grouping.py`, proven non-vacuous against the old
full-dump renderer. Divergence offset is computed from the live
`expected_message`/`actual_message`, not read from a field - live comparison
rows do not carry `divergence_offset`/`byte_delta` (only the curated
`issue-004-failure-sample.jsonl` does).

## FW-7 - Generation depends on YAML key order (FIXED)

Reordering keys in a workload config changed output for a fixed seed, because
`_weighted_item` (`framework/workload/generate_workload.py`) fed
`list(items.keys())` straight into `random.choices` - the draw walked the names
in dict insertion order, i.e. YAML key order. Any re-serialization with sorted
keys would have silently invalidated reproducibility.

Fixed by sorting the names into a canonical order before the draw
(`names = sorted(items.keys())`), so a catalog depends on the seed and the map
contents alone. Single-point fix; scale generation shares `_weighted_item` by
import, so both paths are covered.

Tests in `tests/test_generation_determinism.py`: reordered-but-identical config
now produces identical artifacts, with a non-vacuous guard that patches back the
old insertion-order draw and proves it diverged. Two brittle tests in
`tests/test_customer_record_csv.py` that pinned seed-42 incidental values (a
specific first-record case set, and `2000-01-01` appearing as a catalog DOB
literal) were generalized to assert their real invariants - the latter now
exercises the metadata/policy separation mechanism by forcing the collision.

**Reproducibility consequence (deliberate) - resolved by re-qualifying.** The
canonical sort changes what seed 42 produces, which briefly left the deployed
policy and the then-authoritative qualification `20260720T193444152733Z`
unreproducible from seed 42. Resolved the same session: a fresh 5,000/10,000
seed-42 bundle was generated under the current generator
(`overlapping_match_documents: 0`), deployed to Themis, and verified airtight
(10,000 PASS, 0 inconclusive) as the new authoritative run
`20260720T221534714262Z` (policy SHA `27fe47db...`). Evidence in
`artifacts/evidence/` is promoted; the prior policy `c3b763aa...` is superseded
history. The deployed policy again regenerates from seed 42.

## FW-8 - Policy tests polluted the real deployment ledger (FIXED)

`ValidatePolicyTests` ran the CLI policy-deploy path with a mocked transport but
did not isolate the ledger, so every suite run appended fixture deployments
(6 rules, targets themis/aergia) to the real `artifacts/policy-deployments.jsonl`.
On a development machine `validate policy --status` then listed those as if they
were real operator actions - the same class of dishonesty as the report bugs,
in the audit trail rather than the report.

Found while smoke-testing permissions. No real deployment ever occurred (the dev
machine cannot reach the VPC-internal control plane); it was purely a polluted
local ledger. Now: `setUp` patches `_policy_ledger_path` to a temp file, matching
the isolation the dedicated ledger test already used. Verified load-bearing - with
the patch removed, one suite run repolluted the real file.

## FW-9 - Bearer token exposed on the command line (FIXED)

Both transports (`scripts/load-policy.sh`, `scripts/run-validation.sh`) passed
the token as `-H "Authorization: Bearer $TOKEN"` in curl's argument list, where
any local user can read it via `ps` - once per record on the execution path.
Now each writes the header to a `0600` `mktemp` file and passes it with
`-H @file`, so the token is never an argv element while the request stays
authenticated; the file is removed by the existing exit trap. Verified live
against Themis (policy deploy 200, run 5/5) and by a transport test that resolves
`-H @file` and asserts the token appears in no argv element (T2-3).

## FW-10 - Dead transport scripts carried insecure paths (FIXED)

The Tier 2 review flagged unauthenticated processing calls (T2-5) and a
plaintext-writing execution path (T2-4). Both lived only in code the live path
does not use: `scripts/process-message.sh`, `framework/execution/run_functional_test.py`
(and the one-time `scripts/restructure-framework.sh` that referenced it). The
live path (`run-validation.sh`) authenticates and sanitizes. Resolved by deleting
the dead files outright - verified unreferenced by any live code or test. See
OBS-3 for the remaining T2-4 residual on live artifacts.

## FW-11 - Scattered atomic writes and a crash-prone JSONL reader (FIXED, pragmatic Tier 5)

`main.py` (~2,200 lines) had four hand-rolled atomic writes sharing two defects
the plan named (T5-1): fixed temp names (`.{name}.tmp`, collide between concurrent
writers) and no `fsync` (a crash could leave the target partial or not-yet-durable).
And an inline JSONL reader that called `json.loads` with no guard, so one torn
line surfaced a raw `JSONDecodeError` in a CLI summary.

Fixed: one `_atomic_write_bytes` primitive - unique `mkstemp` temp in the target
directory, `fsync` of the file and the directory around the rename - that
`write_manifest_atomic`, `_write_jsonl_atomic`, `_initialize_jsonl_atomic`, and
`_repair_jsonl_tail` all route through (its `0600` temp also leaves run artifacts
owner-only, aligning with OBS-3). `_read_cli_jsonl` is now robust (blank-tolerant,
skips non-objects, raises a clear file+line error surfaced as a clean message).

Also delivered under pragmatic Tier 5: **T5-2** an end-to-end pipeline test on a
real generated corpus (`tests/test_end_to_end_pipeline.py`), catching inter-stage
schema drift the fixture-based stage tests could not; **T5-3** hermetic transport
tests via `NOL8_CONFIG_FILE`/`NOL8_SECRETS_FILE` overrides, so the suite needs no
real `.env`.

**Deferred (chosen scope):** the full architectural layer-split of `main.py` -
high churn on a working core, "before external release" value not needed pre-demo.

## FW-12 - KB-001 attributed truncation to the wrong engine (FIXED)

KB-001 recorded that "Themis runtime truncates replacement strings longer than
15 characters", and the README documents
`validate compare --replacement-max-length 15` as the standard normalisation.

Measured on an identical policy and corpus: **Themis returns tokens intact**
(2,144,853 responses, none truncated) and **Aergia cuts every one at exactly 15
characters**, because its rule record has a fixed 15-byte `replacement[15]`
field. So the normalisation is wrong against Themis - it discards a correct
answer - and right against Aergia.

Now: the generator keeps every token inside the budget
(`_assert_replacements_within_budget`), so neither engine truncates and one
expectation serves both. KB-001 carries the correction; the flag remains
available for checking older policies.

## FW-13 - Corpora were unrealistic as measurement inputs (FIXED)

Good for proving correctness, misleading for measuring throughput. Seven of nine
scenarios listed sensitive values as `validation_rule_1: <value>` on labelled
lines; no near misses existed, so nothing could be falsely matched; documents
were padded with one repeated sentence; the driver replayed 4,000 bodies
hundreds of times per window; and nothing recorded how dense a corpus was.

Now: values are placed by document type and value type, near misses are derived
from the catalog and verified non-matching, filler is composed per document, a
bulk-export scenario provides the dense workload, and every manifest carries an
`input_profile` recording the regime.

Detail: `docs/CORPUS-REALISM.md`.

## FW-14 - Throughput was measured without checking output (FIXED)

The load driver checked HTTP status and drained the body, so a 200 carrying
corrupted output counted as a success. Most throughput figures taken before
2026-07-27 were gathered that way.

It matters more than it sounds: a 5,000-rule run reported 674,893 successful
responses of which **every one was wrong** (FW-12), and no throughput number
would ever have shown it.

Now: `expected-digests.py` precomputes the oracle's answer as md5 digests, one
per record per contract, and `dp4driver --expected` checks every response
against them. `verify-corpus.py` covers the sampled case and reports which
overlap contract an engine followed.

---

# OBS - Recorded, deliberately not findings

## OBS-1 - Control plane TLS is self-signed

The policy endpoint presents `CN=ip-172-31-40-100`; the processing endpoint has
a valid Amazon certificate.

**This was briefly written up as a high-severity limitation. That was wrong and
it was withdrawn. Do not re-promote it.** The sandbox serves one team, is
reachable only inside the VPC, and carries no customer traffic. A certificate
proves server identity; anyone able to exploit its absence is already inside
that network.

The only open question is why the two endpoints differ - and the topology
answers it: the data plane is on the local network (10.8.11.x) while the
control plane is in EC2 (10.10.1.x). Two provisioning paths, not a decision.
Worth one question about production intent, nothing more.

## OBS-2 - Processed payload returns to the caller

Today the transformed payload comes back to whoever posted it, who must forward
it onward - meaning the caller handles unredacted data on both sides. But the
response carries `jid`, `frameId`, and `last: true`, suggesting a framed or
streaming protocol we may simply not be using.

**Raise as a question, not a finding:** is there an inline or proxy mode, and
what is the intended production integration pattern? Recorded at the end of the
ISSUE-004 handover drafts.

## OBS-3 - Run artifacts are plaintext (T2-4 residual)

The live path writes full expected/actual messages into `artifacts/runs/` with
default file permissions. T2-4's concern - plaintext sensitive content on disk -
does not bite here because the framework operates on **synthetic data by design**
(`expected.jsonl` is our test oracle, not customer data; see "the oracle is
ours"). Accepted as a residual, not fixed in code.

**Guardrail:** do not point this framework at real customer data without first
adding restrictive artifact permissions and, ideally, encryption at rest. The
dead plaintext-writing path was removed (FW-10); this note covers the remaining
live path.

---

# Where things live

| Document | Contains |
|---|---|
| `docs/FINDINGS.md` | **this file** - the index of everything |
| `docs/product/themis-product-limitations.md` | THM-1 to THM-7 and OPS-1 to OPS-3 in full |
| `docs/issues/` | engineering-facing register: ISSUE-001..007, one sendable doc each, plus README index |
| `docs/issues/internal/ISSUE-004-corruption-investigation.md` | THM-4 evidence and reproduction (internal) |
| `docs/issues/internal/KNOWN_BEHAVIORS.md` | KB-001 (THM-5) and the THM-4 authoring constraint |
| `docs/issues/internal/ENGINE-SEMANTICS.md` | THM-8, THM-9, and the KB-001 re-attribution, with reproductions |
| `docs/CORPUS-REALISM.md` | what the generated corpora contain and the density they reach |
| `docs/WHAT-COSTS-A-MATCHER.md` | measured ablation: which input properties cost the software engine, and which do not |
| `docs/CODE_REVIEW_PLAN.md` | FW-1 to FW-7 with tiering |
| `docs/issues/internal/technical_debt.md` | minor framework debt, no customer impact |
| `docs/architecture/validation-boundaries.md` | what the framework does and does not prove |
| `artifacts/evidence/` | the policy, failure samples, a reference report |

---

# What to send engineering, in order

1. **THM-4 (ISSUE-004).** Drafts ready. Silent data corruption from ordinary
   policy authoring - the only finding that destroys customer data.
2. **OPS-1 to OPS-3 plus THM-7.** Cheap fixes, and together they turn a
   one-call recovery into an hour of misdirected work. Good will costs little.
3. **THM-1 to THM-3.** The policy lifecycle. One root cause: a policy is not a
   first-class object.
4. **THM-6.** Environment reachability - a commercial argument, not a bug
   report, and probably a different conversation.

THM-5 is already understood and worked around; raise it as context for THM-4
rather than on its own.
