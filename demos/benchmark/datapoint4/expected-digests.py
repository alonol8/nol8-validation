#!/usr/bin/env python3
"""Precompute what each corpus record should come back as, as md5 digests.

The load driver measures how fast an engine answers, not whether the answer is
right, so a 200 carrying corrupted output counts as a success. Checking every
response against the oracle inside the driver closes that, but the oracle is
Python and the driver is Go and has to sustain six figures a second - so the
expensive half is done once, here, and the driver is left with a hash compare.

Two digests per record, because the engines implement different transformation
contracts and both are self-consistent:

    one-byte-one-match   a byte is consumed by at most one match
    every-match-fires    overlapping matches all fire, shared bytes once

Measured on real email, Aergia reproduces the first and Themis the second. A
file with both lets one set of digests check either engine, and lets the driver
report which contract a response actually followed rather than assuming.

Where a record contains no overlapping matches the two contracts agree and the
digests are identical, which is the common case.

    python demos/benchmark/datapoint4/expected-digests.py \\
        --policy <policy.nol> \\
        --corpus demos/benchmark/datapoint4/results/enron.jsonl \\
        --out demos/benchmark/datapoint4/results/enron.digests

Output is one line per corpus record, in corpus order:

    <md5 one-byte-one-match> <md5 every-match-fires>

The driver counts a response correct if it matches either. Digests are of the
processed message only - the response envelope carries a per-request job id, so
hashing the whole body would differ every time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from framework.policy.matching import (  # noqa: E402
    LiteralMatcher,
    apply_leftmost_longest,
    apply_overlap_aware,
)

_RULE = re.compile(r'^"((?:[^"\\]|\\.)*)"\s*->\s*"((?:[^"\\]|\\.)*)";\s*$')


def _unescape(text: str) -> str:
    return text.replace('\\"', '"').replace("\\\\", "\\")


def parse_policy(path: Path) -> dict[str, str]:
    rules: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _RULE.match(line)
        if not match:
            raise ValueError(f"{path}:{lineno}: not a rule: {raw!r}")
        rules[_unescape(match.group(1))] = _unescape(match.group(2))
    return rules


def digest(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--replacement-max-length", type=int, default=None,
        help="truncate every replacement to this many characters before "
             "hashing. The runtime truncates at 15 (KB-001), so without this "
             "the oracle expects a token the engine never emits and every "
             "document carrying a match is reported wrong",
    )
    args = parser.parse_args()

    rules = parse_policy(args.policy)
    if args.replacement_max_length is not None:
        limit = args.replacement_max_length
        rules = {literal: value[:limit] for literal, value in rules.items()}
        print(f"Replacements truncated to {limit} characters (KB-001)")
    matcher = LiteralMatcher(rules)
    print(f"Policy: {args.policy.name} ({len(rules)} rules)")

    records = 0
    differing = 0
    unchanged = 0
    with args.corpus.open(encoding="utf-8") as source, \
            args.out.open("w", encoding="utf-8") as sink:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            text = record.get("message") or record.get("text") or ""
            found = matcher.find_all(text)
            one = apply_leftmost_longest(text, found, rules)
            every = apply_overlap_aware(text, found, rules)
            sink.write(f"{digest(one)} {digest(every)}\n")
            records += 1
            if one != every:
                differing += 1
            if one == text:
                unchanged += 1

    print(f"Wrote {args.out}: {records} records")
    print(f"  {records - unchanged} are changed by the policy, {unchanged} pass through")
    print(f"  {differing} contain overlapping matches, so the two contracts differ "
          f"on them ({100 * differing / max(1, records):.1f}%)")
    if differing == 0:
        print("  the contracts agree everywhere here, so either digest identifies "
              "a correct response")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
