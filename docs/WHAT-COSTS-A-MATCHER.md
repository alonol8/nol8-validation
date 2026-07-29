# What costs a software matcher, measured

Date: 2026-07-29
Scope: Aergia (the RE2-based baseline) at concurrency 1024, 20,000 documents of
~4 KB, verified corpora. Themis figures noted where taken.

An ablation, not a benchmark. The question was why a corpus of realistically
shaped values costs the software engine several times what our generated corpora
did, and the answer turned out not to be any of the first four things tried.

---

## The headline

| Corpus | Rules | Openings | matches/KB | Aergia req/s | MiB/s |
|---|---|---|---|---|---|
| sequential literals, all stressors | 8,000 | 10 | 44.8 | 16,137 | 64.7 |
| **realistic literals, all stressors** | **5,000** | **2,763** | **31.3** | **2,574** | **10.2** |

**6.3× slower on a corpus with fewer rules and 30% less matching work.** Verified:
51,484 responses, all byte-correct against the oracle, zero errors, zero stalls.
The engine is doing the job properly, just slowly.

Latency at that point: p50 303 ms, p99 1,185 ms, max 2,380 ms.

---

## The ablation

Each axis varied alone, everything else held constant. The `families` catalog
mode exists for this: fixed length drawn from a controlled number of distinct
4-byte openings, so match density stays within 0.5% across a sweep.

| Axis | Range | Cost |
|---|---|---|
| automaton width (distinct openings) | 8 → 5,000 | **1.46×** |
| literal length | 12 → 28 bytes | **1.23×** |
| rule count | 2,500 → 5,000 | **1.18×** |
| literal alphabet | 36 → 93 characters | **1.21×** |
| product of all four | | **~2.6×** |
| observed gap | | **~6.0×** |

Automaton width is smooth and monotonic with **no knee**, which rules out a
lazily-built automaton exhausting a memory budget and falling back to a slower
mode. It is ordinary state-set pressure, and mild.

### Hypotheses that failed

**Fragments and overlapping matches.** Predicted to dominate. A corpus that is
43% partial literals, with deliberate adjacency and overlap and high-entropy
noise between segments, runs *60% faster* than a plain corpus at the same density
whose literals are longer. Near-noise.

**Automaton width.** Predicted next. 625× more width costs 1.46×.

**Literal alphabet.** 36 → 93 characters costs 1.21×.

**Near-duplicate clustering.** Measured as the longest common prefix with the
nearest other literal. It does not separate the catalogs, and points the wrong
way: the sequential catalog is by far the most clustered and by far the fastest.

| catalog | mean LCP | max | avg length |
|---|---|---|---|
| realistic | 5.0 | 21 | 17.3 |
| families | 3.8 | 6 | 12.0 |
| sequential | **9.3** | 10 | 10.3 |

### The residual

After length and alphabet are accounted for, a **3.2× gap remains** between the
realistic catalog and the closest controlled one. Four measured axes and one
structural statistic do not explain it.

The honest reading: the cost is a property of the *composite* structure of
realistically shaped values and does not decompose into independent parameters.
The one variable never isolated is length *variability* — the realistic catalog
spans 5 to 36 bytes where every controlled arm is fixed-width.

What can be said and defended:

> A catalog of realistically-shaped values costs the software engine roughly 6×
> a synthetic catalog of uniform random strings, at comparable density and rule
> count. Width, length, rule count and character set each contribute 1.2–1.5×
> and together account for about half the gap. The remainder is a property of the
> composite and is not reducible to any one of them.

---

## What this means for the harness

**Literal entropy is the lever, and it is the realistic one.** This matters more
than the mechanism. Real watch lists contain API keys, bearer tokens, UUIDs, card
numbers, MAC addresses and cloud resource identifiers - values that genuinely are
random. `_realistic_rule_value` generates sequential counters
(`CUST-000001`, `sk_test_enterprise_000123`), so 5,000 rules collapse into ten
trie branches. That is the artifact, not the realistic case.

The sequential shape exists only to satisfy the ISSUE-004 containment guard:
fixed-width values cannot nest. With that runtime issue resolved the constraint
can go, and `find_contained_literals` becomes an opt-in check.

**Noise entropy is not the lever, and cannot be.** Real documents are prose or
structured records. The random-ASCII filler in the stress generator is
deliberately artificial and a corpus using it should be labelled a worst case,
never presented as representative.

That asymmetry is the useful conclusion: **the demanding property is one a real
policy has, and the artificial one is not needed.**

---

## Method notes

Three tooling bugs were fixed during this work, each of which had corrupted a
result before it was caught:

- The load driver checked HTTP status only, so a 200 carrying wrong output
  counted as a success. One 5,000-rule run reported 674,893 successful responses
  of which every one was wrong (see ENGINE-SEMANTICS.md ES-2).
- `verified-run.sh` grepped for the string `WRONG`, which matches its own success
  line `0 WRONG`, so every verified run reported failure.
- Result CSVs and run directories were named without the full parameter set, so
  two arms of a sweep overwrote each other. Twice. Run ids now carry a digest of
  every parameter, and each run directory holds a `stress-params.json`.

The pattern in all three: a tool that quietly reports the wrong thing costs more
than one that fails loudly. The verification path exists because throughput
figures taken without it were not measuring what they appeared to.

## Reproducing

```bash
# the headline pair
python demos/benchmark/datapoint4/make-stress-corpus.py --literals sequential \
    --rules 8000 --docs 20000 --doc-bytes 4000 --noise-min 2 --noise-max 10
python demos/benchmark/datapoint4/make-stress-corpus.py --literals entropy \
    --rules 5000 --docs 20000 --doc-bytes 4000 --noise-min 2 --noise-max 10

# any single axis, everything else held constant
python demos/benchmark/datapoint4/make-stress-corpus.py --literals families \
    --prefix-families <K> --literal-length <L> --literal-alphabet <A> \
    --rules 5000 --docs 20000 --doc-bytes 4000 --noise-min 2 --noise-max 10

bash demos/benchmark/datapoint4/verified-run.sh --run <printed id> \
    --engines aergia --skip-verify
```

`--skip-verify` is for comparing corpora. Verify the arm you intend to quote.
