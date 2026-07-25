#!/usr/bin/env python3
"""Showcase: one message through the Argus Data API (/v1/process), self-verified.

Sends a single realistic message to a live engine, prints the before/after, and
oracle-checks the redaction against the deployed policy: for every governed value
that appears in the ORIGINAL message, it asserts (a) the raw value is gone from the
output and (b) the policy's replacement token is present. The oracle is derived
from the policy file itself — no hand-maintained expected answers to drift.

This is the customer-facing surface (a single synchronous HTTPS call, no SDK,
no agent) exercised honestly. NOL8 does deterministic literal replacement only.

Usage:
    redact-demo.py --endpoint URL --token T --policy P.nol --message M.txt [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

POLICY_RULE = re.compile(r'^\s*"(?P<lit>.*)"\s*->\s*"(?P<tok>.*)"\s*;\s*$')


def load_policy_pairs(path: str) -> list[tuple[str, str]]:
    """Parse `"literal" -> "replacement";` rules, skipping comments/blanks."""
    pairs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.lstrip().startswith("#"):
                continue
            m = POLICY_RULE.match(line)
            if m:
                pairs.append((m.group("lit"), m.group("tok")))
    return pairs


def call_process(endpoint: str, token: str, message: str, timeout: float = 15.0) -> str:
    """POST one message to /v1/process and return the processed message."""
    body = json.dumps(
        {"message": message, "jid": 1, "frameId": 1, "last": True}
    ).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["result"]["message"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--endpoint", required=True, help="/v1/process URL")
    ap.add_argument("--token", default="", help="bearer token")
    ap.add_argument("--policy", required=True, help="deployed .nol policy file")
    ap.add_argument("--message", required=True, help="message text file")
    ap.add_argument("--engine-label", default="engine", help="name for output")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    with open(args.message, encoding="utf-8") as fh:
        original = fh.read()

    pairs = load_policy_pairs(args.policy)
    # Only values that actually appear in this message are in scope for the oracle.
    expected = [(lit, tok) for lit, tok in pairs if lit and lit in original]

    processed = call_process(args.endpoint, args.token, original)

    # Oracle: every in-scope governed value must be gone; its token must appear.
    checks = []
    for lit, tok in expected:
        redacted = lit not in processed
        token_present = tok in processed
        checks.append(
            {"value": lit, "token": tok, "redacted": redacted, "token_present": token_present,
             "ok": redacted and token_present}
        )
    passed = sum(1 for c in checks if c["ok"])
    total = len(checks)

    if args.json:
        print(json.dumps(
            {"engine": args.engine_label, "in_scope": total, "verified": passed,
             "original": original, "processed": processed, "checks": checks}, indent=2))
        return 0 if passed == total and total > 0 else 1

    bar = "─" * 68
    print(f"\n{bar}\n  BEFORE  (what the caller sent)\n{bar}")
    print(original.rstrip())
    print(f"\n{bar}\n  AFTER   (what {args.engine_label} returned via /v1/process)\n{bar}")
    print(processed.rstrip())
    print(f"\n{bar}\n  ORACLE  (verified against the deployed policy)\n{bar}")
    if not checks:
        print("  ⚠  no governed values from the policy were present in this message.")
        return 1
    for c in checks:
        mark = "✓" if c["ok"] else "✗"
        detail = "" if c["ok"] else (
            "  (still present!)" if not c["redacted"] else "  (token missing!)")
        print(f"   {mark}  {c['value']!r:40s} → {c['token']}{detail}")
    print(f"\n  {passed}/{total} governed values redacted and verified.")
    if passed == total:
        print("  Deterministic literal replacement confirmed against the oracle.\n")
        return 0
    print("  ✗ MISMATCH — output does not match the policy. Do not proceed.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
