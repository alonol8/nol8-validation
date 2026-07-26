# Console UI — handoff for a UI/design pass

The live demo console (`server.py` + `static/index.html`) is **functionally
complete and honest**. This note is for whoever does the visual/interaction pass
(e.g. Fable): what you can freely polish, the **data contract** you build against,
and the **integrity rules you must not break**. This is a benchmark shown to
customers — a laundered number is worse than an ugly page.

## What the page is

A dependency-free (Python stdlib) single-page console on `nol8-demo` that drives the
real engines. Cards, top to bottom:
1. **Bring Your Own Data (flagship)** — paste a customer's governed values + docs,
   then build → deploy → verify → load, each step revealing its output.
2. **Drive it / Head-to-head** — one message through both engines, redaction + stats.
3. **Corpus** — run the built-in catalog through both engines.
4. **Scale** — a sustained load burst (numbers currently pre-10-Argus; being re-based).
5. **Efficiency** — CPU-cost contrast measured on the engine hosts.

Run it: `bash console/run.sh` on nol8-demo → `ssh -f -N -L 8770:localhost:8770
nol8-demo` → http://localhost:8770. (The `-f -N` matters; plain `-L` won't persist.)

## Data contract (build the UI against these; don't change shapes without updating server.py)

All POST, JSON in/out. Errors come back as `{"error": "..."}` with a non-200.

- `POST /api/process` `{engine, message}` → `{before, after, checks[], verified,
  in_scope, near_misses[], matches_per_kb, message_bytes, response_bytes, latency_ms}`
- `POST /api/batch` → per-engine `{agg{...}, rows[]}` over the catalog.
- `POST /api/scale` `{concurrency, duration}` → per-engine load result (+ note).
- `POST /api/byo/build` `{categories:[{name,values}], documents:[str]}` →
  `{rule_count, categories:[{token,label,count}], dropped:[{value,why}],
  policy_preview:[str], docs, avg_bytes, doc_sample}`
- `POST /api/byo/deploy` → `{status:{engine:{state,label}}, settled}`
- `POST /api/byo/correctness` → `{rows[], totals:{engine:{verified,in_scope,pct,label}},
  parity_ok, parity_total}`
- `POST /api/byo/load` `{engine?, concurrency, duration}` → `{engines:{engine:{label,
  cells:[{payload,rps,p99,errors,mib_s}]}}, distinct_docs, warn?, ratio?}`.
  **Pass `engine` to drive ONE engine** (the UI calls it twice for live progress).

## Integrity rules — do NOT break these

1. **The cache-fairness `warn` on load MUST stay visible** whenever present. A small
   working set (few distinct docs) inflates the software engine (CPU cache); hiding
   the warning turns a caveated number into a lie. Same for any future warning field.
2. **Absolute req/s is point-in-time on a shared host.** Fine to show, but the
   defensible facts are the **ratio** and the **CPU cost** — lead with those, don't
   present a single absolute as "the" number.
3. **Never fabricate "live" data.** No fake tickers, no interpolated rps between real
   samples presented as measured. The driver reports once per cell; a progress
   animation is fine, invented numbers are not.
4. **Keep engine labels honest** — Themis = FPGA, Aergia = RE2 software. Don't imply
   NOL8 does anything beyond deterministic literal replacement (no "blocking",
   "masking as enforcement", classification).
5. **Deploy → settle → verify ordering is load-bearing.** The control plane returns
   "applied" before the data plane loads the policy; the server waits `settled`
   seconds. Don't let the UI race ahead of it.

## Known UI TODOs (good places for the pass)

- **Load step real-time feel.** Now has a status panel + elapsed timer + per-engine
  step lines + incremental cards. Could become live bar charts / a race viz as each
  engine's number lands. (True per-tick rps isn't available — the driver reports per
  cell — so animate around the real end-of-cell numbers, don't invent intermediate.)
- **Build/deploy/verify feedback** is just button spinners; could match the load
  step's status treatment for consistency.
- **Layout / hierarchy** — the BYO card is dense (two-column inputs + four staged
  buttons + four output regions). Could use step-wise progressive disclosure.
- **Mobile / narrow** — grids collapse but haven't been designed for small screens.
- **File upload** for values/docs (currently paste only); backend accepts the same
  shapes, so this is front-end + a small parse.
- **Empty/error states** are minimal (a red line). Could be friendlier.

## Brand

Charcoal `#404040`, green `#33B046`, Google Sans (served from `/assets/fonts/`),
dark web mode. Logo at `/assets/logo.svg`. Full guide: `~/Code/nol8/nol8-brand-guide`.
