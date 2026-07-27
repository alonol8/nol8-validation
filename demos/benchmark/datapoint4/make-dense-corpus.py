#!/usr/bin/env python3
"""Build an input corpus with a CONTROLLED match density (matches per KB).

Why: software matchers stay cheap at ~1 match/KB (the hidden assumption behind
regex/DPI) but do real work as density rises to enterprise data-processing levels
(10-50 matches/KB); a fixed FPGA pipeline shouldn't care. To test that on the real
engines we need input where we KNOW the density — so we inject real policy literals
into clean filler at a target rate, deploy the SAME policy, and drive both engines.

Density is held INDEPENDENT of the deployed rule count: we inject only from the
first `--lit-pool` literals (present in every policy of that size or larger), so a
1k-rule and a 16k-rule policy see the exact same matches/KB. That cleanly separates
"more rules" from "more matches."

  python make-dense-corpus.py --policy <scale-policy.nol> --matches-per-kb 12 \
      --doc-bytes 4000 --docs 6000 --out input_d12.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from framework.policy.matching import LiteralMatcher  # noqa: E402
from framework.workload import prose  # noqa: E402
from framework.workload.near_miss import NearMissFactory  # noqa: E402


def load_literals(policy_path: Path, cap: int) -> list[str]:
    """Parse the policy's literals. `cap` of 0 means all of them."""

    lits: list[str] = []
    for line in policy_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith('"'):
            continue
        end = line.find('" ->')
        if end <= 1:
            end = line.find('"->')
        if end <= 1:
            continue
        lits.append(line[1:end])
        if cap and len(lits) >= cap:
            break
    if not lits:
        raise SystemExit(f"no literals parsed from {policy_path}")
    return lits


def build_doc(
    literals: list[str],
    start: int,
    per_doc: int,
    doc_bytes: int,
    rng: random.Random,
    near_misses: list[str],
    near_miss_per_doc: int,
) -> str:
    """Intersperse `per_doc` literals through business text to ~doc_bytes.

    Filler is composed per document rather than repeated from a constant, and
    carries the almost-matching text a real corpus contains alongside the values
    that are actually governed.
    """
    placed = [literals[(start + j) % len(literals)] for j in range(per_doc)]
    if near_misses and near_miss_per_doc:
        placed.extend(rng.choice(near_misses) for _ in range(near_miss_per_doc))
        rng.shuffle(placed)

    value_bytes = sum(len(value) for value in placed) + 2 * len(placed)
    fill_total = max(0, doc_bytes - value_bytes)
    per_gap = fill_total // (len(placed) + 1) if placed else doc_bytes

    parts: list[str] = []
    for value in placed:
        parts.append(prose.text_of_at_least(rng, per_gap)[:per_gap])
        parts.append(" " + value + " ")
    parts.append(prose.text_of_at_least(rng, per_gap)[:per_gap])
    return "".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, required=True)
    ap.add_argument("--matches-per-kb", type=float, required=True)
    ap.add_argument("--doc-bytes", type=int, default=4000)
    ap.add_argument("--docs", type=int, default=6000)
    ap.add_argument("--lit-pool", type=int, default=0,
                    help="inject only from the first K literals (0 = the whole policy). "
                         "A low value holds density independent of rule count, which is "
                         "useful as a comparison point but is not what traffic against a "
                         "large policy looks like")
    ap.add_argument("--near-miss-per-kb", type=float, default=6.0,
                    help="text that nearly matches a rule and does not: values cut short "
                         "by a field width, masked down to a prefix, or differing in their "
                         "last character. 0 disables")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    literals = load_literals(args.policy, args.lit_pool)
    rng = random.Random(args.seed)

    near_misses: list[str] = []
    if args.near_miss_per_kb > 0:
        all_literals = load_literals(args.policy, 0)
        factory = NearMissFactory(
            LiteralMatcher(all_literals), {"policy": all_literals}
        )
        near_misses = [
            near_miss.value
            for near_miss in factory.build_pool(min(4000, len(all_literals) * 2), rng)
        ]
        if not near_misses:
            print("warning: no near misses could be derived from this policy")

    per_doc = max(1, round(args.matches_per_kb * args.doc_bytes / 1024))
    near_per_doc = round(args.near_miss_per_kb * args.doc_bytes / 1024)
    start = 0
    total_bytes = 0
    total_lits = 0
    total_near = 0
    with args.out.open("w", encoding="utf-8") as fh:
        for i in range(args.docs):
            doc = build_doc(
                literals, start, per_doc, args.doc_bytes, rng, near_misses, near_per_doc
            )
            start += per_doc
            total_bytes += len(doc.encode("utf-8"))
            total_lits += per_doc
            total_near += near_per_doc if near_misses else 0
            fh.write(json.dumps({"record_id": f"d-{i:06d}", "kind": "dirty", "message": doc},
                                ensure_ascii=False) + "\n")
    kb = total_bytes / 1024
    print(f"wrote {args.out}: {args.docs} docs, {total_bytes/1e6:.0f} MB, "
          f"~{total_lits/kb:.1f} matches/KB (target {args.matches_per_kb}), "
          f"~{total_near/kb:.1f} near-misses/KB, "
          f"{len(literals)} distinct literals in play, {per_doc} matches/doc")


if __name__ == "__main__":
    main()
