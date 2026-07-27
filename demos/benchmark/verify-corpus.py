#!/usr/bin/env python3
"""Adjudicate a live engine against the oracle on any corpus, directly.

`verify-oracle.py` compares `<engine>_output.jsonl` files that the DP1 Go
harness leaves behind, which ties it to that harness's corpus and its output
format. This sends the documents itself, so any corpus and any literal policy
can be checked against the oracle without a benchmark run first.

The oracle is the framework's Aho-Corasick matcher: leftmost-longest,
non-overlapping literal replacement. It was written for corpus validation and
knows nothing about either engine, so agreement with it is evidence rather than
two implementations sharing a mistake.

This matters most for policies whose rules are common words. A token-reduction
policy fires tens of times per kilobyte on ordinary prose, and it has to be
right every time - text that comes back shorter but mangled is worth less than
text that was left alone.

    python demos/benchmark/verify-corpus.py \\
        --policy demos/policies/token-reduction-aggressive.nol \\
        --corpus demos/benchmark/datapoint4/results/enron.jsonl \\
        --engines themis,aergia --limit 500
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from framework.policy.matching import (  # noqa: E402
    LiteralMatcher,
    apply_leftmost_longest,
    apply_overlap_aware,
)

# The two transformation contracts a literal engine can implement. They agree
# whenever matches are disjoint and differ whenever matches share a byte, so an
# engine is adjudicated against both rather than against a guess.
CONTRACTS = {
    "one-byte-one-match": apply_leftmost_longest,
    "every-match-fires": apply_overlap_aware,
}

_RULE = re.compile(r'^"((?:[^"\\]|\\.)*)"\s*->\s*"((?:[^"\\]|\\.)*)";\s*$')

ENDPOINT_ENV = {
    "themis": ("THEMIS_ENDPOINT", "THEMIS_PROCESS_ENDPOINT"),
    "aergia": ("AERGIA_ENDPOINT", "AERGIA_PROCESS_ENDPOINT"),
}


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


def load_corpus(path: Path, limit: int | None) -> list[tuple[str, str]]:
    """Accept either corpus shape used in this repository."""

    documents: list[tuple[str, str]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        record = json.loads(line)
        text = record.get("message") or record.get("text")
        identifier = record.get("record_id") or record.get("id") or f"doc-{index:06d}"
        if isinstance(text, str) and text:
            documents.append((identifier, text))
        if limit and len(documents) >= limit:
            break
    if not documents:
        raise SystemExit(f"no documents found in {path}")
    return documents


def oracle_outputs(
    text: str, matcher: LiteralMatcher, rules: dict[str, str]
) -> dict[str, str]:
    """What each contract says the output should be."""

    found = matcher.find_all(text)
    return {name: apply(text, found, rules) for name, apply in CONTRACTS.items()}


def endpoint_for(engine: str) -> str:
    for name in ENDPOINT_ENV.get(engine, ()):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def process(endpoint: str, token: str, message: str, timeout: float) -> str:
    body = json.dumps(
        {"message": message, "jid": 1, "frameId": 1, "last": True}
    ).encode("utf-8")
    request = urllib.request.Request(endpoint, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))["result"]["message"]


def first_divergence(left: str, right: str) -> int:
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    return min(len(left), len(right))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--engines", default="themis,aergia")
    parser.add_argument("--limit", type=int, default=500,
                        help="documents to check; the whole corpus is usually "
                             "unnecessary and this path is one request at a time")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--replacement-max-length", type=int, default=None,
        help="truncate every replacement to this many characters. The runtime "
             "truncates at 15 (KB-001); without this the oracle expects a token "
             "the engine never emits",
    )
    args = parser.parse_args()

    rules = parse_policy(args.policy)
    if args.replacement_max_length is not None:
        limit = args.replacement_max_length
        rules = {literal: value[:limit] for literal, value in rules.items()}
    matcher = LiteralMatcher(rules)
    documents = load_corpus(args.corpus, args.limit)
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]

    removals = sum(1 for value in rules.values() if not value.strip())
    print(f"Policy: {args.policy.name} ({len(rules)} rules, "
          f"{removals} replacing with whitespace)")
    print(f"Corpus: {args.corpus.name}, checking {len(documents)} documents\n")

    expected = {doc_id: oracle_outputs(text, matcher, rules)
                for doc_id, text in documents}
    changed = sum(1 for doc_id, text in documents
                  if expected[doc_id]["one-byte-one-match"] != text)
    ambiguous = sum(1 for doc_id, _ in documents
                    if len(set(expected[doc_id].values())) > 1)
    print(f"Oracle changes {changed} of {len(documents)} documents")
    print(f"The two contracts disagree on {ambiguous} of them "
          f"({100 * ambiguous / len(documents):.0f}%) - documents containing "
          f"overlapping matches\n")

    any_unexplained = False
    for engine in engines:
        endpoint = endpoint_for(engine)
        if not endpoint:
            print(f"[{engine}] no endpoint configured; skipping")
            any_unexplained = True
            continue
        token = os.environ.get(f"{engine.upper()}_TOKEN", "")

        agree = {name: 0 for name in CONTRACTS}
        neither: list[tuple[str, dict[str, str], str]] = []
        errors = 0
        for doc_id, text in documents:
            try:
                actual = process(endpoint, token, text, args.timeout)
            except Exception as error:  # noqa: BLE001 - report, don't abort
                errors += 1
                if errors <= 2:
                    print(f"[{engine}] request failed for {doc_id}: {str(error)[:120]}")
                continue
            matched = [n for n, want in expected[doc_id].items() if want == actual]
            for name in matched:
                agree[name] += 1
            if not matched:
                neither.append((doc_id, expected[doc_id], actual))

        checked = len(documents) - errors
        print(f"[{engine}] {checked} documents checked"
              + (f" ({errors} request errors)" if errors else ""))
        for name in CONTRACTS:
            print(f"    {name:20s} {agree[name]:5d}/{checked} "
                  f"({100 * agree[name] / max(1, checked):5.1f}%)")

        best = max(agree, key=lambda n: agree[n])
        if agree[best] == checked:
            print(f"    -> implements '{best}' exactly")
        elif neither:
            print(f"    -> {len(neither)} documents match NEITHER contract; "
                  "that is a defect rather than a difference of semantics")
            any_unexplained = True
        else:
            print(f"    -> mixed; closest is '{best}'")
            any_unexplained = True

        for doc_id, wants, got in neither[:args.samples]:
            offset = min(first_divergence(w, got) for w in wants.values())
            start = max(0, offset - 40)
            print(f"  - {doc_id} (first difference at byte {offset})")
            for name, want in wants.items():
                print(f"      {name:20s} ...{want[start:offset + 60]!r}")
            print(f"      {'engine':20s} ...{got[start:offset + 60]!r}")
        print()

    print("VERDICT: " + (
        "at least one engine matches neither contract - investigate."
        if any_unexplained else
        "every engine implements one of the two contracts exactly."))
    return 1 if any_unexplained else 0


if __name__ == "__main__":
    raise SystemExit(main())
