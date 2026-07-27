#!/usr/bin/env python3
"""Adjudicate each engine's optimization-run output against an independent oracle.

The integrity check pointed at US. We measured that the optimization policy cuts
Themis's forwarded payload ~64% and that Aergia (RE2) diverges. Before we tell
that story we must prove Themis is actually CORRECT, not merely different-and-
prettier. This script computes the correct expected output of a literal `.nol`
policy on every corpus chunk using the framework's Aho-Corasick matcher (written
for a different job, already tested - a genuinely independent oracle), then diffs
each engine's recorded output against it.

Oracle semantics: leftmost-longest, non-overlapping literal replacement. For each
selected match, the matched span is replaced by the rule's replacement (a token
for governance rules, "" for strip rules). This is exactly what a correct literal
matcher should produce.

  Themis == oracle  -> Themis is correct; any Aergia divergence is a real defect.
  Themis != oracle  -> we do NOT claim the win; investigate before reporting.

Usage (run where the optimization-run output jsonls live, e.g. EC2 results/):

  python demos/benchmark/verify-oracle.py \
      --policy demos/policies/optimization.nol \
      --corpus demos/benchmark/datapoint1/data/sample_chunks.jsonl \
      --results demos/benchmark/datapoint1/results \
      themis_api aergia_api

Each engine named on the command line reads `<results>/<engine>_output.jsonl`.
Exit status is non-zero if any named engine diverges from the oracle, so this can
gate a demo run. The report prints per-engine divergence counts and sample diffs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# The framework's literal matcher IS the independent oracle. Reusing it (rather
# than reimplementing here) is the point: it was written and tested for corpus
# validation, so it did not learn the answer from either engine.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from framework.policy.matching import LiteralMatcher, resolve_non_overlapping  # noqa: E402

# "literal" -> "replacement";  (both strings may contain \" and \\ escapes)
_RULE = re.compile(r'^"((?:[^"\\]|\\.)*)"\s*->\s*"((?:[^"\\]|\\.)*)";\s*$')


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\")


def parse_policy(path: Path) -> dict[str, str]:
    """Parse a literal .nol policy into {literal: replacement}.

    Full-line `#` comments and blank lines are ignored. A trailing inline comment
    after a rule is a parse error in the real engine, so we treat it as one here.
    """
    rules: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _RULE.match(line)
        if not m:
            raise ValueError(f"{path}:{lineno}: not a rule: {raw!r}")
        rules[_unescape(m.group(1))] = _unescape(m.group(2))
    return rules


def oracle_output(text: str, matcher: LiteralMatcher, rules: dict[str, str]) -> str:
    """Correct literal-replacement output: leftmost-longest, non-overlapping."""
    selected = resolve_non_overlapping(matcher.find_all(text))
    out: list[str] = []
    cursor = 0
    for match in selected:
        out.append(text[cursor:match.start])
        out.append(rules[match.literal])
        cursor = match.end
    out.append(text[cursor:])
    return "".join(out)


def load_outputs(path: Path) -> dict[str, str]:
    """Map chunk id -> processed_text from a `<engine>_output.jsonl`."""
    outputs: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        outputs[rec["id"]] = rec["processed_text"]
    return outputs


def _show(s: str, width: int = 70) -> str:
    shown = s if len(s) <= width else s[:width] + "..."
    return repr(shown)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("engines", nargs="+", help="engine names, e.g. themis_api aergia_api")
    ap.add_argument("--policy", type=Path, default=REPO_ROOT / "demos/policies/optimization.nol")
    ap.add_argument("--corpus", type=Path,
                    default=REPO_ROOT / "demos/benchmark/datapoint1/data/sample_chunks.jsonl")
    ap.add_argument("--results", type=Path, default=REPO_ROOT / "demos/benchmark/datapoint1/results")
    ap.add_argument("--samples", type=int, default=5, help="sample diffs to print per engine")
    args = ap.parse_args()

    rules = parse_policy(args.policy)
    matcher = LiteralMatcher(rules.keys())
    print(f"Policy: {args.policy.name}  ({len(rules)} literal rules; "
          f"{sum(1 for v in rules.values() if v == '')} strip, "
          f"{sum(1 for v in rules.values() if v != '')} redact)")

    # Two corpus shapes exist in this repository: {id, text} from the DP1 data
    # sets, and {record_id, kind, message} from the load driver and the workload
    # generator. Accept either, so pointing this at the wrong one is not a
    # KeyError three screens into a run.
    corpus = {}
    for line in args.corpus.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        identifier = record.get("id") or record.get("record_id")
        text = record.get("text") or record.get("message")
        if identifier is not None and isinstance(text, str):
            corpus[identifier] = text
    if not corpus:
        raise SystemExit(f"no usable records in {args.corpus}")
    expected = {cid: oracle_output(text, matcher, rules) for cid, text in corpus.items()}
    print(f"Corpus: {len(corpus)} chunks; oracle computed expected output for each.\n")

    any_diverged = False
    for engine in args.engines:
        out_path = args.results / f"{engine}_output.jsonl"
        if not out_path.exists():
            print(f"[{engine}] MISSING {out_path} - run the optimization benchmark first.")
            any_diverged = True
            continue
        got = load_outputs(out_path)

        diffs = [cid for cid in expected if got.get(cid) != expected[cid]]
        missing = [cid for cid in expected if cid not in got]
        verdict = "MATCHES ORACLE" if not diffs else "DIVERGES FROM ORACLE"
        print(f"[{engine}] {len(got)} chunks; {len(expected) - len(diffs)}/{len(expected)} "
              f"match oracle -> {verdict}")
        if missing:
            print(f"    ({len(missing)} corpus chunks absent from output)")
        for cid in diffs[:args.samples]:
            print(f"  - {cid}")
            print(f"      oracle: {_show(expected[cid])}")
            print(f"      engine: {_show(got.get(cid, '<absent>'))}")
        if len(diffs) > args.samples:
            print(f"  ... and {len(diffs) - args.samples} more divergent chunks")
        print()
        any_diverged = any_diverged or bool(diffs)

    if any_diverged:
        print("VERDICT: at least one engine diverges from the oracle (details above).")
    else:
        print("VERDICT: every engine matches the oracle byte-for-byte.")
    return 1 if any_diverged else 0


if __name__ == "__main__":
    raise SystemExit(main())
