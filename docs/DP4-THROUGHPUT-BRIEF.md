# NOL8 Throughput Benchmark — plain-English brief

*A source document. Hand this to Claude (or anyone) to turn into a one-pager,
deck, or explainer. Every number here was measured on the live engines — same
policy, same data, same test harness to both — not simulated and not asserted.*

*Last revised 2026-07-25. **This revision corrects a number in an earlier version
of this brief — see the Correction Notice directly below.***

---

## ⚠️ Correction Notice (read first)

An earlier version of this brief reported that the software engine **"fell off a
cache cliff" at 8,000 rules — dropping to ~8,400 req/s, a 3.4× gap** vs the FPGA.

**That number does not hold up, and we are retracting it.** On clean re-testing —
the *identical* policy (deterministic, byte-for-byte the same), the *identical*
load, the *same* host — the software engine ran at **~26,400 req/s at 8,000 rules,
not 8,400.** The original "8,400" was a **transient depression of the shared test
host** during that one measurement window. The three repeats we ran looked
consistent only because they ran back-to-back *inside* that same bad window, so
they were all depressed together.

Every *independent* measurement we have since taken at 8,000 rules — three
separate corpora, on different days — puts the software engine at **25,000–27,000
req/s.** The lone outlier was the 8,400 figure, and it is the one that made it
into the earlier brief. We caught it, we re-ran it, and the corrected picture is
below.

**Why we're telling it this way:** the whole point of this exercise is a number we
can defend in front of a skeptic. Same policy, same data, same driver to both
engines — and when a result doesn't reproduce, we say so out loud rather than
quietly changing a cell. The corrected story is less dramatic but it is true, and
it still points clearly at where the hardware's real advantage lives.

---

## The 30-second version (corrected)

We put NOL8's hardware engine (an **FPGA**, "Themis") head-to-head against the
standard software approach (**Google's RE2**, "Aergia" — what most people would
reach for) on the exact same job: scanning text for a list of known sensitive
values and replacing them. We pushed both hard, under heavy simultaneous load.
What holds up:

1. **The matching work itself is essentially free on the FPGA.** A request's time
   is almost entirely about moving the bytes, not finding the matches. *(Strongly
   proven — see the diagnostic.)*
2. **On small, frequent messages — the everyday case — the FPGA is steadily
   ahead:** about **9% more throughput** (~28,600 vs ~26,300 req/s) with a tighter,
   flatter latency tail.
3. **Adding rules to the policy does *not* slow either engine** across the range we
   can deploy (up to ~8,000 rules). Both stay flat; the FPGA keeps its steady ~9%
   edge. **There is no cliff, and the edge does not widen with policy size** — this
   corrects the earlier claim.
4. **On very large payloads, both engines are limited by byte *delivery*, not
   matching.** The absolute ceiling we saw (~150 MB/s) is **partly our test host's
   cloud egress cap, not the engine** — we measured the throttle firing during the run
   (see Open Questions). The engine-vs-engine comparison stays fair; the real ceiling
   needs a multi-host driver.

**Where the real story is — and now we've measured it:** at the pure request-rate
level, in this rig, the two engines are *close*. The FPGA's decisive advantage is
**efficiency** — doing that same work at a fraction of the CPU. Measured on the
engine hosts: **the software engine burns ~8 dedicated CPU cores on the matching
that the FPGA does in silicon** — roughly **half the host CPU per request** for the
same result. That is the win, and it is now measured, not asserted. See "The
efficiency result."

---

## What we're comparing (and how we keep it honest)

- **Themis** = NOL8's engine, running on an **FPGA** (a fixed hardware pipeline).
- **Aergia** = **Google RE2**, a fast, respected **software** matcher — the
  incumbent, and a fair stand-in for "the normal way to do this."
- **The job:** both do *deterministic literal replacement* — given a list of
  exact strings (a "policy"), find them in text and swap them out. That's all NOL8
  claims to do here; this is a **speed and capacity** test of that one job, not a
  claim about anything else.
- **The fairness rules:** identical policy, identical data, identical load
  generator to both engines. Where a result went *against* our expectations — or
  failed to reproduce — we kept it and explain it. The goal is a number we can
  defend, not a number that flatters us.

**How to picture the setup:** think of each engine as a **toll booth** that reads
every car (byte) that passes. The road leading up to the booth is the network and
the engine's front door. Some of what we found is about the booth; some is about
the road.

---

## The runs, in order

### Run 1 — "How much can each engine take?"

We drove both engines with many requests at once (up to ~1,000 simultaneous) at
three message sizes — small (~2.6 KB), medium (~34 KB), and large (~290 KB) — and
measured sustained throughput and the latency tail.

- **Small messages:** the FPGA sustained **~28,600 requests/second**, steadily
  ahead of software (~26,300), with a tighter response time under load.
- **Large messages:** both engines flat-lined around the same byte rate
  (~150 MB/s). That ceiling is now qualified — see Open Questions.

### Diagnostic — "Why is the FPGA slower on *big* payloads?" *(holds up)*

We sent single requests (no competition) of increasing size, twice: once with
**no matches** in the text, once **packed with matches**. This separates "cost of
moving bytes" from "cost of matching."

**Result:** on the FPGA, the two were **identical** — a 512 KB message took the
same time whether it had zero matches or hundreds (≈373 ms either way). In other
words, **the matching is free; the whole cost is moving the bytes.** The FPGA
moves large payloads at about 1.4 MB/s per single connection; the software engine
moves them faster *per connection* but has no matching advantage to show for it.

**Plain-English meaning:** the booth is lightning fast. Any slowdown on big trucks
isn't the booth — it's the *road and the on-ramp* feeding it.

### Run 2 — "Make it dead fair"

A reviewer rightly pointed out that a small, repeated set of test messages can let
a *software* engine cheat by keeping recent inputs in its CPU cache — an advantage
the FPGA can't use. So we rebuilt the test with **thousands of unique messages**
and a matched rule set, and re-ran it. **Result:** the cache worry didn't move the
numbers — the FPGA kept its steady, modest edge.

### Run 3 — "Does policy size change the picture?" *(this is the corrected one)*

We fixed everything — same message size, same load — and changed **only the number
of rules in the policy**, from 1,000 up to the largest the engine will accept. The
question: does the FPGA's edge grow with policy size?

**Result (clean re-run, median of 3 repeats per point, spread under 1%):**

| Rules in policy | FPGA (Themis) | Software (RE2) | FPGA advantage |
|---|---|---|---|
| 1,000 | ~28,640 req/s | ~26,360 req/s | ~1.09× |
| 2,000 | ~28,500 req/s | ~26,260 req/s | ~1.09× |
| 4,000 | ~28,580 req/s | ~26,270 req/s | ~1.09× |
| 6,000 | ~28,530 req/s | ~26,270 req/s | ~1.09× |
| 8,000 | ~28,650 req/s | ~26,380 req/s | ~1.09× |

**Both engines are flat across the whole range, and the FPGA holds a steady ~9%
edge that does *not* widen with rule count.** The software engine does **not** slow
down as rules grow — not at 8,000 rules, and not anywhere below it. Latency tracks
the same story: FPGA 99th-percentile ~16 ms, software ~19 ms, both flat throughout
(these are **at 256 concurrency** — at concurrency 1 both are ~2 ms; see "Latency —
what the ~19 ms P99 actually is").

**This corrects the earlier brief on two points, not one:**
1. There is no 3.4× cliff at 8,000 rules (retracted above).
2. There is also no *gradual* "software gets slower as the policy grows" effect
   within the deployable range. Rule count, up to ~8,000, is simply **not** the
   axis where the hardware pulls away.

**One real limit worth stating:** the engine refuses to *deploy* a policy larger
than roughly **8,000–10,000 rules** (10,000 was refused). So we have a clean,
confirmed "flat, no cliff" result up to 8,000 rules, and **we genuinely cannot see
past that** — not because the software held or broke, but because the policy won't
load. If a cliff exists beyond the deployable range, this test cannot reach it.

---

## What the honest result means (positioning)

At the level of raw requests-per-second, in this environment, **the two engines
are close** — the FPGA a steady ~9% ahead on small messages, level on medium, and
byte-delivery-bound (like software) on large. That, by itself, is not the
headline. The defensible FPGA story rests on two things:

- **Predictability.** The FPGA's throughput and latency are **flat and tight
  regardless of policy size and match density** — we varied both and it didn't
  move. Software's *throughput* was also flat here, but a fixed hardware pipeline
  has no cache, no garbage collection, and no per-rule cost to fall victim to as
  conditions get harsher. You provision against a flat line.
- **Efficiency — the thesis, now with a number.** The real advantage is not "more
  requests" but "the *same* requests at a fraction of the cost." Measured directly
  on the engine hosts (see next section): the software engine spends **~8 dedicated
  CPU cores** on the matching that the FPGA does in silicon — **~1.9× the host CPU
  per request**. At fleet scale that is the **cores, power, and dollars** line, and
  it is where the hardware earns its keep.

**We are not going to oversell the request-rate numbers.** On small policies and
light load the two engines are close, and we say so. The hardware's case is
predictability and efficiency at enterprise scale — and we have now measured the
efficiency part directly.

---

## The efficiency result (measured on the engine hosts)

We got onto both engine hosts and measured the CPU each engine's data plane
actually consumes. Both run the *same* front-end data plane (Apollo), so it
subtracts out cleanly and the comparison is fair:

| Engine | Data plane (Apollo) | Matching | **Total host cores** | Throughput |
|---|---|---|---|---|
| **Themis** (FPGA) | ~11.3 cores | **FPGA silicon — 0 host cores** | **~11.3** | ~28,600 req/s |
| **Aergia** (RE2 software) | ~11.3 cores | **~8.2 CPU cores (RE2 lexers)** | **~19.4** | ~26,300 req/s |

- **The software tax the FPGA eliminates is ~8 dedicated CPU cores.** That is the
  matching work, moved from general-purpose cores into silicon.
- **Cores per 1,000 req/s: ~0.39 (FPGA) vs ~0.74 (software) → ~1.9×.** The software
  path costs nearly double the host CPU for the same result.
- **It's a standing cost, not a spike.** Both data planes are DPDK *poll-mode*, so
  those cores are consumed **continuously — whether or not traffic is flowing.** The
  software matcher burns its ~8 cores 24/7; the FPGA hands them back for other work.
- **Verified real:** the FPGA is genuinely doing the matching (loaded FPGA image on
  an AWS F2 instance; correct output confirmed by DP1–DP3), not a software fallback.

This is the honest headline: on raw speed the engines are close, but the FPGA does
the same job at roughly **half the host CPU per request** — the cores/power/cost
advantage that scales with a fleet.

---

## Latency — what the "~19 ms P99" actually is (read before quoting it)

The P99 latencies elsewhere in this brief are measured at **256 concurrent requests**.
That number describes our *load profile*, **not** the engine's matching speed — and it
must not be quoted bare. Dropping the concurrency shows why:

| Concurrency | Throughput | P99 | Mean | Min |
|---|---|---|---|---|
| **1** | 566 req/s | **2.5 ms** | 1.8 | 1.0 |
| 16 | 8,967 | 2.9 ms | 1.8 | 0.9 |
| 64 | 23,755 | 5.9 ms | 2.7 | 1.0 |
| 128 | 25,435 | 10.1 ms | 5.0 | 1.0 |
| **256** | 26,323 | **19.3 ms** | 9.7 | 1.2 |

*(software engine; small payloads. FPGA tracks the same shape, ~15% lower.)*

- **At concurrency 1, a full redaction round-trip is ~2 ms P99 with a ~1 ms floor.**
  That floor is network + Argus edge + Iris QUIC + Apollo + the engine; the **matching
  itself is sub-millisecond**, inside the noise. Software matching is *not* 19 ms.
- **Throughput saturates by ~64 concurrency (~24k req/s).** Past that, more load buys
  no throughput — it only deepens the queue, so P99 climbs 5.9 → 10 → 19 ms while req/s
  is flat. That is textbook closed-loop queuing, not an engine defect.
- **Little's Law closes the loop to three decimals:** mean latency = concurrency ÷
  throughput. 256 ÷ 26,323 = 9.73 ms → measured mean 9.728 ms; 128 ÷ 25,435 = 5.03 →
  5.033; 64 ÷ 23,755 = 2.69 → 2.694. The latency is *fully* accounted for by queue depth
  ÷ service rate — there is no unexplained slack for a hidden "software problem" to live in.

**Takeaway:** the ~19 ms P99 is real and correct, but it is the cost of running 256
requests in flight, not the cost of matching. Quote it as "P99 at 256 concurrency,"
never as the engine's latency.

---

## Open questions (being straight about it)

- **The big-payload ceiling is partly *our* network, not the engines — now
  confirmed.** Our test host runs on cloud infrastructure that **throttles outbound
  bandwidth** and *records when it does*. We measured it directly: during a 20-second
  large-payload run (~154 MB/s of uploads), the host's outbound-allowance-exceeded
  counter **climbed by ~4,000** (and it was *bandwidth*, not packet-rate — the
  packet-rate counter didn't move). So the cloud was **actively clipping our egress
  during the run**, which means the ~150 MB/s "engine ceiling" is **at least partly
  the test host's cloud bandwidth allowance, not the engine.** The *absolute* byte
  ceiling therefore cannot be attributed to the engine; the *relative* engine
  comparison (same host, same throttle) stays fair. This also settles the shape of a
  "push to 380 MB/s" test: one host is allowance-capped, so it must be driven from
  **multiple hosts** to find the real ceiling.
- **Beyond ~8,000 rules is untestable today** — the engine won't accept a larger
  policy (a deployment cap, not a speed result).
- **Does the ~8-lexer count set Aergia's ceiling?** A coherent, testable hypothesis
  (unlike the retracted cliff): Aergia's ~26k plateau may be the 8 RE2 lexers
  saturating — more lexers would buy more req/s but more cores, while the FPGA isn't
  lexer-bound. Falsifiable by varying `--num-lexers`; not yet run.

---

## What we're measuring next (metrics gaps + how we'll capture them)

The 8,400 artifact taught us that our instrumentation had blind spots. Here's what
we're adding, in priority order.

**1. Server-side CPU / cores-per-throughput — DONE (see "The efficiency result").**
Measured directly on the engine hosts: ~8-core software tax, ~1.9× host CPU per
request. This was the biggest gap; it is now closed.

**2. A permanent guard against the class of error we just hit.** Two cheap
additions: (a) report the *spread* across repeats for every data point and
auto-flag any point whose repeats disagree; (b) interleave a fixed "canary"
request between measurements — if the canary slows, the shared host is degraded
and every nearby number is suspect. Either one would have caught the 8,400 in real
time.

**3. Correctness *under load*.** We verify correctness separately from throughput.
Sampling even 1% of responses against the expected output *during* a load run
proves the engines stay correct at saturation — tying the speed story back to the
integrity story.

**4. Where it chokes, and why.** Per-measurement network signals (retransmits,
queue depth, the cloud throttle counters above) plus longer soak runs (minutes,
not seconds) to catch slow drift — thermal, memory growth, software GC pauses —
that a 15-second run misses. And an error *taxonomy* (timeout vs 5xx vs rejected)
instead of a bare count.

**How we capture and show it — self-contained, no heavyweight stack.** We measure
engine-host CPU directly with lightweight on-box sampling (`/proc`, over SSH) and
render the contrast from data *we* capture — no Prometheus/Grafana dependency to
stand up, keep running, or pay for. The demo (`demos/showcase/efficiency-demo.sh`)
does exactly this live: *"the software engine is burning ~8 cores right now, serving
nothing; the FPGA does that in silicon."* We deliberately keep the load driver lean
and put **no per-request tracing** in the hot path — at ~28,000 req/s that would
corrupt the very numbers we're protecting.

---

## Next steps

1. **~~Capture cores-per-throughput~~ — DONE** (the efficiency result above).
2. **~~Build the customer-facing demo system~~ — DONE.** A self-contained,
   SA-runnable demo lives in `demos/showcase/` (live `/v1/process` redaction,
   oracle-verified, plus the efficiency contrast). See its `RUNBOOK.md`.
3. **Settle the large-payload ceiling** — measure the cloud bandwidth-throttle
   delta directly; separate "engine limit" from "our host's cloud cap."
4. **(Optional) Test the lexer-count hypothesis** — vary `--num-lexers` to confirm
   whether Aergia's ~26k plateau is lexer-bound.

---

## One-line summary for a slide

> *On raw speed the FPGA and the software engine are close — the FPGA a steady ~9%
> ahead on small messages and flat as the policy grows. The hardware's real win is
> efficiency: it does the same, correct, verifiable job at **~half the host CPU per
> request** — the software matcher burns ~8 CPU cores that the FPGA does in silicon.
> (An earlier "3.4× cliff" figure was a measurement artifact and has been retracted.)*

---

## Appendix — the firm numbers (corrected)

- **Small-message throughput under load (median of 3, spread <1%):** FPGA
  ~28,600 req/s vs software ~26,300 req/s → **~1.09×**, steady from 1,000 to 8,000
  rules.
- **Latency under load, small messages (at 256 concurrency):** FPGA 99th-percentile
  ~16 ms vs software ~19 ms (both flat across rule count) — the FPGA tail is tighter by
  ~15%, *not* the "roughly half" the earlier brief claimed (that was based on the
  retracted 8,400 point). **This is a 256-deep-queue number, not matching time** — at
  concurrency 1 both engines are ~2 ms P99 with a ~1 ms floor; matching is sub-ms. See
  the "Latency" section for the full concurrency curve + Little's Law check.
- **Matching is free (single-request probe):** identical latency for zero-match vs
  match-packed text of the same size on the FPGA (512 KB: ≈373 ms either way).
- **Big-payload ceiling:** both engines ~135–155 MB/s aggregate — **but the absolute
  figure is NOT an engine limit:** measured directly, the test host's cloud egress-
  allowance-exceeded counter rose ~4,000 during a 20 s / ~154 MB/s run, so the cloud
  was actively throttling our uploads. Relative engine comparison stays valid; the
  real ceiling needs a multi-host driver. ~1 MB requests are rejected by a shared
  front-door size cap.
- **Rule count (corrected):** software throughput **flat at ~26,300 req/s from
  1,000 through 8,000 rules — no cliff, no slope**; FPGA flat at ~28,600 req/s
  throughout. Deployment ceiling observed between 8,000 and 10,000 rules (10,000
  refused), so the range above 8,000 is untestable today.
- **Efficiency (measured on the engine hosts):** Themis ~11.3 total host cores
  (Apollo data plane; FPGA does matching in silicon, 0 host cores); Aergia ~19.4
  (~11.3 Apollo + ~8.2 RE2 lexer cores). **~8-core software tax; ~0.39 vs ~0.74
  cores per 1k req/s → ~1.9× host CPU per request.** Both poll-mode, so consumed
  continuously. FPGA verified engaged (loaded AFI on f2.6xlarge; DP1–DP3 correct).
- **Retracted:** the earlier "~8,400 req/s / 3.4× at 8,000 rules" figure — a
  transient shared-host artifact that did not reproduce.

*All figures measured on the live engines. Test harness, policies, and raw results
are versioned in the repo; every run is reproducible from a single command.*
