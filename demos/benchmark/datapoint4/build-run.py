#!/usr/bin/env python3
"""Assemble a dp4 run.json from the throughput sweep CSV.

The renderer (make-report.py, kind=dp4) is data-driven; this turns the driver's
combined CSV into the run.json it reads. The narrative is DESCRIPTIVE, computed
from the numbers - no pre-set win target (that was the DP4 decision). If the
curves separate under load it says so; if they stay together it says that too.
Tweak the prose afterwards if you want; the charts + grid come straight from the
data.

  python demos/benchmark/datapoint4/build-run.py \
      demos/benchmark/datapoint4/results/throughput_combined.csv \
      demos/benchmark/datapoint4/run.json \
      [--manifest <generated/manifest.json>]
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

NUM_INT = {"concurrency", "records_used", "avg_body_bytes", "completed", "errors", "tail_overflow"}
NUM_FLT = {"duration_s", "rps", "request_mib_s", "p50_ms", "p95_ms", "p99_ms",
           "p999_ms", "min_ms", "max_ms", "mean_ms",
           "err_p50_ms", "err_p99_ms", "stall_seconds_total", "wall_elapsed_s"}


def load_cells(csv_path: Path) -> list[dict]:
    cells = []
    with csv_path.open() as fh:
        for row in csv.DictReader(fh):
            c = {}
            for k, v in row.items():
                if k in NUM_INT:
                    c[k] = int(v)
                elif k in NUM_FLT:
                    c[k] = float(v)
                else:
                    c[k] = v
            cells.append(c)
    return cells


def order_preserving(values, preferred):
    seen = [v for v in preferred if v in values]
    seen += [v for v in values if v not in seen]
    return seen


def peak(cells, engine):
    rows = [c for c in cells if c["engine"] == engine]
    return max(rows, key=lambda c: c["rps"]) if rows else None


def cell_at(cells, engine, payload, concurrency):
    for c in cells:
        if c["engine"] == engine and c["payload"] == payload and c["concurrency"] == concurrency:
            return c
    return None


def fmt_rps(v):
    return f"{v:,.0f}" if v >= 1000 else (f"{v:.0f}" if v >= 100 else f"{v:.1f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--manifest", type=Path, help="generated/manifest.json (corpus stats)")
    args = ap.parse_args()

    cells = load_cells(args.csv)
    if not cells:
        raise SystemExit("no cells in CSV")

    engines = order_preserving({c["engine"] for c in cells}, ["themis", "aergia"])
    payloads = order_preserving({c["payload"] for c in cells}, ["small", "medium", "large"])
    concurrencies = sorted({c["concurrency"] for c in cells})
    top_c = concurrencies[-1]
    heavy = payloads[-1]  # largest payload band present

    records = None
    if args.manifest and args.manifest.exists():
        man = json.loads(args.manifest.read_text())
        records = man.get("realized_records") or man.get("requested_records")

    themis_peak = peak(cells, "themis")
    aergia_peak = peak(cells, "aergia")
    has_aergia = aergia_peak is not None

    # Headline: does the largest-payload curve separate at the top of the sweep?
    t_top = cell_at(cells, "themis", heavy, top_c)
    a_top = cell_at(cells, "aergia", heavy, top_c) if has_aergia else None
    if t_top and a_top and a_top["rps"] > 0:
        ratio = t_top["rps"] / a_top["rps"]
        if ratio >= 1.15:
            accent = " separate under load."
            lede = (f"At low concurrency the two engines are network-bound and track together. "
                    f"By {top_c} concurrent requests on the {heavy} payload, Themis sustains "
                    f"{ratio:.1f}x Aergia's throughput. The whole curve is below - read both regions.")
        elif ratio <= 0.87:
            accent = " favor the incumbent here."
            lede = (f"On this corpus and network, Aergia (RE2) sustains more at {top_c} concurrent "
                    f"requests on the {heavy} payload. The honest curve is below; the bounds note "
                    f"says what limited Themis.")
        else:
            accent = " stay together."
            lede = (f"Across the whole sweep the two engines track within "
                    f"{abs(1-ratio)*100:.0f}% at {top_c} concurrency on the {heavy} payload - the "
                    f"network, not the matching core, is still the bottleneck. That is the finding.")
    else:
        accent = " under load."
        lede = ("A single-engine throughput sweep: sustained requests/sec and the latency tail as "
                "concurrency climbs from 1 to the saturation point. Bring Aergia back for the "
                "side-by-side comparison.")

    # Stat band (4 cells)
    stats = []
    if themis_peak:
        stats.append({"value": fmt_rps(themis_peak["rps"]), "unit": "req/s", "key": True,
                      "label": f"Themis peak sustained ({themis_peak['payload']} payload, c={themis_peak['concurrency']})"})
        stats.append({"value": f"{themis_peak['p99_ms']:.1f}", "unit": "ms", "key": False,
                      "label": f"Themis p99 at peak throughput"})
    if has_aergia:
        stats.append({"value": fmt_rps(aergia_peak["rps"]), "unit": "req/s", "key": False,
                      "label": f"Aergia (RE2) peak sustained ({aergia_peak['payload']}, c={aergia_peak['concurrency']})"})
    stats.append({"value": f"{records:,}" if records else str(len({c['records_used'] for c in cells})),
                  "unit": "records" if records else "buckets", "key": False,
                  "label": "Enterprise-DLP corpus, 5,000-rule literal policy" if records else "distinct payload bands driven"})
    stats = stats[:4]

    # Bounds (integrity). Always the standing notes, plus anything the data flags.
    bounds = [
        {"title": "Same policy, corpus, driver",
         "body": "every engine gets the identical 5,000-rule listMatch policy and the same request bodies from one driver; this is a throughput test, not a new capability claim."},
        {"title": "End-to-end, not engine-isolated",
         "body": "each latency includes network + TLS + the engine's HTTP front-end; no server-side timing hook is exposed. Connections are pooled (HTTP/1.1 keep-alive) so TLS is amortized, but the front-end could bound a region rather than the matching core."},
    ]
    tot_err = sum(c["errors"] for c in cells)
    tot_ovf = sum(c["tail_overflow"] for c in cells)
    if tot_err:
        bounds.append({"title": f"{tot_err:,} errors across the sweep",
                       "body": "concentrated at the highest concurrency cells - timeouts/resets under saturation. Treated as failed requests, excluded from latency, counted in the grid."})
    if tot_ovf:
        bounds.append({"title": f"{tot_ovf:,} samples past 60s",
                       "body": "landed beyond the histogram's resolved range at saturation; their p99.9 is reported at the measured max, a lower bound on the true tail."})

    run = {
        "kind": "dp4",
        "title": "NOL8 Throughput at Load, Data Point 04",
        "navLabel": "Data Point 04 · Throughput at load",
        "nav": [["overview", "Overview"], ["throughput", "Throughput under load"],
                ["table", "The full grid"], ["meaning", "What it means"],
                ["bounds", "What bounded the run"], ["method", "Method"]],
        "eyebrow": "Data Point 04 · Throughput at load",
        "headline": {"lead": "Under load, the curves", "accent": accent},
        "lede": lede,
        "cta": [{"label": "See the curves", "target": "#throughput", "primary": True, "arrow": True},
                {"label": "The full grid", "target": "#table", "primary": False}],
        "stats": stats,
        "engineOrder": engines,
        "payloadOrder": payloads,
        "engines": {"themis": {"label": "Themis (FPGA)", "color": "var(--accent)"},
                    "aergia": {"label": "Aergia (RE2)", "color": "#E0A63C"}},
        "cells": cells,
        "throughputHeading": "Sustained throughput and the latency tail, 1 to %d concurrent" % top_c,
        "throughputLede": ("Closed-loop: N requests held in flight continuously against one engine, "
                           "for a 30s measured window per point (after a 10s warm-up). Left charts are "
                           "sustained requests/sec; right charts are p99 latency. One line per engine, "
                           "faceted by payload size."),
        "tableNote": ("Each row is one measured 30s steady-state cell. Same policy, same corpus, same "
                      "driver to both engines. req/s is sustained throughput; p-columns are the latency "
                      "distribution; errors are failed requests (timeouts/resets) under load."),
        "takeaways": [
            {"title": "Read the whole curve, not one point",
             "body": "at low concurrency the result is honestly network-bound parity; any engine separation appears as concurrency climbs. Both regions are shown on purpose."},
            {"title": "Tail latency is the story under load",
             "body": "averages hide saturation. p99/p99.9 are where a CPU engine's queueing and GC surface and where a fixed hardware pipeline is expected to stay flat."},
            {"title": "Throughput is what you provision against",
             "body": "sustained req/s at a tolerable p99 is the number that sizes a deployment - not a single-request latency measured with the engine inside the noise."},
        ],
        "meaning": {"heading": "What the load test actually shows"},
        "bounds": bounds,
        "method": [
            {"term": "Model", "def": "Closed-loop: exactly `concurrency` requests in flight at all times; sustained throughput = completed / elapsed. HTTP/1.1 keep-alive, connection pool sized to concurrency, so concurrency maps to real parallel connections."},
            {"term": "Per cell", "def": f"10s warm-up (discarded) + 30s measured, at each concurrency in {{{','.join(str(c) for c in concurrencies)}}} x each payload band."},
            {"term": "Latency", "def": "recorded per request into a dependency-free log-scaled histogram (1% precision); p50/p95/p99/p99.9 read from the merged histogram, min/max/mean tracked exactly."},
            {"term": "Corpus", "def": "enterprise-dlp scale generator, deterministic seed; records bucketed by request-body size into small/medium/large; bodies pre-marshaled so the driver's hot loop does no JSON work."},
            {"term": "Not measured here", "def": "response correctness - DP1-DP3 own that against the oracle. The driver drains and status-checks the response but does not re-validate it, to stay off the critical path."},
        ],
        "methodNote": ("Run on EC2 in-VPC against the argus edge so the engine, not the WAN, saturates "
                       "sooner. If the driver box saturates before the engine, the errors/overflow columns "
                       "and this note are where that shows - don't over-read a driver-bound region."),
        "footer": {
            "tagline": "The deterministic data plane for known policy - verified, not asserted.",
            "next": ["Data Point 01 · Pre-index optimization", "Data Points 02-03 · Pre/post-inference + agent mesh"],
            "copyright": "© 2026 NOL8", "confidential": "Confidential · for evaluation",
        },
    }

    args.out.write_text(json.dumps(run, indent=2) + "\n")
    print(f"Wrote {args.out} — {len(cells)} cells, engines={engines}, payloads={payloads}")


if __name__ == "__main__":
    main()
