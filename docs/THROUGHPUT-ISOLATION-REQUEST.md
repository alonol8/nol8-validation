# Throughput isolation — what's capping large-payload bandwidth?

**Ask, in one line:** we have a clean, reproducible result showing the *matching*
is free but *large-payload throughput* is capped at ~150 MB/s and collapses at
high concurrency. We can't tell from the client whether that cap is the argus
front end, the path into the FPGA card, or the network. Four things below would
let us isolate it — the first one alone probably settles it.

## What we measured (all end-to-end, from an in-VPC load driver)

Same 5,000-rule literal (listMatch) policy and the same request corpus to both
the FPGA engine (:443) and a software RE2 engine (:444). Closed-loop load, N
requests in flight, 30s steady-state per point.

**Small payloads (~2.6 KB): the FPGA wins clearly.** ~29,000 req/s, ~1.7x the RE2
engine, with a 2.5x tighter p99, flat under load. No complaint here — this is the
engine doing its job.

**Large payloads (~293 KB): both engines are bandwidth-bound.**

| concurrency | FPGA req/s | FPGA p99 | FPGA errors |
|---|---|---|---|
| 128 | 532 | 434 ms | 2 |
| 256 | 540 | 933 ms | 0 |
| 512 | 557 | 1,645 ms | 7 |
| 1024 | 570 | 3,111 ms | 3 |
| 2048 | **~2** | — | **17,225** |

Throughput is flat from 128 -> 1024 (~550 req/s, ~155 MB/s); adding connections
only inflates latency (queueing), then the engine collapses at 2048 concurrency.

**The key control — matching is not the bottleneck.** At concurrency 1, we sent
clean text (zero policy matches) and match-packed text of the *same size*:

| payload | clean | match-packed |
|---|---|---|
| 64 KB | 49.0 ms | 48.9 ms |
| 256 KB | 187.5 ms | 187.0 ms |
| 512 KB | 372.9 ms | 373.3 ms |

Identical. The replacement work adds nothing; per-request latency scales linearly
with **bytes** (~0.73 ms/KB, ~1.4 MB/s per connection). So the cost is the data
path, not the matcher.

Also observed: **~1 MB request bodies return an error on both engines** — looks
like a shared request-size cap at the edge.

## The question we can't answer from the client

The ~1.4 MB/s-per-connection / ~150 MB/s-aggregate ceiling lives somewhere in the
path *in front of the matcher*. We measured the whole path as one number, so we
cannot tell which stage it is:

1. the **argus / HTTP front end** (TLS termination, proxying, buffering), or
2. the **path into the FPGA card** (PCIe / DMA ingest rate), or
3. the **network** between the driver and the edge.

Each is a different fix. We'd rather prove which than guess.

## What would isolate it (any one helps; #1 likely settles it)

1. **A server-side processing-time metric** — time spent *in the engine* per
   request, excluding transport. If engine time is tiny while our end-to-end time
   is large, the cap is the front end / transport, not the core. This is the
   cleanest single answer.
2. **The front end's documented limits** — max concurrent connections, per-
   connection and aggregate bandwidth, and the request-size cap (we hit an error
   near 1 MB). The 2048-concurrency collapse smells like a hard connection cap.
3. **Permission/path to drive load from the engine host itself** (or immediately
   adjacent to the edge), to remove the network hop and see if the ceiling moves.
4. **The FPGA card's ingest bandwidth spec** — the ceiling we *should* expect if
   bytes were fed straight to the card at line rate.

## Why it matters

The small-payload result is a strong, honest story on its own. But the large-
payload story is currently "both engines are bandwidth-bound and ours collapses
at extreme concurrency" — which undersells the hardware if the limiter is really
the front end and the card could take far more. Isolating this tells us whether
the fix is "tune/scale the front end" or "this is the card's real limit," and lets
us state the large-payload number with the same confidence as the small-payload one.

Everything above is reproducible on demand (the load driver, the size probe, and
the exact policy/corpus are all in hand).
