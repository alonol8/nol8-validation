# Corpus match-density across rule counts + workload coordinates (2026-07-26)

The load-bearing check for the rule-count throughput trend (findings 008). If the
generator produced denser corpora at higher rule counts, the Aergia throughput decline
would be a density effect rather than a rule-count effect. Computed offline with the
framework oracle over each rule count's own corpus. Raw: `corpus-density-20260726.json`.
Script: `demos/benchmark/datapoint4/corpus_density.py`.

## Result — match density is FLAT across rule counts

| rules | matches/KB | near-misses/KB | distinct bodies | avg bytes | diversity |
|---|---|---|---|---|---|
| 2,000 | 0.1253 | 0.0 | 15,000 | 115,074 | 1.00 |
| 4,000 | 0.1243 | 0.0 | 12,000\* | 117,513 | 1.00 |
| 6,000 | 0.1200 | 0.0 | 15,000 | 121,350 | 1.00 |
| 8,000 | 0.1241 | 0.0 | 15,000 | 117,502 | 1.00 |

Range 0.120–0.125 matches/KB, **no upward trend with rule count** (6k is the lowest).
So the generator holds match density roughly constant as the ruleset grows, and the
throughput trend in `rulecount-2k4k6k8k-clean-20260726.csv` is attributable to
**ruleset / automaton size, not corpus density**. The findings-007/008 assumption holds.

## Method notes

- Density is computed over the **full generated corpus** (all size bands), using each
  corpus's own policy: matches = leftmost-longest non-overlapping oracle matches; KB =
  total UTF-8 bytes. `avg bytes` is the full-corpus mean (large bodies dominate it), not
  the small-band mean (~2.6 KB) that the small-payload sweep actually drove. The density
  question is a per-corpus generator property, so full-corpus is the right denominator
  for "does density rise with rule count."
- near-misses/KB = 0.0: no normalized-only matches (generated values are exact). Approx
  metric (normalized matcher minus exact); included for Alon's coordinate system.
- diversity = distinct / total = 1.00: every body is unique (no cache-warming repeats).
- \*4k: the script selected the most-recent 4k corpus, which is the **large re-run's**
  4k corpus (12,000 records) rather than the small sweep's (15,000). The density value
  is in line with the others and the flat-density conclusion is unaffected.

## Workload coordinates (Alon's proposal)

Corpus-measured axes are the columns above (matches_per_kb, near_misses_per_kb,
distinct_bodies, diversity_ratio, avg_bytes), per rule count, in the JSON. The generator
config is identical across all rule counts (`config/workloads/enterprise-dlp.yaml`:
`match_distribution.matches_per_document` per band, `size_distribution`, `near_limit`);
only the catalog size changes. Filler mode / overlap profile are generator-config
properties (same for every cell here), not corpus-derived. Recorded so these runs can be
placed on the curve Alon's proposal produces.
