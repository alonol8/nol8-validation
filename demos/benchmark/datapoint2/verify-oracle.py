#!/usr/bin/env python3
"""Adjudicate the DP2 engine outputs against an independent oracle.

The integrity check pointed at us, generalized to the pre/post-inference boundary.
For every prompt (and every model-stub output) the framework's Aho-Corasick matcher
computes the correct leftmost-longest literal replacement of `boundary.nol`. We
then derive the expected block/mask/route/tag action from the sentinels exactly as
the harness does, and compare against what each engine actually produced:

  - action correctness: recorded pre/post action + tags match the oracle's.
  - byte correctness: where text is forwarded (allow/mask/tag), the engine's
    forwarded text matches the oracle's replacement byte-for-byte.

If Themis matches the oracle, its parity with Aergia is a genuinely correct result,
not two engines agreeing on the same mistake.

Usage (run where the DP2 output jsonls live, e.g. EC2 results/):

  python demos/benchmark/datapoint2/verify-oracle.py \
      --policy demos/policies/boundary.nol \
      --results demos/benchmark/datapoint2/results \
      themis_api_infer aergia_api_infer
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
from framework.policy.matching import LiteralMatcher, resolve_non_overlapping  # noqa: E402
from framework.policy.oracle import parse_policy  # noqa: E402
# One shared strict parser (framework.policy.oracle); findings 016 item 2.


def oracle_output(text: str, matcher: LiteralMatcher, rules: dict[str, str]) -> str:
    selected = resolve_non_overlapping(matcher.find_all(text))
    out, cursor = [], 0
    for match in selected:
        out.append(text[cursor:match.start])
        out.append(rules[match.literal])
        cursor = match.end
    out.append(text[cursor:])
    return "".join(out)


# The harness's action derivation, mirrored from engine_infer.go deriveAction. A
# marker-based action counts only when the marker is NEW here. Precedence:
# block > route > drop > mask > redact > allow. block/route are roadmap signals.
def load_actions(path: Path) -> dict:
    return json.loads(path.read_text())


def derive_action(input_text: str, processed: str, actions: dict) -> str:
    m = actions.get("markers", {})

    def new_marker(mk: str) -> bool:
        return bool(mk) and mk in processed and mk not in input_text

    if new_marker(m.get("block", "")):
        return "block"
    if new_marker(m.get("route", "")):
        return "route"
    li, lp = input_text.lower(), processed.lower()
    for d in actions.get("dropLiterals", []):
        if d and d.lower() in li and d.lower() not in lp:
            return "drop"
    if new_marker(m.get("maskPrefix", "")):
        return "mask"
    if new_marker(m.get("redact", "")):
        return "redact"
    return "allow"


def load_records(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def verify_engine(records, matcher, rules, actions, samples):
    """No-stop model: verify both edges independently. Pre transforms the prompt, post
    transforms the model output; the engine's processed text and derived action must match
    the oracle at each edge."""
    problems = []
    for r in records:
        oracle_pre = oracle_output(r["prompt_original"], matcher, rules)
        exp_pre = derive_action(r["prompt_original"], oracle_pre, actions)
        if r["pre_action"] != exp_pre:
            problems.append((r["prompt_id"], "pre_action", r["pre_action"], exp_pre))
        elif r["prompt_processed"] != oracle_pre:
            problems.append((r["prompt_id"], "prompt_processed",
                             repr(r["prompt_processed"]), repr(oracle_pre)))

        oracle_post = oracle_output(r["raw_model_output"], matcher, rules)
        exp_post = derive_action(r["raw_model_output"], oracle_post, actions)
        if r["post_action"] != exp_post:
            problems.append((r["prompt_id"], "post_action", r["post_action"], exp_post))
        elif r["final_output"] != oracle_post:
            problems.append((r["prompt_id"], "final_output",
                             repr(r["final_output"]), repr(oracle_post)))
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("engines", nargs="+")
    ap.add_argument("--policy", type=Path, default=REPO_ROOT / "demos/policies/boundary.nol")
    ap.add_argument("--actions", type=Path, default=REPO_ROOT / "demos/policies/boundary-actions.json")
    ap.add_argument("--results", type=Path, default=REPO_ROOT / "demos/benchmark/datapoint2/results")
    ap.add_argument("--samples", type=int, default=5)
    args = ap.parse_args()

    rules = parse_policy(args.policy)
    matcher = LiteralMatcher(rules.keys())
    actions = load_actions(args.actions)
    print(f"Policy: {args.policy.name} ({len(rules)} literal rules)\n")

    any_bad = False
    for engine in args.engines:
        path = args.results / f"{engine}_output.jsonl"
        if not path.exists():
            print(f"[{engine}] MISSING {path}")
            any_bad = True
            continue
        records = load_records(path)
        problems = verify_engine(records, matcher, rules, actions, args.samples)
        verdict = "MATCHES ORACLE" if not problems else "DIVERGES FROM ORACLE"
        print(f"[{engine}] {len(records)} prompts; {len(records) - len({p[0] for p in problems})}"
              f"/{len(records)} fully match oracle -> {verdict}")
        for pid, field, got, exp in problems[:args.samples]:
            print(f"  - {pid} [{field}]\n      engine: {got}\n      oracle: {exp}")
        if len(problems) > args.samples:
            print(f"  ... and {len(problems) - args.samples} more")
        print()
        any_bad = any_bad or bool(problems)

    print("VERDICT: " + ("at least one engine diverges from the oracle."
                          if any_bad else "every engine matches the oracle."))
    return 1 if any_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
