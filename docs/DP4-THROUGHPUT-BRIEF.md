# NOL8 Throughput Benchmark — plain-English brief

*A source document. Hand this to Claude (or anyone) to turn into a one-pager,
deck, or explainer. Every number here was measured on the live engines — same
policy, same data, same test harness to both — not simulated and not asserted.*

*Last revised 2026-07-26. **This revision replaces the previous one wholesale.**
The previous brief's throughput numbers were measured through a **single edge
node** that was itself the bottleneck — so they described the front door, not the
engines. With the edge scaled out, the real numbers are 2–5× higher and the story
is clearer. See the Correction Notice.*

---

## ⚠️ Correction Notice (read first)

Two earlier claims are now superseded, and it matters that we say why.

1. **The old throughput numbers (~28,600 FPGA / ~26,300 software, "~1.09× close")
   were edge-limited, not engine-limited.** During those runs there was only **one
   "Argus" edge node** in front of each engine — the component that terminates the
   HTTPS connection and forwards the request inward. A single edge node caps out
   around **~27,000 req/s**, so *both* engines were pinned at that number. We were
   measuring the front door, and the front door made the two engines look nearly
   identical. When the edge was scaled to **10 nodes** and the *identical* test was
   re-run, both engines jumped: the software engine to **~57,000 req/s** and the
   FPGA to **~77,000** at the same load level — and much higher when pushed (below).

2. **The earlier "8,400 req/s collapse at 8,000 rules" was the single edge node
   saturating — not the software engine, and not (as the last brief guessed) a
   random "bad test host."** With 10 edge nodes it does not happen: five back-to-back
   runs at 8,000 rules held a flat ~57,000 req/s with no crater. The collapse was
   real, it was reproducible on a single edge node, and it is now explained and gone.

**Why we tell it this way:** the whole point of this exercise is a number we can
defend in front of a skeptic. When a result turns out to have been measuring the
wrong thing, we say so plainly and re-measure — we don't quietly edit a cell. The
corrected picture is *stronger* than the one it replaces.

---

## The 30-second version

We put NOL8's hardware engine (an **FPGA**, "Themis") head-to-head against the
standard software approach (**Google's RE2**, "Aergia" — what most people would
reach for) on the exact same job: scanning text for a list of known sensitive
values and replacing them. Same policy, same data, same load driver to both. What
holds up, now that the edge is no longer the bottleneck:

1. **The matching work itself is essentially free on the FPGA.** A request's time
   is almost entirely moving the bytes, not finding the matches. *(Strongly proven —
   see the diagnostic.)*
2. **At a normal load level the FPGA is ~1.35× the software throughput** (~77k vs
   ~57k req/s at 8,000 rules), with a tighter latency tail (~6 ms vs ~8 ms P99).
3. **The FPGA's lead *widens as you push harder*.** Increasing the load, the FPGA
   keeps scaling while the software engine hits a wall:
   **1.35× → 1.83× → 2.15×.**
4. **The software engine has a real ceiling; the FPGA's is higher than we could
   reach.** Software RE2 tops out around **~68,000 req/s** (a genuine engine limit —
   our load box was only half-busy). The FPGA was still climbing at **~146,000
   req/s** when *our driver box* — not the FPGA — ran out of CPU. We never found the
   FPGA's ceiling.
5. **Efficiency is the durable thesis.** Separate from raw speed: the software
   engine burns **~8 dedicated CPU cores** doing the matching that the FPGA does in
   silicon — roughly **half the host CPU per request** for the same result.

**The honest shape of it:** at a light load the engines look close-ish (~1.35×);
under real pressure the FPGA pulls away (2×+) because it scales where software
saturates; and at the fleet level the FPGA does the same job on far less CPU.

---

## What we're comparing (and how we keep it honest)

- **Themis** = NOL8's engine on an **FPGA** (a fixed hardware pipeline).
- **Aergia** = **Google RE2**, a fast, respected **software** matcher — the
  incumbent, a fair stand-in for "the normal way to do this."
- **The job:** both do *deterministic literal replacement* — given a list of exact
  strings (a "policy"), find them in text and swap them out. That is all NOL8 claims
  to do here; this is a **speed and capacity** test of that one job.
- **The path a request takes:** client → **Argus** (edge / HTTPS front door, now 10
  nodes) → Iris → **Apollo** (shared data plane) → the engine (FPGA on Themis, RE2
  lexers on Aergia). Both engines sit behind the *same* edge and the *same* data
  plane, so the comparison stays apples-to-apples.
- **The fairness rules:** identical policy, identical data, identical load generator
  to both engines. Where a result went against expectation — or turned out to be
  measuring the wrong thing — we keep it and explain it. The goal is a number we can
  defend, not a number that flatters us.

**One caution on absolute numbers.** This is a shared test environment; absolute
req/s drifts with what else is running. The **ratios** (FPGA vs software) and the
**CPU cost** are the defensible facts; treat any single absolute number as
point-in-time.

---

## The runs, in order

### Run 1 — "Does policy size change the picture?" (rule-count sweep)

Fix everything — message size (~2.6 KB), load (256 simultaneous requests) — and
change **only the number of rules in the policy**. Five repeats per point, both
engines, 10-node edge.

| Rules | FPGA (Themis) | Software (Aergia) | FPGA advantage |
|---|---|---|---|
| 2,000 | ~75k (clean reps)\* | ~60.8k | ~1.24× |
| 4,000 | ~71.7k | ~59.1k | ~1.21× |
| 8,000 | **~76.6k** | **~56.9k** | **~1.35×** |

\* *The FPGA's 2,000-rule point was noisy this run — three of five reps took a burst
of server-side 5xx errors that dragged their throughput down (see "The errors").
Its clean reps sat at ~75k; we report the number but flag the noise rather than
cherry-pick it.*

Two clean findings:
- **The software engine gently *declines* as rules grow** (60.8k → 59.1k → 56.9k) —
  the expected "RE2 gets a little slower with more patterns" effect, now visible
  because the edge ceiling no longer masks it.
- **The FPGA holds flat-to-high and its lead widens** with rule count (clearest at
  8,000: ~1.35×). A fixed hardware pipeline doesn't care how many rules it holds.

**The 8,000-rule collapse is gone.** Five back-to-back reps: 56.9 / 56.9 / 57.5 /
57.8 / 56.8k, P99 ~7.9 ms, no crater. The old "8,400" was the single edge node
saturating; with 10 nodes it simply doesn't occur.

### Run 2 — "Where is each engine's ceiling?" (concurrency push)

Fix the policy at 8,000 rules and raise the load (concurrent requests) from 256 to
1,024. This separates "our chosen load level" from "the engine's actual limit."

| Load (concurrency) | FPGA (Themis) | Software (Aergia) | gap |
|---|---|---|---|
| 256 | 77.2k req/s (P99 5.8 ms) | 57.1k (P99 7.7 ms) | 1.35× |
| 512 | 115.5k (P99 9.2 ms) | 63.1k (P99 14.6 ms) | 1.83× |
| 1,024 | **145.8k** (P99 20.2 ms) | **67.9k** (P99 27.8 ms) | **2.15×** |

This is the real story:
- **Software saturates at ~68k.** Doubling load from 256 barely moved throughput
  (57k → 63k → 68k) while latency scaled ~linearly — the signature of an engine at
  its wall, just deepening its queue. And **it is a genuine engine limit, not our
  test rig:** during Aergia's run our load box was only **~47% busy** (plenty of
  spare capacity to push it harder — the engine simply couldn't take more).
- **The FPGA kept scaling to 146k and beyond.** Throughput climbed 77k → 115k →
  146k. At the top, **our driver box hit ~84% CPU** — so **146k is where *our test
  harness* ran out, not where the FPGA did.** The FPGA's true ceiling is higher than
  we could measure with one load box.
- **So the gap widens under load** (1.35× → 2.15×) — and the *real* gap is larger
  still, because at 146k the FPGA wasn't yet at its own limit while software was long
  since at its.

### Diagnostic — "Is the matching itself the cost?" *(holds up, unchanged)*

Single requests (no competition) of increasing size, once with **no matches** and
once **packed with matches**. On the FPGA the two were **identical** — a 512 KB
message took the same time (~373 ms) whether it had zero matches or hundreds. **The
matching is free; the cost is moving the bytes.** The engine is lightning fast; any
slowness on very large payloads is the road feeding it, not the booth.

---

## The efficiency result (measured on the engine hosts)

Separate from raw speed, and **unaffected by the edge question** (it's measured
directly on each engine's host, nothing to do with the front door): we measured the
CPU each engine's data plane actually consumes. Both run the *same* front-end data
plane (Apollo), so it subtracts out cleanly.

| Engine | Data plane (Apollo) | Matching | **Total host cores** |
|---|---|---|---|
| **Themis** (FPGA) | ~11.3 cores | **FPGA silicon — 0 host cores** | **~11.3** |
| **Aergia** (RE2 software) | ~11.3 cores | **~8.2 CPU cores (RE2 lexers)** | **~19.4** |

- **The software tax the FPGA eliminates is ~8 dedicated CPU cores** — the matching
  work, moved from general-purpose cores into silicon.
- **It's a standing cost, not a spike.** Both data planes are DPDK *poll-mode*, so
  those cores are consumed **continuously — whether or not traffic is flowing.** The
  software matcher burns its ~8 cores 24/7; the FPGA hands them back.
- **Verified real:** the FPGA is genuinely doing the matching (loaded FPGA image on
  an AWS F2 instance; output confirmed correct by DP1–DP3), not a software fallback.

*Note: the per-request efficiency multiplier (cores per 1,000 req/s) will be
re-measured against the corrected, higher throughput — it will move in the FPGA's
favor, since the FPGA now shows ~2× the throughput of software on fewer host cores.
The ~8-core structural difference above is throughput-independent (poll-mode) and
stands as-is.*

---

## Latency — read before quoting it

Latency depends entirely on how hard you push. At a light load a full redaction
round-trip is a few milliseconds; the numbers climb only because we deliberately
stack requests up.

- **At the 256-load level, 8,000 rules:** FPGA **P99 ~5.8 ms**, software **~7.9 ms**.
  (The previous brief's "~19 ms P99" was a single-edge-node queuing artifact — with
  the edge scaled out it's gone.)
- **Under the heaviest push (1,024):** FPGA P99 ~20 ms, software ~28 ms — that's the
  cost of running 1,024 requests in flight, not the cost of matching.
- **The matching itself is sub-millisecond** (see the diagnostic). Always quote
  latency *with* its load level ("P99 at 256 concurrency"), never bare.

---

## The errors (what they are, and what's still open)

Both engines return a small number of **HTTP 5xx** responses under sustained load —
and *only* 5xx. We instrumented the load driver to classify every failure by cause,
and across every run the breakdown was the same: **zero** dial failures, **zero**
timeouts, **zero** connection resets — **exclusively server-side 5xx.** So this is
the system shedding a small fraction of requests under pressure (backpressure), not
a fault in the test harness. (An early theory that the driver box was exhausting
network ports was **checked directly and ruled out** — the connections held stable,
no port churn.)

- **It's a small fraction** (typically well under 0.1% of requests) but it **rises
  under sustained load** and hits the **FPGA's path harder** — most likely *because*
  the FPGA drives far more throughput into the shared downstream, so it reaches
  whatever component sheds 5xx sooner than the slower software path does.
- **Open question, being confirmed with engineering:** *where* the 5xx originate —
  the edge (Argus) or a downstream component — and whether it's a tunable limit. We
  have asked for the server-side logs for the run window. Until that's answered, we
  report the 5xx honestly as a top-of-range backpressure signal rather than
  attribute a cause.

---

## Open questions (being straight about it)

- **The FPGA's true throughput ceiling is unknown** — we hit *our load box's* CPU
  limit (~84% at 146k req/s) before the FPGA's. Finding it needs a second/bigger
  driver host. What we can say: it is **well above 146k**, and **well above
  software's ~68k wall.**
- **Where do the 5xx come from?** (above) — needs server-side logs; requested.
- **Beyond ~8,000–12,000 rules is untestable today** — the FPGA **refuses to deploy**
  a 12,000-rule policy (a deployment cap, not a speed result). 8,000 deploys and runs
  clean; 12,000 is rejected. So the sweep is honest up to 8,000 and genuinely can't
  see past the deploy ceiling.
- **Very large payloads are limited by byte *delivery*, not matching** — and the
  absolute ceiling we saw (~150 MB/s) is **partly our driver host's NIC bandwidth
  allowance**, measured firing under load and zero at idle (same-VPC, but the cap is
  per-instance-NIC, not a VPC boundary). The relative engine comparison stays fair;
  a real large-payload ceiling test needs multiple driver hosts.

---

## What the honest result means (positioning)

- **Raw speed:** at a normal load the FPGA is ~1.35× the software throughput; under
  pressure that grows past 2× because the FPGA scales where software saturates. The
  software engine has a firm ~68k wall; the FPGA's ceiling is higher than a single
  load box can find.
- **Predictability:** the FPGA's throughput and latency are flat and tight
  regardless of policy size and match density — a fixed pipeline with no cache, no
  garbage collection, no per-rule cost to fall victim to. You provision against a
  flat line.
- **Efficiency (the thesis):** the same, correct, verifiable job at **~half the host
  CPU per request** — the software matcher burns ~8 cores the FPGA does in silicon.
  At fleet scale that's the cores/power/dollars line, and it's where the hardware
  earns its keep.

---

## One-line summary for a slide

> *At a normal load the FPGA does ~1.35× the software engine's throughput; push
> harder and it pulls away past 2× — the FPGA keeps scaling to 146k+ req/s while the
> software engine walls out at ~68k. And it does the same, verifiable job at ~half
> the host CPU per request, because the matching runs in silicon instead of burning
> ~8 CPU cores. (Earlier "~1.09× close" numbers were measured through a single
> overloaded edge node and have been superseded.)*

---

## Appendix — the firm numbers

- **Rule-count sweep (conc 256, 5 reps, 10-node edge):** software (Aergia) ~60.8k →
  59.1k → 56.9k across 2,000 → 4,000 → 8,000 rules (tight, gently declining); FPGA
  (Themis) ~75–77k (8,000-rule median 76.6k). **8,000-rule ratio ~1.35×.** No
  collapse: five 8,000-rule reps held ~57k for software with no crater.
- **Concurrency push (8,000 rules, 10-node edge):** FPGA 77.2k / 115.5k / 145.8k at
  256 / 512 / 1,024; software 57.1k / 63.1k / 67.9k. **Gap 1.35× → 1.83× → 2.15×.**
  Software is engine-bound at ~68k (driver ~47% idle during its run); the FPGA is
  driver-bound at 146k (driver ~84% busy) — its own ceiling is higher.
- **Latency (8,000 rules):** at conc 256, FPGA P99 ~5.8 ms vs software ~7.9 ms; at
  conc 1,024, ~20 ms vs ~28 ms. Matching itself is sub-millisecond (single-request
  probe). Quote with the load level.
- **Errors:** exclusively HTTP 5xx, server-side; <0.1% typical, rising under
  sustained load, heavier on the FPGA path (it drives more throughput downstream).
  Dial/timeout/reset all zero; port-exhaustion ruled out by direct socket
  measurement. 5xx source being confirmed with engineering.
- **Matching is free (single-request probe):** identical latency for zero-match vs
  match-packed text of the same size on the FPGA (512 KB: ≈373 ms either way).
- **Efficiency (measured on the engine hosts):** Themis ~11.3 total host cores
  (Apollo data plane; FPGA does matching in silicon, 0 host cores); Aergia ~19.4
  (~11.3 Apollo + ~8.2 RE2 lexer cores). **~8-core structural software tax**, both
  poll-mode (consumed continuously). Per-request multiplier to be re-measured at the
  corrected throughput. FPGA verified engaged (loaded AFI on f2.6xlarge; DP1–DP3
  correct).
- **Deployment ceiling:** the FPGA refuses a 12,000-rule policy; 8,000 deploys and
  runs clean. Range above the deploy ceiling is untestable today.
- **Large payloads:** ~135–155 MB/s aggregate — **not an engine limit**; the driver
  host's NIC bandwidth-allowance-exceeded counter rose under load and was zero at
  idle (per-instance NIC cap, same-VPC path). ~1 MB requests are rejected by a shared
  front-door size cap.
- **Superseded:** the earlier ~28,600 / ~26,300 req/s "~1.09× close" figures and the
  "~19 ms P99" — both were single-edge-node artifacts. The earlier "8,400 / 3.4×
  cliff" was single-edge-node saturation, now resolved with a scaled edge.

*All figures measured on the live engines. Test harness, policies, and raw results
are versioned in the repo (`artifacts/evidence/`); every run is reproducible from a
single command.*
