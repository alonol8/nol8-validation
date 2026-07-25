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

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # repo root
HERE = Path(__file__).resolve().parent
BRAND = ROOT / "demos" / "benchmark" / "brand"
POLICY = ROOT / "demos" / "policies" / "starter-known-values.nol"
SCEN = HERE.parent / "scenarios"
PORT = int(os.environ.get("CONSOLE_PORT", "8770"))
# Bind all interfaces by default so the console is reachable over the VPN
# (http://<box-ip>:PORT). Set CONSOLE_HOST=127.0.0.1 to restrict to localhost
# (then reach it only via an SSH tunnel).
HOST = os.environ.get("CONSOLE_HOST", "0.0.0.0")


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

# Efficiency numbers measured on the engine hosts (DPDK poll-mode → constant, so a
# fixed reading is representative; see docs/DP4-THROUGHPUT-BRIEF.md "efficiency result").
EFFICIENCY = {
    "themis": {"apollo": 11.3, "matching": 0.0, "total": 11.3, "rps": 28600, "matching_label": "FPGA / 0"},
    "aergia": {"apollo": 11.3, "matching": 8.2, "total": 19.4, "rps": 26300, "matching_label": "8.2 (RE2 lexers)"},
    "tax_cores": 8.2, "ratio": 1.9,
}

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


def process(engine: str, message: str) -> dict:
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
            if path == "/api/process":
                engine = payload.get("engine", "themis")
                message = payload.get("message", "")
                if engine not in ENGINES:
                    return self._send(400, {"error": "unknown engine"})
                if not message.strip():
                    return self._send(400, {"error": "empty message"})
                return self._send(200, process(engine, message))
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
    print(f"   or via tunnel:  ssh -L {PORT}:localhost:{PORT} nol8-demo   (leave open)  ->  http://localhost:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
