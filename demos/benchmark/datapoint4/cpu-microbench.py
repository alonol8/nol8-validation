#!/usr/bin/env python3
"""RE2 matching CPU cost vs policy size — the self-owned half of the CPU story.

Measures how much CPU real RE2 (google-re2, the C++ engine) spends scanning text
as the rule count grows, using RE2's Set API (its purpose-built multi-pattern
matcher — the faithful way to run thousands of literals, not one giant alternation
which RE2 refuses to compile). Uses REAL diverse policy literals and a REAL diverse
corpus so RE2's DFA state cache is exercised the way it is in production — a
repeated buffer or common-prefix literals would keep the cache artificially warm
and hide any cliff.

The output is CPU-per-work: MB scanned per CPU-second per core, and its inverse
(core-seconds per GB). That is the number that says "how many cores you buy to
sustain a given throughput" — the founder's CPU-to-scale angle. The FPGA side of
the comparison (host CPU near-idle because matching is offloaded) needs a
server-side capture on the engine host; see docs/CPU-EFFICIENCY-REQUEST.md.

  python demos/benchmark/datapoint4/cpu-microbench.py \
      --policy <16k scale-policy.nol> --corpus <input.jsonl> \
      --rule-counts 1000,2000,4000,8000,16000 --sample-mb 150 \
      --out demos/benchmark/datapoint4/results/cpu-microbench.csv
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import re2


def load_literals(policy_path: Path, need: int) -> list[str]:
    lits: list[str] = []
    for line in policy_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith('"'):
            continue
        end = line.find('" ->')
        if end <= 1:
            end = line.find('"->')
        if end <= 1:
            continue
        lits.append(line[1:end])
        if len(lits) >= need:
            break
    if len(lits) < need:
        raise SystemExit(f"policy has {len(lits)} literals, need {need}")
    return lits


def load_corpus_sample(corpus_path: Path, sample_mb: int) -> tuple[list[str], int]:
    """Read diverse docs until ~sample_mb of text is accumulated."""
    budget = sample_mb * 1024 * 1024
    docs, total = [], 0
    with corpus_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line).get("message", "")
            except json.JSONDecodeError:
                continue
            if not msg:
                continue
            docs.append(msg)
            total += len(msg.encode("utf-8"))
            if total >= budget:
                break
    return docs, total


def build_set(literals: list[str]) -> "re2.Set":
    opt = re2.Options()
    opt.max_mem = 1 << 30      # 1 GiB: don't let RE2's default 8MB program cap truncate the set
    opt.case_sensitive = False  # listMatch is case-insensitive
    s = re2.Set.SearchSet(opt)
    for lit in literals:
        s.Add(re2.escape(lit))
    s.Compile()
    return s


def measure(s: "re2.Set", docs: list[str], sample_bytes: int, min_cpu_s: float) -> tuple[float, int, int]:
    """Scan the sample repeatedly until >= min_cpu_s of CPU time; return
    (cpu_seconds, total_bytes_scanned, total_matches)."""
    total_bytes = 0
    total_matches = 0
    passes = 0
    t0 = time.process_time()
    while time.process_time() - t0 < min_cpu_s:
        for d in docs:
            m = s.Match(d)          # RE2 Set.Match returns None when nothing matched
            total_matches += len(m) if m else 0
        total_bytes += sample_bytes
        passes += 1
    cpu = time.process_time() - t0
    return cpu, total_bytes, total_matches


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, required=True, help="a large scale-policy.nol (literal pool)")
    ap.add_argument("--corpus", type=Path, required=True, help="input.jsonl (diverse text)")
    ap.add_argument("--rule-counts", default="1000,2000,4000,8000,16000")
    ap.add_argument("--sample-mb", type=int, default=150)
    ap.add_argument("--min-cpu-s", type=float, default=4.0, help="min CPU seconds per point (timing stability)")
    ap.add_argument("--out", type=Path, default=Path("cpu-microbench.csv"))
    args = ap.parse_args()

    counts = sorted(int(x) for x in args.rule_counts.split(",") if x.strip())
    pool = load_literals(args.policy, max(counts))          # nested subsets: only N varies
    docs, sample_bytes = load_corpus_sample(args.corpus, args.sample_mb)
    print(f"corpus sample: {len(docs)} docs, {sample_bytes/1e6:.0f} MB diverse text; "
          f"literal pool: {len(pool)} from {args.policy.name}")

    rows = [("rule_count", "sample_mb", "cpu_seconds", "gb_scanned",
             "mb_per_s_per_core", "core_seconds_per_gb", "matches_per_mb")]
    print(f"\n{'rules':>7} | {'MB/s/core':>10} | {'core-s/GB':>10} | {'matches/MB':>11}")
    print("-" * 50)
    for n in counts:
        s = build_set(pool[:n])
        cpu, scanned, matches = measure(s, docs, sample_bytes, args.min_cpu_s)
        mbps = (scanned / 1e6) / cpu
        core_s_per_gb = cpu / (scanned / 1e9)
        matches_per_mb = matches / (scanned / 1e6)
        rows.append((str(n), str(args.sample_mb), f"{cpu:.2f}", f"{scanned/1e9:.2f}",
                     f"{mbps:.1f}", f"{core_s_per_gb:.3f}", f"{matches_per_mb:.2f}"))
        print(f"{n:>7} | {mbps:>10.1f} | {core_s_per_gb:>10.3f} | {matches_per_mb:>11.2f}")

    with args.out.open("w") as fh:
        for r in rows:
            fh.write(",".join(r) + "\n")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
