# Corpus match-density across rule counts + workload coordinates (2026-07-26)

The load-bearing check for the rule-count throughput trend (findings 008). If the
generator produced denser corpora at higher rule counts, the Aergia throughput decline
would be a density effect rather than a rule-count effect. Computed offline with the
framework oracle over each rule count's own corpus. Raw: `corpus-density-20260726.json`.
Script: `demos/benchmark/datapoint4/corpus_density.py`.

## Two objects — measure the RIGHT one (findings 009)

The first pass measured density over the **full source documents** (avg ~115 KB). But
the driver sends **small-band bodies** (≤4096-byte messages, ~2.6 KB). Those are
different objects by ~45×, so the source figure does not describe what the benchmark
scanned. Both are below; **the sent-body row is the one that describes the ratios.**

### A. SENT bodies — what the driver actually scanned (the relevant object)

Replicating loadCorpus (band by message byte-length, first 4,000 in file order).
Raw: `corpus-density-sent-20260726.json`.

| rules | matches/request | matches/KB | % requests w/ a match | avg msg bytes |
|---|---|---|---|---|
| 2,000 | 11.16 | 4.76 | 73.8% | 2,398 |
| 4,000 | 11.24 | 4.82 | 74.1% | 2,390 |
| 6,000 | 11.13 | 4.77 | 73.7% | 2,388 |
| 8,000 | 11.09 | 4.82 | 73.4% | 2,356 |

**~4.8 matches/KB, ~11 matches/request, ~74% of requests contain a match** — a real
redaction workload, not "scan and find nothing." And **flat across rule counts** (4.76–
4.82), so the Aergia throughput decline in `rulecount-2k4k6k8k-clean-20260726.csv` is a
**ruleset/automaton-size effect, not a density artifact** — now confirmed on the object
the ratios were measured on. **Alon's ~5 matches/KB estimate was accurate** (the earlier
0.12 made it look conservative; that was the wrong object).

### B. SOURCE documents — the full generated corpus (context only)

Raw: `corpus-density-20260726.json`.

| rules | matches/KB | near/KB | distinct | avg bytes | diversity |
|---|---|---|---|---|---|
| 2,000 | 0.1253 | 0.0 | 15,000 | 115,074 | 1.00 |
| 4,000 | 0.1243 | 0.0 | 12,000\* | 117,513 | 1.00 |
| 6,000 | 0.1200 | 0.0 | 15,000 | 121,350 | 1.00 |
| 8,000 | 0.1241 | 0.0 | 15,000 | 117,502 | 1.00 |

Also flat, but this is density over the large source docs — not the sent bodies. Kept
for provenance; do not quote it as the benchmark's density.

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
