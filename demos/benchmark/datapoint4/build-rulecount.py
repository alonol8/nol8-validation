#!/usr/bin/env python3
"""Render the rule-count sweep (rulecount.csv) into a focused chart page.

Fixed payload + concurrency, varying only policy size. The question the page
answers: does the FPGA stay flat while software RE2 slopes down as rules climb?
Reuses make-report.py's chart + table + CSS so it matches the DP reports.

  python demos/benchmark/datapoint4/build-rulecount.py \
      demos/benchmark/datapoint4/results/rulecount.csv \
      demos/benchmark/datapoint4/rulecount-report.html
"""
from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("make_report", HERE.parent / "make-report.py")
mr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mr)

ENGINE = {"themis": ("Themis (FPGA)", "var(--accent)"),
          "aergia": ("Aergia (RE2)", "#E0A63C")}


def load(csv_path: Path):
    rows = []
    for r in csv.DictReader(csv_path.open()):
        rows.append({
            "rule_count": int(r["rule_count"]),
            "engine": r["engine"],
            "payload": r["payload"],
            "concurrency": int(r["concurrency"]),
            "rps": float(r["rps"]),
            "p99_ms": float(r["p99_ms"]),
            "mib_s": float(r["throughput_mib_s"]),
            "p50_ms": float(r["p50_ms"]),
            "errors": int(r["errors"]),
        })
    return rows


def series_for(rows, engine, ykey):
    pts = sorted([(r["rule_count"], r[ykey]) for r in rows if r["engine"] == engine])
    lbl, color = ENGINE.get(engine, (engine, "var(--fg2)"))
    return {"label": lbl, "color": color, "points": pts}


def main() -> None:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "results/rulecount.csv"
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "rulecount-report.html"
    rows = load(csv_path)
    if not rows:
        raise SystemExit("no rows in rulecount.csv")

    engines = [e for e in ("themis", "aergia") if any(r["engine"] == e for r in rows)]
    rules = sorted({r["rule_count"] for r in rows})
    payload = rows[0]["payload"]
    conc = rows[0]["concurrency"]

    xlabel = "policy size (rules, log scale)"
    rps_series = [series_for(rows, e, "rps") for e in engines]
    p99_series = [series_for(rows, e, "p99_ms") for e in engines]
    rps_max = mr._nice_max(max(r["rps"] for r in rows))
    p99_max = mr._nice_max(max(r["p99_ms"] for r in rows))
    rps_chart = mr._svg_line_chart(rps_series, rules, rps_max, "requests / sec",
                                   "Sustained throughput vs policy size", xlabel=xlabel)
    p99_chart = mr._svg_line_chart(p99_series, rules, p99_max, "p99 latency (ms)",
                                   "Tail latency vs policy size", xlabel=xlabel)

    # headline numbers: change across the rule range, per engine
    def at(engine, rc):
        return next((r["rps"] for r in rows if r["engine"] == engine and r["rule_count"] == rc), None)
    lo, hi = rules[0], rules[-1]
    lines = []
    for e in engines:
        a, b = at(e, lo), at(e, hi)
        if a and b:
            pct = (b - a) / a * 100.0
            arrow = "held" if abs(pct) < 6 else ("fell" if pct < 0 else "rose")
            lines.append(f"{ENGINE[e][0]}: {a:,.0f} -> {b:,.0f} req/s ({arrow} {abs(pct):.0f}%) from {lo:,} to {hi:,} rules")

    cols = ["Rules", *[ENGINE[e][0] + " req/s" for e in engines], *[ENGINE[e][0] + " p99 ms" for e in engines]]
    trows = []
    for rc in rules:
        row = [f"{rc:,}"]
        for e in engines:
            v = next((r["rps"] for r in rows if r["engine"] == e and r["rule_count"] == rc), None)
            row.append(f"{v:,.0f}" if v is not None else "-")
        for e in engines:
            v = next((r["p99_ms"] for r in rows if r["engine"] == e and r["rule_count"] == rc), None)
            row.append(f"{v:.1f}" if v is not None else "-")
        trows.append(row)
    table = mr._num_table(cols, trows, min_width=560)

    takeaway = "; ".join(lines)
    body = f"""
  <section style="max-width:1100px;margin:0 auto;padding:56px 40px;">
    <div style="color:var(--accent);font-weight:600;font-size:13px;letter-spacing:.18em;text-transform:uppercase;">Data Point 04 &middot; Rule-count sweep</div>
    <h1 style="font-family:var(--font-display);font-weight:500;font-size:40px;line-height:1.05;color:var(--fg1);margin:16px 0 10px;">Does the FPGA's edge scale with <span style="color:var(--accent);">policy size?</span></h1>
    <p style="color:var(--fg2);font-size:15.5px;line-height:1.6;max-width:80ch;margin:0 0 6px;">Fixed payload (<b>{mr.esc(payload)}</b>) at fixed concurrency (<b>{conc}</b>), varying only the deployed rule count. Same corpus, same driver, same policy to both engines &mdash; only the number of literal rules changes. Software RE2's match cost grows with the pattern set; a fixed FPGA pipeline should not.</p>
    <p style="color:var(--fg3);font-size:13px;line-height:1.6;margin:0 0 26px;">{mr.esc(takeaway)}</p>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px;">
      <div data-card style="background:var(--card);border:1px solid var(--cardline);border-radius:12px;padding:14px 16px 8px;overflow-x:auto;">{rps_chart}</div>
      <div data-card style="background:var(--card);border:1px solid var(--cardline);border-radius:12px;padding:14px 16px 8px;overflow-x:auto;">{p99_chart}</div>
    </div>
    <div style="margin-top:30px;">{table}</div>
    <p style="color:var(--fg3);font-size:12px;line-height:1.6;margin:18px 0 0;max-width:80ch;">Measured end-to-end on the live engines. Throughput is sustained req/s over a steady-state window; p99 is the tail latency. If Themis stays flat while RE2 slopes down as rules climb, the FPGA advantage is a function of policy complexity &mdash; which is the enterprise-DLP reality (large policies).</p>
  </section>"""

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NOL8 Rule-Count Sweep, Data Point 04</title>
<style>{mr.build_css()}</style></head>
<body>
<div data-rpt data-theme="dark" style="background:var(--bg);color:var(--fg1);font-family:var(--font-ui);min-height:100vh;-webkit-font-smoothing:antialiased;">
{body}
</div></body></html>"""
    out_path.write_text(html)
    kb = out_path.stat().st_size / 1024
    print(f"Wrote {out_path} ({kb:.0f} KB) — {len(rules)} rule counts, engines={engines}")


if __name__ == "__main__":
    main()
