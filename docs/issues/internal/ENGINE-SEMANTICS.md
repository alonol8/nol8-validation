# Engine semantics: where Themis and Aergia disagree

Date: 2026-07-27
Status: measured, not yet raised with engineering
Scope: internal. Two of these change what "correct output" means, so they affect
every comparison the framework produces.

Both engines run the same literal policy on the same input and do **not** return
the same bytes. Neither is malfunctioning; they implement different, internally
consistent rules. Until it is settled which rules are the product's, a
validation framework cannot score either of them without choosing sides.

---

## ES-1 - Overlapping matches: two contracts, one policy

**What.** When two matches share a byte, there are two self-consistent answers
and the engines pick different ones.

| Contract | Rule |
|---|---|
| one-byte-one-match | a byte is consumed by at most one match; the second never fires |
| every-match-fires | both fire; the shared bytes are consumed once |

```
rules   " to " -> " ",  " me " -> " ",  " be " -> " "
input   "There seem to me to be two questions"

one-byte-one-match   "There seem me be two questions"
every-match-fires    "There seem    two questions"
```

**Measured.** 500 real business emails, a policy of space-delimited common
words:

| Engine | Reproduces one-byte-one-match |
|---|---|
| Aergia | 500 / 500 |
| Themis | 15 / 500 |

Themis reproduced **every-match-fires** byte for byte on the remainder. It is
not corrupting anything - the model was confirmed against its output exactly,
including on the ISSUE-004 shapes.

**Why it never surfaced before.** The identifier catalogs are built to exclude
overlapping literals and the generator refuses them, so every prior corpus sat
in the region where the two contracts agree. A policy of space-delimited words
overlaps in almost every sentence, because "of the" offers `" of "` and `" the "`
one shared space and only one of them can have it.

**Handled by.** `framework/policy/matching.py` implements both
(`apply_leftmost_longest`, `apply_overlap_aware`); `verify-corpus.py` and
`expected-digests.py` adjudicate against both and report which an engine
followed. Tests in `tests/test_overlap_contracts.py`.

**Open question for engineering.** Which contract is Themis specified to
implement? A two-rule policy and one request settles it, and the answer decides
whether any future validation of an overlapping policy is meaningful.

---

## ES-2 - Replacement truncation is Aergia's, not Themis's

**KB-001 attributes this to Themis. The measurement says otherwise.**

Identical 5,000-rule policy, identical corpus, same request:

```
oracle   ...,[BIZ:EMPLOYEE_ID],[INFRA:IPV4_ADDRESS],[INFRA:HOSTNAME],export
themis   ...,[BIZ:EMPLOYEE_ID],[INFRA:IPV4_ADDRESS],[INFRA:HOSTNAME],export
aergia   ...,[BIZ:EMPLOYEE_I,[INFRA:IPV4_ADD,[INFRA:HOSTNAME,export
```

Every Aergia token is cut at exactly 15 characters, closing bracket included.
Themis returned all of them intact - **2,144,853 responses verified, zero
truncated**.

**Mechanism.** The Aergia rule record has a fixed 15-byte replacement field
(`docs/utilities.md`, `dumputil --aergia`: offset 5, size 15,
`replacement[15]`). It cannot hold a longer token.

**Consequence for the framework.** `validate compare --replacement-max-length 15`
is documented in the README as the standard normalisation. Against Themis it is
now **wrong** - it discards a correct full-length answer. It remains correct for
Aergia.

**Handled by.** The generator now keeps every token inside the budget
(`_assert_replacements_within_budget`, longest is `[CRED:CONTRACT]` at 15
bytes), so neither engine has to truncate and one expectation serves both. The
`--replacement-max-length` flag was added to `verify-corpus.py` and
`expected-digests.py` for checking older policies that still carry long tokens.

**Caution.** If Aergia's field is a C string needing a terminator it holds 14,
not 15, and a token at exactly 15 bytes would still truncate. That would appear
as a small residue rather than a total mismatch. Dropping the budget to 14
removes the question.

---

## ES-3 - Themis: rare divergence under load

**What.** In a verified load run, **2 responses out of 2,144,853** did not match
the oracle - roughly one in a million. A second run of the same cell showed 0.

**Why it is worth recording.** It is only findable with full-coverage
verification. A 300-document sample would never see it, and no throughput number
would either.

**Not yet characterised.** Unknown whether it is load-dependent, whether the
same record diverges each time, or what the divergent bytes are. Before treating
it as real:

1. re-run the same cell several times and see whether the rate is stable;
2. run `verify-corpus.py` sequentially at low concurrency on the same policy -
   if that is clean while the loaded run is not, it is load-dependent;
3. capture the divergent record and diff the bytes.

**Status.** Open, uncharacterised, low frequency. Do not report it as a defect
until at least (1) and (2) are done.

---

## What to do with this

1. **Ask engineering which overlap contract is specified** (ES-1). Everything
   else about overlapping policies depends on the answer.
2. **Correct KB-001's attribution** (ES-2) and the README's normalisation
   guidance.
3. **Characterise ES-3** before it is either reported or dismissed.

Reproductions for ES-1 and ES-2 are two rules and one request each; neither
needs the framework.
