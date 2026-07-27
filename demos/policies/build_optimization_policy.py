#!/usr/bin/env python3
"""Build a combined GOVERNANCE + OPTIMIZATION policy for the pre-index demo.

Two jobs in one literal policy (Themis and Aergia both run it):

  GOVERNANCE  - redact known sensitive values to tokens (the starter policy):
                "Red Flag Logistics" -> "[DENIED]"      (security / compliance)
  OPTIMIZATION - strip repeated low-value filler so less is embedded:
                "<generic sentence that repeats N times>" -> ""   (ship less)

The optimization rules are DATA-DRIVEN: we scan the demo corpus for the most-
repeated exact sentences (generic framing that adds no per-chunk retrieval value)
and strip them. For a real customer you would supply their own filler list; the
mechanism is identical.

  python demos/policies/build_optimization_policy.py [--strip-top N] [--min-count M]
  -> demos/policies/optimization.nol   (deploy with: validate policy --file ... --target themis)

Themis is a literal matcher, so this only strips EXACT repeated sentences. Variable
boilerplate ("Welcome to <varies>") is pattern work (RE2/Aergia), out of scope here.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import build_policy  # governance rules (same 42 known values)

HERE = Path(__file__).resolve().parent
CORPUS = HERE.parent / "benchmark" / "usecase-1-pre-index" / "data" / "sample_chunks.jsonl"
OUTPUT = HERE / "optimization.nol"


def top_filler(corpus: Path, top_n: int, min_count: int) -> list[tuple[str, int]]:
    """Return [(sentence, count)] for the most-repeated exact sentences."""
    counts: collections.Counter[str] = collections.Counter()
    for line in corpus.read_text().splitlines():
        if not line.strip():
            continue
        for sentence in json.loads(line)["text"].split("\n"):
            sentence = sentence.strip()
            if sentence:
                counts[sentence] += 1
    return [(s, n) for s, n in counts.most_common(top_n) if n >= min_count]


def build(top_n: int, min_count: int) -> str:
    categories = build_policy.load_categories(build_policy.VALUES_DIR)
    build_policy.check_safe(categories)  # governance rules stay safe (ISSUE-004/005)
    governance = build_policy.build_nol(categories).rstrip()

    filler = top_filler(CORPUS, top_n, min_count)
    lines = [
        governance,
        "",
        "# --- OPTIMIZATION: strip repeated low-value filler (ship less to embeddings) ---",
        f"# Top {len(filler)} most-repeated exact sentences in the demo corpus, stripped to nothing.",
    ]
    # NOTE: the policy parser does not allow a trailing comment after a rule
    # (`... -> ""; # note` is rejected); comments must be on their own line.
    for sentence, count in filler:
        escaped = sentence.replace('"', '\\"')
        lines.append(f"# repeats {count}x")
        lines.append(f'"{escaped}" -> "";')
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strip-top", type=int, default=10, help="strip the N most-repeated sentences")
    ap.add_argument("--min-count", type=int, default=50, help="only strip sentences seen at least M times")
    args = ap.parse_args()

    text = build(args.strip_top, args.min_count)
    OUTPUT.write_text(text)
    gov = sum(len(v) for _, _, v in build_policy.load_categories(build_policy.VALUES_DIR))
    strip = text.count('-> "";')
    print(f"Wrote {OUTPUT.name}: {gov} governance rules + {strip} filler-strip rules.")


if __name__ == "__main__":
    main()
