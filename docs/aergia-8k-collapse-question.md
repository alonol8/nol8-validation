# Question for engineering: Aergia at 8,000 rules, July 24 → July 25

**Ask:** what changed in the Aergia (RE2) build/config between July 24 and July 25
that removed a throughput collapse at 8,000 rules? We are not blocked on this, but
we want to describe the cause correctly rather than guess.

## What we measured

Two DP4 rule-count sweeps, **same single-edge configuration**, consecutive days,
concurrency 256, small payload, 4,000-record working set. The corpus is identical
across the two days (per-rule-count `avg_body_bytes` match exactly:
2604/2624/2611/2614/2580). Every cell agrees within ~3% **except Aergia at 8,000
rules**:

| Rules | Jul 24 Aergia (3 reps, req/s) | Jul 25 Aergia (3 reps, req/s) |
|---|---|---|
| 1,000 | 26,296 / 26,188 / 26,169 | 26,361 / 26,388 / 26,289 |
| 4,000 | 26,319 / 26,221 / 26,070 | 26,266 / 26,249 / 26,212 |
| 6,000 | 26,323 / 26,119 / 26,157 | 26,275 / 26,230 / 26,269 |
| 8,000 | **8,402 / 8,382 / 8,512** | **26,442 / 26,384 / 26,352** |

On July 24 the 8k cell was not shedding — it served slowly. Mean latency was
30.45 ms and Little's Law closes (256 / 8,401.9 = 30.47 ms), i.e. all 256 clients
were busy waiting on genuinely slow responses, not getting errors. By July 25 the
same 8k cell was healthy (~26.4k, in line with every other rule count).

## Why we are asking engineering and not chasing it ourselves

- **It is Aergia-only.** Themis at 8k was ~28.7k both days.
- **It is 8k-only.** 1k/4k/6k were unaffected on both days.
- **It is July-24-only.** It does not reproduce on July 25 (single edge) or on any
  later 10-edge run.
- **The edge is excluded.** Both days ran the same single Argus edge node, so the
  edge cannot explain a change that happened between them. (This corrects an earlier
  guess of ours that blamed edge saturation — the data rules it out.)

That leaves the Aergia build/config itself. Candidate questions:

1. Was there an Aergia redeploy, version bump, or config change on/around July 25 —
   specifically a change to **`--num-lexers`** or the lexer/thread configuration? We
   have a separate open hypothesis that Aergia's ~26k plateau is the 8 RE2 lexers
   saturating, so the lexer count is the first named knob we'd want ruled in or out.
2. Does RE2 do something different at ~8,000 literal rules specifically — a
   compilation path, DFA size threshold, or memory/cache limit that a smaller
   ruleset stays under? Roughly 8k is where we first saw it.
3. Was the July 24 8k policy fully loaded and compiled, or could it have been in a
   degraded/partial state that a later redeploy cleared? **We cannot answer this
   ourselves:** deployment is fire-and-forget (ISSUE-003), there is no runtime health
   signal (ISSUE-007), and there is no policy read-back to confirm what is actually
   live. So we cannot distinguish "8k policy loaded and genuinely slow" from "8k
   policy half-loaded" from our side — which is itself a product-observability gap
   worth flagging independent of this collapse.

## Evidence (committed)

- `artifacts/evidence/rulecount-jul24-cliff.csv` — the collapse.
- `artifacts/evidence/rulecount-jul25-clean.csv` — same config next day, no collapse.

Both are single-edge sweeps; the 10-edge runs
(`rulecount-10argus-*.csv`) also show no collapse.
