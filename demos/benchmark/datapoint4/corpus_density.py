#!/usr/bin/env python3
"""Corpus coordinates per rule count — the offline check that protects the rule-count
throughput trend, plus the recordable axes from Alon's workload proposal.

The load-bearing question (findings 008): does the generator hold MATCH DENSITY
roughly constant across rule counts? rulecount-live.sh regenerates a corpus per rule
count, so if a bigger ruleset also comes with a denser corpus, the throughput trend
would be a density effect, not a rule-count effect. This computes matches-per-KB (and
a few companion axes) over each rule count's OWN corpus, matched by its OWN policy,
using the framework oracle. Flat across rule counts => trend attributable to ruleset
size.

Runs offline over artifacts/runs/*/generated (policy + input.jsonl). No fleet needed.
Identifies each corpus's rule count from its policy; uses the most recent dir per
requested rule count.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
from framework.policy.oracle import build_matcher, parse_policy  # noqa: E402
from framework.policy.matching import LiteralMatcher, resolve_non_overlapping  # noqa: E402


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def load_docs(input_jsonl: Path) -> list[str]:
    docs = []
    for line in Path(input_jsonl).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            docs.append(json.loads(line)["message"])
        except Exception:  # noqa: BLE001
            pass
    return docs


def coords(policy_path: Path, input_path: Path) -> dict:
    rules = parse_policy(policy_path)
    matcher = build_matcher(rules)
    matcher_norm = LiteralMatcher({_norm(l) for l in rules})
    docs = load_docs(input_path)
    total_bytes = total_occ = total_near = 0
    seen: set[str] = set()
    for d in docs:
        total_bytes += len(d.encode("utf-8"))
        occ = len(resolve_non_overlapping(matcher.find_all(d)))
        total_occ += occ
        norm_occ = len(resolve_non_overlapping(matcher_norm.find_all(_norm(d))))
        total_near += max(0, norm_occ - occ)  # approximate: extra matches after norm
        seen.add(d)
    kb = total_bytes / 1024.0
    n = len(docs) or 1
    return {
        "rule_count": len(rules),
        "docs": len(docs),
        "distinct_bodies": len(seen),
        "diversity_ratio": round(len(seen) / n, 4),
        "avg_bytes": round(total_bytes / n),
        "total_matches": total_occ,
        "matches_per_kb": round(total_occ / kb, 4) if kb else 0.0,
        "near_misses_per_kb": round(total_near / kb, 4) if kb else 0.0,
    }


def rule_count_of(policy_path: Path) -> int | None:
    try:
        return len(parse_policy(policy_path))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    targets = [int(x) for x in (sys.argv[1].split(",") if len(sys.argv) > 1
                                else ["2000", "4000", "6000", "8000"])]
    runs = REPO_ROOT / "artifacts" / "runs"
    newest: dict[int, tuple[Path, Path]] = {}
    for pol in sorted(runs.glob("*/generated/scale-policy.nol")):
        inp = pol.parent / "input.jsonl"
        if not inp.exists():
            continue
        rc = rule_count_of(pol)
        if rc is not None:
            newest[rc] = (pol, inp)  # sorted ascending -> most recent dir wins
    rows = []
    for t in targets:
        if t not in newest:
            print(f"  rule_count={t}: NO corpus found")
            continue
        pol, inp = newest[t]
        c = coords(pol, inp)
        c["run_dir"] = pol.parent.parent.name
        rows.append(c)
        print(f"  {t:>5}: matches/KB={c['matches_per_kb']:<8} near/KB={c['near_misses_per_kb']:<7} "
              f"distinct={c['distinct_bodies']:<6} avg_bytes={c['avg_bytes']:<6} div={c['diversity_ratio']}")
    out = REPO_ROOT / "artifacts" / "evidence" / "corpus-density-20260726.json"
    out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
