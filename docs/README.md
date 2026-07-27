# Documentation Map

Every document, what it is for, and when to read it.

## Start here

| Document | Read it when |
|---|---|
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | **Something is broken right now.** Symptom, check, fix. |
| [FINDINGS.md](FINDINGS.md) | **You want to know what we have found.** Every finding, stable IDs, one paragraph each, links to detail. |

Those three answer almost every question. The rest is detail they point to.

## Product findings - things Themis does

| Document | Contains |
|---|---|
| [product/themis-product-limitations.md](product/themis-product-limitations.md) | THM-1 to THM-7 and OPS-1 to OPS-3, in full, with evidence (internal synthesis) |

## Issues - engineering-facing, sendable

Self-contained reports, one per issue, safe to attach to an email. No repo
references; reproductions are inline curl.

| Document | Contains |
|---|---|
| [issues/README.md](issues/README.md) | The issue register: ISSUE-001 to ISSUE-007, severity and status, with the shared-root-cause map |
| [issues/ISSUE-001..007-*.md](issues/) | One self-contained report per finding. ISSUE-004 is the overlapping-match corruption defect |

## Issues - internal (not for distribution)

| Document | Contains |
|---|---|
| [issues/internal/ISSUE-004-corruption-investigation.md](issues/internal/ISSUE-004-corruption-investigation.md) | The corruption defect in full: evidence, reproduction, what was ruled out |
| [issues/internal/KNOWN_BEHAVIORS.md](issues/internal/KNOWN_BEHAVIORS.md) | Accepted runtime behaviour to design around (KB-001) |
| [issues/internal/technical_debt.md](issues/internal/technical_debt.md) | Minor framework debt, no customer impact |

## Our framework

| Document | Contains |
|---|---|
| [CODE_REVIEW_PLAN.md](CODE_REVIEW_PLAN.md) | Full review of the codebase, tiered by risk. FW-1 to FW-7 |
| [architecture/validation-boundaries.md](architecture/validation-boundaries.md) | What the framework proves and, importantly, what it does not |
| [USE_CASES.md](USE_CASES.md) | Scenarios the framework is built to cover |
| [CLEANUP_PLAN.md](CLEANUP_PLAN.md) | What was removed from the repo and what still needs a decision |

## Evidence

`artifacts/evidence/` holds what must survive cleanup - the deployed policy
(the only copy, see THM-1), failure samples, and a reference passing report.
Its README explains provenance.

`artifacts/runs/` is **not** tracked. Anything that matters goes to
`artifacts/evidence/`.

## Added 2026-07-27

- `CORPUS-REALISM.md` - what the generated corpora contain, the match densities
  they reach, and the two rules for anything measured on them.
- `issues/internal/ENGINE-SEMANTICS.md` - the three places Themis and Aergia
  return different bytes for the same policy and input, with reproductions.
