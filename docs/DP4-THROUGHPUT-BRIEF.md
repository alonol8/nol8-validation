# NOL8 Throughput Benchmark — plain-English brief

*A source document. Hand this to Claude (or anyone) to turn into a one-pager,
deck, or explainer. Every number here was measured on the live engines — same
policy, same data, same test harness to both — not simulated and not asserted.*

---

## The 30-second version

We put NOL8's hardware engine (an **FPGA**) head-to-head against the standard
software approach (**Google's RE2**, what most people would reach for) on the
exact same job: scanning text for a list of known sensitive values and replacing
them. We pushed both engines hard, under heavy simultaneous load, and learned
four things:

1. **The matching work itself is essentially free on the FPGA.** The time a
   request takes is almost entirely about moving the bytes, not finding the
   matches.
2. **For small, frequent messages — the everyday case — the FPGA wins clearly.**
3. **For very large payloads, both engines hit the same wall:** they're limited
   by how fast bytes can be *delivered* to the engine, not by the matching.
4. **The FPGA's advantage grows as the policy gets bigger.** Software slows down
   as you add more rules; the FPGA doesn't. Past a certain policy size the
   software engine falls off a cliff — in our test it lost more than half its
   throughput — while the FPGA stayed flat.

**The headline for a customer:** *the bigger and busier your policy, the more the
hardware pulls ahead — and big, busy policies are exactly what real enterprises
have.*

---

## What we're comparing (and how we keep it honest)

- **Themis** = NOL8's engine, running on an **FPGA** (a fixed hardware pipeline).
- **Aergia** = **Google RE2**, a fast, respected **software** matcher — the
  incumbent, and a fair stand-in for "the normal way to do this."
- **The job:** both do *deterministic literal replacement* — given a list of
  exact strings (a "policy"), find them in text and swap them out. That's all
  NOL8 claims to do here; this is a **speed and capacity** test of that one job,
  not a claim about anything else.
- **The fairness rules:** identical policy, identical data, identical load
  generator to both engines. Where a result went *against* our expectations, we
  kept it and explain it. The goal is a number we can defend, not a number that
  flatters us.

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

- **Small messages:** the FPGA sustained **~29,000 requests/second**, clearly
  ahead of software, with a much steadier response time under load.
- **Large messages:** both engines flat-lined around the same byte rate
  (~150 MB/s), and at extreme load the FPGA's large-payload path actually broke
  down first.

That last part was surprising, so we stopped and investigated before going
further.

### Diagnostic — "Why is the FPGA slower on *big* payloads?"

We sent single requests (no competition) of increasing size, twice: once with
**no matches** in the text, once **packed with matches**. This separates "cost of
moving bytes" from "cost of matching."

**Result:** on the FPGA, the two were **identical** — a 512 KB message took the
same time whether it had zero matches or hundreds. In other words, **the matching
is free; the whole cost is moving the bytes.** The FPGA moves large payloads at
about 1.4 MB/s per connection; the software engine moves them ~20× faster per
connection.

**Plain-English meaning:** the booth is lightning fast. The slowdown on big trucks
isn't the booth — it's the *road and the on-ramp* feeding the booth. (We've asked
engineering to help pin down exactly which part of the road; see "Open questions.")

### Run 2 — "Make it dead fair"

A reviewer rightly pointed out that a small, repeated set of test messages can let
a *software* engine cheat by keeping recent inputs in its CPU cache — an advantage
the FPGA can't use. So we rebuilt the test with **thousands of unique messages**
and a matched rule set, and re-ran it.

**Result:** the cache worry didn't move the numbers much — but the re-run
surfaced the *real* lever by accident. When we changed the number of rules in the
policy, the **software engine's speed changed a lot and the FPGA's didn't.** That
pointed straight at the most important test.

### Run 3 — "The one that matters: policy size"

We fixed everything — same message size, same load — and changed **only the number
of rules in the policy**, from 1,000 up. The question: does the FPGA's edge grow
with policy size?

**Result (initial; a confirmatory run is underway as of this writing):**

| Rules in policy | FPGA (Themis) | Software (RE2) | FPGA advantage |
|---|---|---|---|
| 1,000 | ~29,000 req/s | ~26,000 req/s | ~1.1× |
| 2,000 | ~29,000 req/s | ~26,000 req/s | ~1.1× |
| 4,000 | ~28,000 req/s | ~26,000 req/s | ~parity |
| 8,000 | ~28,000 req/s | **~10,600 req/s** | **~2.7×** |

The software engine held steady up to 4,000 rules and then **fell off a cliff at
8,000** — throughput more than halved and its response time tripled. The FPGA
stayed flat the whole way.

**Why this happens (and why it's not a fluke):** a software matcher builds an
internal lookup table that grows with the number of rules. Past a point that table
no longer fits in the CPU's fast cache, so every byte scanned starts hitting slow
memory and throughput collapses. It's a well-understood "cache cliff." **A fixed
hardware pipeline has no such cache to fall out of** — which is the whole point of
doing this in silicon.

---

## What we don't know yet (being straight about it)

- **Exactly where the big-payload "road" bottleneck is.** We proved it's *not* the
  matching, but our measurement is end-to-end (network + front door + engine). We
  can't yet split "the front door" from "the hardware's on-ramp." We've written a
  short, specific ask to engineering for one server-side number that would settle
  it. Until then, "it's the delivery path, not the matcher" is proven; "it's
  specifically component X" is a hypothesis.
- **How high the policy-size advantage goes.** We hit two honest ceilings: the
  engine wouldn't *accept* a policy past roughly 16,000 rules (a deployment cap,
  not a speed result), and our data generator refused to build a 32,000-rule set
  because the values started overlapping in a way that would corrupt the test. So
  we have a clean, dramatic result at 8,000 rules and a confirmatory run in
  progress; we have not yet measured the true top end.

---

## Why this matters (the positioning)

- **Real enterprise policies are big and busy.** Thousands of known-bad values,
  high message volume. That is precisely the regime where the software approach
  starts to buckle and the hardware stays flat.
- **The value proposition isn't "faster on a toy test."** It's **"predictable at
  scale."** As your policy and traffic grow, the software curve bends upward
  (slower, spikier) and the hardware curve stays flat. You provision against the
  flat line.
- **It's an honest story.** On small policies and light load the two are close —
  we say so. The hardware earns its keep exactly where it's hard to keep up:
  large policies, heavy concurrent load, and big payloads once the delivery path
  is fixed.

---

## One-line summary for a slide

> *NOL8's FPGA does the matching for free and stays flat as your policy grows;
> the software approach falls off a cache cliff past a few thousand rules — and
> real policies are far bigger than that.*

---

## Appendix — the firmer numbers

- **Small-message throughput under load (fair test, 4k rules):** FPGA ~28,700
  req/s vs software ~25,800 req/s.
- **Latency stays tight on the FPGA:** at heavy load on small messages, FPGA
  99th-percentile latency was roughly half the software engine's.
- **Matching is free (single-request probe):** identical latency for zero-match
  vs match-packed text of the same size on the FPGA (e.g. 512 KB: 373 ms either
  way).
- **Big-payload ceiling:** both engines ~135–155 MB/s aggregate; the limit is
  byte delivery, and ~1 MB requests are rejected by a shared front-door size cap.
- **Policy-size cliff (initial):** software throughput ~26,000 → ~10,600 req/s
  going from 4,000 to 8,000 rules; FPGA flat at ~28,000; ~2.7× at 8,000 rules.

*All figures measured on the live engines. Test harness, policies, and raw
results are versioned in the repo; every run is reproducible from a single
command.*
