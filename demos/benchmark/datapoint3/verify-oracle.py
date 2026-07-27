#!/usr/bin/env python3
"""Adjudicate the DP3 agent-mesh engine outputs against an independent oracle.

The integrity check pointed at us, generalized to a multi-hop agent workflow. DP3's
flow is stateful - a message is governed at every handoff, then the tool call, then the
final output, and redactions carry forward - so a per-event check is not enough. Instead
this re-simulates the ENTIRE mesh flow (the same orchestration as engine_mesh.go /
runMode) but performs every literal transformation with the framework's Aho-Corasick
matcher (leftmost-longest, non-overlapping) over mesh.nol, instead of the engine. It
then compares the engine's recorded events to the oracle's expected events one-for-one.

The orchestration (flow, action derivation, model stub) is shared harness logic; the
thing being independently verified is the engine's literal MATCHING and REPLACEMENT at
each hop - exactly where ISSUE-004-style corruption would show up. If Themis reproduces
the oracle event-for-event, its parity with Aergia is a genuinely correct result, not
two engines agreeing on the same mistake.

Usage (run where the DP3 event jsonls live, e.g. EC2 results/):

  python demos/benchmark/datapoint3/verify-oracle.py \
      --policy demos/policies/mesh.nol \
      --results demos/benchmark/datapoint3/results \
      themis_api_mesh aergia_api_mesh
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

# Stages, matching engine_mesh.go / runMode.
_HANDOFF_STAGES = [
    ("triage", "user", "triage_agent"),
    ("research", "triage_agent", "research_agent"),
    ("decision", "research_agent", "decision_agent"),
    ("action", "decision_agent", "action_agent"),
]


def oracle_output(text: str, matcher: LiteralMatcher, rules: dict[str, str]) -> str:
    """The correct leftmost-longest, non-overlapping literal replacement of `text`."""
    selected = resolve_non_overlapping(matcher.find_all(text))
    out, cursor = [], 0
    for match in selected:
        out.append(text[cursor:match.start])
        out.append(rules[match.literal])
        cursor = match.end
    out.append(text[cursor:])
    return "".join(out)


# The harness's per-hop action derivation, mirrored from engine_mesh.go deriveMeshAction.
# A marker-based action counts only when the marker is NEW this hop (a value redacted here,
# not one carried forward). Precedence: block > route > drop > mask > redact > allow.
# block/route are roadmap signals; the rest are live data actions.
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
        # drop = the value was present in the input and removed here.
        if d and d.lower() in li and d.lower() not in lp:
            return "drop"
    if new_marker(m.get("maskPrefix", "")):
        return "mask"
    if new_marker(m.get("redact", "")):
        return "redact"
    return "allow"


def model_output(task: dict, processed: str) -> str:
    """The agent model stub, mirrored from main.go modelOutput."""
    profile = task.get("agent_stub_profile", "")
    task_id = task.get("task_id", "")
    if profile == "external_send_attempt":
        return "Action agent prepared an external distribution package using " + processed
    if profile == "external_leak_attempt":
        return "Action agent prepared partner-facing notes containing " + processed
    if profile == "blocked_final":
        return "Final response contains disallowed instructions and should be blocked."
    if profile == "privileged_context":
        return f"Final response references privileged context for {task_id}."
    if profile == "maskable":
        return "Final response summarizes " + processed
    return f"Final response is benign for {task_id}."


def oracle_events(task: dict, matcher: LiteralMatcher, rules: dict[str, str],
                  actions: dict) -> list[dict]:
    """Re-run the whole mesh flow for one task using the oracle matcher; return the
    expected event stream (stage, event_type, action, processed_text). No stopping: NOL8
    redacts/masks/drops and the text flows on; route/block are recorded signals."""
    events: list[dict] = []
    text = task["user_task"]

    for stage_name, _src, _dst in _HANDOFF_STAGES:
        processed = oracle_output(text, matcher, rules)
        events.append({"stage": stage_name, "event_type": "agent_message",
                       "action": derive_action(text, processed, actions), "processed_text": processed})
        text = processed

    processed = oracle_output(text, matcher, rules)
    events.append({"stage": "tool", "event_type": "tool_call",
                   "action": derive_action(text, processed, actions), "processed_text": processed})
    text = processed

    final_text = model_output(task, text)
    final_processed = oracle_output(final_text, matcher, rules)
    events.append({"stage": "final", "event_type": "final_output",
                   "action": derive_action(final_text, final_processed, actions),
                   "processed_text": final_processed})
    return events


def load_tasks(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def load_events_by_task(path: Path) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        grouped.setdefault(ev["task_id"], []).append(ev)
    return grouped


def verify_engine(tasks, engine_events, matcher, rules, actions):
    """Return list of (task_id, detail) divergences."""
    problems = []
    for task in tasks:
        tid = task["task_id"]
        expected = oracle_events(task, matcher, rules, actions)
        actual = engine_events.get(tid, [])
        if len(actual) != len(expected):
            problems.append((tid, f"event count: engine {len(actual)} vs oracle {len(expected)}"))
            continue
        for i, (exp, act) in enumerate(zip(expected, actual)):
            if act.get("stage") != exp["stage"] or act.get("action") != exp["action"]:
                problems.append((tid, f"{exp['stage']}: engine action "
                                      f"{act.get('action')!r} vs oracle {exp['action']!r}"))
            elif act.get("processed_text") != exp["processed_text"]:
                problems.append((tid, f"{exp['stage']} processed_text:\n"
                                      f"      engine: {act.get('processed_text')!r}\n"
                                      f"      oracle: {exp['processed_text']!r}"))
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("engines", nargs="+")
    ap.add_argument("--policy", type=Path, default=REPO_ROOT / "demos/policies/mesh.nol")
    ap.add_argument("--actions", type=Path, default=REPO_ROOT / "demos/policies/mesh-actions.json")
    ap.add_argument("--results", type=Path, default=REPO_ROOT / "demos/benchmark/datapoint3/results")
    ap.add_argument("--tasks", type=Path,
                    default=REPO_ROOT / "demos/benchmark/datapoint3/data/tasks/sample_agent_tasks.jsonl")
    ap.add_argument("--samples", type=int, default=5)
    args = ap.parse_args()

    rules = parse_policy(args.policy)
    matcher = LiteralMatcher(rules.keys())
    actions = load_actions(args.actions)
    tasks = load_tasks(args.tasks)
    print(f"Policy: {args.policy.name} ({len(rules)} literal rules); {len(tasks)} tasks\n")

    any_bad = False
    for engine in args.engines:
        path = args.results / f"{engine}_events.jsonl"
        if not path.exists():
            print(f"[{engine}] MISSING {path}")
            any_bad = True
            continue
        engine_events = load_events_by_task(path)
        problems = verify_engine(tasks, engine_events, matcher, rules, actions)
        bad_tasks = {p[0] for p in problems}
        verdict = "MATCHES ORACLE" if not problems else "DIVERGES FROM ORACLE"
        print(f"[{engine}] {len(tasks) - len(bad_tasks)}/{len(tasks)} tasks "
              f"reproduce the oracle event-for-event -> {verdict}")
        for tid, detail in problems[:args.samples]:
            print(f"  - {tid} [{detail}]")
        if len(problems) > args.samples:
            print(f"  ... and {len(problems) - args.samples} more")
        print()
        any_bad = any_bad or bool(problems)

    print("VERDICT: " + ("at least one engine diverges from the oracle."
                          if any_bad else "every engine matches the oracle."))
    return 1 if any_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
