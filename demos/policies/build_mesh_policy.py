#!/usr/bin/env python3
"""Build the Data Point 3 mesh policy from the agent-to-agent reference lists.

Data Point 3 generalizes DP2 from two control points to many: NOL8 runs at every hop of
an agent workflow (Triage -> Research -> Decision -> Action -> Final). The controls are
literal, so the same `.nol` policy runs on both engines (NOL8/Themis and RE2/Aergia).

IMPORTANT - what NOL8 actually does. NOL8 does deterministic literal *replacement* only.
That gives two honest families of action:

  LIVE TODAY (NOL8 transforms the data, oracle-verifiable):
    redact  - replace a known value with a marker           value -> "[REDACT]"
    mask    - replace a known value with a usable stand-in   card  -> "XXXX <last4>"
    drop    - remove a known value entirely                  value -> ""            (DP1 strip)

  ROADMAP (NOL8 emits a signal today; a control plane enforces; native enforcement later):
    route   - flag for a controlled path                     value -> "[ROUTE]"
    block   - flag to refuse                                 value -> "[BLOCK]"

NOL8 does not itself route, block, or stop a message today; it emits the signal and the
(redacted) text flows on. The harness simulates the downstream control plane for the
roadmap actions, and that is labeled as such.

Replacements are <= 15 chars so the runtime's 15-char truncation (ISSUE-005) never garbles
them - which is exactly why the mask is a compact "XXXX <last4>", not a full 16-char PAN.
The generator refuses containing literals (ISSUE-004) like build_policy.py.

Emits two files:
  mesh.nol          - the literal policy (deploys to the engine)
  mesh-actions.json - the action map (marker strings + drop literals) the engine mode and
                      the oracle use to label each hop's action

Regenerate:  python demos/policies/build_mesh_policy.py
"""
from __future__ import annotations

import json
from pathlib import Path

import build_policy  # reuse MAX_TOKEN_LENGTH and the safety discipline

REDACT_MARKER = "[REDACT]"
MASK_PREFIX = "XXXX "
ROUTE_SIGNAL = "[ROUTE]"
BLOCK_SIGNAL = "[BLOCK]"

# (list file, action, roadmap?, stage-note, human label). Action is one of
# redact / mask / drop (live) or route / block (roadmap signal).
LISTS: list[tuple[str, str, bool, str, str]] = [
    ("internal_projects.txt", "redact", False, "handoff", "Internal project codenames, redacted from the message"),
    ("account_ids.txt", "redact", False, "handoff", "Account identifiers, redacted"),
    ("output_tag_phrases.txt", "redact", False, "final", "Privileged-output markers, redacted"),
    ("payment_cards.txt", "mask", False, "handoff", "Customer cards on file, masked to last four"),
    ("rogue_cards.txt", "drop", False, "handoff", "Known-rogue cards (fraud denylist), dropped"),
    ("flagged_customers.txt", "route", True, "handoff", "Flagged customers, signalled for a controlled path"),
    ("denied_entities.txt", "route", True, "handoff", "Denied entities, signalled for a controlled path"),
    ("blocked_tool_phrases.txt", "block", True, "tool", "Tool-bypass / exfil phrases, signalled to refuse"),
    ("output_block_phrases.txt", "block", True, "final", "Unsafe-output phrases, signalled to refuse"),
]

HERE = Path(__file__).resolve().parent
LIST_DIR = HERE.parent / "benchmark" / "usecase-3-agent-mesh" / "data" / "policies"
OUTPUT = HERE / "mesh.nol"
ACTIONS_OUTPUT = HERE / "mesh-actions.json"


def _last4(value: str) -> str:
    alnum = [c for c in value if c.isalnum()]
    return "".join(alnum[-4:])


def replacement_for(action: str, value: str) -> str:
    if action == "redact":
        return REDACT_MARKER
    if action == "mask":
        return MASK_PREFIX + _last4(value)
    if action == "drop":
        return ""
    if action == "route":
        return ROUTE_SIGNAL
    if action == "block":
        return BLOCK_SIGNAL
    raise ValueError(f"unknown action {action!r}")


def load_lists(list_dir: Path):
    """Return [(action, roadmap, stage, label, [(literal, replacement)...])] per list."""
    loaded = []
    for filename, action, roadmap, stage, label in LISTS:
        path = list_dir / filename
        if not path.is_file():
            continue
        values = [line.strip() for line in path.read_text().splitlines()
                  if line.strip() and not line.lstrip().startswith("#")]
        if values:
            pairs = [(v, replacement_for(action, v)) for v in values]
            loaded.append((action, roadmap, stage, label, pairs))
    return loaded


def check_safe(lists) -> None:
    """Refuse an unsafe policy: over-length replacements (ISSUE-005) or containing
    literals (ISSUE-004)."""
    for action, _roadmap, _stage, _label, pairs in lists:
        for literal, replacement in pairs:
            if len(replacement) > build_policy.MAX_TOKEN_LENGTH:
                raise ValueError(
                    f"Replacement {replacement!r} for {literal!r} exceeds "
                    f"{build_policy.MAX_TOKEN_LENGTH} chars; it would truncate at runtime "
                    "(ISSUE-005)."
                )

    all_values = [literal for _a, _r, _s, _l, pairs in lists for literal, _rep in pairs]
    if len(set(all_values)) != len(all_values):
        raise ValueError("Duplicate values across the reference lists; each must be unique.")

    lowered = {value: value.lower() for value in all_values}
    for outer in all_values:
        for inner in all_values:
            if inner != outer and lowered[inner] in lowered[outer]:
                raise ValueError(
                    f"Value {inner!r} is contained in {outer!r}; overlapping literals "
                    "trigger ISSUE-004. Remove one or make them disjoint."
                )


def build_nol(lists) -> str:
    lines = [
        "# Data Point 3 mesh policy - agent-to-agent control (literal matching).",
        "# Generated by demos/policies/build_mesh_policy.py; edit the reference lists",
        "# under demos/benchmark/usecase-3-agent-mesh/data/policies/ and regenerate.",
        "# Same file deploys to both engines. NOL8 does literal replacement only:",
        "#   redact value -> [REDACT], mask card -> XXXX <last4>, drop value -> (empty),",
        "#   route value -> [ROUTE] (signal), block value -> [BLOCK] (signal).",
        "# route/block are signals a control plane acts on; NOL8 does not enforce them today.",
        "",
    ]
    for action, roadmap, stage, label, pairs in lists:
        tag = "roadmap signal" if roadmap else "live"
        lines.append(f"# {label} -> action={action} ({tag}, stage={stage})")
        for literal, replacement in pairs:
            esc_l = literal.replace('"', '\\"')
            esc_r = replacement.replace('"', '\\"')
            lines.append(f'"{esc_l}" -> "{esc_r}";')
        lines.append("")
    return "\n".join(lines)


def build_actions(lists) -> dict:
    """The action map the engine mode and oracle load to label each hop."""
    drop_literals = [literal for action, _r, _s, _l, pairs in lists if action == "drop"
                     for literal, _rep in pairs]
    rules = []
    for action, roadmap, stage, _label, pairs in lists:
        for literal, replacement in pairs:
            rules.append({"literal": literal, "replacement": replacement,
                          "action": action, "roadmap": roadmap, "stage": stage})
    return {
        "markers": {"redact": REDACT_MARKER, "route": ROUTE_SIGNAL,
                    "block": BLOCK_SIGNAL, "maskPrefix": MASK_PREFIX},
        "dropLiterals": drop_literals,
        "rules": rules,
    }


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list-dir", type=Path, default=LIST_DIR,
                    help="directory of reference lists (default: the DP3 policy lists)")
    ap.add_argument("--output", type=Path, default=OUTPUT,
                    help="output .nol path (default: demos/policies/mesh.nol)")
    ap.add_argument("--actions-output", type=Path, default=ACTIONS_OUTPUT,
                    help="output action-map JSON (default: demos/policies/mesh-actions.json)")
    args = ap.parse_args()

    lists = load_lists(args.list_dir)
    if not lists:
        raise SystemExit(f"No reference lists found under {args.list_dir}")
    check_safe(lists)
    args.output.write_text(build_nol(lists))
    args.actions_output.write_text(json.dumps(build_actions(lists), indent=2) + "\n")
    rule_count = sum(len(pairs) for _a, _r, _s, _l, pairs in lists)
    live = sorted({a for a, r, _s, _l, _p in lists if not r})
    roadmap = sorted({a for a, r, _s, _l, _p in lists if r})
    print(f"Wrote {args.output.name}: {rule_count} rules across {len(lists)} lists; "
          f"live actions {', '.join(live)}; roadmap signals {', '.join(roadmap)}.")
    print(f"Wrote {args.actions_output.name}: action map for the engine mode and oracle.")


if __name__ == "__main__":
    main()
