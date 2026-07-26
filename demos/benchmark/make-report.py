#!/usr/bin/env python3
"""Render run.json into a self-contained, on-brand NOL8 pre-index report.

Reproduces the Design handoff (`Pre-Index Web Report.dc.html`) as a single static
HTML file: brand fonts, logos, and the hero pattern are inlined as data URIs, so
the file opens anywhere and prints to a clean light PDF leave-behind (the "deck").
Interactivity (theme toggle, engine-compare tabs, nav scroll-spy, back-to-top)
is vanilla JS and degrades to fully-visible content with no JS and in print.

  python demos/benchmark/make-report.py \
      [demos/benchmark/run.json] [demos/benchmark/pre-index-report.html]

Data contract: demos/benchmark/run.json (see the Design handoff README). Brand
assets: demos/benchmark/brand/ (fonts/, assets/).
"""
from __future__ import annotations

import base64
import difflib
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRAND = HERE / "brand"
GREEN = "#33B046"


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def font_face(family: str, weight: int, path: Path) -> str:
    return (
        f'@font-face{{font-family:"{family}";font-style:normal;font-weight:{weight};'
        f'font-display:swap;src:url("{data_uri(path, "font/woff2")}") format("woff2");}}'
    )


def build_fonts() -> str:
    f = BRAND / "fonts"
    faces = [
        font_face("Google Sans", 400, f / "GoogleSans-400.woff2"),
        font_face("Google Sans", 500, f / "GoogleSans-500.woff2"),
        font_face("Google Sans", 600, f / "GoogleSans-600.woff2"),
        font_face("Google Sans", 700, f / "GoogleSans-700.woff2"),
        font_face("Space Grotesk", 500, f / "SpaceGrotesk-500.woff2"),
        font_face("Space Grotesk", 700, f / "SpaceGrotesk-700.woff2"),
    ]
    return "\n".join(faces)


def logo(name: str) -> str:
    return data_uri(BRAND / "assets" / name, "image/svg+xml")


# ---- CSS: tokens (dark default), light override, print (light) ----
def build_css() -> str:
    pattern = data_uri(BRAND / "assets" / "brand-pattern.png", "image/png")
    return f"""
{build_fonts()}
*{{box-sizing:border-box;}}
html{{scroll-behavior:smooth;}}
body{{margin:0;background:#404040;}}
[data-rpt]{{
  --nol8-green:{GREEN}; --accent:{GREEN}; --accent-hover:#2C9A3D;
  --bg:#404040; --fg1:#FFFFFF; --fg2:#D2D2D2; --fg3:rgba(210,210,210,0.60);
  --hairline:rgba(210,210,210,0.40); --hairline-soft:rgba(210,210,210,0.20);
  --card:rgba(255,255,255,0.06); --cardline:rgba(255,255,255,0.09); --rowline:rgba(255,255,255,0.12);
  --seg-net:rgba(255,255,255,0.14); --seg-tls:rgba(255,255,255,0.30); --tint:rgba(51,176,70,0.10);
  --navbg:rgba(48,48,48,0.82); --herofade:64,64,64; --pattern-op:0.4; --silver:#D2D2D2;
  --font-ui:"Google Sans","Helvetica Neue",Arial,sans-serif;
  --font-display:"Space Grotesk","Google Sans",sans-serif;
}}
[data-rpt][data-theme="light"]{{
  --bg:#FFFAEF; --fg1:#404040; --fg2:#5b5b5b; --fg3:rgba(91,91,91,0.72);
  --hairline:#cfccc2; --hairline-soft:#e2ded3;
  --card:rgba(0,0,0,0.035); --cardline:rgba(0,0,0,0.08); --rowline:rgba(0,0,0,0.10);
  --seg-net:rgba(0,0,0,0.10); --seg-tls:rgba(0,0,0,0.24); --tint:rgba(51,176,70,0.12);
  --navbg:rgba(255,250,239,0.85); --herofade:255,250,239; --pattern-op:0.24;
}}
.brand-pattern{{background:url("{pattern}") right center / cover no-repeat;}}
.logo-light{{display:none;}} .logo-dark{{display:block;}}
[data-theme="light"] .logo-dark{{display:none;}} [data-theme="light"] .logo-light{{display:block;}}
a.cta:hover{{background:var(--accent-hover) !important;}}
a.ghost:hover{{background:var(--card) !important;}}
a.foot:hover{{color:var(--accent) !important;}}
.trow:hover{{background:var(--tint);}}
@keyframes navIn{{from{{opacity:0;transform:translateY(-10px);}}to{{opacity:1;transform:none;}}}}
@media (prefers-reduced-motion:reduce){{
  html{{scroll-behavior:auto;}}
}}
@media print{{
  [data-rpt]{{
    --bg:#FFFAEF !important; --fg1:#404040 !important; --fg2:#555 !important; --fg3:#777 !important;
    --hairline:#c9c9c9 !important; --hairline-soft:#e0ddd4 !important;
    --card:rgba(0,0,0,0.035) !important; --cardline:rgba(0,0,0,0.1) !important; --rowline:rgba(0,0,0,0.12) !important;
    --seg-net:rgba(0,0,0,0.12) !important; --seg-tls:rgba(0,0,0,0.26) !important; --tint:rgba(51,176,70,0.12) !important;
    background:#FFFAEF !important;
  }}
  body{{background:#fff !important;-webkit-print-color-adjust:exact;print-color-adjust:exact;}}
  .no-print{{display:none !important;}}
  .logo-dark{{display:none !important;}} .logo-light{{display:block !important;}}
  [data-wf]{{opacity:1 !important;}}
  .method-body,.raw-body{{display:block !important;}}
  [data-card],section,.avoid-break{{break-inside:avoid;}}
  @page{{margin:14mm;}}
}}
"""


# ---- section builders ----
_DEFAULT_CTAS = [
    {"label": "See where the time goes", "target": "#latency", "primary": True, "arrow": True},
    {"label": "The benchmark", "target": "#benchmark", "primary": False},
]


def _hero_ctas(d) -> str:
    out = ""
    for c in d.get("cta", _DEFAULT_CTAS):
        arrow = ' <span style="font-weight:700;">&rsaquo;</span>' if c.get("arrow") else ""
        if c.get("primary"):
            out += (f'\n          <a class="cta" href="{esc(c["target"])}" style="display:inline-flex;'
                    f'align-items:center;gap:9px;background:var(--accent);color:#fff;font-weight:600;'
                    f'font-size:15px;padding:13px 22px;border-radius:8px;text-decoration:none;">{esc(c["label"])}{arrow}</a>')
        else:
            out += (f'\n          <a class="ghost" href="{esc(c["target"])}" style="display:inline-flex;'
                    f'align-items:center;background:transparent;color:var(--fg1);font-weight:600;font-size:15px;'
                    f'padding:13px 22px;border-radius:8px;border:1px solid var(--hairline);text-decoration:none;">{esc(c["label"])}</a>')
    return out


def hero(d) -> str:
    h = d["headline"]
    return f"""
  <section id="top" data-section="overview" style="position:relative;overflow:hidden;scroll-margin-top:80px;">
    <div class="brand-pattern" style="position:absolute;top:0;right:0;bottom:0;width:56%;opacity:var(--pattern-op);">
      <div style="position:absolute;inset:0;background:linear-gradient(100deg,var(--bg) 6%,rgba(var(--herofade),0.55) 42%,rgba(var(--herofade),0) 74%);"></div>
    </div>
    <div style="position:relative;max-width:1200px;margin:0 auto;padding:64px 40px 56px;">
      <div style="max-width:720px;">
        <div style="color:var(--accent);font-weight:600;font-size:13px;letter-spacing:.18em;text-transform:uppercase;">{esc(d["eyebrow"])}</div>
        <h1 style="font-family:var(--font-display);font-weight:500;font-size:56px;line-height:1.03;letter-spacing:-.015em;color:var(--fg1);margin:22px 0 0;">{esc(h["lead"])}<span style="color:var(--accent);">{esc(h["accent"])}</span></h1>
        <p style="color:var(--fg2);font-size:18px;line-height:1.6;max-width:60ch;margin:24px 0 0;">{esc(d["lede"])}</p>
        <div class="no-print" style="display:flex;flex-wrap:wrap;gap:12px;margin-top:32px;">{_hero_ctas(d)}
        </div>
      </div>
    </div>
  </section>"""


def stat_band(d) -> str:
    cells = ""
    for s in d["stats"]:
        color = "var(--accent)" if s["key"] else "var(--fg1)"
        cells += f"""
          <div data-card style="padding:34px 30px;border-left:1px solid var(--hairline-soft);">
            <div style="font-family:var(--font-display);font-weight:700;font-size:40px;line-height:1;color:{color};">{esc(s["value"])}<span style="font-size:.4em;color:var(--fg2);margin-left:2px;">{esc(s["unit"])}</span></div>
            <div style="color:var(--fg3);font-size:12.5px;line-height:1.4;margin-top:10px;">{esc(s["label"])}</div>
          </div>"""
    return f"""
  <section style="border-top:1px solid var(--hairline-soft);border-bottom:1px solid var(--hairline-soft);">
    <div style="max-width:1200px;margin:0 auto;padding:0 40px;">
      <div style="display:grid;grid-template-columns:repeat(4,1fr);background:var(--card);">{cells}
      </div>
    </div>
  </section>"""


APPROACH_STYLE = {
    "baseline":  dict(surface="var(--card)", border="var(--cardline)", rail="var(--hairline)",
                      metric="var(--fg3)", opacity="0.72", shadow="none", tag="var(--fg3)"),
    "benchmark": dict(surface="var(--card)", border="var(--cardline)", rail="var(--silver)",
                      metric="var(--fg1)", opacity="1", shadow="none", tag="var(--fg2)"),
    "nol8":      dict(surface="var(--tint)", border="rgba(51,176,70,0.45)", rail="var(--accent)",
                      metric="var(--accent)", opacity="1",
                      shadow="0 0 0 1px rgba(51,176,70,0.28), 0 0 26px rgba(51,176,70,0.12)", tag="var(--accent)"),
}


def _approach_cards(approaches) -> str:
    cards = ""
    for a in approaches:
        s = APPROACH_STYLE[a["role"]]
        cards += f"""
          <div data-card style="position:relative;background:{s['surface']};border:1px solid {s['border']};border-left:4px solid {s['rail']};border-radius:10px;padding:24px 24px 26px;opacity:{s['opacity']};box-shadow:{s['shadow']};">
            <div style="font-weight:700;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:{s['tag']};">{esc(a['tag'])}</div>
            <div style="color:var(--fg1);font-weight:600;font-size:15px;line-height:1.3;margin-top:6px;">{esc(a['headline'])}</div>
            <div style="font-family:var(--font-display);font-weight:700;font-size:42px;line-height:1;color:{s['metric']};margin-top:18px;">{esc(a['metric'])}<span style="font-size:.32em;color:var(--fg2);font-weight:600;margin-left:5px;">{esc(a['metricUnit'])}</span></div>
            <p style="color:var(--fg3);font-size:13px;line-height:1.5;margin:14px 0 0;">{esc(a['desc'])}</p>
          </div>"""
    return cards


def benchmark(d) -> str:
    b = d["benchmark"]
    cards = _approach_cards(d["approaches"])
    r = d["redaction"]
    after = ""
    for part in r["after"]:
        if part["token"]:
            after += f'<span style="color:var(--accent);font-weight:600;background:var(--tint);padding:2px 6px;border-radius:4px;white-space:nowrap;">{esc(part["text"])}</span>'
        else:
            after += f'<span style="white-space:pre-wrap;">{esc(part["text"])}</span>'
    return f"""
  <section id="benchmark" data-section="benchmark" style="scroll-margin-top:80px;">
    <div style="max-width:1200px;margin:0 auto;padding:88px 40px;">
      <div>
        <div style="display:flex;align-items:center;gap:16px;margin-bottom:22px;">
          <span style="color:var(--accent);font-weight:600;font-size:13px;letter-spacing:.18em;text-transform:uppercase;">01 · The benchmark</span>
          <span style="flex:1;height:1px;background:var(--hairline-soft);"></span>
        </div>
        <h2 style="font-weight:700;font-size:38px;line-height:1.08;letter-spacing:-.01em;color:var(--fg1);margin:0;max-width:20ch;">{esc(b['heading'])}</h2>
        <p style="color:var(--fg2);font-size:17px;line-height:1.6;max-width:66ch;margin:14px 0 0;">{esc(b['lede'])}</p>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:18px;margin-top:36px;">{cards}
      </div>
      <div data-card style="background:var(--card);border:1px solid var(--cardline);border-radius:10px;padding:26px 28px;margin-top:18px;">
        <div style="color:var(--fg3);font-size:13.5px;line-height:1.9;">{esc(r['before'])}</div>
        <div style="color:var(--accent);font-weight:700;font-size:11px;letter-spacing:.12em;text-transform:uppercase;margin:14px 0 10px;">NOL8 governs &rsaquo;</div>
        <div style="font-size:14.5px;line-height:2;color:var(--fg2);">{after}</div>
        <div style="display:inline-flex;align-items:center;gap:9px;margin-top:20px;color:var(--accent);font-size:13px;font-weight:600;">
          <span style="width:8px;height:8px;border-radius:50%;background:var(--accent);"></span>{esc(r['note'])}
        </div>
      </div>
    </div>
  </section>"""


def latency(d) -> str:
    lat = d["latency"]
    bars = ""
    for i, wf in enumerate(d["waterfall"]):
        gap = "22px" if i < len(d["waterfall"]) - 1 else "0"
        segs = ""
        for seg in wf["segments"]:
            if seg["kind"] == "net":
                bg, fg, glow, mw = "var(--seg-net)", "var(--fg1)", "none", "0"
            elif seg["kind"] == "tls":
                bg, fg, glow, mw = "var(--seg-tls)", "var(--fg1)", "none", "0"
            else:
                bg, fg, glow, mw = "var(--accent)", "#0e2a13", "inset 0 0 0 1px rgba(255,255,255,0.4)", "6px"
            segs += f'<div style="flex:{seg["ms"]};min-width:{mw};background:{bg};box-shadow:{glow};display:flex;align-items:center;justify-content:center;color:{fg};font-size:11.5px;font-weight:600;white-space:nowrap;overflow:hidden;">{esc(seg["label"])}</div>'
        bars += f"""
        <div data-wf data-engine="{esc(wf['key'])}" style="margin-bottom:{gap};transition:opacity .3s ease;">
          <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:9px;">
            <b style="color:var(--fg1);font-weight:600;font-size:14px;">{esc(wf['name'])}</b>
            <span style="color:var(--fg3);font-size:13px;letter-spacing:-.01em;">{esc(wf['total'])}</span>
          </div>
          <div style="display:flex;height:52px;border-radius:8px;overflow:hidden;border:1px solid var(--hairline-soft);">{segs}</div>
        </div>"""
    head = """
          <div style="text-align:left;padding:14px 16px;color:var(--fg3);font-weight:600;font-size:11px;letter-spacing:.06em;text-transform:uppercase;">Engine</div>"""
    for col in ["Network RTT", "Warm (pooled)", "Cold (TLS/call)", "TLS tax", "Engine"]:
        head += f'<div style="text-align:right;padding:14px 16px;color:var(--fg3);font-weight:600;font-size:11px;letter-spacing:.06em;text-transform:uppercase;">{col}</div>'
    rows = ""
    for i, row in enumerate(d["table"]):
        border = "1px solid var(--rowline)" if i < len(d["table"]) - 1 else "none"
        rows += f"""
          <div class="trow" style="display:grid;grid-template-columns:1.5fr repeat(5,1fr);border-bottom:{border};">
            <div style="text-align:left;padding:15px 16px;color:var(--fg1);font-weight:600;">{esc(row['engine'])}</div>
            <div style="text-align:right;padding:15px 16px;color:var(--fg2);">{esc(row['rtt'])}</div>
            <div style="text-align:right;padding:15px 16px;color:var(--fg2);">{esc(row['warm'])}</div>
            <div style="text-align:right;padding:15px 16px;color:var(--fg2);">{esc(row['cold'])}</div>
            <div style="text-align:right;padding:15px 16px;color:var(--fg2);">{esc(row['tls'])}</div>
            <div style="text-align:right;padding:15px 16px;color:var(--accent);font-weight:700;">{esc(row['eng'])}</div>
          </div>"""
    return f"""
  <section id="latency" data-section="latency" style="scroll-margin-top:80px;border-top:1px solid var(--hairline-soft);">
    <div style="max-width:1200px;margin:0 auto;padding:88px 40px;">
      <div>
        <div style="display:flex;align-items:center;gap:16px;margin-bottom:22px;">
          <span style="color:var(--accent);font-weight:600;font-size:13px;letter-spacing:.18em;text-transform:uppercase;">02 · Where the time goes</span>
          <span style="flex:1;height:1px;background:var(--hairline-soft);"></span>
        </div>
        <h2 style="font-weight:700;font-size:38px;line-height:1.08;letter-spacing:-.01em;color:var(--fg1);margin:0;">{esc(lat['heading'])}</h2>
        <p style="color:var(--fg2);font-size:17px;line-height:1.6;max-width:66ch;margin:14px 0 0;">{esc(lat['lede'])}</p>
      </div>
      <div data-card style="background:var(--card);border:1px solid var(--cardline);border-radius:12px;padding:28px 30px;margin-top:34px;">
        <div class="no-print" style="display:flex;align-items:center;gap:10px;margin-bottom:24px;flex-wrap:wrap;">
          <span style="color:var(--fg3);font-size:11px;letter-spacing:.1em;text-transform:uppercase;margin-right:4px;">Compare</span>
          <button class="etab" data-view="both" style="cursor:pointer;font-family:inherit;font-size:12.5px;font-weight:600;padding:7px 15px;border-radius:999px;">Both</button>
          <button class="etab" data-view="themis" style="cursor:pointer;font-family:inherit;font-size:12.5px;font-weight:600;padding:7px 15px;border-radius:999px;">Themis (NOL8)</button>
          <button class="etab" data-view="aergia" style="cursor:pointer;font-family:inherit;font-size:12.5px;font-weight:600;padding:7px 15px;border-radius:999px;">Aergia (RE2)</button>
        </div>{bars}
        <div style="display:flex;flex-wrap:wrap;gap:20px;margin-top:22px;">
          <span style="display:inline-flex;align-items:center;gap:8px;color:var(--fg2);font-size:12.5px;"><i style="width:11px;height:11px;border-radius:3px;background:var(--seg-net);display:inline-block;"></i>Network round-trip</span>
          <span style="display:inline-flex;align-items:center;gap:8px;color:var(--fg2);font-size:12.5px;"><i style="width:11px;height:11px;border-radius:3px;background:var(--seg-tls);display:inline-block;"></i>TLS handshake, per call, removable by pooling</span>
          <span style="display:inline-flex;align-items:center;gap:8px;color:var(--fg2);font-size:12.5px;"><i style="width:11px;height:11px;border-radius:3px;background:var(--accent);display:inline-block;"></i>Engine processing</span>
        </div>
        <div style="margin-top:22px;padding:14px 18px;border-left:3px solid var(--accent);background:var(--tint);border-radius:0 8px 8px 0;font-size:14px;line-height:1.55;color:var(--fg1);">{esc(lat['callout'])}</div>
      </div>
      <div data-card style="background:var(--card);border:1px solid var(--cardline);border-radius:12px;padding:8px 8px;margin-top:18px;overflow-x:auto;">
        <div style="min-width:640px;font-variant-numeric:tabular-nums;letter-spacing:-.01em;">
          <div style="display:grid;grid-template-columns:1.5fr repeat(5,1fr);border-bottom:1px solid var(--rowline);">{head}
          </div>{rows}
        </div>
      </div>
      <p style="color:var(--fg3);font-size:12.5px;line-height:1.55;max-width:84ch;margin:16px 0 0;">{esc(d['tableNote'])}</p>
    </div>
  </section>"""


def meaning(d) -> str:
    items = ""
    for t in d["takeaways"]:
        items += f"""
          <div style="display:flex;gap:16px;align-items:flex-start;">
            <span style="color:var(--accent);font-size:24px;font-weight:700;line-height:1;flex-shrink:0;">&rsaquo;</span>
            <div><div style="color:var(--fg1);font-weight:600;font-size:16.5px;line-height:1.3;">{esc(t['title'])}</div><p style="color:var(--fg2);font-size:15px;line-height:1.55;margin:6px 0 0;">{esc(t['body'])}</p></div>
          </div>"""
    return f"""
  <section id="meaning" data-section="meaning" style="scroll-margin-top:80px;border-top:1px solid var(--hairline-soft);">
    <div style="max-width:1200px;margin:0 auto;padding:88px 40px;">
      <div>
        <div style="display:flex;align-items:center;gap:16px;margin-bottom:22px;">
          <span style="color:var(--accent);font-weight:600;font-size:13px;letter-spacing:.18em;text-transform:uppercase;">03 · What it means</span>
          <span style="flex:1;height:1px;background:var(--hairline-soft);"></span>
        </div>
        <h2 style="font-weight:700;font-size:38px;line-height:1.08;letter-spacing:-.01em;color:var(--fg1);margin:0;">{esc(d['meaning']['heading'])}</h2>
      </div>
      <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:38px 56px;margin-top:34px;">{items}
      </div>
    </div>
  </section>"""


def method(d) -> str:
    rows = ""
    for i, m in enumerate(d["method"]):
        border = "none" if i == len(d["method"]) - 1 else "1px solid var(--hairline-soft)"
        rows += f"""
          <div style="display:grid;grid-template-columns:180px 1fr;gap:24px;padding:13px 0;border-bottom:{border};">
            <div style="color:var(--fg3);font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;padding-top:1px;">{esc(m['term'])}</div>
            <div style="color:var(--fg2);font-size:13.5px;line-height:1.6;">{esc(m['def'])}</div>
          </div>"""
    return f"""
  <section id="method" data-section="method" style="scroll-margin-top:80px;border-top:1px solid var(--hairline-soft);">
    <div style="max-width:1200px;margin:0 auto;padding:64px 40px;">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:16px;">
        <span style="color:var(--accent);font-weight:600;font-size:13px;letter-spacing:.18em;text-transform:uppercase;">Method</span>
        <button id="method-toggle" class="no-print" style="border:1px solid var(--hairline);background:transparent;color:var(--fg2);font-family:inherit;font-size:12px;font-weight:600;padding:6px 14px;border-radius:999px;cursor:pointer;">Hide</button>
      </div>
      <div class="method-body" style="display:block;margin-top:18px;">{rows}
        <p style="color:var(--fg3);font-size:12px;line-height:1.5;margin:16px 0 0;">{esc(d['methodNote'])}</p>
      </div>
    </div>
  </section>"""


WARN = "#cf6a4a"  # semantic "corrupted" hue for the RE2 fragments, not the accent


def _subhead(title: str, first: bool = False) -> str:
    mt = "4px" if first else "40px"
    return (f'<h3 style="font-size:16px;font-weight:700;letter-spacing:-.01em;color:var(--fg1);'
            f'margin:{mt} 0 8px;">{esc(title)}</h3>')


def _note(text: str) -> str:
    return (f'<p style="color:var(--fg3);font-size:12.5px;line-height:1.6;max-width:92ch;'
            f'margin:0 0 14px;">{esc(text)}</p>')


def _num_table(cols, rows, min_width=560) -> str:
    """First column is a left label; the rest are right-aligned readouts."""
    head = "".join(
        f'<th style="text-align:{"left" if i == 0 else "right"};padding:11px 14px;color:var(--fg3);'
        f'font-weight:600;font-size:11px;letter-spacing:.06em;text-transform:uppercase;white-space:nowrap;'
        f'border-bottom:1px solid var(--rowline);">{esc(c)}</th>'
        for i, c in enumerate(cols)
    )
    body = ""
    for r_i, row in enumerate(rows):
        last = r_i == len(rows) - 1
        nol8 = "NOL8" in str(row[0]) or "Themis" in str(row[0])
        div = "" if last else "border-bottom:1px solid var(--hairline-soft);"
        cells = ""
        for i, cell in enumerate(row):
            align = "left" if i == 0 else "right"
            color = "var(--accent)" if (nol8 and i == 0) else ("var(--fg1)" if i == 0 else "var(--fg2)")
            weight = "600" if i == 0 else "400"
            cells += (f'<td style="text-align:{align};padding:12px 14px;color:{color};font-weight:{weight};'
                      f'white-space:nowrap;{div}">{esc(cell)}</td>')
        body += f"<tr>{cells}</tr>"
    return (f'<div data-card style="background:var(--card);border:1px solid var(--cardline);border-radius:12px;'
            f'padding:6px 6px;overflow-x:auto;"><table style="width:100%;min-width:{min_width}px;'
            f'border-collapse:collapse;font-variant-numeric:tabular-nums;letter-spacing:-.01em;font-size:13px;">'
            f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>")


def _strip_table(cols, rows) -> str:
    """Count column (green, narrow) + a wrapping sentence column."""
    head = "".join(
        f'<th style="text-align:left;padding:11px 14px;color:var(--fg3);font-weight:600;font-size:11px;'
        f'letter-spacing:.06em;text-transform:uppercase;border-bottom:1px solid var(--rowline);'
        f'white-space:nowrap;">{esc(c)}</th>'
        for c in cols
    )
    body = ""
    for r_i, (count, sentence) in enumerate(rows):
        div = "" if r_i == len(rows) - 1 else "border-bottom:1px solid var(--hairline-soft);"
        body += (
            f'<tr><td style="padding:11px 14px;color:var(--accent);font-weight:600;white-space:nowrap;'
            f'vertical-align:top;font-variant-numeric:tabular-nums;{div}">{esc(count)}</td>'
            f'<td style="padding:11px 14px;color:var(--fg2);line-height:1.5;{div}">{esc(sentence)}</td></tr>'
        )
    return (f'<div data-card style="background:var(--card);border:1px solid var(--cardline);border-radius:12px;'
            f'padding:6px 6px;overflow-x:auto;"><table style="width:100%;min-width:560px;border-collapse:collapse;'
            f'font-size:13px;"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')


def _chipify(escaped_text: str) -> str:
    return re.sub(
        r"(\[[A-Z0-9_]+\])",
        r'<span style="color:var(--accent);font-weight:600;background:var(--tint);'
        r'padding:1px 5px;border-radius:4px;">\1</span>',
        escaped_text,
    )


def _row_label(text: str, color: str) -> str:
    return (f'<div style="font-size:10.5px;letter-spacing:.11em;text-transform:uppercase;'
            f'font-weight:600;color:{color};margin-bottom:5px;">{esc(text)}</div>')


def _sample_row(label: str, label_color: str, text: str, role: str) -> str:
    """The 'Original in' and 'NOL8 Themis' rows (the clean/reference side)."""
    stripped = text.strip()
    if role == "in":
        color, inner = "var(--fg3)", esc(text)
    else:  # themis
        color = "var(--fg1)"
        inner = (_chipify(esc(text)) if stripped
                 else '<span style="color:var(--fg3);font-style:italic;">nothing forwarded, stripped to blank</span>')
    return (f'<div>{_row_label(label, label_color)}'
            f'<div style="white-space:pre-wrap;color:{color};font-size:12.5px;line-height:1.7;">{inner}</div></div>')


def _highlight_corruption(themis_text: str, aergia_text: str) -> str:
    """Render Aergia's output with the parts it forwarded that Themis correctly
    removed marked, so the divergence reads at a glance. Themis == the oracle, so
    the diff against it is exactly the corruption Aergia added.
    """
    hl = ("background:rgba(207,106,74,0.32);border-radius:3px;padding:0 2px;"
          "text-decoration:underline;text-decoration-color:#cf6a4a;text-underline-offset:2px;")
    out = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(
            None, themis_text, aergia_text, autojunk=False).get_opcodes():
        seg = aergia_text[j1:j2]
        if not seg:
            continue
        out.append(esc(seg) if tag == "equal" else f'<span style="{hl}">{esc(seg)}</span>')
    return "".join(out)


def _aergia_row(aergia_text: str, themis_text: str) -> str:
    """The RE2 (Aergia) row: corruption-highlighted, in a warning-tinted box."""
    box = ("background:rgba(207,106,74,0.09);border:1px solid rgba(207,106,74,0.28);"
           "border-radius:6px;padding:8px 11px;")
    if not aergia_text.strip():
        inner, caption = '<span style="color:var(--fg3);font-style:italic;">nothing forwarded</span>', ""
    else:
        inner = _highlight_corruption(themis_text, aergia_text)
        caption = (f'<div style="font-size:10.5px;color:{WARN};margin-top:7px;line-height:1.5;">'
                   f'Highlighted: forwarded by Aergia, correctly removed by Themis. It becomes vector garbage.</div>')
    return (f'<div>{_row_label("RE2 (Aergia) · forwarded", WARN)}'
            f'<div style="white-space:pre-wrap;color:{WARN};font-size:12.5px;line-height:1.7;{box}">{inner}</div>'
            f'{caption}</div>')


def _samples(items) -> str:
    cards = ""
    for it in items:
        rows = (
            _sample_row("Original in", "var(--fg3)", it["in"], "in")
            + _sample_row("NOL8 Themis · forwarded", "var(--accent)", it["themis"], "themis")
            + _aergia_row(it["aergia"], it["themis"])
        )
        note = ""
        if it.get("note"):
            note = (f'<div style="font-size:11.5px;color:var(--fg3);line-height:1.55;margin-top:14px;'
                    f'padding-top:12px;border-top:1px solid var(--hairline-soft);">{esc(it["note"])}</div>')
        cards += (
            f'<div data-card style="background:var(--card);border:1px solid var(--cardline);border-radius:12px;'
            f'padding:18px 20px;margin-top:14px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px;">'
            f'<span style="color:var(--fg2);font-size:12px;font-weight:600;font-variant-numeric:tabular-nums;">{esc(it["id"])}</span>'
            f'<span style="color:var(--fg3);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;">{esc(it.get("kind",""))}</span>'
            f'</div><div style="display:grid;gap:14px;">{rows}</div>{note}</div>'
        )
    return cards


def raw_section(d) -> str:
    raw = d.get("raw")
    if not raw:
        return ""
    bd = raw["breakdown"]
    sr = raw["stripRules"]
    sm = raw["samples"]
    ag = raw["aggregate"]
    dot = '<span style="width:8px;height:8px;border-radius:50%;background:var(--accent);"></span>'
    verified = (f'<div style="display:inline-flex;align-items:center;gap:9px;margin-top:14px;color:var(--accent);'
                f'font-size:13px;font-weight:600;">{dot}{esc(bd["verified"])}</div>')
    return f"""
  <section id="appendix" data-section="appendix" style="scroll-margin-top:80px;border-top:1px solid var(--hairline-soft);">
    <div style="max-width:1200px;margin:0 auto;padding:64px 40px;">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:16px;">
        <span style="color:var(--accent);font-weight:600;font-size:13px;letter-spacing:.18em;text-transform:uppercase;">Appendix · {esc(raw['heading'])}</span>
        <button id="raw-toggle" class="no-print" style="border:1px solid var(--hairline);background:transparent;color:var(--fg2);font-family:inherit;font-size:12px;font-weight:600;padding:6px 14px;border-radius:999px;cursor:pointer;">Show</button>
      </div>
      <div class="raw-body" style="display:none;margin-top:22px;">
        <p style="color:var(--fg2);font-size:14px;line-height:1.6;max-width:88ch;margin:0 0 8px;">{esc(raw['intro'])}</p>

        {_subhead(bd['title'])}
        {_num_table(bd['columns'], bd['rows'])}
        {verified}

        {_subhead(sr['title'])}
        {_note(sr['note'])}
        {_strip_table(sr['columns'], sr['rows'])}

        {_subhead(sm['title'])}
        {_note(sm['note'])}
        {_samples(sm['items'])}

        {_subhead(ag.get('title', 'Forwarded payload'))}
        {_num_table(ag['columns'], ag['rows'], min_width=680)}
        <p style="color:var(--fg3);font-size:12px;line-height:1.55;max-width:92ch;margin:16px 0 0;">{esc(ag['note'])}</p>
      </div>
    </div>
  </section>"""


def footer(d) -> str:
    f = d["footer"]
    nxt = "".join(f'<span style="color:var(--fg2);font-size:14px;">{esc(x)}</span>' for x in f["next"])
    nav = d.get("nav", [("overview", "Overview"), ("benchmark", "The benchmark"),
                        ("latency", "Where the time goes"), ("method", "Method")])
    readout = "".join(
        f'<a class="foot" href="#{sid}" style="color:var(--fg2);font-size:14px;text-decoration:none;">{esc(label)}</a>'
        for sid, label in nav if sid not in ("overview", "appendix"))
    return f"""
  <footer style="border-top:1px solid var(--hairline);background:var(--card);">
    <div style="max-width:1200px;margin:0 auto;padding:52px 40px 30px;display:flex;gap:48px;flex-wrap:wrap;align-items:flex-start;">
      <div style="flex:1 1 300px;">
        <img class="logo-dark" src="{logo('logotype-tagline-dark.svg')}" alt="Nol8, The AI Data Plane" style="height:38px;">
        <img class="logo-light" src="{logo('logotype-tagline-full-color.svg')}" alt="Nol8, The AI Data Plane" style="height:38px;">
        <p style="color:var(--fg2);font-size:14px;line-height:1.55;margin:16px 0 0;max-width:34ch;">{esc(f['tagline'])}</p>
      </div>
      <div>
        <div style="color:var(--fg3);font-size:11px;letter-spacing:.14em;text-transform:uppercase;">This readout</div>
        <div style="display:flex;flex-direction:column;gap:10px;margin-top:14px;">{readout}
        </div>
      </div>
      <div>
        <div style="color:var(--fg3);font-size:11px;letter-spacing:.14em;text-transform:uppercase;">Next</div>
        <div style="display:flex;flex-direction:column;gap:10px;margin-top:14px;">{nxt}</div>
      </div>
    </div>
    <div style="max-width:1200px;margin:0 auto;padding:0 40px 34px;">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;padding-top:24px;border-top:1px solid var(--hairline-soft);">
        <span style="color:var(--fg3);font-size:13px;">{esc(f['copyright'])}</span>
        <span style="color:var(--fg3);font-size:13px;">{esc(f['confidential'])}</span>
      </div>
    </div>
  </footer>"""


def top_bar(d) -> str:
    return f"""
  <header class="no-print" style="position:sticky;top:0;z-index:50;background:var(--navbg);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border-bottom:1px solid var(--hairline-soft);">
    <div style="max-width:1200px;margin:0 auto;padding:0 40px;height:66px;display:flex;align-items:center;gap:20px;">
      <a href="#top" style="display:flex;align-items:center;">
        <img class="logo-dark" src="{logo('logotype-dark.svg')}" alt="Nol8" style="height:23px;">
        <img class="logo-light" src="{logo('logotype-full-color.svg')}" alt="Nol8" style="height:23px;">
      </a>
      <span style="color:var(--fg3);font-size:12px;letter-spacing:.12em;text-transform:uppercase;padding-left:18px;border-left:1px solid var(--hairline-soft);">{esc(d['navLabel'])}</span>
      <div style="margin-left:auto;display:flex;align-items:center;gap:14px;">
        <div style="display:flex;border:1px solid var(--hairline);border-radius:999px;overflow:hidden;">
          <button id="theme-dark" class="ttab" data-theme="dark" style="border:none;cursor:pointer;font-family:inherit;font-size:12px;font-weight:600;padding:7px 14px;">Dark</button>
          <button id="theme-light" class="ttab" data-theme="light" style="border:none;cursor:pointer;font-family:inherit;font-size:12px;font-weight:600;padding:7px 14px;">Light</button>
        </div>
        <button id="nav-toggle" aria-label="Menu" style="display:flex;align-items:center;justify-content:center;width:40px;height:40px;border:1px solid var(--hairline);border-radius:8px;background:transparent;color:var(--fg1);cursor:pointer;">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="7" x2="21" y2="7"></line><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="17" x2="21" y2="17"></line></svg>
        </button>
      </div>
    </div>
  </header>
  <div id="nav-drawer" class="no-print" style="display:none;">
    <div id="nav-scrim" style="position:fixed;inset:66px 0 0 0;z-index:40;background:rgba(0,0,0,0.35);"></div>
    <div style="position:fixed;top:66px;right:0;z-index:45;width:min(340px,86vw);background:var(--bg);border-left:1px solid var(--hairline);border-bottom:1px solid var(--hairline);padding:20px 20px 26px;animation:navIn .28s cubic-bezier(.2,.6,.2,1);">
      <div style="color:var(--fg3);font-size:11px;letter-spacing:.14em;text-transform:uppercase;padding:0 8px 10px;">On this page</div>
      {"".join(f'<a class="navlink" data-target="{sid}" href="#{sid}" style="display:flex;align-items:center;gap:12px;padding:12px 8px;border-radius:8px;text-decoration:none;font-size:16px;border-bottom:1px solid var(--hairline-soft);"><span class="navdot" style="width:6px;height:6px;border-radius:50%;flex-shrink:0;"></span>{label}</a>' for sid, label in d.get("nav", [("overview","Overview"),("benchmark","The benchmark"),("latency","Where the time goes"),("meaning","What it means"),("method","Method"),("appendix","Full data")]))}
    </div>
  </div>"""


BACK_TO_TOP = """
  <a id="back-to-top" href="#top" class="no-print" aria-label="Back to top" style="display:none;position:fixed;right:26px;bottom:26px;z-index:40;width:46px;height:46px;align-items:center;justify-content:center;background:var(--accent);color:#fff;border-radius:50%;text-decoration:none;box-shadow:0 6px 20px rgba(0,0,0,.35);">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="6 11 12 5 18 11"></polyline></svg>
  </a>"""


SCRIPT = """
<script>
(function(){
  var root=document.querySelector('[data-rpt]');
  var GREEN='#33B046';
  // ---- theme ----
  function paintTheme(){
    var light=root.getAttribute('data-theme')==='light';
    document.querySelectorAll('.ttab').forEach(function(b){
      var on=(b.getAttribute('data-theme')==='light')===light;
      b.style.background=on?GREEN:'transparent'; b.style.color=on?'#fff':'var(--fg2)';
    });
  }
  document.querySelectorAll('.ttab').forEach(function(b){
    b.addEventListener('click',function(){ root.setAttribute('data-theme',b.getAttribute('data-theme')); paintTheme(); });
  });
  // ---- engine compare tabs ----
  function paintEngine(view){
    document.querySelectorAll('[data-wf]').forEach(function(w){
      var k=w.getAttribute('data-engine'); w.style.opacity=(view==='both'||view===k)?'1':'0.3';
    });
    document.querySelectorAll('.etab').forEach(function(t){
      var on=t.getAttribute('data-view')===view;
      t.style.background=on?GREEN:'transparent'; t.style.color=on?'#fff':'var(--fg2)';
      t.style.border='1px solid '+(on?GREEN:'var(--hairline)');
    });
  }
  document.querySelectorAll('.etab').forEach(function(t){
    t.addEventListener('click',function(){ paintEngine(t.getAttribute('data-view')); });
  });
  // ---- nav drawer ----
  var drawer=document.getElementById('nav-drawer');
  function setNav(open){ drawer.style.display=open?'block':'none'; }
  document.getElementById('nav-toggle').addEventListener('click',function(){ setNav(drawer.style.display==='none'); });
  document.getElementById('nav-scrim').addEventListener('click',function(){ setNav(false); });
  document.querySelectorAll('.navlink').forEach(function(a){ a.addEventListener('click',function(){ setNav(false); }); });
  // ---- method toggle ----
  var mt=document.getElementById('method-toggle'), mb=document.querySelector('.method-body');
  mt.addEventListener('click',function(){ var hide=mb.style.display!=='none'; mb.style.display=hide?'none':'block'; mt.textContent=hide?'Show':'Hide'; });
  // ---- raw data appendix (collapsed by default) ----
  var rt=document.getElementById('raw-toggle'), rb=document.querySelector('.raw-body');
  if(rt&&rb){ rt.addEventListener('click',function(){ var open=rb.style.display==='none'; rb.style.display=open?'block':'none'; rt.textContent=open?'Hide':'Show'; }); }
  // ---- back to top + scroll-spy ----
  var btt=document.getElementById('back-to-top');
  var sections=[].slice.call(document.querySelectorAll('[data-section]'));
  function spy(){
    btt.style.display=window.scrollY>560?'flex':'none';
    var active=sections.length?sections[0].getAttribute('data-section'):'overview';
    sections.forEach(function(s){ if(s.getBoundingClientRect().top<150) active=s.getAttribute('data-section'); });
    document.querySelectorAll('.navlink').forEach(function(a){
      var on=a.getAttribute('data-target')===active;
      a.style.color=on?GREEN:'var(--fg2)'; a.style.fontWeight=on?'600':'400';
      a.querySelector('.navdot').style.background=on?GREEN:'var(--hairline)';
    });
  }
  window.addEventListener('scroll',spy,{passive:true});
  // Content is visible by default (no fade-gating), so nothing can get stuck
  // hidden if the page is wrapped by another runtime or JS partially fails.
  // Scroll-spy nav and back-to-top stay live.
  paintTheme(); paintEngine('both'); spy();
})();
</script>"""


# ---- DP2 (pre/post-inference control) sections ----
_ACTION_COLOR = {"block": WARN, "block_handoff": WARN, "block_tool": WARN, "route": WARN,
                 "redact": "var(--accent)", "mask": "var(--accent)", "drop": "var(--accent)",
                 "tag": "var(--accent)", "allow": "var(--fg3)"}


def _roadmap_badge() -> str:
    return ('<span style="display:inline-block;font-size:9.5px;font-weight:700;letter-spacing:.1em;'
            f'text-transform:uppercase;color:{WARN};border:1px solid {WARN};border-radius:999px;'
            'padding:1px 8px;white-space:nowrap;">Roadmap</span>')


def _action_badge(action: str, tags=None) -> str:
    color = _ACTION_COLOR.get(action, "var(--fg3)")
    label = action.upper()
    if tags:
        label += " · " + ", ".join(tags)
    return (f'<span style="display:inline-block;font-size:10px;font-weight:700;letter-spacing:.08em;'
            f'text-transform:uppercase;color:{color};border:1px solid {color};border-radius:999px;'
            f'padding:2px 9px;white-space:nowrap;">{esc(label)}</span>')


def boundary(d) -> str:
    b = d["boundary"]
    cards = _approach_cards(b["approaches"])
    cp = b["controlPoints"]

    def point(p, num):
        rows = "".join(
            f'<div style="display:flex;justify-content:space-between;gap:12px;padding:9px 0;'
            f'border-bottom:1px solid var(--hairline-soft);">'
            f'<span style="color:var(--fg2);font-size:13.5px;">{esc(a)}</span>'
            f'<span style="color:var(--accent);font-weight:600;font-size:13.5px;'
            f'font-variant-numeric:tabular-nums;white-space:nowrap;">{esc(n)}</span></div>'
            for a, n in p["actions"])
        return (f'<div data-card style="background:var(--card);border:1px solid var(--cardline);'
                f'border-radius:12px;padding:24px 26px;">'
                f'<div style="color:var(--accent);font-weight:600;font-size:11px;letter-spacing:.14em;'
                f'text-transform:uppercase;">{esc(num)}</div>'
                f'<div style="color:var(--fg1);font-weight:700;font-size:19px;margin-top:8px;">{esc(p["title"])}</div>'
                f'<p style="color:var(--fg3);font-size:13px;line-height:1.55;margin:8px 0 14px;">{esc(p["desc"])}</p>'
                f'{rows}</div>')

    return f"""
  <section id="benchmark" data-section="benchmark" style="scroll-margin-top:80px;">
    <div style="max-width:1200px;margin:0 auto;padding:88px 40px;">
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:22px;">
        <span style="color:var(--accent);font-weight:600;font-size:13px;letter-spacing:.18em;text-transform:uppercase;">01 · The boundary</span>
        <span style="flex:1;height:1px;background:var(--hairline-soft);"></span>
      </div>
      <h2 style="font-weight:700;font-size:38px;line-height:1.08;letter-spacing:-.01em;color:var(--fg1);margin:0;max-width:22ch;">{esc(b['heading'])}</h2>
      <p style="color:var(--fg2);font-size:17px;line-height:1.6;max-width:70ch;margin:14px 0 0;">{esc(b['lede'])}</p>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:18px;margin-top:36px;">{cards}
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px;margin-top:18px;">
        {point(cp['pre'], 'Control point 1')}
        {point(cp['post'], 'Control point 2')}
      </div>
    </div>
  </section>"""


def flows(d) -> str:
    f = d["flows"]
    cards = ""
    for it in f["items"]:
        called = it.get("inferenceCalled", True)
        step = lambda label_html, body: (
            f'<div><div style="font-size:10px;letter-spacing:.11em;text-transform:uppercase;font-weight:600;'
            f'color:var(--fg3);margin-bottom:4px;display:flex;align-items:center;gap:8px;">{label_html}</div>'
            f'<div style="font-size:12.5px;line-height:1.6;">{body}</div></div>')
        parts = [
            step("Prompt in", f'<span style="color:var(--fg1);">{esc(it["prompt"])}</span>'),
            step(f"Pre-inference control &rsaquo; {_action_badge(it['pre'], it.get('preTags'))}", ""),
        ]
        if called:
            # Full journey: the prompt reaches the model and both edges act.
            parts[-1] = step(f"Pre-inference control &rsaquo; {_action_badge(it['pre'], it.get('preTags'))}",
                             f'<span style="white-space:pre-wrap;color:var(--fg2);">{_chipify(esc(it["forwarded"]))}</span>')
            parts.append(step("Model",
                              f'<span style="white-space:pre-wrap;color:var(--fg2);">{esc(it["rawOutput"])}</span>'))
            parts.append(step(f"Post-inference control &rsaquo; {_action_badge(it['post'], it.get('postTags'))}",
                              f'<span style="white-space:pre-wrap;color:var(--fg2);">{_chipify(esc(it["final"])) if it.get("final") else "&mdash;"}</span>'))
        else:
            # Stopped at the boundary: the flow ends here. One clear outcome, no
            # fake model/post rows (there is no post decision to show).
            oc = it.get("outcome", "Stopped at the boundary. The model is never called.")
            color = _ACTION_COLOR.get(it["pre"], WARN)
            parts[-1] = step(f"Pre-inference control &rsaquo; {_action_badge(it['pre'], it.get('preTags'))}",
                             f'<div style="border-left:2px solid {color};padding:2px 0 2px 12px;color:{color};'
                             f'font-size:13px;line-height:1.55;">{esc(oc)}</div>')
        rows = "".join(parts)
        cards += (
            f'<div data-card style="background:var(--card);border:1px solid var(--cardline);border-radius:12px;'
            f'padding:18px 20px;margin-top:14px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px;">'
            f'<span style="color:var(--fg1);font-size:13px;font-weight:700;">{esc(it["label"])}</span>'
            f'<span style="color:var(--fg3);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;">{esc(it.get("category",""))}</span>'
            f'</div><div style="display:grid;gap:13px;">{rows}</div></div>')
    return f"""
  <section id="flows" data-section="flows" style="scroll-margin-top:80px;border-top:1px solid var(--hairline-soft);">
    <div style="max-width:1200px;margin:0 auto;padding:88px 40px;">
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:22px;">
        <span style="color:var(--accent);font-weight:600;font-size:13px;letter-spacing:.18em;text-transform:uppercase;">02 · Governance in action</span>
        <span style="flex:1;height:1px;background:var(--hairline-soft);"></span>
      </div>
      <h2 style="font-weight:700;font-size:38px;line-height:1.08;letter-spacing:-.01em;color:var(--fg1);margin:0;max-width:22ch;">{esc(f['heading'])}</h2>
      <p style="color:var(--fg2);font-size:17px;line-height:1.6;max-width:70ch;margin:14px 0 0;">{esc(f['lede'])}</p>
      <div style="margin-top:24px;">{cards}</div>
    </div>
  </section>"""


def dp2_appendix(d) -> str:
    raw = d["raw"]
    ag = raw["aggregate"]
    return f"""
  <section id="appendix" data-section="appendix" style="scroll-margin-top:80px;border-top:1px solid var(--hairline-soft);">
    <div style="max-width:1200px;margin:0 auto;padding:64px 40px;">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:16px;">
        <span style="color:var(--accent);font-weight:600;font-size:13px;letter-spacing:.18em;text-transform:uppercase;">Appendix · {esc(raw['heading'])}</span>
        <button id="raw-toggle" class="no-print" style="border:1px solid var(--hairline);background:transparent;color:var(--fg2);font-family:inherit;font-size:12px;font-weight:600;padding:6px 14px;border-radius:999px;cursor:pointer;">Show</button>
      </div>
      <div class="raw-body" style="display:none;margin-top:22px;">
        <p style="color:var(--fg2);font-size:14px;line-height:1.6;max-width:88ch;margin:0 0 14px;">{esc(raw['intro'])}</p>
        {_num_table(ag['columns'], ag['rows'], min_width=760)}
        <p style="color:var(--fg3);font-size:12px;line-height:1.55;max-width:92ch;margin:16px 0 0;">{esc(ag['note'])}</p>
      </div>
    </div>
  </section>"""


# ---- DP3 (agent-to-agent mesh control) sections ----
def mesh(d) -> str:
    m = d["mesh"]
    cards = _approach_cards(m["approaches"])
    chain = m.get("chain", [])
    chain_html = ""
    for i, stg in enumerate(chain):
        if i:
            chain_html += '<span style="color:var(--fg3);font-size:15px;">&rsaquo;</span>'
        chain_html += (f'<span style="color:var(--fg1);font-weight:600;font-size:13px;'
                       f'border:1px solid var(--cardline);border-radius:999px;padding:6px 14px;'
                       f'background:var(--card);white-space:nowrap;">{esc(stg)}</span>')

    def point(p, num):
        rows = "".join(
            f'<div style="display:flex;justify-content:space-between;gap:12px;padding:9px 0;'
            f'border-bottom:1px solid var(--hairline-soft);">'
            f'<span style="color:var(--fg2);font-size:13.5px;">{esc(a)}</span>'
            f'<span style="color:var(--accent);font-weight:600;font-size:13.5px;'
            f'font-variant-numeric:tabular-nums;white-space:nowrap;">{esc(str(n))}</span></div>'
            for a, n in p["actions"])
        return (f'<div data-card style="background:var(--card);border:1px solid var(--cardline);'
                f'border-radius:12px;padding:24px 26px;">'
                f'<div style="color:var(--accent);font-weight:600;font-size:11px;letter-spacing:.14em;'
                f'text-transform:uppercase;">{esc(num)}</div>'
                f'<div style="color:var(--fg1);font-weight:700;font-size:19px;margin-top:8px;">{esc(p["title"])}</div>'
                f'<p style="color:var(--fg3);font-size:13px;line-height:1.55;margin:8px 0 14px;">{esc(p["desc"])}</p>'
                f'{rows}</div>')

    points = "".join(point(p, f"Control point {i+1}") for i, p in enumerate(m["controlPoints"]))
    return f"""
  <section id="benchmark" data-section="benchmark" style="scroll-margin-top:80px;">
    <div style="max-width:1200px;margin:0 auto;padding:88px 40px;">
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:22px;">
        <span style="color:var(--accent);font-weight:600;font-size:13px;letter-spacing:.18em;text-transform:uppercase;">01 · The mesh</span>
        <span style="flex:1;height:1px;background:var(--hairline-soft);"></span>
      </div>
      <h2 style="font-weight:700;font-size:38px;line-height:1.08;letter-spacing:-.01em;color:var(--fg1);margin:0;max-width:22ch;">{esc(m['heading'])}</h2>
      <p style="color:var(--fg2);font-size:17px;line-height:1.6;max-width:70ch;margin:14px 0 0;">{esc(m['lede'])}</p>
      <div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-top:30px;">{chain_html}</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:18px;margin-top:30px;">{cards}
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;margin-top:18px;">{points}
      </div>
    </div>
  </section>"""


def mesh_flows(d) -> str:
    f = d["meshFlows"]
    cards = ""
    for it in f["items"]:
        steps = ""
        for st in it["steps"]:
            badge = _action_badge(st["action"])
            if st.get("roadmap"):
                badge += " " + _roadmap_badge()
            body = (f'<span style="white-space:pre-wrap;color:var(--fg2);">{_chipify(esc(st["text"]))}</span>'
                    if st.get("text") else "")
            steps += (f'<div><div style="font-size:10px;letter-spacing:.11em;text-transform:uppercase;font-weight:600;'
                      f'color:var(--fg3);margin-bottom:4px;display:flex;align-items:center;gap:8px;">'
                      f'{esc(st["stage"])} &rsaquo; {badge}</div>'
                      f'<div style="font-size:12.5px;line-height:1.6;">{body}</div></div>')
        oc = it.get("outcome", "")
        oc_color = _ACTION_COLOR.get(it.get("outcomeAction", ""), "var(--fg3)")
        outcome_html = (f'<div style="border-left:2px solid {oc_color};padding:2px 0 2px 12px;color:{oc_color};'
                        f'font-size:13px;line-height:1.55;margin-top:2px;">{esc(oc)}</div>') if oc else ""
        cards += (
            f'<div data-card style="background:var(--card);border:1px solid var(--cardline);border-radius:12px;'
            f'padding:18px 20px;margin-top:14px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px;">'
            f'<span style="color:var(--fg1);font-size:13px;font-weight:700;display:flex;align-items:center;gap:8px;">'
            f'{esc(it["label"])}{(" " + _roadmap_badge()) if it.get("roadmap") else ""}</span>'
            f'<span style="color:var(--fg3);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;">{esc(it.get("category",""))}</span>'
            f'</div>'
            f'<div style="font-size:10px;letter-spacing:.11em;text-transform:uppercase;font-weight:600;color:var(--fg3);margin-bottom:4px;">Task in</div>'
            f'<div style="font-size:12.5px;line-height:1.6;color:var(--fg1);margin-bottom:13px;">{esc(it["task"])}</div>'
            f'<div style="display:grid;gap:13px;">{steps}</div>{outcome_html}</div>')
    return f"""
  <section id="flows" data-section="flows" style="scroll-margin-top:80px;border-top:1px solid var(--hairline-soft);">
    <div style="max-width:1200px;margin:0 auto;padding:88px 40px;">
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:22px;">
        <span style="color:var(--accent);font-weight:600;font-size:13px;letter-spacing:.18em;text-transform:uppercase;">02 · Governance across the chain</span>
        <span style="flex:1;height:1px;background:var(--hairline-soft);"></span>
      </div>
      <h2 style="font-weight:700;font-size:38px;line-height:1.08;letter-spacing:-.01em;color:var(--fg1);margin:0;max-width:22ch;">{esc(f['heading'])}</h2>
      <p style="color:var(--fg2);font-size:17px;line-height:1.6;max-width:70ch;margin:14px 0 0;">{esc(f['lede'])}</p>
      <div style="margin-top:24px;">{cards}</div>
    </div>
  </section>"""


# ---- DP4: throughput at load (curves + percentile table) ----

# Engine line colors. Themis is the accent; Aergia gets a warm gold that reads on
# both themes and never collides with the green. Overridable per engine in run.json.
_DP4_ENGINE_COLOR = {"themis": "var(--accent)", "aergia": "#E0A63C"}


def _dp4_color(engine: str, engines_meta: dict) -> str:
    meta = engines_meta.get(engine, {})
    return meta.get("color") or _DP4_ENGINE_COLOR.get(engine, "var(--fg2)")


def _dp4_label(engine: str, engines_meta: dict) -> str:
    meta = engines_meta.get(engine, {})
    return meta.get("label") or engine.capitalize()


def _nice_max(v: float) -> float:
    """Round a max value up to a clean axis bound (1/2/5 x 10^n)."""
    if v <= 0:
        return 1.0
    import math
    exp = math.floor(math.log10(v))
    base = 10 ** exp
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * base:
            return m * base
    return 10 * base


def _fmt_num(v: float) -> str:
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 100:
        return f"{v:.0f}"
    if v >= 10:
        return f"{v:.1f}"
    return f"{v:.2f}"


def _svg_line_chart(series, xs, ymax, ylabel, title, unit="",
                    xlabel="concurrency (in-flight requests, log scale)") -> str:
    """A small, theme-aware line chart. x is log-scaled over the values `xs`;
    y is linear 0..ymax. `series` is a list of {label, color, points:[(x,y)]}.
    Colors may be CSS vars, so it themes itself.
    """
    import math
    W, H = 560, 320
    pad_l, pad_r, pad_t, pad_b = 58, 18, 40, 46
    pw, ph = W - pad_l - pad_r, H - pad_t - pad_b
    xmin, xmax = min(xs), max(xs)
    lxmin, lxmax = math.log(xmin), math.log(xmax)

    def xp(x):
        if lxmax == lxmin:
            return pad_l + pw / 2
        return pad_l + (math.log(x) - lxmin) / (lxmax - lxmin) * pw

    def yp(y):
        return pad_t + ph - (y / ymax if ymax else 0) * ph

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}" '
             f'style="width:100%;max-width:{W}px;height:auto;font-family:var(--font-ui);">']
    parts.append(f'<text x="{pad_l}" y="22" fill="var(--fg1)" font-size="13" '
                 f'font-weight="600">{esc(title)}</text>')
    # horizontal gridlines + y labels
    for i in range(5):
        gy = pad_t + ph - i / 4 * ph
        val = ymax * i / 4
        parts.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{pad_l+pw}" y2="{gy:.1f}" '
                     f'stroke="var(--hairline-soft)" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l-8}" y="{gy+3.5:.1f}" fill="var(--fg3)" font-size="10.5" '
                     f'text-anchor="end" style="font-variant-numeric:tabular-nums;">{_fmt_num(val)}</text>')
    parts.append(f'<text x="14" y="{pad_t+ph/2:.1f}" fill="var(--fg3)" font-size="10.5" '
                 f'text-anchor="middle" transform="rotate(-90 14 {pad_t+ph/2:.1f})">{esc(ylabel)}</text>')
    # x ticks at each concurrency value
    for x in xs:
        px = xp(x)
        parts.append(f'<line x1="{px:.1f}" y1="{pad_t+ph}" x2="{px:.1f}" y2="{pad_t+ph+4}" '
                     f'stroke="var(--hairline)" stroke-width="1"/>')
        parts.append(f'<text x="{px:.1f}" y="{pad_t+ph+18:.1f}" fill="var(--fg3)" font-size="10.5" '
                     f'text-anchor="middle" style="font-variant-numeric:tabular-nums;">{x}</text>')
    parts.append(f'<text x="{pad_l+pw/2:.1f}" y="{H-6}" fill="var(--fg3)" font-size="10.5" '
                 f'text-anchor="middle">{esc(xlabel)}</text>')
    # series
    for s in series:
        pts = [(xp(x), yp(y)) for x, y in s["points"]]
        d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        parts.append(f'<path d="{d}" fill="none" stroke="{s["color"]}" stroke-width="2.5" '
                     f'stroke-linejoin="round" stroke-linecap="round"/>')
        for px, py in pts:
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.2" fill="{s["color"]}"/>')
    # legend
    lx, ly = pad_l + 8, pad_t + 4
    for s in series:
        parts.append(f'<line x1="{lx}" y1="{ly}" x2="{lx+18}" y2="{ly}" stroke="{s["color"]}" stroke-width="2.5"/>')
        parts.append(f'<circle cx="{lx+9}" cy="{ly}" r="3.2" fill="{s["color"]}"/>')
        parts.append(f'<text x="{lx+24}" y="{ly+3.5}" fill="var(--fg2)" font-size="11" '
                     f'font-weight="600">{esc(s["label"])}</text>')
        lx += 34 + len(s["label"]) * 7
    parts.append("</svg>")
    return "".join(parts)


def _dp4_cells_index(cells):
    """Index cells by (engine, payload) -> sorted list by concurrency."""
    idx = {}
    for c in cells:
        idx.setdefault((c["engine"], c["payload"]), []).append(c)
    for k in idx:
        idx[k].sort(key=lambda c: c["concurrency"])
    return idx


def throughput(d) -> str:
    cells = d["cells"]
    engines = d.get("engineOrder") or sorted({c["engine"] for c in cells})
    engines_meta = d.get("engines", {})
    payloads = d.get("payloadOrder") or sorted({c["payload"] for c in cells})
    idx = _dp4_cells_index(cells)
    xs_all = sorted({c["concurrency"] for c in cells})

    blocks = ""
    for pay in payloads:
        # y bounds across engines for this payload
        rps_vals = [c["rps"] for e in engines for c in idx.get((e, pay), [])]
        p99_vals = [c["p99_ms"] for e in engines for c in idx.get((e, pay), [])]
        if not rps_vals:
            continue
        rps_max = _nice_max(max(rps_vals))
        p99_max = _nice_max(max(p99_vals))
        xs = sorted({c["concurrency"] for e in engines for c in idx.get((e, pay), [])})

        rps_series, p99_series = [], []
        for e in engines:
            pts = idx.get((e, pay), [])
            if not pts:
                continue
            color, label = _dp4_color(e, engines_meta), _dp4_label(e, engines_meta)
            rps_series.append({"label": label, "color": color,
                               "points": [(c["concurrency"], c["rps"]) for c in pts]})
            p99_series.append({"label": label, "color": color,
                               "points": [(c["concurrency"], c["p99_ms"]) for c in pts]})

        avg_bytes = next((c.get("avg_body_bytes") for e in engines for c in idx.get((e, pay), [])), 0)
        cap = f"{pay} payload &middot; ~{int(avg_bytes):,} bytes/request"
        blocks += f"""
        <div style="margin-top:34px;">
          <div style="color:var(--fg1);font-weight:700;font-size:15px;margin-bottom:2px;text-transform:capitalize;">{esc(pay)} payload</div>
          <div style="color:var(--fg3);font-size:12px;margin-bottom:14px;">{cap}</div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px;">
            <div data-card style="background:var(--card);border:1px solid var(--cardline);border-radius:12px;padding:14px 16px 8px;overflow-x:auto;">
              {_svg_line_chart(rps_series, xs, rps_max, "requests / sec", "Sustained throughput")}
            </div>
            <div data-card style="background:var(--card);border:1px solid var(--cardline);border-radius:12px;padding:14px 16px 8px;overflow-x:auto;">
              {_svg_line_chart(p99_series, xs, p99_max, "p99 latency (ms)", "Tail latency (p99)")}
            </div>
          </div>
        </div>"""

    return f"""
  <section id="throughput" data-section="throughput" style="scroll-margin-top:80px;border-top:1px solid var(--hairline-soft);">
    <div style="max-width:1200px;margin:0 auto;padding:72px 40px;">
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:22px;">
        <span style="color:var(--accent);font-weight:600;font-size:13px;letter-spacing:.18em;text-transform:uppercase;">01 &middot; Throughput under load</span>
        <span style="flex:1;height:1px;background:var(--hairline-soft);"></span>
      </div>
      <h2 style="font-weight:700;font-size:38px;line-height:1.08;letter-spacing:-.01em;color:var(--fg1);margin:0 0 12px;">{esc(d['throughputHeading'])}</h2>
      <p style="color:var(--fg2);font-size:15.5px;line-height:1.6;max-width:80ch;margin:0;">{esc(d['throughputLede'])}</p>
      {blocks}
    </div>
  </section>"""


def dp4_table(d) -> str:
    cells = d["cells"]
    engines = d.get("engineOrder") or sorted({c["engine"] for c in cells})
    engines_meta = d.get("engines", {})
    payloads = d.get("payloadOrder") or sorted({c["payload"] for c in cells})
    idx = _dp4_cells_index(cells)

    cols = ["Engine · concurrency", "req/s", "req MiB/s", "p50 ms", "p95 ms", "p99 ms", "p99.9 ms", "max ms", "errors"]
    tables = ""
    for pay in payloads:
        rows = []
        for e in engines:
            for c in idx.get((e, pay), []):
                label = f"{_dp4_label(e, engines_meta)} · c={c['concurrency']}"
                rows.append([
                    label,
                    _fmt_num(c["rps"]),
                    f"{c['request_mib_s']:.1f}",
                    f"{c['p50_ms']:.2f}",
                    f"{c['p95_ms']:.2f}",
                    f"{c['p99_ms']:.2f}",
                    f"{c['p999_ms']:.2f}",
                    f"{c['max_ms']:.1f}",
                    str(c.get("errors", 0)),
                ])
        if not rows:
            continue
        # Themis rows render green because the label carries "Themis"; keep that.
        tables += _subhead(f"{pay.capitalize()} payload", first=(tables == ""))
        tables += _num_table(cols, rows, min_width=720)

    return f"""
  <section id="table" data-section="table" style="scroll-margin-top:80px;border-top:1px solid var(--hairline-soft);">
    <div style="max-width:1200px;margin:0 auto;padding:64px 40px;">
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:22px;">
        <span style="color:var(--accent);font-weight:600;font-size:13px;letter-spacing:.18em;text-transform:uppercase;">02 &middot; The full grid</span>
        <span style="flex:1;height:1px;background:var(--hairline-soft);"></span>
      </div>
      <h2 style="font-weight:700;font-size:30px;line-height:1.1;letter-spacing:-.01em;color:var(--fg1);margin:0 0 8px;">Every cell, both engines</h2>
      {_note(d.get('tableNote', 'Each row is one measured 30s steady-state cell. Same policy, same corpus, same driver to both engines.'))}
      {tables}
    </div>
  </section>"""


def dp4_bounds(d) -> str:
    """The honest 'what bounded the run' block - integrity, do not skip."""
    items = ""
    for b in d.get("bounds", []):
        items += f"""
          <div style="display:flex;gap:14px;align-items:flex-start;">
            <span style="color:var(--accent);font-size:20px;font-weight:700;line-height:1.2;flex-shrink:0;">&rsaquo;</span>
            <div><span style="color:var(--fg1);font-weight:600;font-size:14.5px;">{esc(b['title'])}</span>
            <span style="color:var(--fg2);font-size:14px;line-height:1.55;"> — {esc(b['body'])}</span></div>
          </div>"""
    if not items:
        return ""
    return f"""
  <section id="bounds" style="scroll-margin-top:80px;border-top:1px solid var(--hairline-soft);">
    <div style="max-width:1000px;margin:0 auto;padding:56px 40px;">
      <h3 style="font-weight:700;font-size:20px;color:var(--fg1);margin:0 0 6px;">What bounded the run</h3>
      <p style="color:var(--fg3);font-size:13px;line-height:1.6;margin:0 0 22px;max-width:80ch;">So nobody over-reads a curve: here is what was actually limiting each region, measured, not assumed.</p>
      <div style="display:flex;flex-direction:column;gap:16px;">{items}
      </div>
    </div>
  </section>"""


def _document(body: str, title: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="omelette-owns-print" content="true">
<title>{esc(title)}</title>
<style>{build_css()}</style>
</head>
<body>
<div data-rpt data-theme="dark" style="background:var(--bg);color:var(--fg1);font-family:var(--font-ui);min-height:100vh;-webkit-font-smoothing:antialiased;">
{body}
</div>
{SCRIPT}
</body>
</html>"""


def build(run: dict) -> str:
    if run.get("kind") == "dp2":
        # DP2's honest action model is the same as DP3's, so it reuses the mesh/mesh_flows
        # sections (redact/mask live, route/block Roadmap). The older boundary()/flows()
        # renderers are retained but unused.
        sections = [top_bar(run), hero(run), stat_band(run), mesh(run),
                    mesh_flows(run), meaning(run), method(run), dp2_appendix(run), footer(run), BACK_TO_TOP]
        return _document("".join(sections), run.get("title", "NOL8 Pre/Post-Inference Control, Data Point 02"))
    if run.get("kind") == "dp3":
        sections = [top_bar(run), hero(run), stat_band(run), mesh(run),
                    mesh_flows(run), meaning(run), method(run), dp2_appendix(run), footer(run), BACK_TO_TOP]
        return _document("".join(sections), run.get("title", "NOL8 Agent-to-Agent Control, Data Point 03"))
    if run.get("kind") == "dp4":
        sections = [top_bar(run), hero(run), stat_band(run), throughput(run),
                    dp4_table(run), meaning(run), dp4_bounds(run), method(run), footer(run), BACK_TO_TOP]
        return _document("".join(sections), run.get("title", "NOL8 Throughput at Load, Data Point 04"))
    body = "".join([
        top_bar(run), hero(run), stat_band(run), benchmark(run),
        latency(run), meaning(run), method(run), raw_section(run), footer(run), BACK_TO_TOP,
    ])
    return _document(body, run.get("title", "NOL8 Pre-Index Governance, Data Point 01"))


def main() -> None:
    run_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "run.json"
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "pre-index-report.html"
    run = json.loads(run_path.read_text())
    out_path.write_text(build(run))
    kb = out_path.stat().st_size / 1024
    print(f"Wrote {out_path} ({kb:.0f} KB) from {run_path.name}")


if __name__ == "__main__":
    main()
