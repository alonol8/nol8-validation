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

from framework.policy.matching import LiteralMatcher, resolve_non_overlapping  # noqa: E402

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


def oracle_output(text: str, matcher: LiteralMatcher, rules: dict[str, str]) -> str:
    selected = resolve_non_overlapping(matcher.find_all(text))
    out: list[str] = []
    cursor = 0
    for match in selected:
        out.append(text[cursor:match.start])
        out.append(rules[match.literal])
        cursor = match.end
    out.append(text[cursor:])
    return "".join(out)


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
    args = parser.parse_args()

    rules = parse_policy(args.policy)
    matcher = LiteralMatcher(rules)
    documents = load_corpus(args.corpus, args.limit)
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]

    removals = sum(1 for value in rules.values() if not value.strip())
    print(f"Policy: {args.policy.name} ({len(rules)} rules, "
          f"{removals} replacing with whitespace)")
    print(f"Corpus: {args.corpus.name}, checking {len(documents)} documents\n")

    expected = {doc_id: oracle_output(text, matcher, rules)
                for doc_id, text in documents}
    changed = sum(1 for doc_id, text in documents if expected[doc_id] != text)
    print(f"Oracle changes {changed} of {len(documents)} documents\n")

    any_diverged = False
    for engine in engines:
        endpoint = endpoint_for(engine)
        if not endpoint:
            print(f"[{engine}] no endpoint configured; skipping")
            any_diverged = True
            continue
        token = os.environ.get(f"{engine.upper()}_TOKEN", "")

        diverged: list[tuple[str, str, str]] = []
        errors = 0
        for doc_id, text in documents:
            try:
                actual = process(endpoint, token, text, args.timeout)
            except Exception as error:  # noqa: BLE001 - report, don't abort
                errors += 1
                if errors <= 2:
                    print(f"[{engine}] request failed for {doc_id}: {str(error)[:120]}")
                continue
            if actual != expected[doc_id]:
                diverged.append((doc_id, expected[doc_id], actual))

        checked = len(documents) - errors
        verdict = "MATCHES ORACLE" if not diverged else "DIVERGES FROM ORACLE"
        print(f"[{engine}] {checked - len(diverged)}/{checked} documents "
              f"reproduce the oracle byte-for-byte -> {verdict}"
              + (f"  ({errors} request errors)" if errors else ""))

        for doc_id, want, got in diverged[:args.samples]:
            offset = first_divergence(want, got)
            start = max(0, offset - 40)
            print(f"  - {doc_id} (first difference at byte {offset})")
            print(f"      oracle: ...{want[start:offset + 60]!r}")
            print(f"      engine: ...{got[start:offset + 60]!r}")
        if len(diverged) > args.samples:
            print(f"  ... and {len(diverged) - args.samples} more")
        print()
        any_diverged = any_diverged or bool(diverged)

    print("VERDICT: " + ("at least one engine diverges from the oracle."
                         if any_diverged else "every engine matches the oracle."))
    return 1 if any_diverged else 0


if __name__ == "__main__":
    raise SystemExit(main())
