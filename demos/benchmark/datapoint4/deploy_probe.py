#!/usr/bin/env python3
"""Deploy verification probe for the DP4 harnesses.

A deploy is fire-and-forget (ISSUE-003), there is no runtime health signal
(ISSUE-007), and no policy read-back. So "the engine is flat across rule count"
is indistinguishable from "the policy never changed on the engine." This probe
closes that gap: after deploying policy N it sends documents containing literals
UNIQUE to N (present in N, absent from the previously deployed policy) and checks
the engine's output BYTE-FOR-BYTE against the independent oracle. A stale policy
cannot pass, because it never held those literals — its output for the probe
document differs from N's oracle output.

Byte-for-byte, not substring: a "token appears / literal absent" check passes on a
stale policy whose literal is a substring of the probe literal (it produces the
token plus a leftover fragment). Whole-document equality against oracle_output
does not. See review/findings/006.

Because token-truncation attribution is unresolved (ISSUE-005: the runtime
truncates a replacement token, observed at 15 chars, and it is not yet established
which engine(s) do so), a pass is accepted against EITHER the full-token oracle
output OR its 15-char-truncated variant, and which one matched is recorded — that
is free evidence toward the truncation question.

It also reports |set(N) - set(prev)| per cell, pass or fail. If that difference is
empty or trivial, the rule-count sweep is not varying what we think it varies —
a finding on its own that would invalidate the trend claim, independent of
everything else.

Reuses the framework's ONE parser + oracle (framework.policy.oracle).

Exit non-zero if any named engine fails the probe, so the caller aborts the cell.

Usage:
  # rule-count sweep: literals unique to N, diff against the prior cell's policy
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
from framework.policy.oracle import build_matcher, oracle_output, parse_policy  # noqa: E402

# ISSUE-005: the runtime truncates a replacement token, observed at 15 chars.
# Which engine(s) apply it is unresolved (review/findings/006), so the probe is
# deliberately truncation-agnostic — it accepts the full-token oracle output OR
# the 15-char-truncated variant, and records which matched. It never asserts a
# per-engine truncation behaviour.
MAX_TOKEN_LEN = 15


def _collides(lit: str, others: set[str]) -> bool:
    """True if `lit` has a substring relationship with any literal in `others`."""
    return any(o != lit and (o in lit or lit in o) for o in others)


def probe_plan(cur: dict[str, str], prev: dict[str, str], count: int = 4) -> tuple[list[tuple[str, str]], int]:
    """Choose the literals to probe with.

    Returns (probe_pairs, new_count). Selection, in order of preference:
      - literals UNIQUE to `cur` (present in cur, absent from prev) so a stale
        policy cannot pass;
      - with NO substring relationship to any literal in prev (defence in depth —
        byte-for-byte already defeats the stale-substring case, but skipping these
        keeps the probe document unambiguous);
      - spread across the sorted set (so a partial deploy that lands only part of
        the ruleset is more likely to be caught), up to `count` of them; for a
        single probe (count<=1) the longest such literal, least collision-prone.
    Falls back to any literals from cur when there is no previous policy or no
    usable unique literal remains. new_count = |set(cur) - set(prev)|, reported
    regardless.
    """
    new = [lit for lit in cur if lit not in prev]
    new_count = len(new)
    safe = [lit for lit in new if not _collides(lit, set(prev))]
    pool = safe or new or list(cur)
    if not pool:
        return [], new_count
    if count <= 1:
        picks = [max(pool, key=lambda s: (len(s), s))]
    else:
        ordered = sorted(pool)
        n = min(count, len(ordered))
        idxs = sorted(set(round(k * (len(ordered) - 1) / (n - 1)) for k in range(n)))
        picks = [ordered[i] for i in idxs]
    return [(lit, cur[lit]) for lit in picks], new_count


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
    ap.add_argument("--count", type=int, default=4, help="literals to probe, spread across the new set")
    ap.add_argument("--attempts", type=int, default=5, help="probe retries per engine (propagation lag)")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between retries")
    args = ap.parse_args()

    cur = parse_policy(Path(args.policy))
    prev = parse_policy(Path(args.prev)) if args.prev and Path(args.prev).exists() else {}
    picks, new_count = probe_plan(cur, prev, args.count)

    print(f"   probe: |policy|={len(cur)}  |new vs prev|={new_count}  probing {len(picks)} literal(s)", flush=True)
    if prev and new_count == 0:
        print("   probe: WARNING set(N)-set(prev) is EMPTY — this cell does not vary the "
              "ruleset from the previous one; the rule-count trend is not measuring what "
              "it claims here.", flush=True)
    if not picks:
        print("   probe: FAILED — policy has no literals to probe", flush=True)
        return 1
    if not prev:
        basis = "any-literal (first cell, no prev)"
    elif new_count:
        basis = "unique-to-N"
    else:
        basis = "any-literal (EMPTY DIFF)"

    # The engine applies the whole policy, so compute the oracle over the whole
    # policy (not just the probe literal) — anything else in the document that
    # happens to be a policy literal is accounted for. Two variants because the
    # truncation attribution is unresolved.
    matcher = build_matcher(cur)
    rules_trunc = {lit: tok[:MAX_TOKEN_LEN] for lit, tok in cur.items()}

    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    endpoints = {"themis": os.environ.get("THEMIS_ENDPOINT", ""),
                 "aergia": os.environ.get("AERGIA_ENDPOINT", "")}
    ok = True
    for e in engines:
        token = os.environ.get(f"{e.upper()}_TOKEN", "")
        passed, variants, detail = 0, set(), ""
        for lit, _tok in picks:
            doc = f"deploy probe: {lit} .end"
            expected_full = oracle_output(doc, matcher, cur)
            expected_trunc = oracle_output(doc, matcher, rules_trunc)
            hit = False
            for attempt in range(args.attempts):
                if attempt:
                    time.sleep(args.delay)
                try:
                    resp = call(endpoints.get(e, ""), token, doc)
                except Exception as exc:  # noqa: BLE001
                    detail = f"request error on {lit!r}: {str(exc)[:80]}"
                    continue
                if resp == expected_full:
                    hit, variant = True, "full"
                elif resp == expected_trunc:
                    hit, variant = True, "trunc15"
                if hit:
                    variants.add(variant)
                    break
                detail = f"mismatch on {lit!r}: got {resp[:70]!r}"
            if hit:
                passed += 1
            else:
                break  # a genuine miss on any literal fails the engine; stop probing it
        engine_ok = passed == len(picks)
        vlabel = "/".join(sorted(variants)) if variants else "none"
        print(f"   probe: {e} {'OK' if engine_ok else 'FAILED'} [{basis}] "
              f"{passed}/{len(picks)} literals byte-for-byte; oracle-variant={vlabel}"
              + (f"; {detail}" if not engine_ok else ""), flush=True)
        ok = ok and engine_ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
