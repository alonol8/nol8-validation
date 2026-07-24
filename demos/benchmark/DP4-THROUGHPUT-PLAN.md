# Data Point 4 - Throughput at load, plan

Planning only. This is the benchmark that lets NOL8 (Themis, FPGA) visibly pull ahead of
Aergia (RE2, software). Everything in DP1-DP3 proves **correctness + parity + payload
reduction**; none of it shows **throughput under load**, which is the FPGA's actual
advantage.

## Why the current numbers don't show it

- DP1 measured engine time at **<0.3 ms, and ~97% of a call is network + TLS.** At one
  request at a time, the engine is inside the measurement noise; the network dominates.
- The functional sets are tiny (52 / 1000 / 13 records) and run **sequentially**. They
  answer "is it correct?" not "how much can it take?"
- The FPGA story is: a **fixed hardware pipeline** sustains high, flat throughput; a CPU
  RE2 engine **saturates** under concurrency (latency balloons, throughput plateaus).
  That divergence only appears when you drive enough concurrent load to make the *engine*
  (not the network) the bottleneck.

## What to measure (the honest way)

The deliverable is a **throughput-vs-latency curve** for each engine on the identical
policy + data, not a single number:

- **Throughput:** sustained requests/sec (and bytes/sec) at steady state.
- **Latency percentiles:** p50 / p95 / p99 / p99.9 (NOT averages - tail latency is the
  story under load).
- **Saturation point:** the load level where each engine's latency knees upward /
  throughput plateaus. Show BOTH engines' knees. The claim is "Themis holds flat past
  where RE2 saturates," and it must be measured, not asserted.
- **Sustained-throughput stability:** does throughput/latency degrade over a multi-minute
  run (thermal, queueing, GC on the RE2 side)?
- **Error rate** under load (timeouts, resets, 5xx).
- Vary **payload size** (small / medium / large chunks) and **concurrency** (1, 8, 32,
  128, 512, ...) - both stress the matcher differently.

## How to build it

Two viable drivers; decide with the user:

- **A) Go load driver (reuse what we have).** We already own `callEngineProcess` + the
  engine config. Add a concurrency pool (N goroutines, connection reuse via
  `http.Transport{MaxIdleConnsPerHost}`), open-loop or closed-loop rate control, and an
  HDR-histogram for percentiles. Full control, integrity-consistent with DP1-3, emits a
  CSV we can render. Most work, best fit.
- **B) Off-the-shelf (bombardier / k6 / vegeta / hey).** Post the `{"message": ...}`
  contract at a target rps/concurrency; capture the rps + latency report. Fast to stand
  up, well-understood output. Needs a targets file / script for realistic varied payloads
  (a request corpus). Good for a quick first read; less integrated.

Recommendation: **B for a fast first signal, then A for the reportable, integrity-clean
run.**

**Run location:** on EC2 (10.8.10.40) against the argus edge (10.8.11.254) - same VPC, low
RTT, so the engine (not WAN latency) becomes the bottleneck sooner. Watch that the *driver
box* has headroom (it must not saturate before the engine); if it does, run multiple
drivers.

**Data / load corpus:** generate at scale with `validate generate` (the scale knobs exist:
`config/workloads/enterprise-dlp.yaml`, seed / rule-count / record-count; the 5,000-rule /
10,000-record qualification is the floor - go bigger). Deterministic, reproducible. Feed
records as request bodies; keep the same policy on both engines.

## Honest design (integrity, do not skip)

- **Same policy + same data to both engines.** [[benchmark-integrity-no-rigging]]
- **Report the whole curve, not a cherry-picked point.** At low concurrency the result
  will (honestly) be network-bound parity; the FPGA win appears at high concurrency. Show
  both regions.
- **Isolate the engine or say you didn't.** Client-side latency includes network + TLS +
  the engine's HTTP front-end. Pool connections (amortize TLS), push concurrency until
  engine-bound, and be explicit that we are measuring end-to-end unless a server-side
  timing hook is exposed (none is, per DP1). The TLS/front-end could be the limiter rather
  than the matching core - note it if the curves suggest it.
- **Watch the confounds:** the load driver saturating first; the network card / SG rate
  limits; connection-pool limits on either engine's front-end; RE2 warm-up / GC. Log what
  bounded the run so nobody over-reads it.
- **NOL8 still does listMatch only** - the load test uses the same literal policy; this is
  a throughput test, not a new capability claim.

## Deliverable

A scale report (`kind: dp4` / `throughput`) with: the throughput-latency curves (Themis
vs Aergia), a percentile table at each concurrency level, the saturation points, and an
honest "what bounded the run" note. This is the report that finally shows the FPGA
advantage - if it's there, the curve proves it; if the network dominates all the way up,
that's the honest finding and tells us the next thing to change (get closer, bigger
payloads, more concurrency).

## Open decisions for the user (before the build)

1. **Driver:** off-the-shelf first (B) for a quick read, or straight to the Go driver (A)?
2. **Load profile:** target concurrency levels + payload sizes + run duration.
3. **Corpus scale:** how big (records), and reuse DP1's pre-index corpus or generate a
   fresh enterprise-DLP set?
4. **What "win" looks like:** agree the honest success criterion up front (e.g. "Themis
   sustains >= Xk rps at flat p99 past where Aergia's p99 crosses N ms").
