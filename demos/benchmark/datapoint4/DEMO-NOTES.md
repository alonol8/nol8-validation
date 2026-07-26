# Data Point 4 - Throughput at load

> ⚠️ **SUPERSEDED — read `docs/DP4-THROUGHPUT-BRIEF.md` for current numbers.**
> The throughput figures below were measured through a **single Argus edge node**
> that was itself the bottleneck (both engines pinned ~27k). With the edge scaled to
> 10 nodes the real numbers are far higher: **Themis ~76.6k vs Aergia ~56.9k @8k
> rules (1.35×), widening to 2.15× under concurrency; software walls ~68k, FPGA >146k;
> efficiency ~2.3× host CPU/req.** The method here is still valid; the absolute
> numbers in the tables below are not. See the brief.

**Use case:** how much can each engine actually take? DP1-DP3 prove correctness,
parity, and payload reduction one request at a time - where ~97% of a call is
network + TLS and the engine sits inside the measurement noise. DP4 does the
opposite: it holds many requests in flight continuously against one engine and
measures sustained throughput and the latency tail as concurrency climbs. This is
where a fixed FPGA pipeline is *expected* to hold flat past where a CPU RE2 engine
saturates - and if the network dominates all the way up, the flat curves say so.

## The honest frame

- **Same policy, same corpus, same driver to every engine.** The load uses the
  same 5,000-rule **listMatch (literal)** policy - a throughput test, not a new
  capability claim. NOL8 still does deterministic literal replacement only.
- **Show the whole curve, no pre-set target.** At low concurrency the result is
  honestly network-bound parity; any separation appears under load. Both regions
  are reported. The report's headline is *computed from the data*, not asserted.
- **End-to-end, not engine-isolated.** Each latency includes network + TLS + the
  engine's HTTP front-end (no server-side timing hook is exposed). Connections are
  pooled so TLS is amortized, but the front-end could bound a region rather than
  the matching core. The "What bounded the run" section calls that out.

## What it measures

Per `(engine, concurrency, payload)` cell, a closed-loop load: exactly
`concurrency` requests in flight at all times for a 30s measured window (after a
10s warm-up), sustained throughput = completed / elapsed. Emits req/s, MiB/s,
p50/p95/p99/p99.9 latency, min/max/mean, errors, and a tail-overflow count.

- **Concurrency sweep:** 1, 8, 32, 128, 512, 1024 (in-flight requests = real
  parallel HTTP/1.1 connections, not HTTP/2 streams).
- **Payload bands:** small (=4 KB), medium (4-64 KB), large (=64 KB), bucketed
  from the enterprise-dlp size distribution.
- **Corpus:** 50,000 records / 5,000 rules, deterministic seed.

## Diagnostic finding: latency is byte-bound, not match-bound (2026-07-24)

A payload-size probe at concurrency 1 (`probe-live.sh` -> `probe-size.py`, clean
vs matched bodies, same policy on both engines) characterized the per-request cost:

| size | Themis clean | Themis matched | Aergia clean | Aergia matched |
|---|---|---|---|---|
| 16KB | 13.9ms | 13.4ms | 2.3ms | 3.3ms |
| 64KB | 49.0ms | 48.9ms | 4.1ms | 5.5ms |
| 256KB | 187.5ms | 187.0ms | 9.4ms | 11.4ms |
| 512KB | 372.9ms | 373.3ms | 16.8ms | 20.4ms |

- **Themis: clean ≈ matched at every size** — the matching core adds ~nothing.
  Latency scales **linearly with bytes**, ~0.73 ms/KB, i.e. **~1.4 MB/s per
  connection**. The per-request cost is the **data path** (front-end / streaming),
  not the FPGA matcher.
- **Aergia (RE2): ~30 MB/s per connection**, ~20x faster per large request; its
  software path adds a small, real matching increment (clean -> matched).
- **1 MB bodies errored on BOTH engines** — a shared ~1 MB request-size cap at the
  edge, not an engine difference. The driver's "large" bucket is capped below it
  (786 KB) so a 413 can't contaminate the throughput numbers.

Implication: at concurrency 1, Themis is transport-bound and slower per large
request - state that plainly. But that is *per connection*. The FPGA thesis is
about **parallel** streams: in the throughput smoke, Themis large-payload
throughput scaled ~24x from c=1->32 (near-linear, unsaturated) while Aergia
scaled ~4.8x (CPU saturating). Whether Themis overtakes at c=512/1024 is what the
full sweep decides.

## Sweep results (2026-07-24, high-concurrency focus 128-2048)

50k-record / 5k-rule corpus, both engines, 30s measured per cell. Three regimes:

| payload | Themis peak rps | RE2 peak rps | Themis p99 @512 | RE2 p99 @512 | verdict |
|---|---|---|---|---|---|
| small (2.6 KB) | **29,174** (c=512) | 17,719 | **34 ms** | 87 ms | Themis up to 1.7x, 2.5x tighter tail |
| medium (34 KB) | 5,890 | 5,085 | 194 ms | 274 ms | ~parity, Themis ~15% ahead |
| large (293 KB) | 570 (c=1024) | 486 | 1,645 ms | 1,988 ms | bandwidth-bound both; see cliff |

- **Small, frequent payloads are the win:** Themis is higher-throughput AND
  lower-latency at every concurrency level. The fixed pipeline absorbs request
  rate where RE2's tail climbs. This is the common inline-guardrail workload.
- **Medium narrows to parity** as the per-request byte cost (transport, not
  matching) starts to dominate and both engines pay it.
- **Large is bandwidth-bound on both** (~135-159 MiB/s); they saturate by ~128
  concurrency, so adding connections only inflates latency. Themis holds a
  slightly higher ceiling through 1024, then **collapses at 2048 (17,225 errors,
  ~2 rps)** while RE2 degrades gracefully (2,185 errors) - a hard parallel-transfer
  ceiling on Themis's byte-bound front end, not a matcher issue. Provision
  large-payload concurrency below that cliff.
- **Caveat:** at 2048 on tiny payloads both engines wobble (Themis 111 errors and
  a dip from its 512 peak; RE2 jumps) - at ~26k rps of 2.6 KB requests the 8-core
  driver box is a plausible limiter. Themis's real peak is at 512.

Report: `run.json` (committed) -> `throughput-report.html` (below).

## Reproduce (on EC2 - has Go 1.22 and reaches the engines)

```bash
cd /opt/nol8/nol8-validation
bash demos/check-engines.sh          # both engines OK first

# Full sweep, both engines (~24 min per engine). Generates a fresh corpus,
# deploys its policy to each engine, drives the sweep, writes per-engine CSVs.
bash demos/benchmark/datapoint4/run-live.sh

# Quick read (smaller sweep, shorter windows, Themis only):
DP4_ENGINES=themis DP4_CONCURRENCY=1,32,256 DP4_DURATION=10 DP4_WARMUP=3 \
  bash demos/benchmark/datapoint4/run-live.sh
```

Knobs (env): `DP4_RECORDS`, `DP4_RULES`, `DP4_CONCURRENCY`, `DP4_PAYLOADS`,
`DP4_WARMUP`, `DP4_DURATION`, `DP4_ENGINES`, `DP4_CORPUS` (reuse a corpus dir),
`DP4_INSECURE=1` (skip TLS verify).

## Build the report

```bash
# CSV -> run.json (descriptive; narrative computed from the numbers)
python demos/benchmark/datapoint4/build-run.py \
    demos/benchmark/datapoint4/results/throughput_combined.csv \
    demos/benchmark/datapoint4/run.json \
    --manifest <run-dir>/generated/manifest.json      # optional: adds corpus size

# run.json -> self-contained HTML (dark web / light on Export-to-PDF)
python demos/benchmark/make-report.py \
    demos/benchmark/datapoint4/run.json \
    demos/benchmark/datapoint4/throughput-report.html
```

The report renders throughput and p99 curves (one line per engine, faceted by
payload), the full per-cell grid, and the "What bounded the run" integrity notes.

## What's tracked vs generated

Tracked: the Go driver, `run-live.sh`, `build-run.py`, these notes, and `run.json`
once a real run is committed. Gitignored: `results/` (CSVs + the `dp4driver`
binary), `.gocache/`, and the rendered `throughput-report.html`.
