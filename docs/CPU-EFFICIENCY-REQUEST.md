# CPU cost to scale — what we want to measure, and the ask

**The selling point, in one line:** software matching (RE2) buys throughput with
**CPU cores**, and the bill grows with policy size; the FPGA does the matching in
hardware, so the host CPU is freed. We've measured the *throughput* side of this
(RE2 falls off a cliff past ~6,000 rules; the FPGA stays flat). This is about
measuring the *CPU* side: **for the same workload, how many cores does RE2 burn on
matching/replacing vs. how much host CPU the FPGA path needs?**

## Why it matters

- Throughput numbers answer "how fast." CPU numbers answer "**how much hardware do
  I have to buy, and how does that bill grow?**" For a buyer sizing a deployment,
  the second question is often the real one.
- It reframes the cliff we measured: past ~6,000 rules RE2 didn't just slow down —
  to hold the *same* throughput you'd have to throw **more cores** at it, and even
  then the per-core efficiency has collapsed. The FPGA's host CPU shouldn't move,
  because the matching never touched the CPU in the first place.

## The number we want

For the identical workload (same policy, same corpus, same offered load), at each
rule count:

- **RE2:** host CPU (core-seconds) consumed, and **CPU per unit of work** —
  core-seconds per GB scanned, or cores needed to sustain a target req/s.
- **FPGA (Themis):** host CPU consumed for the *same* delivered throughput. The
  matching is offloaded to the card, so this should be dominated by the HTTP front
  end (TLS, request handling) and stay roughly flat as rules grow.
- **The headline contrast:** `RE2 cores − FPGA cores` at matched load ≈ the CPU the
  FPGA takes off your host, and how that gap *widens* with policy size.

## Two ways to get it

### 1. Ask engineering (the definitive, real-engine number)

Both engines share the tenant/data-plane host, and our sweep drives them **one at a
time**, so a per-cell host-CPU capture cleanly attributes CPU to whichever engine
is under load. The ask:

- While we run a fixed-load sweep, **capture host CPU on the engine box** per cell
  — overall utilization and, ideally, **per-process** (`pidstat -u`, `mpstat -P
  ALL`, or whatever's handy), plus core count. A few seconds of steady-state per
  point is enough.
- Do it at several rule counts (1k / 4k / 8k) so we see the CPU curve, not one
  point. We'll coordinate timing so the box is otherwise quiet.
- If a metrics endpoint already exposes per-process CPU, even better — we just read
  it during the run.

This is the same family as the [throughput isolation ask](THROUGHPUT-ISOLATION-REQUEST.md):
we need a little server-side visibility on a box we don't control.

### 2. Measure it ourselves (self-owned, and it goes further)

We don't need the engine host to show the *RE2 CPU-scaling wall* — RE2's matching
is CPU-bound and deterministic, so we can measure the matching cost directly on
hardware we fully instrument:

- **In-process RE2 microbenchmark (fastest to stand up).** Go's `regexp` is an
  RE2-equivalent engine. Compile a policy of N literals, scan a fixed corpus
  in-process, and measure **matching throughput per core** and **core-seconds per
  GB** as N climbs. Because it's in-process, we are **not** capped by the engine's
  ~8k-rule deploy limit — we can push to 16k / 32k / 64k rules and show the CPU
  wall well past where the networked test had to stop. Honest labeling: this is
  "RE2-family matching cost," a proxy for the C++ RE2 engine's CPU shape, not the
  full networked engine.
- **Real RE2 on our own box (fuller ownership).** Stand up the RE2 engine on
  hardware we control (there's terraform for this) and capture its CPU under the
  same driver load — the same measurement engineering would run, but on a box we
  own end to end.

The FPGA "host CPU stays near-idle for matching" claim still needs the engine-host
capture (option 1) to confirm on the real product — but the *RE2 half*, which is
the dramatic half, we can own today.

## Recommendation

Do **both**: stand up the in-process RE2 CPU microbenchmark now (it turns "RE2 is
CPU-hungry" into a measured cores-per-GB curve that keeps climbing past the deploy
cliff), and send engineering the option-1 ask so we can put the FPGA's near-flat
host-CPU line next to it on the real product. Together they make the cleanest
scaling slide we have: **one line that climbs with every rule, next to one that
doesn't.**
