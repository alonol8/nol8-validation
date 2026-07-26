#!/usr/bin/env python3
"""Bring-Your-Own-Data POC — the customer's own policy + their own documents,
proven end to end on the live engines.

A load generator is not a POC: a customer evaluating NOL8 wants to answer three
questions with THEIR inputs, not ours —
  1. Does it redact MY data correctly?      -> oracle-verified on their docs
  2. What does it cost at MY scale?          -> ~8-core software tax (efficiency)
  3. Does it hold up at MY volume?           -> load pass on their own corpus

This walks the full pipeline visibly, each stage showing its output:
  ingest -> build policy -> build corpus -> deploy (confirm applied) ->
  correctness (both engines, oracle) -> load (both engines) -> summary.

Everything is deterministic literal replacement (listMatch). Same policy, same
data, same driver to both engines — we report divergence honestly, never rig.

Input layout (an SA drops the customer's files here):
    <byo-dir>/
      values/       one <category>.txt per governed-value list (value per line)
      documents/    the customer's sample docs (*.txt / *.md), or a single *.jsonl
                    of {"message": "..."} records

Usage (via run-byo-poc.sh, which sources the venv + endpoints):
    byo_poc.py --byo-dir sample [--engines themis,aergia] [--skip-load]
               [--concurrency 256] [--duration 15]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

MAX_TOKEN_LENGTH = 15  # runtime truncates tokens past 15 chars (ISSUE-005)
POLICY_RULE = re.compile(r'^\s*"(?P<lit>.*)"\s*->\s*"(?P<tok>.*)"\s*;\s*$')

BAR = "─" * 72


def hr(title: str) -> None:
    print(f"\n{BAR}\n  {title}\n{BAR}")


# ---------------------------------------------------------------- policy build

def _token_for(filename: str, used: set[str]) -> str:
    """Derive a distinct, <=15-char governance token from a category filename.

    'payment_cards.txt' -> '[PAYMENT_CARDS]'. Truncates the slug so the whole
    token (with brackets) fits the 15-char runtime budget, and de-dupes.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "_", Path(filename).stem).strip("_").upper()
    base = slug[: MAX_TOKEN_LENGTH - 2]  # room for the two brackets
    token = f"[{base}]"
    n = 1
    while token in used:
        n += 1
        suffix = str(n)
        base = slug[: MAX_TOKEN_LENGTH - 2 - len(suffix)] + suffix
        token = f"[{base}]"
    used.add(token)
    return token


def load_customer_values(values_dir: Path) -> list[tuple[str, str, list[str]]]:
    """Return [(token, label, values)] for each <category>.txt in the dir."""
    used: set[str] = set()
    cats = []
    for path in sorted(values_dir.glob("*.txt")):
        values = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not values:
            continue
        token = _token_for(path.name, used)
        label = Path(path.name).stem.replace("_", " ").title()
        cats.append((token, label, values))
    return cats


def sanitize(categories):
    """Drop values that would make an UNSAFE policy, reporting each drop, and
    return (safe_categories, dropped). Mirrors build_policy.py's guards but, for
    a customer's raw list, we drop-and-warn instead of refusing the whole run:
      - a value contained in another (ISSUE-004 overlapping-match corruption),
      - exact duplicates across lists.
    Token length/distinctness is already guaranteed by _token_for.
    """
    seen: set[str] = set()
    dropped: list[tuple[str, str]] = []
    # Build the full value set for containment checks.
    all_values = [v for _, _, vs in categories for v in vs]
    safe_cats = []
    for token, label, values in categories:
        kept = []
        for v in values:
            if v in seen:
                dropped.append((v, "duplicate value"))
                continue
            contained_in = next((o for o in all_values if o != v and v in o), None)
            contains = next((i for i in all_values if i != v and i in v), None)
            if contained_in is not None:
                dropped.append((v, f"contained in {contained_in!r} (ISSUE-004)"))
                continue
            if contains is not None:
                # keep the outer, drop is handled when we hit the inner; but if the
                # inner is in a later category we still want to flag the outer only
                # once. Simplest safe choice: drop the OUTER too if it strictly
                # contains another governed value, since overlapping literals are
                # the corruption trap.
                dropped.append((v, f"contains {contains!r} (ISSUE-004)"))
                continue
            seen.add(v)
            kept.append(v)
        if kept:
            safe_cats.append((token, label, kept))
    return safe_cats, dropped


def render_policy(categories) -> str:
    lines = [
        "# BYO customer policy — known governed values (deterministic literal match).",
        "# Generated by byo_poc.py from the customer's values/*.txt.",
        "",
    ]
    for token, label, values in categories:
        lines.append(f"# {label} -> {token}")
        for v in values:
            lines.append(f'"{v.replace(chr(34), chr(92) + chr(34))}" -> "{token}";')
        lines.append("")
    return "\n".join(lines)


def policy_pairs(path: Path) -> list[tuple[str, str]]:
    pairs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = POLICY_RULE.match(line)
        if m:
            pairs.append((m.group("lit"), m.group("tok")))
    return pairs


# ---------------------------------------------------------------- corpus build

def load_documents(docs_dir: Path) -> list[str]:
    """Return the customer's documents as message strings. Accepts a single
    *.jsonl of {message} records, or a folder of *.txt / *.md files."""
    docs: list[str] = []
    jsonls = sorted(docs_dir.glob("*.jsonl"))
    if jsonls:
        for jf in jsonls:
            for line in jf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict) and "message" in rec:
                        docs.append(str(rec["message"]))
                except json.JSONDecodeError:
                    continue
    for tf in sorted(docs_dir.glob("*.txt")) + sorted(docs_dir.glob("*.md")):
        text = tf.read_text(encoding="utf-8").strip()
        if text:
            docs.append(text)
    return docs


def write_corpus(docs: list[str], out: Path) -> None:
    with out.open("w", encoding="utf-8") as fh:
        for d in docs:
            fh.write(json.dumps({"message": d}) + "\n")


# ---------------------------------------------------------------- engine calls

def call_process(endpoint: str, token: str, message: str, timeout: float = 20.0) -> str:
    body = json.dumps({"message": message, "jid": 1, "frameId": 1, "last": True}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["result"]["message"]


def deploy(policy: Path, engine: str, env: dict) -> bool:
    r = subprocess.run(
        ["validate", "policy", "--file", str(policy), "--target", engine],
        env=env, capture_output=True, timeout=180)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-500:] + "\n")
    return r.returncode == 0


# ---------------------------------------------------------------- endpoints

ENGINES = {
    "themis": {"label": "Themis (FPGA)", "endpoint_env": ("THEMIS_PROCESS_ENDPOINT", "THEMIS_ENDPOINT")},
    "aergia": {"label": "Aergia (RE2 software)", "endpoint_env": ("AERGIA_PROCESS_ENDPOINT", "AERGIA_ENDPOINT")},
}


def endpoint_for(engine: str) -> str:
    for var in ENGINES[engine]["endpoint_env"]:
        v = os.environ.get(var, "").strip()
        if v:
            return v
    return ""


# ---------------------------------------------------------------- stages

def stage_correctness(docs, pairs, engines) -> dict:
    """Run every doc through each engine, oracle-verify, and check both engines
    agree. Returns aggregates + per-doc rows."""
    def norm(s):
        return re.sub(r"\s+", " ", s).strip()

    rows = []
    totals = {e: {"verified": 0, "in_scope": 0} for e in engines}
    parity_ok = 0
    parity_total = 0
    for i, original in enumerate(docs):
        in_scope = [(l, t) for l, t in pairs if l and l in original]
        near = [(l, t) for l, t in pairs if l and l not in original and norm(l) in norm(original)]
        msg_bytes = len(original.encode("utf-8"))
        occurrences = sum(original.count(l) for l, _ in in_scope)
        density = occurrences / (msg_bytes / 1024) if msg_bytes else 0.0
        outputs = {}
        row_engines = {}
        for e in engines:
            try:
                processed = call_process(endpoint_for(e), os.environ.get(f"{e.upper()}_TOKEN", ""), original)
            except Exception as exc:  # noqa: BLE001 — report, don't crash the POC
                row_engines[e] = {"error": str(exc)[:120]}
                continue
            outputs[e] = processed
            checks = [(l in original and l not in processed and t in processed) for l, t in in_scope]
            verified = sum(1 for c in checks if c)
            totals[e]["verified"] += verified
            totals[e]["in_scope"] += len(in_scope)
            row_engines[e] = {"verified": verified, "in_scope": len(in_scope), "ok": verified == len(in_scope)}
        if len(outputs) == 2:
            parity_total += 1
            if len(set(outputs.values())) == 1:
                parity_ok += 1
        rows.append({"doc": i + 1, "bytes": msg_bytes, "in_scope": len(in_scope),
                     "density": round(density, 1), "near_misses": len(near),
                     "engines": row_engines,
                     "identical": len(outputs) == 2 and len(set(outputs.values())) == 1})
    return {"rows": rows, "totals": totals, "parity_ok": parity_ok, "parity_total": parity_total}


def run_driver(driver: Path, engine: str, corpus: Path, concurrency: int,
               duration: int, warmup: int, env: dict) -> dict | None:
    out_csv = f"/tmp/byo_load_{engine}.csv"
    r = subprocess.run(
        [str(driver), "--engine", engine, "--label", engine, "--input", str(corpus),
         "--concurrency", str(concurrency), "--payloads", "small,medium,large",
         "--warmup", str(warmup), "--duration", str(duration),
         "--cap-small", "20000", "--cap-medium", "8000", "--cap-large", "4000",
         "--output", out_csv],
        env=env, capture_output=True, timeout=(warmup + duration) * 4 + 60)
    print(r.stdout.decode("utf-8", "replace").rstrip())
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-500:] + "\n")
        return None
    lines = Path(out_csv).read_text(encoding="utf-8").strip().splitlines()
    out = {"cells": []}
    for ln in lines[1:]:
        c = ln.split(",")
        out["cells"].append({"payload": c[2], "rps": round(float(c[8])),
                             "p99": float(c[12]), "errors": int(c[7]), "mib_s": round(float(c[9]), 1)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--byo-dir", required=True, help="dir with values/ and documents/")
    ap.add_argument("--engines", default="themis,aergia")
    ap.add_argument("--skip-load", action="store_true", help="correctness + cost only, no load pass")
    ap.add_argument("--concurrency", type=int, default=256)
    ap.add_argument("--duration", type=int, default=15)
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--settle", type=int, default=8,
                    help="seconds to wait after deploy for the policy to propagate to the data plane")
    ap.add_argument("--work-dir", default="", help="where to write policy/corpus (default: <byo-dir>/generated)")
    args = ap.parse_args()

    byo = Path(args.byo_dir)
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    work = Path(args.work_dir) if args.work_dir else byo / "generated"
    work.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for e in engines:
        env[f"{e.upper()}_ENDPOINT"] = endpoint_for(e)

    print(f"\n{'='*72}\n  NOL8 — Bring-Your-Own-Data POC\n  customer input: {byo}\n{'='*72}")

    # 1) build policy from their values ------------------------------------
    hr("STEP 1 · Build the policy from the customer's governed values")
    vdir = byo / "values"
    if not vdir.is_dir():
        print(f"  ✗ no values/ dir under {byo}"); return 2
    cats = load_customer_values(vdir)
    cats, dropped = sanitize(cats)
    if not cats:
        print("  ✗ no usable governed values found"); return 2
    policy = work / "byo-policy.nol"
    policy.write_text(render_policy(cats), encoding="utf-8")
    rule_count = sum(len(v) for _, _, v in cats)
    print(f"  Built {policy} — {rule_count} rules across {len(cats)} categories:")
    for token, label, values in cats:
        print(f"    {token:16s} {label:24s} {len(values):>5d} values")
    if dropped:
        print(f"  ⚠  dropped {len(dropped)} unsafe value(s) (kept the policy safe to deploy):")
        for v, why in dropped[:8]:
            print(f"       • {v!r}: {why}")
    print("  ── policy sample ──")
    for ln in policy.read_text(encoding="utf-8").splitlines()[3:9]:
        print(f"    {ln}")

    # 2) build corpus from their documents --------------------------------
    hr("STEP 2 · Build the corpus from the customer's documents")
    ddir = byo / "documents"
    if not ddir.is_dir():
        print(f"  ✗ no documents/ dir under {byo}"); return 2
    docs = load_documents(ddir)
    if not docs:
        print("  ✗ no documents found"); return 2
    corpus = work / "byo-input.jsonl"
    write_corpus(docs, corpus)
    avg = sum(len(d.encode()) for d in docs) // len(docs)
    print(f"  Built {corpus} — {len(docs)} documents, avg {avg} bytes.")
    print("  ── document sample (first, truncated) ──")
    print("    " + docs[0][:240].replace("\n", "\n    "))

    # 3) deploy -----------------------------------------------------------
    hr("STEP 3 · Deploy the policy to the engines (confirm applied)")
    for e in engines:
        ok = deploy(policy, e, env)
        print(f"  {'✓' if ok else '✗'} {ENGINES[e]['label']:24s} deploy {'APPLIED' if ok else 'FAILED'}")
        if not ok:
            print("     (a deploy failure here is usually the policy exceeding a size/limit)")
            return 3
    # The control plane returns "applied" before the data plane has finished
    # loading the new policy; give it a moment so the first requests don't hit
    # the previous policy (which would show as false "not redacted" misses).
    if args.settle > 0:
        print(f"  … waiting {args.settle}s for the policy to propagate to both data planes")
        time.sleep(args.settle)

    # 4) correctness ------------------------------------------------------
    hr("STEP 4 · Correctness on the customer's data (oracle-verified, both engines)")
    pairs = policy_pairs(policy)
    cres = stage_correctness(docs, pairs, engines)
    print(f"  {'doc':>4s} {'bytes':>7s} {'in-scope':>9s} {'matches/KB':>11s}  " +
          "  ".join(f"{ENGINES[e]['label'].split()[0]:>8s}" for e in engines) + "   identical")
    for r in cres["rows"]:
        cells = []
        for e in engines:
            ev = r["engines"].get(e, {})
            cells.append(f"{ev.get('verified','-')}/{ev.get('in_scope','-')}" if "error" not in ev else "ERR")
        idc = "✓" if r["identical"] else ("—" if len(engines) < 2 else "✗")
        print(f"  {r['doc']:>4d} {r['bytes']:>7d} {r['in_scope']:>9d} {r['density']:>11.1f}  " +
              "  ".join(f"{c:>8s}" for c in cells) + f"   {idc}")
    for e in engines:
        t = cres["totals"][e]
        pct = (100.0 * t["verified"] / t["in_scope"]) if t["in_scope"] else 0.0
        print(f"  {ENGINES[e]['label']}: {t['verified']}/{t['in_scope']} governed values verified ({pct:.1f}%).")
    if len(engines) == 2:
        print(f"  Output parity: {cres['parity_ok']}/{cres['parity_total']} documents identical across both engines.")

    # 5) load -------------------------------------------------------------
    if not args.skip_load:
        hr("STEP 5 · Load — the customer's corpus at volume (both engines)")
        driver = Path("demos/benchmark/datapoint4/results/dp4driver")
        if not driver.exists():
            print("  ⚠  load driver not built; skipping load. (build: cd demos/benchmark/datapoint4/go && go build -o ../results/dp4driver .)")
        else:
            if len(docs) < 2000:
                print(f"  ⚠  only {len(docs)} distinct documents — a small working set can flatter the")
                print("      software engine (it serves repeats warm from CPU cache). For a load number")
                print("      that's cache-fair, supply a few thousand representative documents.")
            load = {}
            for e in engines:
                print(f"  ── driving {ENGINES[e]['label']} (conc {args.concurrency}) ──")
                load[e] = run_driver(driver, e, corpus, args.concurrency, args.duration, args.warmup, env)
            print(f"\n  {'engine':24s} {'payload':8s} {'req/s':>9s} {'MB/s':>8s} {'p99 ms':>8s} {'errors':>7s}")
            for e in engines:
                if not load.get(e):
                    print(f"  {ENGINES[e]['label']:24s} (no result)"); continue
                for c in load[e]["cells"]:
                    print(f"  {ENGINES[e]['label']:24s} {c['payload']:8s} {c['rps']:>9d} {c['mib_s']:>8.1f} {c['p99']:>8.1f} {c['errors']:>7d}")
            # ratio on small payload if both present
            if len(engines) == 2 and all(load.get(e) for e in engines):
                def small_rps(e):
                    return next((c["rps"] for c in load[e]["cells"] if c["payload"] == "small"), 0)
                a, b = small_rps(engines[0]), small_rps(engines[1])
                if a and b:
                    hi, lo = (a, b) if a >= b else (b, a)
                    lead = engines[0] if a >= b else engines[1]
                    print(f"\n  Small-payload throughput on the customer's data: "
                          f"{ENGINES[lead]['label']} leads {hi/lo:.2f}× ({hi:,} vs {lo:,} req/s).")

    # 6) summary ----------------------------------------------------------
    hr("POC SUMMARY — the customer's three questions, on the customer's data")
    okc = all(cres["totals"][e]["verified"] == cres["totals"][e]["in_scope"] for e in engines)
    print(f"  1. Redacts MY data correctly?   {'✓ yes' if okc else '✗ see mismatches above'} "
          f"— oracle-verified against the customer's own policy"
          + (f"; {cres['parity_ok']}/{cres['parity_total']} identical on both engines" if len(engines) == 2 else ""))
    print(f"  2. Costs what at MY scale?      the FPGA does the matching in silicon — ~8 CPU cores")
    print(f"                                  the software path burns on the RE2 lexers "
          f"(run efficiency-demo.sh for live cores).")
    if not args.skip_load:
        print(f"  3. Holds up at MY volume?       load pass above, on the customer's own corpus.")
    print(f"\n  Artifacts: {policy}  |  {corpus}\n")
    return 0 if okc else 1


if __name__ == "__main__":
    sys.exit(main())
