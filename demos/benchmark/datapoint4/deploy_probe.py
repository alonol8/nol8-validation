#!/usr/bin/env python3
"""Deploy verification probe for the DP4 harnesses.

A deploy is fire-and-forget (ISSUE-003), there is no runtime health signal
(ISSUE-007), and no policy read-back. So "the engine is flat across rule count"
is indistinguishable from "the policy never changed on the engine." This probe
closes that gap: after deploying policy N it sends a document containing a literal
that is UNIQUE to N (present in N, absent from the previously deployed policy) and
asserts the engine redacts it. A stale policy cannot pass, because it never held
that literal.

It also reports |set(N) - set(prev)| per cell, pass or fail. If that difference is
empty or trivial, the rule-count sweep is not varying what we think it varies —
a finding on its own that would invalidate the trend claim, independent of
everything else.

Reuses the framework's ONE policy parser (framework.policy.oracle.parse_policy).

Exit non-zero if any named engine fails the probe, so the caller aborts the cell.

Usage:
  # rule-count sweep: unique-to-N literal, diff against the prior cell's policy
  deploy_probe.py --policy N.nol --prev (N-1).nol --engines themis,aergia
  # single-policy run: no previous, any literal must redact
  deploy_probe.py --policy scale.nol --engines themis
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
from framework.policy.oracle import parse_policy  # noqa: E402

# The runtime truncates a replacement token to 15 chars (ISSUE-005), and the two
# engines were observed to differ on this: Themis emits the full token, Aergia the
# 15-char prefix. So the liveness signal is "the literal was redacted" plus "the
# token's first 15 chars appear" — never the full token, which long tokens never
# yield on Aergia.
MAX_TOKEN_LEN = 15


def probe_plan(cur: dict[str, str], prev: dict[str, str]) -> tuple[str | None, str | None, int]:
    """Choose the literal to probe with.

    Returns (probe_literal, token, new_count). Prefer a literal UNIQUE to `cur`
    (present in cur, absent from prev) so a stale policy cannot pass; fall back to
    any literal from cur when there is no previous policy or the two share no
    difference. Selection is deterministic (shortest then lexicographic) so a run
    is reproducible. new_count is |set(cur) - set(prev)|, reported regardless.
    """
    new = [lit for lit in cur if lit not in prev]
    candidates = new if new else list(cur)
    if not candidates:
        return None, None, len(new)
    probe_lit = sorted(candidates, key=lambda s: (len(s), s))[0]
    return probe_lit, cur[probe_lit], len(new)


def call(endpoint: str, token: str, message: str, timeout: float = 20.0) -> str:
    body = json.dumps({"message": message, "jid": 1, "frameId": 1, "last": True}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))["result"]["message"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", required=True, help="the policy just deployed (N)")
    ap.add_argument("--prev", default="", help="the previously deployed policy (N-1), if any")
    ap.add_argument("--engines", default="themis,aergia")
    ap.add_argument("--attempts", type=int, default=5, help="probe retries per engine (propagation lag)")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between retries")
    args = ap.parse_args()

    cur = parse_policy(Path(args.policy))
    prev = parse_policy(Path(args.prev)) if args.prev and Path(args.prev).exists() else {}
    probe_lit, token, new_count = probe_plan(cur, prev)

    print(f"   probe: |policy|={len(cur)}  |new vs prev|={new_count}", flush=True)
    if prev and new_count == 0:
        print("   probe: WARNING set(N)-set(prev) is EMPTY — this cell does not vary the "
              "ruleset from the previous one; the rule-count trend is not measuring what "
              "it claims here.", flush=True)
    if probe_lit is None:
        print("   probe: FAILED — policy has no literals to probe", flush=True)
        return 1

    doc = f"deploy probe: {probe_lit} .end"
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    endpoints = {"themis": os.environ.get("THEMIS_ENDPOINT", ""),
                 "aergia": os.environ.get("AERGIA_ENDPOINT", "")}
    if not prev:
        basis = "any-literal (first cell, no prev)"
    elif new_count:
        basis = "unique-to-N"
    else:
        basis = "any-literal (EMPTY DIFF)"
    ok = True
    for e in engines:
        # Retry a bounded window: a just-deployed policy can still be propagating
        # to the data plane (ISSUE-003, no health signal to wait on). A genuinely
        # stale policy never gains the unique literal, so it fails every attempt —
        # the retry only rescues propagation lag, it does not mask staleness.
        redacted, detail = False, ""
        for attempt in range(args.attempts):
            if attempt:
                time.sleep(args.delay)
            try:
                resp = call(endpoints.get(e, ""), os.environ.get(f"{e.upper()}_TOKEN", ""), doc)
            except Exception as exc:  # noqa: BLE001
                detail = f"request error: {str(exc)[:100]}"
                continue
            token_seen = token[:MAX_TOKEN_LEN] in resp  # truncation-aware (ISSUE-005)
            if token_seen and (probe_lit not in resp):
                redacted, detail = True, f"got {resp[:80]!r}"
                break
            detail = f"not redacted: {resp[:80]!r}"
        print(f"   probe: {e} {'OK' if redacted else 'FAILED'} [{basis}] "
              f"lit={probe_lit!r} -> {token!r}; {detail}", flush=True)
        ok = ok and redacted
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
