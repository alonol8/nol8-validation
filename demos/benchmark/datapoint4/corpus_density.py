#!/usr/bin/env python3
"""Corpus coordinates per rule count — the offline check that protects the rule-count
throughput trend, plus the recordable axes from Alon's workload proposal.

Two modes:

  --mode source  (default): density over the FULL generated corpus (all bands), each
     corpus matched by its own policy. Answers "does the generator raise match density
     with rule count?" (findings 008). This is a per-corpus generator property.

  --mode sent: density over the bodies the DRIVER ACTUALLY SENT for a payload band —
     replicating loadCorpus in main.go: band by len(message) in bytes, keep the first
     `--cap` in file order (the driver does not dedup; the corpus is all-distinct
     anyway). Reports matches per KB AND matches per request, because the throughput
     ratios were measured on these bodies, not the source documents (findings 009).

Uses the framework oracle. Runs offline over artifacts/runs/*/generated (policy +
input.jsonl); no engines needed. Give explicit --dirs to pin exact run dirs, else the
most-recent dir per requested --rules is used.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
from framework.policy.oracle import build_matcher, parse_policy  # noqa: E402
from framework.policy.matching import LiteralMatcher, resolve_non_overlapping  # noqa: E402

BANDS = {"small": (0, 4096), "medium": (4097, 65536), "large": (65537, 786432), "all": (0, 0)}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def iter_messages(input_jsonl: Path):
    for line in Path(input_jsonl).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)["message"]
        except Exception:  # noqa: BLE001
            pass


def coords_source(policy_path: Path, input_path: Path) -> dict:
    rules = parse_policy(policy_path)
    matcher = build_matcher(rules)
    matcher_norm = LiteralMatcher({_norm(l) for l in rules})
    total_bytes = total_occ = total_near = 0
    seen: set[str] = set()
    docs = 0
    for d in iter_messages(input_path):
        docs += 1
        total_bytes += len(d.encode("utf-8"))
        occ = len(resolve_non_overlapping(matcher.find_all(d)))
        total_occ += occ
        norm_occ = len(resolve_non_overlapping(matcher_norm.find_all(_norm(d))))
        total_near += max(0, norm_occ - occ)
        seen.add(d)
    kb = total_bytes / 1024.0
    n = docs or 1
    return {"mode": "source", "rule_count": len(rules), "docs": docs,
            "distinct_bodies": len(seen), "diversity_ratio": round(len(seen) / n, 4),
            "avg_bytes": round(total_bytes / n),
            "matches_per_kb": round(total_occ / kb, 4) if kb else 0.0,
            "near_misses_per_kb": round(total_near / kb, 4) if kb else 0.0}


def coords_sent(policy_path: Path, input_path: Path, band: str, cap: int) -> dict:
    """Replicate the driver's band selection: keep the first `cap` messages whose UTF-8
    byte length falls in the band (loadCorpus bands by len(rec.Message), no dedup)."""
    lo, hi = BANDS[band]
    rules = parse_policy(policy_path)
    matcher = build_matcher(rules)
    kept = total_msg_bytes = total_occ = 0
    docs_with_match = 0
    for msg in iter_messages(input_path):
        mb = len(msg.encode("utf-8"))
        if mb < lo or (hi > 0 and mb > hi):
            continue
        if cap and kept >= cap:
            break
        occ = len(resolve_non_overlapping(matcher.find_all(msg)))
        total_occ += occ
        total_msg_bytes += mb
        docs_with_match += 1 if occ else 0
        kept += 1
    kb = total_msg_bytes / 1024.0
    k = kept or 1
    return {"mode": f"sent:{band}", "rule_count": len(rules), "bodies_sent": kept,
            "cap": cap, "avg_msg_bytes": round(total_msg_bytes / k),
            "total_matches": total_occ,
            "matches_per_request": round(total_occ / k, 4),
            "matches_per_kb": round(total_occ / kb, 4) if kb else 0.0,
            "pct_requests_with_a_match": round(100 * docs_with_match / k, 1)}


def rule_count_of(policy_path: Path):
    try:
        return len(parse_policy(policy_path))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["source", "sent"], default="source")
    ap.add_argument("--rules", default="2000,4000,6000,8000")
    ap.add_argument("--dirs", default="", help="explicit run-dir names (comma), overrides auto-select")
    ap.add_argument("--band", default="small", choices=list(BANDS))
    ap.add_argument("--cap", type=int, default=4000)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    runs = REPO_ROOT / "artifacts" / "runs"
    pairs: list[tuple[Path, Path]] = []
    if args.dirs:
        for d in args.dirs.split(","):
            pol = runs / d / "generated" / "scale-policy.nol"
            inp = runs / d / "generated" / "input.jsonl"
            if pol.exists() and inp.exists():
                pairs.append((pol, inp))
            else:
                print(f"  MISSING dir {d}")
    else:
        newest: dict[int, tuple[Path, Path]] = {}
        for pol in sorted(runs.glob("*/generated/scale-policy.nol")):
            inp = pol.parent / "input.jsonl"
            if inp.exists() and (rc := rule_count_of(pol)) is not None:
                newest[rc] = (pol, inp)
        for t in [int(x) for x in args.rules.split(",")]:
            if t in newest:
                pairs.append(newest[t])
            else:
                print(f"  rule_count={t}: NO corpus")

    rows = []
    for pol, inp in pairs:
        c = coords_source(pol, inp) if args.mode == "source" else coords_sent(pol, inp, args.band, args.cap)
        c["run_dir"] = pol.parent.parent.name
        rows.append(c)
        print("  " + "  ".join(f"{k}={v}" for k, v in c.items() if k != "run_dir"))
    if args.out:
        (REPO_ROOT / "artifacts" / "evidence" / args.out).write_text(
            json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        print(f"saved artifacts/evidence/{args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
