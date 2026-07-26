#!/usr/bin/env python3
"""ISSUE-005 token-truncation reproduction, both engines, several token lengths.

The runtime truncates a replacement token (observed at 15 chars). ISSUE-005 is
filed against Themis and its repro shows Themis truncating; the deploy probe's
byte-for-byte preview showed the opposite (Themis full, Aergia truncated). This
resolves the attribution with a controlled experiment rather than a guess:

  Deploy one policy whose rules carry tokens of lengths 15, 16, 20, 29 (a distinct
  literal per length), send a document containing each literal to EACH engine, and
  record the exact token each engine emits and its length.

That answers, in one pass: (1) which engine(s) truncate, (2) at what length, and
(3) whether ISSUE-005's Themis attribution holds. Raw JSON per engine per length
is saved as an evidence artifact. Nothing about ISSUE-005 is rewritten from a
guess — only from this table.

Run on nol8-demo (reaches both engines). Restores the starter policy at the end.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LENGTHS = [15, 16, 20, 29]
ENGINES = ("themis", "aergia")
STARTER = REPO_ROOT / "demos" / "policies" / "starter-known-values.nol"


def token_of_length(n: int) -> str:
    """A distinctive bracketed token of exactly n chars: [LEN<nn>XXX…]."""
    body = f"LEN{n:02d}" + "X" * (n - 2 - len(f"LEN{n:02d}"))
    return "[" + body + "]"


def literal_for(n: int) -> str:
    # Distinct, non-overlapping literals (no substring relationships).
    return f"ZZPROBE{n:02d}ZZ"


def call(engine: str, message: str, timeout: float = 20.0) -> dict:
    endpoint = os.environ.get(f"{engine.upper()}_ENDPOINT", "")
    token = os.environ.get(f"{engine.upper()}_TOKEN", "")
    body = json.dumps({"message": message, "jid": 1, "frameId": 1, "last": True}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def deploy(policy: Path, engine: str) -> bool:
    import subprocess
    r = subprocess.run(["validate", "policy", "--file", str(policy), "--target", engine],
                       capture_output=True, timeout=120)
    return r.returncode == 0


def main() -> int:
    stamp = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    work = REPO_ROOT / "demos" / "benchmark" / "datapoint4" / "results"
    work.mkdir(parents=True, exist_ok=True)
    policy = work / "truncation-probe-policy.nol"

    rules = {literal_for(n): token_of_length(n) for n in LENGTHS}
    lines = ["# ISSUE-005 truncation reproduction policy — tokens of varied length.", ""]
    for lit, tok in rules.items():
        lines.append(f'"{lit}" -> "{tok}";')
    policy.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("policy rules (literal -> token, token_len):")
    for lit, tok in rules.items():
        print(f"  {lit} -> {tok}  ({len(tok)})")

    for e in ENGINES:
        ok = deploy(policy, e)
        print(f"deploy {e}: {'OK' if ok else 'FAILED'}")
        if not ok:
            print(f"  (a deploy failure at some length is itself a datapoint for {e})")
    time.sleep(8)

    results: dict[str, list] = {e: [] for e in ENGINES}
    for e in ENGINES:
        for n in LENGTHS:
            lit, tok = literal_for(n), rules[literal_for(n)]
            doc = f"trunc probe: {lit} .end"
            row = {"token_len_sent": n, "literal": lit, "token_sent": tok}
            try:
                raw = call(e, doc)
                out = raw["result"]["message"]
                # Extract the emitted token: everything between the fixed sentinels.
                emitted = out
                if out.startswith("trunc probe: ") and out.endswith(" .end"):
                    emitted = out[len("trunc probe: "):-len(" .end")]
                row.update({"raw_result_message": out, "emitted_token": emitted,
                            "emitted_len": len(emitted),
                            "truncated": emitted != tok, "literal_gone": lit not in out})
            except Exception as exc:  # noqa: BLE001
                row.update({"error": str(exc)[:160]})
            results[e].append(row)

    artifact = REPO_ROOT / "artifacts" / "evidence" / f"issue-005-truncation-{stamp}.json"
    artifact.write_text(json.dumps({
        "stamp": stamp,
        "policy_rules": rules,
        "lengths_tested": LENGTHS,
        "results": results,
    }, indent=2) + "\n", encoding="utf-8")

    print("\n=== TABLE: token length sent -> emitted, per engine ===")
    print("  len-sent  " + "  ".join(f"{e:>30s}" for e in ENGINES))
    for i, n in enumerate(LENGTHS):
        cells = []
        for e in ENGINES:
            r = results[e][i]
            if "error" in r:
                cell = "ERR: " + r["error"][:22]
            else:
                mark = "trunc" if r["truncated"] else "full"
                cell = f"{r['emitted_len']:>2d} ({mark}) {r['emitted_token'][:16]!r}"
            cells.append(f"{cell:>30s}")
        print(f"  {n:>7d}   " + "  ".join(cells))
    print(f"\nraw evidence: {artifact}")

    for e in ENGINES:
        deploy(STARTER, e)
    print("starter policy restored on both engines.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
