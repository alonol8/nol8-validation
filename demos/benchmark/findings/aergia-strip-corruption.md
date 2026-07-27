# Benchmark finding: Aergia (RE2 baseline) corrupts output on strip rules

Date: 2026-07-21
Scope: demo environment, Data Point 1 (pre-index). NOT a Themis/NOL8 product finding.
Status: confirmed, oracle-adjudicated, corpus-wide.

## One line

On the **optimization policy** (governance redaction + strip-to-empty rules), the
RE2 incumbent baseline (**Aergia**, `:444`) corrupts output on the strip rules:
where a rule maps a literal to the empty string, Aergia deletes the front of the
match and **leaves the tail** in the text. NOL8 (**Themis**, `:443`) strips
cleanly. Verified against an independent oracle across all 1,000 corpus chunks.

## Why this is a real result, not a rigged one

Same policy, same dataset, both engines, listMatch only — the benchmark integrity
rule. We do not get to declare NOL8 the winner just because its output is prettier,
so we adjudicated **both** engines against an independent oracle before making any
claim. The oracle is the validation framework's Aho-Corasick matcher
(`framework/policy/matching.py`), written for corpus validation and already tested
— it did not learn the answer from either engine. Its semantics: leftmost-longest,
non-overlapping literal replacement (a token for governance rules, `""` for strip
rules) — exactly what a correct literal matcher must produce.

## Evidence

Run: `demos/policies/optimization.nol` (42 governance redact rules + 10 filler
strip rules) over `usecase-1-pre-index/data/sample_chunks.jsonl` (1,000 chunks), same policy
deployed to both engines.

```
Policy: optimization.nol  (52 literal rules; 10 strip, 42 redact)
Corpus: 1000 chunks

[themis_api]  1000/1000 match oracle  -> MATCHES ORACLE
[aergia_api]   124/1000 match oracle  -> DIVERGES FROM ORACLE  (876 divergent)
```

- **NOL8 (Themis): 1000/1000 byte-identical to the oracle.** Its 64.3% forwarded-
  payload reduction (15,343 of 43,005 tokens) is provably correct.
- **Aergia (RE2 baseline): 876/1000 diverge, and every single divergence involves a
  strip rule. Zero redact-only divergences** — on pure token redaction the two
  engines still agree perfectly (that is the byte-identical governance result from
  the original starter-policy run). The defect is specific to empty-replacement.

Failure mode — Aergia keeps the **tail** of a stripped literal:

| stripped literal (rule `-> ""`) | oracle output | Aergia output |
|---|---|---|
| `...by default.` | `` (removed) | `ault.` |
| `...suppressed early.` | `` (removed) | `ssed early.` |
| `...marketing boilerplate.` | `` (removed) | `lerplate.` |
| `...24 hours support.` | `` (removed) | `ours support.` |

Chunk-level example (`chunk-0000002`, three filler sentences, all strip rules):

```
oracle: '\n\n'
aergia: 'ault.\nssed early.\n'
```

The leftover fragments are then forwarded into the embedding pipeline as if they
were real content — so Aergia both fails to clean the text and pollutes the vectors
with garbage tokens. (This is also why Aergia's headline reduction looks *smaller*,
17,512 vs 15,343 tokens: the number is inflated by corruption remnants, not by
Aergia preserving anything useful.)

## Reproduce

On the box that reaches the engines (EC2):

```bash
# 1. run the optimization benchmark against both engines (same policy to each)
POLICY=demos/policies/optimization.nol \
MODES="nofilter re2 themis_api aergia_api" \
  bash demos/benchmark/run-live.sh

# 2. adjudicate each engine's output against the independent oracle
python demos/benchmark/verify-oracle.py \
  --results demos/benchmark/usecase-1-pre-index/results \
  themis_api aergia_api
```

Exit status is non-zero if any engine diverges, so this can gate a demo run.

## Honest framing (how we talk about this)

- **Do say:** "On identical literal policy and data, NOL8 produced correct output on
  every one of 1,000 chunks, verified against an independent oracle. The RE2-based
  incumbent baseline corrupted 876 of them on strip operations." That is measured
  and defensible.
- **Do NOT say:** "RE2 is broken." Aergia is *our* stand-up of an RE2-based engine.
  Whether the tail-remnant behavior is inherent to RE2 or an artifact of how the
  Aergia harness compiles/applies empty-replacement rules is an **open question** we
  have not isolated. The claim we can stand behind is about the baseline engine's
  behavior on this benchmark, not about RE2 the library.
- **Relationship to NOL8's own defects:** this is a *baseline-engine* finding,
  distinct from THM-4/ISSUE-004 (Themis corrupts on *overlapping redaction* matches).
  Different engine, different operation, different failure. Our own generator avoids
  overlapping catalogs so DP1 does not trip THM-4; the optimization policy's strip
  rules do not overlap, which is why Themis is clean here.

## Follow-ups (open)

- Isolate whether the tail-remnant is RE2-inherent or Aergia-harness. A direct
  minimal repro (single strip rule, one line, direct `:444` curl) would settle it.
- If we ever want the optimization story to lead the demo, decide how prominently to
  show the divergence — it is a genuine NOL8 advantage, but the honest telling notes
  the open question above.
