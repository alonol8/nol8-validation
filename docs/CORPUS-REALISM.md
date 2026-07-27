# What the generated corpora contain, and why

Date: 2026-07-27

The corpora were built to prove *correctness*, and they do that well. Used as
*measurement* inputs they occupied one narrow region of the input space, and it
happened to be the cheapest region for any text-scanning engine to process. This
records what changed, what it measures, and what is still missing.

---

## What was wrong

**Values arrived on labelled lines.** Seven of nine scenarios listed a
document's sensitive values as `validation_rule_1: <value>`, one numbered line
each. Nothing about finding a value on a labelled line resembles finding a
credential inside a log line or an address in an email thread.

**Every identifier-shaped string was a hit.** No near misses at all, so nothing
was present that *could* be falsely matched and the corpora could say nothing
about false positives.

**Documents were padded with one repeated sentence**, identical in every
document and every run.

**The driver replayed a small working set** - 4,000 bodies at the observed
request rates meant each was sent a couple of hundred times per measurement
window.

**Match density was low and unmeasured.** Nothing recorded how dense a corpus
was, so a throughput number carried no indication of the regime that produced it.

---

## What the generator does now

### Values arrive in context

`framework/scenarios/placement.py` places by document type *and* value type. A
token lands in an authentication failure, a hostname in a connection line, a
home address in a payload the application should not have been logging. Both
axes are needed: choosing on document type alone produced log lines listing
street addresses as `principal=`.

Governed and ungoverned values go through the same templates, so the surrounding
text never reveals which is which.

### Near misses

`framework/workload/near_miss.py`. Text that matches a governed literal most of
the way and then fails - not a different value of the same kind, which shares
only a family prefix. Four kinds, each with a mundane cause:

| Kind | Cause | Example against `sk_test_enterprise_000123` |
|---|---|---|
| `altered_tail` | identifiers are issued in sequence | `sk_test_enterprise_000124` |
| `truncated` | log field or CSV column width | `sk_test_enterpri` |
| `masked` | upstream masks before writing | `sk_test_enter****` |
| `word_variant` | entity names are written more than one way | `Acme Corp` for `Acme Corporation` |

Every candidate is checked against the full catalog before use. Truncating or
altering one governed value lands on *another* governed value surprisingly often
where identifiers are sequential, and an unnoticed one would be recorded as text
that should survive while the engine correctly redacts it.

Enabled per workload via `documents.near_miss_distribution.per_kilobyte`.
Omitting the section disables it, so a workload written before this option
existed produces byte-identical artifacts.

### Documents grow the way real ones do

`framework/workload/prose.py` composes filler per document. A long account
record is long because many separate things were written into it over time.

### Bulk exports

`framework/scenarios/database_export.py` and
`config/workloads/database-export.yaml`. Customer master data, payment ledgers,
claims batches, access logs - the workload where governed values *are* the
content rather than values sprinkled through prose.

```
CUST-000123,Sandra Hernandez 00042,s.hernandez@example.net,+1-704-383-0183
```

Ninety bytes carrying four governed values. This is where density comes from,
and there is nothing contrived about it: a customer table really does look like
that. Rows for parties not on the policy list are the majority, as in any real
table.

### The regime is recorded

Every generation manifest now carries `input_profile`:

```
matches_per_kb, near_misses_per_kb, near_miss_total,
distinct_rules_matched, rule_coverage, filler_mode
```

A throughput number is only interpretable against these. Quote them together.

---

## Measured

| Workload | matches/KB | Rule coverage |
|---|---|---|
| enterprise-dlp, prose, small band | ~3.5 | - |
| Enron email, 262-rule word policy | 33.0 | - |
| **database-export, 5,000 rules** | **21.3** | **97%** |
| database-export, heavy profile | 31 | - |

Why this matters, from the density sweep at 8,000 rules: the software engine
went from 45,058 to 10,730 req/s between 1 and 50 matches/KB, and the ratio
between the engines moved 1.26x to 5.09x. Hitting the whole rule set rather than
a 1,000-literal pool cost a further 43% at 25 matches/KB. Density and diversity
are the axes that matter; concurrency is not one, and was shown not to be across
a 32-fold range.

---

## Still missing

**`matches_per_kb` is corpus-wide** and misleading when payloads span 512 bytes
to 1 MB - large documents dominate the denominator. It should be reported per
size band.

**Placement can overshoot a size ceiling.** Narrative is budgeted against the
target, but the estimate is made before serialisation, and JSON escaping plus
the format wrapper add bytes after that. One run pushed 1,825 documents out of
the small band.

**Prose density is inherently low.** An inline guardrail on correspondence sees
a few matches per kilobyte and that is the honest figure for that workload.
Exports are the dense one. Both are real; report each with its payload size and
density attached rather than picking the flattering one.

---

## Two rules for anything measured on these corpora

**Quote the regime with the number.** "57k req/s" means nothing without the
match density, the rule count, the payload size and the concurrency.

**Verify before measuring.** The load driver checks HTTP status only. Correctness
is `verify-corpus.py` (sampled, both overlap contracts) or `--expected` with
`expected-digests.py` (every response). A throughput figure for an engine whose
output nobody checked is a rate of producing unvalidated bytes - which is how a
5,000-rule run reported 674,893 successful responses that were all wrong.
