#!/usr/bin/env python3
"""How much throughput does each engine deliver inside a latency budget?

Peak throughput and tail latency are not two results. Under a closed-loop load
they are the same result seen twice: with N requests in flight, latency is N
divided by throughput, so an engine that serves 3x the requests necessarily
shows a third of the latency. Reporting both as separate wins double-counts.

The question that does not double-count, and the one an operator actually has,
is: **at a tail latency I can live with, how much can each engine carry?**

That is measured by driving each engine across a ladder of concurrencies,
recording the throughput and p99 at each, and reading off the throughput where
the p99 curve crosses the budget. Both engines are measured on the identical
corpus and policy, and the budget applies equally to both.

Two honest failure modes are reported rather than hidden:

* an engine whose p99 exceeds the budget even at the lowest concurrency cannot
  meet it at any load, and is reported as such rather than extrapolated to zero;
* an engine still under the budget at the highest concurrency was not pushed far
  enough, and its figure is a floor rather than an answer.

    python demos/benchmark/datapoint4/slo-throughput.py \\
        --input demos/benchmark/datapoint4/results/enron.jsonl \\
        --engines themis,aergia --budgets 10,25,50,100
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVER = HERE / "results" / "dp4driver"


class Cell:
    """One (engine, concurrency) measurement."""

    __slots__ = ("engine", "concurrency", "rps", "p99", "mib_s", "errors", "mean")

    def __init__(self, row: dict[str, str]) -> None:
        self.engine = row["engine"]
        self.concurrency = int(row["concurrency"])
        self.rps = float(row["rps"])
        self.p99 = float(row["p99_ms"])
        self.mib_s = float(row["throughput_mib_s"])
        self.errors = int(row["errors"])
        self.mean = float(row["mean_ms"])


def run_cell(engine: str, concurrency: int, args) -> Cell | None:
    output = Path(f"/tmp/slo_{engine}_c{concurrency}.csv")
    output.unlink(missing_ok=True)
    command = [
        str(DRIVER),
        "--engine", engine, "--label", engine,
        "--input", str(args.input),
        "--concurrency", str(concurrency),
        "--payloads", args.payload,
        f"--cap-{args.payload}", str(args.cap),
        "--warmup", str(args.warmup),
        "--duration", str(args.duration),
        "--output", str(output),
    ]
    print(f"  {engine:8s} concurrency {concurrency:5d} ... ", end="", flush=True)
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not output.exists():
        print("FAILED")
        sys.stderr.write(result.stderr[-400:] + "\n")
        return None
    with output.open() as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        print("no data row (corpus may miss this payload band)")
        return None
    cell = Cell(rows[0])
    print(f"{cell.rps:9,.0f} req/s   p99 {cell.p99:7.1f} ms   "
          f"{cell.mib_s:6.1f} MiB/s   err {cell.errors}")
    return cell


def throughput_at_budget(cells: list[Cell], budget: float) -> tuple[float | None, str]:
    """Throughput where the p99 curve crosses `budget`, and how it was obtained.

    Latency rises with concurrency once an engine is saturated, so the ladder is
    monotone enough to interpolate between adjacent points. Interpolating rather
    than reporting the nearest cell avoids crediting an engine with throughput it
    only reaches by exceeding the budget.
    """
    ordered = sorted(cells, key=lambda c: c.concurrency)
    if not ordered:
        return None, "no data"
    if ordered[0].p99 > budget:
        return None, f"cannot meet it (best p99 {ordered[0].p99:.1f} ms)"
    if ordered[-1].p99 <= budget:
        return ordered[-1].rps, "floor - never exceeded the budget, push harder"

    for lower, upper in zip(ordered, ordered[1:]):
        if lower.p99 <= budget < upper.p99:
            span = upper.p99 - lower.p99
            weight = 0.0 if span <= 0 else (budget - lower.p99) / span
            return lower.rps + weight * (upper.rps - lower.rps), "interpolated"
    return ordered[-1].rps, "interpolated"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", type=Path, required=True, help="corpus jsonl")
    parser.add_argument("--engines", default="themis,aergia")
    parser.add_argument("--concurrencies", default="64,128,256,512,1024,2048")
    parser.add_argument("--budgets", default="10,25,50,100",
                        help="p99 budgets in milliseconds")
    parser.add_argument("--payload", default="small",
                        choices=("small", "medium", "large"))
    parser.add_argument("--cap", type=int, default=20000)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--duration", type=int, default=15)
    parser.add_argument("--csv", type=Path, default=HERE / "results" / "slo.csv")
    args = parser.parse_args()

    if not DRIVER.exists():
        raise SystemExit(f"driver not built: {DRIVER}")
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    for engine in engines:
        if not os.environ.get(f"{engine.upper()}_ENDPOINT", "").strip():
            raise SystemExit(f"{engine.upper()}_ENDPOINT is not set")
    ladder = [int(c) for c in args.concurrencies.split(",")]
    budgets = [float(b) for b in args.budgets.split(",")]

    print(f"Corpus: {args.input.name}   payload band: {args.payload}")
    print(f"Ladder: {ladder}\n")

    measured: dict[str, list[Cell]] = {engine: [] for engine in engines}
    for concurrency in ladder:
        for engine in engines:
            cell = run_cell(engine, concurrency, args)
            if cell is not None:
                measured[engine].append(cell)

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["engine", "concurrency", "rps", "p99_ms", "mib_s",
                         "mean_ms", "errors"])
        for engine in engines:
            for cell in sorted(measured[engine], key=lambda c: c.concurrency):
                writer.writerow([cell.engine, cell.concurrency, f"{cell.rps:.1f}",
                                 f"{cell.p99:.3f}", f"{cell.mib_s:.2f}",
                                 f"{cell.mean:.3f}", cell.errors])

    print(f"\nThroughput inside a p99 budget  (corpus {args.input.name})")
    header = "  p99 budget  " + "".join(f"{e:>16s}" for e in engines)
    if len(engines) == 2:
        header += "     ratio"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for budget in budgets:
        values: list[float | None] = []
        notes: list[str] = []
        cells = []
        for engine in engines:
            value, note = throughput_at_budget(measured[engine], budget)
            values.append(value)
            notes.append(note)
            cells.append(f"{value:>13,.0f} r/s" if value is not None else f"{'-':>16s}")
        line = f"  {budget:>7.0f} ms  " + "".join(cells)
        if len(engines) == 2 and values[0] and values[1]:
            line += f"   {values[0] / values[1]:6.2f}x"
        elif len(engines) == 2 and values[0] and not values[1]:
            line += "        n/a"
        print(line)
        for engine, note in zip(engines, notes):
            if note not in ("interpolated",):
                print(f"              {engine}: {note}")

    print(f"\nLadder written to {args.csv}")
    print("Latency is quoted with its load level throughout; a p99 without a")
    print("concurrency attached is not a number anybody can act on.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
