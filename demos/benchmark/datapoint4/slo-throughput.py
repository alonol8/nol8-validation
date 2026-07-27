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

Throughput is only comparable between engines doing the same job correctly, so
pass --expected and every response in every cell is checked against the oracle.
Without it the driver checks HTTP status alone, and an engine returning wrong
output scores a throughput figure like any other.

    python demos/benchmark/datapoint4/expected-digests.py \\
        --policy <policy.nol> --corpus <corpus.jsonl> --out /tmp/c.digests

    python demos/benchmark/datapoint4/slo-throughput.py \\
        --input <corpus.jsonl> --expected /tmp/c.digests \\
        --engines themis,aergia --budgets 10,25,50,100
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from pathlib import Path

# The driver reports verification on stdout rather than in the CSV. Each cell is
# a separate driver process, so these counts are per-cell rather than cumulative.
_VERIFIED = re.compile(r"verified (\d+) responses: (\d+) correct, (\d+) WRONG")

HERE = Path(__file__).resolve().parent
DRIVER = HERE / "results" / "dp4driver"


class Cell:
    """One (engine, concurrency) measurement."""

    __slots__ = ("engine", "concurrency", "rps", "p99", "mib_s", "errors", "mean",
                 "verified", "wrong")

    def __init__(self, row: dict[str, str]) -> None:
        self.verified = 0
        self.wrong = 0
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
    if args.expected:
        command += ["--expected", str(args.expected)]
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
    verified = _VERIFIED.search(result.stdout)
    if verified:
        cell.verified = int(verified.group(1))
        cell.wrong = int(verified.group(3))
    suffix = ""
    if cell.verified:
        suffix = (f"   !! {cell.wrong} WRONG of {cell.verified:,}"
                  if cell.wrong else f"   {cell.verified:,} verified")
    print(f"{cell.rps:9,.0f} req/s   p99 {cell.p99:7.1f} ms   "
          f"{cell.mib_s:6.1f} MiB/s   err {cell.errors}{suffix}")
    return cell


def throughput_at_budget(cells: list[Cell], budget: float) -> tuple[float | None, str]:
    """The most throughput reachable while keeping p99 within `budget`.

    Not the throughput where the p99 curve crosses the budget - that is only the
    same thing while throughput is still rising. Past saturation an engine loses
    throughput as concurrency climbs, so the crossing sits on the falling limb
    and understates what the engine can do: Themis measured 128,821 req/s at a
    24 ms p99, and reading the crossing at a 50 ms budget returned 122,372,
    penalising it for a load level nobody would choose to run at.

    So: the best of every operating point inside the budget - each measured
    ladder point, plus the interpolated crossing on any segment that straddles
    it, since concurrency is continuous and a point between two rungs is
    genuinely reachable.
    """
    ordered = sorted(cells, key=lambda c: c.concurrency)
    if not ordered:
        return None, "no data"

    reachable = [cell.rps for cell in ordered if cell.p99 <= budget]

    for lower, upper in zip(ordered, ordered[1:]):
        low, high = (lower, upper) if lower.p99 <= upper.p99 else (upper, lower)
        if low.p99 <= budget < high.p99:
            span = high.p99 - low.p99
            weight = 0.0 if span <= 0 else (budget - low.p99) / span
            reachable.append(low.rps + weight * (high.rps - low.rps))

    if not reachable:
        return None, f"cannot meet it (best p99 {min(c.p99 for c in ordered):.1f} ms)"

    best = max(reachable)
    if max(cell.p99 for cell in ordered) <= budget:
        return best, "budget not binding - this is the measured peak"
    if best >= max(cell.rps for cell in ordered) - 1e-9:
        return best, "at peak throughput; the budget costs nothing"
    return best, "interpolated"


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
    parser.add_argument(
        "--expected", type=Path, default=None,
        help="digest file from expected-digests.py. Every response in every "
             "cell is then checked against the oracle, and a budget figure is "
             "withheld for any engine that returned wrong output - throughput "
             "for an engine doing the wrong job is not a comparable number",
    )
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
                         "mean_ms", "errors", "verified", "wrong"])
        for engine in engines:
            for cell in sorted(measured[engine], key=lambda c: c.concurrency):
                writer.writerow([cell.engine, cell.concurrency, f"{cell.rps:.1f}",
                                 f"{cell.p99:.3f}", f"{cell.mib_s:.2f}",
                                 f"{cell.mean:.3f}", cell.errors,
                                 cell.verified, cell.wrong])

    # A cell that returned wrong output has no comparable throughput: it is a
    # rate of producing something else. Rather than quietly averaging it in, the
    # engine's whole column is withheld and the reason printed.
    unverified: dict[str, str] = {}
    for engine in engines:
        cells = measured[engine]
        if args.expected is None:
            unverified[engine] = "not verified - no --expected given"
        elif any(cell.wrong for cell in cells):
            total = sum(cell.wrong for cell in cells)
            checked = sum(cell.verified for cell in cells)
            unverified[engine] = (
                f"{total:,} of {checked:,} responses did not match the oracle"
            )
        elif not any(cell.verified for cell in cells):
            unverified[engine] = "verification produced no counts"

    if unverified:
        print("\nVerification")
        for engine in engines:
            note = unverified.get(engine)
            print(f"  {engine:8s} {note if note else 'every response matched the oracle'}")

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
            if engine in unverified and "did not match" in unverified[engine]:
                values.append(None)
                notes.append("withheld: output did not match the oracle")
                cells.append(f"{'WRONG':>16s}")
                continue
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
    if args.expected is None:
        print("\nNo --expected given, so nothing here is known to be correct. The")
        print("driver checks HTTP status only; a 200 carrying wrong output counts")
        print("as a success. Generate digests with expected-digests.py and pass")
        print("them to make these figures mean something.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
