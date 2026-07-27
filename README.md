# Nol8 Validation Framework

| If you want to... | Go to |
|---|---|
| **Fix something that is broken right now** | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
| **Know what we have found** - every issue, with IDs | [docs/FINDINGS.md](docs/FINDINGS.md) |
| Understand what the generated corpora contain | [docs/CORPUS-REALISM.md](docs/CORPUS-REALISM.md) |
| Find any other document | [docs/README.md](docs/README.md) |

> **Endpoint returning 503?** Most likely the data plane is paused awaiting a
> policy, not an outage. Deploy any policy before restarting anything -
> [details](docs/TROUBLESHOOTING.md#symptom-pre-flight-fails-or-every-request-returns-http-503).

## Project purpose

This repository validates Nol8/Themis processing behavior with deterministic,
enterprise-shaped workloads. It is a staged validation framework rather than a
single test script: generation, policy deployment, request execution, and
comparison produce durable artifacts in a timestamped Run directory.

The implemented lifecycle is:

```text
generate  ->  policy  ->  run  ->  compare  ->  report
```

All five stages run through the `validate` command. The scripts under
`scripts/` are the HTTP transport layer and are not intended to be called
directly.

Each stage validates its prerequisites and records status, timestamps, counters,
errors, and artifact metadata in `manifest.json`. Generated and execution
evidence is retained when a later stage fails.

## Architecture overview

### Design principles

- **Deterministic and reproducible validation:** the same resolved configuration
  and seed produce the same policy, corpus, and expected evidence.
- **Realistic enterprise-shaped workloads:** synthetic values are placed in
  coherent business records rather than exposed as generator markers.
- **Durable validation evidence:** stage state and artifacts are retained so
  results and failures can be inspected after execution.
- **Explainable comparison results:** outcomes preserve record identifiers,
  expected and actual content, and the rule evidence behind transformations.

### Workload configurations

YAML files define deterministic inputs to generation:

- `config/test-cases.yaml` drives the original functional generator.
- `config/workloads/customer-record-json.yaml` is the focused realistic
  `customer_record + JSON + small` workload.
- `config/workloads/support-ticket-json.yaml` is the focused realistic
  `support_ticket + JSON + small` workload.
- `config/workloads/enterprise-dlp.yaml` defines the broader mixed enterprise-DLP
  schema and scale controls.

Scale-oriented workload configuration includes the seed, rule count, record
count, policy families, scenario and format weights, match distributions, size
profiles, and progress interval. `validate generate --rules N --records N` can
override rule and record counts for scale-oriented configurations without
modifying their source YAML. The resolved configuration is snapshotted into the
Run.

### Synthetic enterprise data generation

`framework/workload/generate_scale_artifacts.py` builds one deterministic rule
catalog and uses it for all three parts of the validation contract:

```text
policy literal -> natural document placement -> expected replacement evidence
```

Rule values are synthetic and non-production, but shaped like enterprise data:
names, email addresses, telephone numbers, customer and case identifiers,
credentials, financial identifiers, infrastructure values, and related data.

The currently implemented realistic slices are:

- Customer records serialized as small JSON documents.
- Support tickets serialized as small JSON documents.

These documents contain enterprise-like fields and natural placement of selected
policy literals. Clean controls are checked to ensure that no configured policy
literal occurs in the serialized record. Realistic documents do not contain
generator markers or `_synthetic_padding` fields.

The broader enterprise-DLP YAML also describes employee records, email messages,
application logs, API transactions, financial transactions, healthcare claims,
and AI interactions across multiple formats. Those combinations currently use
the generic generation path unless a dedicated realistic slice exists; they
should not be described as fully modeled scenarios yet.

### Policy generation and deployment

Generation emits `generated/scale-policy.nol`. Every policy literal and
replacement comes from the same rule catalog used to create the corpus and its
expected evidence.

`validate policy` deploys that artifact through `scripts/load-policy.sh`.
Authentication, endpoint selection, curl invocation, and network timeouts remain
inside the shell transport. The Python stage records only sanitized deployment
facts and the allowlisted Themis response fields; it does not persist credentials
or request headers.

Policy deployment supports `themis` (default) and `aergia`. Execution currently
supports `themis`.

### Workload execution

`validate run` reads `generated/input.jsonl` sequentially and calls
`scripts/run-validation.sh` for each request. It writes
`generated/output.jsonl` incrementally, preserving request order and completed
evidence if execution is interrupted. The Run manifest counters are updated as
requests complete.

The shell transport owns endpoint configuration and bearer authentication. It
returns only transport facts: HTTP status, latency, and the sanitized processing
response. Both transports use a 5-second connection timeout and a 30-second
overall timeout.

Use `--limit N` to execute only the first N generated records for smoke testing.
This does not modify the generated corpus.

### Validation comparison

`validate compare` aligns artifacts using:

```text
output.request_index -> input row -> record_id -> expected row
```

It validates row counts, exact `request_index` ordering, unique record IDs, and
matching input/expected record-ID sets. Each record receives one outcome:

- `PASS`: execution succeeded and `response.message` exactly equals the expected
  message.
- `CONTENT_MISMATCH`: execution succeeded but the processed content differs.
- `EXECUTION_FAILURE`: transport, HTTP, or response-shape evidence is invalid.

Results are written to `generated/comparison.jsonl` with the record ID, expected
and actual messages, latency, outcome, and expected rule evidence.

## Validation model

### Functional validation

Functional validation uses small deterministic workloads and an explicit oracle:

```text
generated/input.jsonl
generated/expected.jsonl
generated/output.jsonl
generated/comparison.jsonl
```

`input.jsonl` contains the requests sent to Themis. `expected.jsonl` contains the
full intended processed message and structured match evidence. `output.jsonl`
contains the observed processing results. `comparison.jsonl` records the durable
comparison outcome.

The expected artifact is necessary because HTTP success alone does not establish
correct processing. Exact expected messages can detect:

- Missed matches.
- Incorrect or truncated replacements.
- Content corruption.
- Unexpected changes to clean or unrelated content.
- Execution failures that did not produce a valid processed message.

### Scale validation

The current scale-oriented generator preserves the same functional artifact contract,
including one `expected.jsonl` row per input row. This is suitable for bounded
scale-oriented exercises, but generating full expected output documents is not the target
design for workloads containing millions of records.

A future large-scale validation mode should use compact evidence:

```text
input.jsonl
validation_manifest.jsonl
output.jsonl
```

In that model, `validation_manifest.jsonl` would record deterministic placement
and transformation evidence rather than duplicating every complete expected
document. Comparison would reconstruct or verify only the required invariants.
This manifest-based mode is a roadmap item; it is not implemented in the current
CLI or artifact schema.

## Quickstart

### Prerequisites

- Python 3.12 or newer.
- `bash`, `curl`, and `jq` for policy and execution transports.
- `config/demo.env` containing non-secret endpoint configuration.
- A local `.env` containing the required non-production bearer token, such as
  `THEMIS_TOKEN`. Do not commit secrets.
- Network access to the configured non-production services.

Install the project in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

That installs the `validate` console script, which is the complete interface to
this framework. Everything below runs through it. The scripts under `scripts/`
are the HTTP transport layer and are not intended to be called directly.

Activate the environment in every new shell:

```bash
source .venv/bin/activate
```

### End-to-end validation in five commands

```bash
validate generate --config config/workloads/customer-record-csv.yaml \
  --rules 100 --records 50
```

Generation prints a Run ID. Every later stage takes it:

```bash
export RID=<run-id-from-generate>

validate policy  --run $RID --target themis
validate run     --run $RID --target themis
validate compare --run $RID --replacement-max-length 15
validate report  --run $RID
```

Expected result: 50 of 50 requests succeed, `PASS: 50`,
`CONTENT_MISMATCH: 0`, and a report whose banner reads `PASS`.

`--replacement-max-length 15` normalises for KB-001, where replacement strings
longer than 15 characters are truncated at runtime.

**Freshly generated catalogs do not need it.** The generator now keeps every
replacement token inside 15 bytes, so nothing is truncated and the flag would
only discard correct output. It is still required for an older policy carrying
longer tokens.

KB-001 was also **re-attributed on 2026-07-27**: measured on identical policy
and corpus, Themis returns tokens intact and Aergia truncates them, because the
Aergia rule record has a fixed 15-byte replacement field. So against Themis the
flag is wrong, and against Aergia it is right. See
`docs/issues/internal/KNOWN_BEHAVIORS.md` and
`docs/issues/internal/ENGINE-SEMANTICS.md`.

**`validate policy` replaces the entire active policy on the target.** Restore
a known policy when you are finished:

```bash
validate policy --file artifacts/evidence/tenant-restore-policy.nol
```

## Commands

### `validate generate`

Creates a run directory and produces the policy, input corpus, expected
results, and generation manifest.

```bash
validate generate --config <workload.yaml> [--rules N] [--records M] \
  [--runs-dir DIR]
```

| option | meaning |
|---|---|
| `--config` | workload YAML, required |
| `--rules` | override the configured rule count |
| `--records` | override the configured record count |
| `--runs-dir` | parent directory for runs (default `artifacts/runs`) |

Generation refuses to proceed if the rule catalog contains literals nested
inside one another, or replacement tokens that collide when truncated to 15
characters. Both conditions make validation results meaningless rather than
merely imperfect - see "Catalog constraints" below.

`config/workloads/enterprise-dlp.yaml` defaults to 5,000 rules and 10,000
records, and produces documents up to 64 KB. Pass `--rules`/`--records` for
anything smaller.

### `validate policy`

Deploys a policy, or reports what this checkout has deployed.

```bash
validate policy --run <RUN_ID> [--target themis]     # a run's generated policy
validate policy --file <path.nol> [--target themis]  # any policy file
validate policy --status                             # recent deployments
```

Deployment **replaces the entire active policy** on the target. There is no
namespacing, no versioning, and no partial update.

Themis cannot report which policy is currently loaded - there is no identifier,
summary, or read-back endpoint. `--status` is a local record of deployments
made from this checkout, which is the closest available substitute. Deployments
made from elsewhere will not appear.

### `validate run`

Executes the generated corpus against the target and records a response for
every record.

```bash
validate run --run <RUN_ID> [--target themis] [--limit N] \
  [--progress-interval N] [--skip-preflight]
```

Execution is sequential at roughly 24 requests/second, so 10,000 records takes
about seven minutes. Evidence is written incrementally, so an interrupted run
retains everything completed so far.

`--limit N` executes only the first N records. Note that `validate compare`
currently requires a complete corpus, so a limited run cannot be compared.

**Pre-flight.** Before sending the corpus, `run` puts one throwaway record
through the endpoint and aborts if it is not processed, so an unavailable
engine costs one request instead of a whole run of failures. The runtime
publishes no health route, so this has to be a real request rather than a cheap
liveness check.

The most common cause of a failed pre-flight is not an outage: Apollo boots
with its data plane paused and un-pauses only when a policy commits, so a
restarted host sits idle until one is deployed. Deploying any policy fixes it:

```bash
validate policy --file artifacts/evidence/tenant-restore-policy.nol --target themis
```

`--skip-preflight` opts out.

### `validate compare`

Compares recorded output against expected results and writes
`generated/comparison.jsonl`.

```bash
validate compare --run <RUN_ID> [--replacement-max-length 15]
```

Reads captured output from disk and makes no network requests, so it can be
re-run freely against a completed run.

### `validate report`

Renders a self-contained HTML report from the comparison evidence.

```bash
validate report --run <RUN_ID>
```

Writes `reports/validation-report.html`. The report is a single portable file
with no external assets.

## Catalog constraints

Two properties of a rule catalog make validation results meaningless. Both are
enforced at generation time rather than discovered after a run.

**No literal may be nested inside another.** Two rules matching overlapping
regions of the input cause the Themis runtime to write the replacement at the
wrong offset and destroy adjacent content, silently, returning HTTP 200. This
is ISSUE-004. A nested literal guarantees the overlap wherever the outer
literal appears.

**Replacement tokens must stay distinct when truncated to 15 characters.**
Themis truncates replacements at runtime and comparison normalises to match.
Truncation is not injective, so two tokens sharing a 15-character prefix become
indistinguishable and the framework cannot tell whether the runtime applied the
correct rule.

Generation reports overlap exposure in the generation manifest:

```
overlapping_match_documents      0
intended_clean_with_literals     0
```

Check `overlapping_match_documents` before treating any run as a qualification.

## Workload generation

A scale-oriented workload YAML is the source of truth for:

- Deterministic seed.
- Rule and record counts.
- Policy families and pattern IDs.
- Scenario and serialization-format distributions.
- Clean, light, moderate, and heavy match profiles.
- Payload-size profiles and explicit size-boundary padding behavior.

The realistic builders receive selected catalog rules and place their exact
values into semantically appropriate fields. Examples include requester email in
a support ticket, customer ID in record metadata, credentials in security notes,
and financial values in billing notes. The builder returns placement evidence;
the generator handles serialization, artifacts, and final expected-message
calculation.

Padding remains available for explicitly configured size-boundary workloads via
`pad_to_target: true`. It is not used by realistic JSON slices; document content
there contains only enterprise-like data. Generation manifests record actual
payload bytes, padding totals, and generation-mode distribution.

## Comparison behavior and replacement normalization

By default, Compare validates the full replacement strings stored in
`expected.jsonl`:

```bash
validate compare --run <RUN_ID>
```

An engine may truncate replacement strings to 15 characters (KB-001 in
`docs/issues/internal/KNOWN_BEHAVIORS.md` - measured as Aergia behaviour, not
Themis). Generated catalogs now stay inside that budget so it does not arise; for
an older policy with longer tokens, normalize at comparison time:

```bash
validate compare --run <RUN_ID> --replacement-max-length 15
```

This option changes only comparison-time normalization. It does not modify the
rule catalog, emitted policy, `input.jsonl`, or `expected.jsonl`; those artifacts
continue to represent the correct product contract. Omitting the option after the
Themis implementation is corrected will validate full replacement behavior and
expose truncation as `CONTENT_MISMATCH`.

## Run artifacts

A typical Run contains:

```text
artifacts/runs/<run-id>/
├── config/
│   └── <resolved-workload>.yaml
├── generated/
│   ├── scale-policy.nol
│   ├── input.jsonl
│   ├── expected.jsonl
│   ├── output.jsonl
│   ├── comparison.jsonl
│   └── generation-manifest.json
└── manifest.json
```

Later-stage artifacts appear only after those stages run. Artifact paths in the
Run manifest are relative and include SHA-256 and byte-size metadata where the
stage supports it. Manifest writes and completed comparison artifacts use atomic
replacement; execution output is appended durably so interrupted work remains
usable.

## Adding a new validation slice

Extend the existing `scenario + format + size` pattern. A new realistic slice
should include:

1. A deterministic scenario builder that creates coherent enterprise data.
2. Natural placement of selected rule-catalog values.
3. Placement evidence linking each value to its rule, category, and replacement.
4. Clean controls proven not to contain any catalog literal.
5. Routing limited to the intended scenario, format, and size profile.
6. Focused deterministic, placement, policy, expected-output, and clean-record
   tests.
7. A small generated corpus that can complete policy deployment, execution, and
   comparison with `PASS` when the target service is available.

Scenario builders should not load YAML, choose rules, serialize documents, write
artifacts, or calculate complete expected messages. Those responsibilities remain
in the workload generator and lifecycle stages.

## Testing

Run the complete unit suite without contacting live services:

```bash
.venv/bin/python3 -B -m unittest discover -v
```

Focused examples:

```bash
.venv/bin/python3 -B -m unittest -v tests.test_support_ticket_scenario
.venv/bin/python3 -B -m unittest -v tests.test_validate_scale_generate
.venv/bin/python3 -B -m unittest -v tests.test_validate_compare
.venv/bin/python3 -B -m unittest -v tests.test_workload_padding
```

Transport tests mock curl and do not contact production services. Live policy and
execution validation requires explicit non-production configuration and suitable
network access. The current suite covers generation, realistic scenario
placement, policy-stage semantics, transport sanitization, incremental execution,
comparison alignment and outcomes, replacement normalization, and format-safe
padding. As of 2026-07-19, the repository suite contains 80 passing unit tests.

## Future roadmap

- Add realistic builders for more enterprise-DLP scenarios and formats.
- Introduce compact manifest-based validation for very large corpora.
- Add controlled performance and throughput benchmarking.
- Build repeatable enterprise regression suites across policy and workload
  versions.
- Add the report stage using existing durable comparison evidence.

## Known behaviors

See `KNOWN_BEHAVIORS.md` for confirmed product limitations and environment
constraints, including Themis replacement truncation and sandbox service
accessibility.
