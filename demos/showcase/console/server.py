#!/usr/bin/env python3
"""NOL8 Live Demo Console — a dependency-free local web app to drive the demo.

Runs on the box that reaches the engines (EC2 `nol8-demo`). Serves a single-page
console and a small JSON API that calls the real Argus Data API (`/v1/process`)
and verifies the result against the deployed policy. No third-party packages, no
Grafana — stdlib only, one file you can read end to end.

    source .venv/bin/activate            # for `validate` on PATH (policy deploy)
    set -a; source config/demo.env; source .env; set +a
    python demos/showcase/console/server.py           # then browse via SSH tunnel

Endpoints:
    GET  /                     the console page
    GET  /assets/*             brand fonts + logo (served from demos/benchmark/brand)
    GET  /api/scenarios        the three use-case messages
    GET  /api/efficiency       measured cores contrast (poll-mode → constant)
    POST /api/process          {message, engine} -> before/after/oracle/density
"""
from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[3]          # repo root
sys.path.insert(0, str(ROOT))
# The correctness step adjudicates engine output against the framework's
# independent oracle (byte-for-byte), the SAME one the CLI POC and verify-oracle
# use — not a substring check.
from framework.policy.oracle import (  # noqa: E402
    LEFTMOST_LONGEST, OVERLAP_AWARE, adjudicate, build_matcher, parse_policy, substring_pass,
)
HERE = Path(__file__).resolve().parent
BRAND = ROOT / "demos" / "benchmark" / "brand"
POLICY = ROOT / "demos" / "policies" / "starter-known-values.nol"
SCEN = HERE.parent / "scenarios"
PORT = int(os.environ.get("CONSOLE_PORT", "8770"))
# Bind localhost only by default. The console has no auth and CAN deploy policies
# (a deploy replaces the whole ruleset, ISSUE-002), so anyone reachable on this
# port could wipe the tenant — do not expose it on all interfaces. Reach it via
# the SSH tunnel: `ssh -f -N -L 8770:localhost:8770 nol8-demo`. Set
# CONSOLE_HOST=0.0.0.0 explicitly only when you intend to expose it over the VPN.
HOST = os.environ.get("CONSOLE_HOST", "127.0.0.1")


def lan_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"

ENGINES = {
    "themis": {"label": "Themis · FPGA", "endpoint": os.environ.get("THEMIS_PROCESS_ENDPOINT", ""),
               "token": os.environ.get("THEMIS_TOKEN", "")},
    "aergia": {"label": "Aergia · RE2 software", "endpoint": os.environ.get("AERGIA_PROCESS_ENDPOINT", ""),
               "token": os.environ.get("AERGIA_TOKEN", "")},
}

# Efficiency numbers: the SINGLE SOURCE OF TRUTH is
# artifacts/evidence/efficiency-constants.json (cores MEASURED with repeats — see
# efficiency-*-20260726.csv). Cores + throughput are loaded from there; the console
# DERIVES cores/1k and the ratio for display so there is no hardcoded copy to drift.
# The authoritative ratio in the JSON is null until the under-load confirmation
# (findings 009 item 5); the derived display value is flagged provisional until then.
def _load_efficiency():
    c = json.loads((ROOT / "artifacts" / "evidence" / "efficiency-constants.json").read_text(encoding="utf-8"))
    eff = {}
    for e in ("themis", "aergia"):
        rps = c["throughput_rps"][e]
        eff[e] = {"apollo": c[e]["apollo"], "matching": c[e]["matching"],
                  "total": c[e]["total"], "box_cores": c[e]["box_cores"], "rps": rps,
                  "matching_label": c[e]["matching_label"],
                  "cores_per_1k": round(c[e]["total"] / (rps / 1000.0), 3)}
    eff["tax_cores"] = c["tax_cores"]
    eff["ratio"] = round(eff["aergia"]["cores_per_1k"] / eff["themis"]["cores_per_1k"], 2)
    eff["cores_load_state"] = c["cores_load_state"]
    eff["provisional"] = c.get("ratio") is None  # true until item 5 confirms under load
    return eff

EFFICIENCY = _load_efficiency()

DRIVER = ROOT / "demos" / "benchmark" / "datapoint4" / "results" / "dp4driver"

# Bring-Your-Own-Data POC scratch: the policy + corpus built from customer input
# pasted into the console (kept out of git; regenerated per build).
BYO_WORK = HERE / "byo_work"
BYO_POLICY = BYO_WORK / "byo-policy.nol"
BYO_CORPUS = BYO_WORK / "byo-input.jsonl"
MAX_TOKEN_LENGTH = 15  # runtime truncates tokens past 15 chars (ISSUE-005)

# Which policy is live on the engines. The built-in cards (process/batch) oracle
# against the STARTER policy, so if a BYO or scale run swapped it, they must re-sync
# it first — otherwise they show 0 redacted (right engine, wrong policy).
_STATE = {"policy": "starter"}


def find_corpus() -> str | None:
    runs = sorted((ROOT / "artifacts" / "runs").glob("*/generated/input.jsonl"), reverse=True)
    return str(runs[0]) if runs else None


def _matched_run(max_rules=8000):
    """Newest run dir with a corpus AND a *deployable* policy (≤ the ~8k deploy
    ceiling — a bigger policy fails to deploy on Themis, leaving an asymmetric setup)."""
    for pol in sorted((ROOT / "artifacts" / "runs").glob("*/generated/scale-policy.nol"), reverse=True):
        if not (pol.parent / "input.jsonl").exists():
            continue
        rules = sum(1 for ln in pol.read_text(encoding="utf-8").splitlines() if "->" in ln)
        if rules <= max_rules:
            return pol.parent / "input.jsonl", pol, rules
    return None, None, 0


def _deploy(env, policy, engine) -> bool:
    r = subprocess.run(["validate", "policy", "--file", str(policy), "--target", engine],
                       env=env, capture_output=True, timeout=120)
    return r.returncode == 0


def scale(engines=("themis", "aergia"), payload="small", concurrency=256, duration=8, warmup=3) -> dict:
    """Honest sustained-load burst: deploy the corpus's OWN policy to both engines
    (apples-to-apples — a mismatched tiny policy makes software look faster on clean
    text), drive at DP4 conditions, then RESTORE the demo policy so redaction still works.
    Absolute throughput is a live point-in-time number on a shared host; the FPGA's lead
    and its CPU cost are the stable facts."""
    corpus, policy, rules = _matched_run()
    if not DRIVER.exists() or not corpus:
        raise RuntimeError("load driver or a matched, deployable corpus+policy not available")
    env = os.environ.copy()
    env["THEMIS_ENDPOINT"] = ENGINES["themis"]["endpoint"]
    env["AERGIA_ENDPOINT"] = ENGINES["aergia"]["endpoint"]
    try:
        for eng in engines:
            if not _deploy(env, policy, eng):
                raise RuntimeError(f"{rules}-rule policy failed to deploy to {eng} — aborting to avoid a mismatched run")
        time.sleep(6)
        out = {"policy_rules": rules, "concurrency": concurrency,
               "note": "live burst · matched enterprise policy · absolute varies with shared-host load"}
        for eng in engines:
            csv = f"/tmp/scale_{eng}.csv"
            subprocess.run(
                [str(DRIVER), "--engine", eng, "--label", eng, "--input", str(corpus),
                 "--concurrency", str(concurrency), "--payloads", payload,
                 "--warmup", str(warmup), "--duration", str(duration),
                 "--cap-small", "4000", "--cap-medium", "4000", "--cap-large", "4000",
                 "--output", csv],
                env=env, capture_output=True, timeout=warmup + duration + 40)
            r = Path(csv).read_text(encoding="utf-8").strip().splitlines()[-1].split(",")
            out[eng] = {
                "label": ENGINES[eng]["label"],
                "rps": round(float(r[8])), "mib_s": round(float(r[9]), 1),
                "p50": float(r[10]), "p99": float(r[12]), "mean": float(r[16]),
                "completed": int(r[6]), "errors": int(r[7]),
                "duration": float(r[5]), "avg_bytes": int(float(r[4])),
                "host_cores_total": EFFICIENCY[eng]["total"], "box_cores": EFFICIENCY[eng]["box_cores"],
            }
        return out
    finally:
        # Always put the human-readable demo policy back for the redaction console.
        for eng in engines:
            _deploy(env, POLICY, eng)
        _STATE["policy"] = "starter"

POLICY_RULE = re.compile(r'^\s*"(?P<lit>.*)"\s*->\s*"(?P<tok>.*)"\s*;\s*$')


def policy_pairs() -> list[tuple[str, str]]:
    pairs = []
    for line in POLICY.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = POLICY_RULE.match(line)
        if m:
            pairs.append((m.group("lit"), m.group("tok")))
    return pairs


PAIRS = policy_pairs()

CATALOG_FILE = HERE / "catalog.json"
CATALOG = json.loads(CATALOG_FILE.read_text(encoding="utf-8")) if CATALOG_FILE.exists() else []


def stats(xs: list) -> dict:
    if not xs:
        return {"p50": 0, "p95": 0, "mean": 0, "min": 0, "max": 0}
    s = sorted(xs)
    n = len(s)
    q = lambda p: s[min(n - 1, int(p * n))]
    return {"p50": round(q(0.5), 2), "p95": round(q(0.95), 2),
            "mean": round(sum(s) / n, 2), "min": round(s[0], 2), "max": round(s[-1], 2)}


def scenarios() -> dict:
    out = {}
    names = {"pre-embedding": "01-pre-embedding.txt",
             "pre-post-inference": "02-pre-post-inference.txt",
             "agent-to-agent": "03-agent-to-agent.txt"}
    for key, fn in names.items():
        p = SCEN / fn
        out[key] = p.read_text(encoding="utf-8") if p.exists() else ""
    return out


def call_process(engine: str, message: str, timeout: float = 15.0) -> str:
    eng = ENGINES[engine]
    body = json.dumps({"message": message, "jid": 1, "frameId": 1, "last": True}).encode("utf-8")
    req = urllib.request.Request(eng["endpoint"], data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if eng["token"]:
        req.add_header("Authorization", f"Bearer {eng['token']}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))["result"]["message"]


def ensure_starter():
    """Re-deploy the starter policy if a BYO/scale run swapped it out, so the built-in
    demo cards (which verify against the starter values) don't show a false 0/N.
    No-op when the starter is already live."""
    if _STATE["policy"] == "starter":
        return
    for eng in ("themis", "aergia"):
        try:
            subprocess.run(["validate", "policy", "--file", str(POLICY), "--target", eng],
                           capture_output=True, timeout=60)
        except Exception:  # noqa: BLE001
            pass
    time.sleep(6)  # let the data plane load it before we verify
    _STATE["policy"] = "starter"


def process(engine: str, message: str) -> dict:
    ensure_starter()
    expected = [(lit, tok) for lit, tok in PAIRS if lit and lit in message]
    t0 = time.perf_counter()
    processed = call_process(engine, message)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    checks = [{"value": lit, "token": tok,
               "ok": (lit not in processed) and (tok in processed)}
              for lit, tok in expected]
    norm = lambda s: re.sub(r"\s+", " ", s).strip()
    nmsg = norm(message)
    near = [{"value": lit, "token": tok} for lit, tok in PAIRS
            if lit and lit not in message and norm(lit) in nmsg]
    msg_bytes = len(message.encode("utf-8"))
    occ = sum(message.count(lit) for lit, _ in expected)
    return {
        "engine": engine, "engine_label": ENGINES[engine]["label"],
        "before": message, "after": processed,
        "checks": checks, "verified": sum(1 for c in checks if c["ok"]),
        "in_scope": len(checks), "near_misses": near,
        "message_bytes": msg_bytes, "response_bytes": len(processed.encode("utf-8")),
        "match_occurrences": occ,
        "matches_per_kb": round(occ / (msg_bytes / 1024), 2) if msg_bytes else 0.0,
        "latency_ms": round(latency_ms, 2),
    }


def batch(engines=("themis", "aergia")) -> dict:
    """Run the whole catalog through each engine; return per-engine aggregates + rows."""
    ensure_starter()
    out = {}
    for eng in engines:
        rows, lat = [], []
        for entry in CATALOG:
            r = process(eng, entry["text"])
            rows.append({"id": entry["id"], "title": entry["title"], "usecase": entry["usecase"],
                         "in_scope": r["in_scope"], "verified": r["verified"],
                         "ok": r["verified"] == r["in_scope"], "latency_ms": r["latency_ms"],
                         "matches": r["match_occurrences"], "bytes": r["message_bytes"],
                         "density": r["matches_per_kb"]})
            lat.append(r["latency_ms"])
        docs = len(rows)
        bytes_total = sum(x["bytes"] for x in rows)
        matches = sum(x["matches"] for x in rows)
        wall = sum(lat)
        out[eng] = {
            "label": ENGINES[eng]["label"],
            "agg": {
                "docs": docs,
                "in_scope": sum(x["in_scope"] for x in rows),
                "verified": sum(x["verified"] for x in rows),
                "docs_ok": sum(1 for x in rows if x["ok"]),
                "matches": matches, "bytes": bytes_total,
                "latency": stats(lat), "wall_ms": round(wall, 1),
                "docs_per_s": round(docs / (wall / 1000), 0) if wall else 0,
                "density": round(matches / (bytes_total / 1024), 2) if bytes_total else 0,
            },
            "rows": rows,
        }
    return out


def deploy_policy() -> dict:
    """Best-effort deploy of the known-values policy to both engines on startup."""
    status = {}
    for eng in ("themis", "aergia"):
        try:
            r = subprocess.run(["validate", "policy", "--file", str(POLICY), "--target", eng],
                               capture_output=True, timeout=60)
            status[eng] = "ok" if r.returncode == 0 else "failed"
        except Exception as exc:  # noqa: BLE001
            status[eng] = f"error: {exc}"
    return status


# ---- Bring-Your-Own-Data POC ------------------------------------------------
# A load generator is not a POC. This lets an SA paste a customer's own governed
# values + documents and prove, live: (1) correct redaction on THEIR data,
# adjudicated BYTE-FOR-BYTE against the framework's independent oracle on both
# engines (not a substring check); (2) the CPU-cost story; (3) throughput on
# THEIR corpus. Mirrors demos/showcase/byo-poc/byo_poc.py, driven from the UI.

def _byo_token(name: str, used: set) -> str:
    """Distinct, <=15-char governance token from a category name (ISSUE-005)."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    base = slug[: MAX_TOKEN_LENGTH - 2]
    token = f"[{base}]"
    n = 1
    while token in used:
        n += 1
        s = str(n)
        token = f"[{slug[: MAX_TOKEN_LENGTH - 2 - len(s)] + s}]"
    used.add(token)
    return token


def _byo_sanitize(cats):
    """Drop values that would make an unsafe policy (ISSUE-004 containment,
    duplicates), reporting each. Keeps the deployed policy safe."""
    seen, dropped, safe = set(), [], []
    allv = [v for _, _, vs in cats for v in vs]
    for token, label, values in cats:
        kept = []
        for v in values:
            if v in seen:
                dropped.append((v, "duplicate value")); continue
            ci = next((o for o in allv if o != v and v in o), None)
            cc = next((i for i in allv if i != v and i in v), None)
            if ci is not None:
                dropped.append((v, f"contained in {ci!r} (ISSUE-004)")); continue
            if cc is not None:
                dropped.append((v, f"contains {cc!r} (ISSUE-004)")); continue
            seen.add(v); kept.append(v)
        if kept:
            safe.append((token, label, kept))
    return safe, dropped


def _byo_render(cats) -> str:
    lines = ["# BYO customer policy — deterministic literal match (built in the console).", ""]
    for token, label, values in cats:
        lines.append(f"# {label} -> {token}")
        for v in values:
            lines.append(f'"{v.replace(chr(34), chr(92) + chr(34))}" -> "{token}";')
        lines.append("")
    return "\n".join(lines)


def _byo_docs():
    docs = []
    if not BYO_CORPUS.exists():
        return docs
    for line in BYO_CORPUS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            docs.append(json.loads(line)["message"])
        except Exception:  # noqa: BLE001
            pass
    return docs


def byo_build(payload: dict) -> dict:
    used, cats = set(), []
    for c in payload.get("categories", []):
        name = (c.get("name") or "").strip()
        raw = c.get("values")
        if isinstance(raw, str):
            values = [v.strip() for v in raw.splitlines() if v.strip()]
        else:
            values = [str(v).strip() for v in (raw or []) if str(v).strip()]
        if name and values:
            cats.append((_byo_token(name, used), name, values))
    cats, dropped = _byo_sanitize(cats)
    if not cats:
        return {"error": "no usable governed values — add at least one category with values"}
    BYO_WORK.mkdir(parents=True, exist_ok=True)
    BYO_POLICY.write_text(_byo_render(cats), encoding="utf-8")
    docs = [d for d in ((s or "").strip() for s in payload.get("documents", [])) if d]
    with BYO_CORPUS.open("w", encoding="utf-8") as fh:
        for d in docs:
            fh.write(json.dumps({"message": d}) + "\n")
    avg = sum(len(d.encode()) for d in docs) // len(docs) if docs else 0
    preview = [ln for ln in BYO_POLICY.read_text(encoding="utf-8").splitlines()[2:] if ln][:10]
    return {
        "rule_count": sum(len(v) for _, _, v in cats),
        "categories": [{"token": t, "label": l, "count": len(v)} for t, l, v in cats],
        "dropped": [{"value": v, "why": w} for v, w in dropped],
        "policy_preview": preview,
        "docs": len(docs), "avg_bytes": avg,
        "doc_sample": docs[0][:400] if docs else "",
    }


def byo_deploy(settle: int = 8) -> dict:
    if not BYO_POLICY.exists():
        return {"error": "build a policy first"}
    status = {}
    for eng in ("themis", "aergia"):
        try:
            r = subprocess.run(["validate", "policy", "--file", str(BYO_POLICY), "--target", eng],
                               capture_output=True, timeout=180)
            status[eng] = "applied" if r.returncode == 0 else "failed"
        except Exception as exc:  # noqa: BLE001
            status[eng] = f"error: {exc}"
    _STATE["policy"] = "byo"  # starter no longer live — built-in cards will re-sync it
    ok = all(v == "applied" for v in status.values())
    if ok:
        time.sleep(settle)  # let the data plane load the policy before we verify
    return {"status": {e: {"state": s, "label": ENGINES[e]["label"]} for e, s in status.items()},
            "settled": settle if ok else 0}


def _byo_new_conn(engine):
    u = urlparse(ENGINES[engine]["endpoint"])
    return http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=25), (u.path or "/")


def _verify_engine(engine, idxs, docs):
    """Verify all sampled docs through ONE engine on ONE reused keep-alive connection.
    This is the pattern the software engine tolerates: sequential on a single reused
    connection is reliable, whereas many parallel connections make it shed requests /
    stall. The two engines run on separate threads (see byo_correctness) so the fast
    one isn't held up by the slow one. Per-doc: up to 3 attempts with a small backoff.
    Returns {doc_index: processed_message | Exception}."""
    hdr = {"Content-Type": "application/json"}
    if ENGINES[engine]["token"]:
        hdr["Authorization"] = "Bearer " + ENGINES[engine]["token"]
    conn, path = _byo_new_conn(engine)
    res = {}
    for i in idxs:
        body = json.dumps({"message": docs[i], "jid": 1, "frameId": 1, "last": True})
        last = None
        for attempt in range(3):
            if attempt:
                time.sleep(0.3 * attempt)
            try:
                conn.request("POST", path, body=body, headers=hdr)
                resp = conn.getresponse()
                data = resp.read()
                if resp.status < 200 or resp.status >= 300:
                    raise RuntimeError(f"status {resp.status}")
                res[i] = json.loads(data)["result"]["message"]
                last = None
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
                conn, path = _byo_new_conn(engine)  # fresh conn for the retry
        if last is not None:
            res[i] = last
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass
    return res


def byo_correctness(engines=("themis", "aergia"), limit=12) -> dict:
    if not BYO_POLICY.exists() or not BYO_CORPUS.exists():
        return {"error": "build + deploy first"}
    try:
        rules = parse_policy(BYO_POLICY)
    except ValueError as exc:
        return {"error": f"policy parse: {exc}"}
    matcher = build_matcher(rules)
    docs = _byo_docs()
    total = len(docs)
    # Verify a representative, evenly-spaced SAMPLE live (default `limit`). The
    # software engine has intermittent multi-second stalls that make verifying a
    # large corpus live slow and flaky — so we prove correctness on a spread of
    # their documents here, and drive the FULL corpus in the load step (the Go
    # driver handles the concurrency cleanly). limit=0 verifies everything.
    if limit and total > limit:
        idxs = sorted(set(round(k * (total - 1) / (limit - 1)) for k in range(limit)))
    else:
        idxs = list(range(total))
    # One thread per engine, each sequential on a single reused connection (reliable
    # for the flaky software engine); the two engines run concurrently so the fast
    # one isn't blocked by the slow one.
    out = {}
    if idxs:
        with ThreadPoolExecutor(max_workers=max(1, len(engines))) as ex:
            futs = {ex.submit(_verify_engine, e, idxs, docs): e for e in engines}
            for f, e in futs.items():
                for i, v in f.result().items():
                    out[(i, e)] = v
    EXCERPT = 160  # customer text: keep only enough to show a defect, never the whole doc
    rows = []
    # `exact` = correct against EITHER contract (kept name for UI compatibility);
    # the contract counters identify which one each engine reproduced on overlaps.
    totals = {e: {"exact": 0, "docs": 0, "overlap_docs": 0,
                  LEFTMOST_LONGEST: 0, OVERLAP_AWARE: 0} for e in engines}
    disagreements = []  # substring PASSED but oracle FAILED (the old console's blind spot)
    parity_ok = parity_total = 0
    for i in idxs:
        original = docs[i]
        substr_pairs = [(l, t) for l, t in rules.items() if l in original]
        in_scope = len(substr_pairs)
        occ = sum(original.count(l) for l, _ in substr_pairs)
        mb = len(original.encode("utf-8"))
        outs, reng = {}, {}
        for e in engines:
            r = out.get((i, e))
            if r is None or isinstance(r, Exception):
                reng[e] = {"error": (str(r)[:120] if r else "no result")}; continue
            processed = r
            outs[e] = processed
            # Accept EITHER contract byte-for-byte (Themis: every-match-fires,
            # Aergia: one-byte-one-match). Both are correct; a single-contract
            # check would falsely fail Themis on any overlapping policy.
            adj = adjudicate(original, processed, matcher, rules)
            totals[e]["docs"] += 1
            totals[e]["exact"] += 1 if adj.correct else 0
            reproduced = ""
            if adj.has_overlap:
                totals[e]["overlap_docs"] += 1
                if adj.correct:
                    for name in adj.contracts:  # exactly one on an overlap doc — it names the engine
                        totals[e][name] += 1
                        reproduced = name
            if substring_pass(processed, substr_pairs) and not adj.correct:
                disagreements.append({"doc": i + 1, "engine": e, "label": ENGINES[e]["label"],
                                      "oracle": adj.expected[OVERLAP_AWARE][:EXCERPT],
                                      "engine_out": processed[:EXCERPT]})
            reng[e] = {"exact": adj.correct, "in_scope": in_scope,
                       "has_overlap": adj.has_overlap, "reproduced": reproduced}
        if len(outs) == 2:
            parity_total += 1
            parity_ok += 1 if len(set(outs.values())) == 1 else 0
        rows.append({"doc": i + 1, "bytes": mb, "in_scope": in_scope,
                     "density": round(occ / (mb / 1024), 1) if mb else 0.0,
                     "engines": reng,
                     "identical": len(outs) == 2 and len(set(outs.values())) == 1})
    # Loud finding: an engine that reproduced BOTH contracts across documents.
    mixed = {e: (totals[e][LEFTMOST_LONGEST] > 0 and totals[e][OVERLAP_AWARE] > 0) for e in engines}
    return {
        "rows": rows,
        "totals": {e: {"label": ENGINES[e]["label"], "exact": totals[e]["exact"],
                       "docs": totals[e]["docs"], "overlap_docs": totals[e]["overlap_docs"],
                       "every_match": totals[e][OVERLAP_AWARE],
                       "one_byte_one": totals[e][LEFTMOST_LONGEST]} for e in engines},
        "parity_ok": parity_ok, "parity_total": parity_total,
        "disagreements": disagreements, "mixed": mixed,
        "sampled": len(idxs), "total": total,
    }


def byo_load(concurrency: int = 256, duration: int = 10, warmup: int = 5,
             engines=("themis", "aergia")) -> dict:
    if not DRIVER.exists():
        return {"error": "load driver not built"}
    if not BYO_CORPUS.exists():
        return {"error": "build + deploy first"}
    env = os.environ.copy()
    env["THEMIS_ENDPOINT"] = ENGINES["themis"]["endpoint"]
    env["AERGIA_ENDPOINT"] = ENGINES["aergia"]["endpoint"]
    docs = _byo_docs()
    res = {}
    for e in engines:
        csv = f"/tmp/byo_console_{e}.csv"
        try:
            r = subprocess.run(
                [str(DRIVER), "--engine", e, "--label", e, "--input", str(BYO_CORPUS),
                 "--concurrency", str(concurrency), "--payloads", "small,medium,large",
                 "--warmup", str(warmup), "--duration", str(duration),
                 "--cap-small", "20000", "--cap-medium", "8000", "--cap-large", "4000",
                 "--output", csv],
                env=env, capture_output=True, timeout=(warmup + duration) * 4 + 60)
        except Exception as exc:  # noqa: BLE001
            res[e] = {"label": ENGINES[e]["label"], "error": str(exc)[:120]}; continue
        if r.returncode != 0 or not Path(csv).exists():
            res[e] = {"label": ENGINES[e]["label"], "error": "driver run failed"}; continue
        cells = []
        for ln in Path(csv).read_text(encoding="utf-8").strip().splitlines()[1:]:
            c = ln.split(",")
            cells.append({"payload": c[2], "rps": round(float(c[8])), "p99": float(c[12]),
                          "errors": int(c[7]), "mib_s": round(float(c[9]), 1)})
        res[e] = {"label": ENGINES[e]["label"], "cells": cells}
    out = {"engines": res, "distinct_docs": len(docs)}
    if len(docs) < 2000:
        out["warn"] = (f"only {len(docs)} distinct documents — a small working set can flatter "
                       "the software engine (it serves repeats warm from cache). Supply a few "
                       "thousand representative docs for a cache-fair number.")

    def small(e):
        return next((c["rps"] for c in res.get(e, {}).get("cells", []) if c["payload"] == "small"), 0)
    a, b = small("themis"), small("aergia")
    if a and b:
        hi, lo = (a, b) if a >= b else (b, a)
        lead = "themis" if a >= b else "aergia"
        out["ratio"] = {"lead": ENGINES[lead]["label"], "x": round(hi / lo, 2), "hi": hi, "lo": lo}
    return out


ASSET_TYPES = {".woff2": "font/woff2", ".svg": "image/svg+xml",
               ".css": "text/css", ".js": "text/javascript", ".png": "image/png"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quieter
        sys.stderr.write("  " + (a[0] % a[1:]) + "\n")

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._send(200, (HERE / "static" / "index.html").read_text(encoding="utf-8"),
                              "text/html; charset=utf-8")
        if path == "/api/scenarios":
            return self._send(200, scenarios())
        if path == "/api/catalog":
            return self._send(200, CATALOG)
        if path == "/api/efficiency":
            return self._send(200, EFFICIENCY)
        if path.startswith("/assets/"):
            return self._serve_asset(path[len("/assets/"):])
        return self._send(404, {"error": "not found"})

    def _serve_asset(self, rel: str):
        candidates = {
            "logo.svg": BRAND / "assets" / "logotype-dark.svg",
        }
        if rel in candidates:
            target = candidates[rel]
        elif rel.startswith("fonts/"):
            target = BRAND / "fonts" / Path(rel).name
        else:
            return self._send(404, {"error": "no asset"})
        if not target.exists():
            return self._send(404, {"error": f"missing {rel}"})
        ctype = ASSET_TYPES.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}") if n else {}
            if path == "/api/batch":
                return self._send(200, batch())
            if path == "/api/scale":
                payload = payload if isinstance(payload, dict) else {}
                return self._send(200, scale(
                    payload=payload.get("payload", "small"),
                    concurrency=int(payload.get("concurrency", 256)),
                    duration=int(payload.get("duration", 8))))
            if path == "/api/process":
                engine = payload.get("engine", "themis")
                message = payload.get("message", "")
                if engine not in ENGINES:
                    return self._send(400, {"error": "unknown engine"})
                if not message.strip():
                    return self._send(400, {"error": "empty message"})
                return self._send(200, process(engine, message))
            if path == "/api/byo/build":
                return self._send(200, byo_build(payload if isinstance(payload, dict) else {}))
            if path == "/api/byo/deploy":
                return self._send(200, byo_deploy())
            if path == "/api/byo/correctness":
                payload = payload if isinstance(payload, dict) else {}
                return self._send(200, byo_correctness(limit=int(payload.get("limit", 12))))
            if path == "/api/byo/load":
                payload = payload if isinstance(payload, dict) else {}
                eng = payload.get("engine")
                engs = (eng,) if eng in ENGINES else ("themis", "aergia")
                return self._send(200, byo_load(
                    concurrency=int(payload.get("concurrency", 256)),
                    duration=int(payload.get("duration", 10)),
                    engines=engs))
            return self._send(404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001
            return self._send(502, {"error": str(exc)})


def main():
    missing = [k for k, v in ENGINES.items() if not v["endpoint"]]
    if missing:
        print(f"!! missing endpoint(s) for {missing} — source config/demo.env + .env first", file=sys.stderr)
    print(f">> deploying known-values policy ({len(PAIRS)} rules) to both engines ...", flush=True)
    print(f"   {deploy_policy()}", flush=True)
    ip = lan_ip()
    print(f">> NOL8 demo console listening on {HOST}:{PORT}", flush=True)
    print(f"   over the VPN:   http://{ip}:{PORT}", flush=True)
    print(f"   or via tunnel:  ssh -f -N -L {PORT}:localhost:{PORT} nol8-demo   (backgrounds itself)  ->  http://localhost:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
