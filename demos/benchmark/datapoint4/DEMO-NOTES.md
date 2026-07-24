# Data Point 4 - Throughput at load

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
