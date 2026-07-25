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
from pathlib import Path

# Clean business-ish filler with no policy literals in it.
FILLER = ("The quarterly account review referenced the following context and notes "
          "for internal handling and downstream processing during this period. ")


def load_literals(policy_path: Path, cap: int) -> list[str]:
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
        if len(lits) >= cap:
            break
    if not lits:
        raise SystemExit(f"no literals parsed from {policy_path}")
    return lits


def build_doc(literals: list[str], start: int, per_doc: int, doc_bytes: int) -> str:
    """Intersperse `per_doc` literals through clean filler to ~doc_bytes."""
    lits = [literals[(start + j) % len(literals)] for j in range(per_doc)]
    lit_bytes = sum(len(x) for x in lits) + 2 * per_doc
    fill_total = max(0, doc_bytes - lit_bytes)
    seg = fill_total // (per_doc + 1) if per_doc else doc_bytes
    fillseg = (FILLER * (seg // len(FILLER) + 1))[:seg]
    parts: list[str] = []
    for x in lits:
        parts.append(fillseg)
        parts.append(" " + x + " ")
    parts.append(fillseg)
    return "".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, required=True)
    ap.add_argument("--matches-per-kb", type=float, required=True)
    ap.add_argument("--doc-bytes", type=int, default=4000)
    ap.add_argument("--docs", type=int, default=6000)
    ap.add_argument("--lit-pool", type=int, default=1000,
                    help="inject only from the first K literals so density is independent of rule count")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    literals = load_literals(args.policy, args.lit_pool)
    per_doc = max(1, round(args.matches_per_kb * args.doc_bytes / 1024))
    start = 0
    total_bytes = 0
    total_lits = 0
    with args.out.open("w", encoding="utf-8") as fh:
        for i in range(args.docs):
            doc = build_doc(literals, start, per_doc, args.doc_bytes)
            start += per_doc
            total_bytes += len(doc.encode("utf-8"))
            total_lits += per_doc
            fh.write(json.dumps({"record_id": f"d-{i:06d}", "kind": "dirty", "message": doc},
                                ensure_ascii=False) + "\n")
    actual = total_lits / (total_bytes / 1024)
    print(f"wrote {args.out}: {args.docs} docs, {total_bytes/1e6:.0f} MB, "
          f"~{actual:.1f} matches/KB (target {args.matches_per_kb}), {per_doc} literals/doc")


if __name__ == "__main__":
    main()
