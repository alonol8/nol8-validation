#!/usr/bin/env python3
"""Diagnostic: per-request latency vs payload size at concurrency 1.

Answers one question the DP4 smoke raised: Themis was ~13x slower than Aergia on
large payloads at concurrency 1 (no contention), so that gap is pure per-request
cost - not saturation. Is it driven by BYTES (transport / front-end buffering /
FPGA streaming) or by MATCHES (the matching + replacement core)?

Method: at concurrency 1, over a ladder of payload sizes, time each engine on two
payloads of the SAME size:
  - clean   : zero policy literals -> the engine scans every byte but replaces
              nothing. Isolates scan + transport + front-end cost.
  - matched : the same size packed with real policy literals -> adds the
              replacement cost on top. matched - clean = the matching-core cost.
One persistent keep-alive connection per engine (TLS amortized, like the driver),
median of N samples after a warm-up. Same literals + sizes to both engines.

  THEMIS_ENDPOINT=.. AERGIA_ENDPOINT=.. THEMIS_TOKEN=.. AERGIA_TOKEN=.. \
    python demos/benchmark/datapoint4/probe-size.py \
      --policy <scale-policy.nol> --out results/size-probe.csv
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import ssl
import statistics
import time
from pathlib import Path
from urllib.parse import urlparse

SIZES_KB = [1, 4, 16, 64, 128, 256, 512, 1024]


def load_literals(policy_path: Path, limit: int = 200) -> list[str]:
    """Grab literal left-hand sides from a .nol policy: `"variant" -> "repl";`."""
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
        if len(lits) >= limit:
            break
    if not lits:
        raise SystemExit(f"no literals parsed from {policy_path}")
    return lits


def clean_payload(size: int) -> str:
    # Benign filler with no policy literals. Repeated word, padded to size.
    base = "lorem ipsum dolor sit amet consectetur adipiscing elit "
    reps = size // len(base) + 1
    return (base * reps)[:size]


def matched_payload(size: int, literals: list[str], every: int = 256) -> str:
    """Same size, but a real policy literal roughly every `every` bytes."""
    out: list[str] = []
    total = 0
    i = 0
    filler = "context notes reference value "
    while total < size:
        lit = literals[i % len(literals)]
        chunk = f"{filler}{lit}. "
        # pad the chunk toward `every` bytes so matches are spaced, not solid
        if len(chunk) < every:
            chunk += "x" * (every - len(chunk))
        out.append(chunk)
        total += len(chunk)
        i += 1
    return "".join(out)[:size]


def conn_for(endpoint: str, insecure: bool):
    u = urlparse(endpoint)
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=60, context=ctx)
    return conn, (u.path or "/")


def time_call(conn, path: str, token: str, body: bytes) -> float:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    t = time.perf_counter()
    conn.request("POST", path, body=body, headers=headers)
    resp = conn.getresponse()
    resp.read()
    dt = time.perf_counter() - t
    if resp.status < 200 or resp.status >= 300:
        raise RuntimeError(f"status {resp.status}")
    return dt * 1000.0  # ms


def measure(endpoint: str, token: str, insecure: bool, payload: str,
            samples: int, warmup: int) -> tuple[float, float]:
    conn, path = conn_for(endpoint, insecure)
    body = json.dumps({"message": payload}).encode("utf-8")
    try:
        for _ in range(warmup):
            time_call(conn, path, token, body)
        xs = [time_call(conn, path, token, body) for _ in range(samples)]
    finally:
        conn.close()
    xs.sort()
    p95 = xs[min(len(xs) - 1, int(0.95 * len(xs)))]
    return statistics.median(xs), p95


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("size-probe.csv"))
    ap.add_argument("--samples", type=int, default=15)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--insecure", action="store_true")
    ap.add_argument("--sizes-kb", type=str, default=",".join(str(s) for s in SIZES_KB))
    args = ap.parse_args()

    engines = []
    for name, ep_env, tok_env in (("themis", "THEMIS_ENDPOINT", "THEMIS_TOKEN"),
                                  ("aergia", "AERGIA_ENDPOINT", "AERGIA_TOKEN")):
        ep = os.environ.get(ep_env, "").strip()
        if ep:
            engines.append((name, ep, os.environ.get(tok_env, "").strip()))
    if not engines:
        raise SystemExit("set THEMIS_ENDPOINT and/or AERGIA_ENDPOINT")

    literals = load_literals(args.policy)
    sizes = [int(s) * 1024 for s in args.sizes_kb.split(",") if s.strip()]

    rows = [("engine", "size_kb", "condition", "bytes", "median_ms", "p95_ms")]
    print(f"payload-size probe @ concurrency 1 | engines={[e[0] for e in engines]} | {len(literals)} literals")
    header = f"{'size':>7} | " + " | ".join(f"{n+' '+c:>16}" for n in [e[0] for e in engines] for c in ("clean", "matched"))
    print(header)
    print("-" * len(header))

    for size in sizes:
        clean = clean_payload(size)
        matched = matched_payload(size, literals)
        cells = []
        for name, ep, tok in engines:
            for cond, payload in (("clean", clean), ("matched", matched)):
                try:
                    med, p95 = measure(ep, tok, args.insecure, payload, args.samples, args.warmup)
                    rows.append((name, f"{size//1024}", cond, str(len(payload)), f"{med:.3f}", f"{p95:.3f}"))
                    cells.append(f"{med:>8.2f}ms")
                except Exception as exc:  # noqa: BLE001 - report, keep going
                    rows.append((name, f"{size//1024}", cond, str(len(payload)), "ERR", "ERR"))
                    cells.append(f"{'ERR':>10}")
        print(f"{size//1024:>5}KB | " + " | ".join(f"{c:>16}" for c in cells))

    with args.out.open("w") as fh:
        for r in rows:
            fh.write(",".join(r) + "\n")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
