# Console UI — handoff for a UI/design pass

The live demo console (`server.py` + `static/index.html`) is **functionally
complete and honest**. This note is for whoever does the visual/interaction pass
(e.g. Fable): what you can freely polish, the **data contract** you build against,
and the **integrity rules you must not break**. This is a benchmark shown to
customers — a laundered number is worse than an ugly page.

## ⛔ Do NOT break the test pipeline (read this first)

This console drives a **real benchmark** against real engines. Under the pretty UI
is machinery that actually **generates data, builds a policy, pushes/deploys the
policy to both engines, drives load, and verifies output against the policy.** That
machinery is the product proof — if the UI pass breaks it, the demo lies.

**Your canvas is front-end only:** `static/index.html` (HTML/CSS/JS). Style it,
re-lay-it-out, animate it, add controls — freely.

**Off-limits without a heads-up (this is the "under the covers" logic):**
- `server.py` endpoint **behavior** and the **JSON response shapes** (the Data
  contract below) — the UI reads these; changing them silently breaks it.
- Anything that calls `validate policy … --target …` (deploy), the policy **build +
  safety guards** (`_byo_token/_byo_sanitize` — token≤15, ISSUE-004 overlaps), the
  **corpus build**, `call_process` (the `/v1/process` call), or the **dp4driver**
  invocation. These are the real test steps: make-policy → make-data → push-policy →
  run → verify. Do not "simplify," stub, mock, or fake any of them.
- The **deploy → settle → verify order** (the data plane loads the policy a few
  seconds after "applied"; skipping the settle makes correct redaction look broken).

If a visual idea needs a new/changed endpoint or a new data field, **add it to
server.py deliberately and update the contract below** — don't reshape the UI around
data that isn't really there. When unsure whether something is "UI" or "pipeline,"
it's pipeline: ask.

**Deliberate design you must NOT "optimize":** `/api/byo/correctness` verifies an
evenly-spaced **sample** (default 12) and runs **each engine sequentially on one
reused keep-alive connection, the two engines in parallel.** This is not laziness —
the software engine (Aergia) is bistable and **sheds/stalls requests when hit with
many parallel connections from this path** (measured: fine one run, 7/34 the next).
Verifying the whole corpus, or fanning out per-doc parallel calls, reintroduces that
flakiness. The full corpus IS exercised — in the load step, via the Go driver, which
Aergia tolerates. Leave the correctness sampling + per-engine-sequential model alone.

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

## Priority asks (from Jamie — do these first)

- **Bigger sample corpus — produce ≥50 records** in the first section. The bundled
  sample is only 3 docs, which is too small to be representative *and* trips the
  cache-fairness warning on the load step. Generate/prefill ~50+ realistic documents
  that actually contain the sample governed values (so correctness + load both look
  real). Keep them fictional (the "Meridian Financial" world in
  `demos/showcase/byo-poc/sample/` is the reference).
- **"add category" should help populate it** — don't just append an empty box. Scaffold
  a sensible category name + a few example values (or a picker of common types: card
  numbers, account IDs, customer names, sanctioned parties…), so an SA isn't staring at
  a blank field in front of a customer.
- **Add a "remove category"** control on each category row (currently you can add but
  not remove).

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
