#!/usr/bin/env python3
"""Build the Data Point 2 boundary policy from the pre/post-inference reference lists.

Data Point 2 governs a model boundary: what reaches the model (pre-inference) and what
leaves it (post-inference). NOL8 does deterministic literal REPLACEMENT only, which gives
two honest families of action (same split as Data Point 3):

  LIVE TODAY (NOL8 transforms the data, oracle-verifiable):
    redact  - replace a known value with a marker           value -> "[REDACT]"
    mask    - replace a known value with a usable stand-in   card  -> "XXXX <last4>"

  ROADMAP (NOL8 emits a signal; a control plane enforces; native enforcement later):
    route   - flag for a controlled path                     value -> "[ROUTE]"
    block   - flag to refuse (do not call the model / withhold output)   value -> "[BLOCK]"

NOL8 does not itself stop a prompt reaching the model, or withhold an output, today. It
redacts/masks the text and emits the signal; the text flows on. The report labels
route/block Roadmap. The live win is real: known secrets never reach the model or the
response.

Replacements are <= 15 chars (ISSUE-005), so the card mask is compact ("XXXX <last4>").
The generator refuses containing literals (ISSUE-004) like build_policy.py.

Emits two files:
  boundary.nol          - the literal policy (deploys to the engine)
  boundary-actions.json - the action map (markers + drop literals) the engine mode and the
                          oracle use to label each control point

Regenerate:  python demos/policies/build_boundary_policy.py
"""
from __future__ import annotations

import json
from pathlib import Path

import build_policy  # reuse MAX_TOKEN_LENGTH and the safety discipline

REDACT_MARKER = "[REDACT]"
MASK_PREFIX = "XXXX "
ROUTE_SIGNAL = "[ROUTE]"
BLOCK_SIGNAL = "[BLOCK]"

# (list file, action, roadmap?, stage, human label). Action is redact / mask (live) or
# route / block (roadmap signal). Stage: pre (prompt), post (output), or pre+post.
LISTS: list[tuple[str, str, bool, str, str]] = [
    ("internal_projects.txt", "redact", False, "pre", "Internal project codenames, redacted from the prompt"),
    ("account_ids.txt", "redact", False, "pre+post", "Account identifiers, redacted"),
    ("payment_cards.txt", "mask", False, "pre+post", "Customer cards, masked to last four"),
    ("output_tag_phrases.txt", "redact", False, "post", "Privileged-output markers, redacted"),
    ("flagged_customers.txt", "route", True, "pre", "Flagged customers, signalled for a controlled path"),
    ("denied_entities.txt", "route", True, "pre", "Denied entities, signalled for a controlled path"),
    ("route_phrases.txt", "route", True, "pre", "Controlled-workflow triggers, signalled to route"),
    ("block_phrases.txt", "block", True, "pre", "Blocked prompt phrases, signalled to refuse"),
    ("output_block_phrases.txt", "block", True, "post", "Unsafe-output phrases, signalled to withhold"),
]

HERE = Path(__file__).resolve().parent
LIST_DIR = HERE.parent / "benchmark" / "usecase-2-inference" / "data" / "reference_lists"
OUTPUT = HERE / "boundary.nol"
ACTIONS_OUTPUT = HERE / "boundary-actions.json"


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
    loaded = []
    for filename, action, roadmap, stage, label in LISTS:
        path = list_dir / filename
        if not path.is_file():
            continue
        values = [line.strip() for line in path.read_text().splitlines()
                  if line.strip() and not line.lstrip().startswith("#")]
        if values:
            loaded.append((action, roadmap, stage, label, [(v, replacement_for(action, v)) for v in values]))
    return loaded


def check_safe(lists) -> None:
    for action, _roadmap, _stage, _label, pairs in lists:
        for literal, replacement in pairs:
            if len(replacement) > build_policy.MAX_TOKEN_LENGTH:
                raise ValueError(
                    f"Replacement {replacement!r} for {literal!r} exceeds "
                    f"{build_policy.MAX_TOKEN_LENGTH} chars; it would truncate (ISSUE-005)."
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
        "# Data Point 2 boundary policy - pre/post-inference control (literal matching).",
        "# Generated by demos/policies/build_boundary_policy.py; edit the reference lists",
        "# under demos/benchmark/usecase-2-inference/data/reference_lists/ and regenerate.",
        "# NOL8 does literal replacement only: redact value -> [REDACT], mask card ->",
        "# XXXX <last4>, route value -> [ROUTE] (signal), block value -> [BLOCK] (signal).",
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
    ap.add_argument("--list-dir", type=Path, default=LIST_DIR)
    ap.add_argument("--output", type=Path, default=OUTPUT)
    ap.add_argument("--actions-output", type=Path, default=ACTIONS_OUTPUT)
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
