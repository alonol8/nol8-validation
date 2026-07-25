# NOL8 Showcase Demo — SA Runbook

A self-contained, SA-runnable demo you can drive live. Two acts:

1. **It works, provably — at all three control points.** The *same* deterministic
   redaction through the real customer API (`/v1/process`), shown where customers
   actually need it: **pre-embedding**, **pre/post-inference**, and **agent-to-agent** —
   each verified against an oracle.
2. **Why the hardware matters** — the FPGA does that matching in silicon, freeing
   ~8 CPU cores the software approach has to burn continuously.

No Grafana, no external load generator, no cloud dashboard — just the live engines
and a couple of scripts. Everything here is measured, not asserted.

**One capability, three use cases.** NOL8 does one thing — deterministic literal
replacement through `/v1/process`. What changes per use case is only *where in the
pipeline it sits*. Each has a benchmark-depth proof already: DP1 (pre-index),
DP2 (pre/post-inference), DP3 (agent mesh); the showcase is the runnable, customer-
facing version of all three.

## Honest scope (say this up front)

- NOL8 does **deterministic literal replacement only** (listMatch, exact match).
  It finds known governed values and swaps them for a token. It does **not**
  classify, route, block, or enforce — a downstream control plane acts on the
  redacted output. "Redaction" here = substitution, and it is lossy by design.
- No regex in v1.0.0 (on the roadmap). Every value in the demo policy is a literal.

## What you need

- On the VPN; `bash demos/check-engines.sh` shows **6/6** (both engines reachable).
- **Two run locations** (the normal two-host workflow):
  - **`nol8-demo`** (EC2) — reaches the engines; runs the redaction act.
  - **Your laptop** — has `~/.ssh/config` for `themis-demo` + `aergia-demo`; runs
    the efficiency act (it samples the engine hosts directly).

---

## Two ways to run it

- **The visual console** (below) — a live, on-brand web UI. Best for a customer room.
- **The CLI tour** (Acts 1–2 further down) — same engine calls, terminal output.
  Best for a quick headless check or when you can't open a browser.

---

## The visual console (recommended for live demos)

A dark, on-brand NOL8 web console that drives `/v1/process` live. Dependency-free
(Python stdlib), no Grafana. What it does:

- **Prompt catalog** — 18 realistic prompts across the three use cases (plus your own).
- **Head-to-head** — runs the *same* message through **both engines at once** and
  shows the redactions side by side with **per-request latency, verified count, match
  density, and bytes** for each, plus a compare strip (who's faster, outputs identical).
- **Corpus automation** — one click runs the **whole catalog through both engines** and
  shows an aggregate dashboard (docs verified, mean/p95 latency, docs/s, density) with a
  per-document detail table.
- **Scale** — a real sustained-load burst: deploys a **matched 8k-rule enterprise policy**
  to both engines, drives the DP4 driver at 256 concurrency (~8s each), shows **live
  throughput** (Themis leads, ~1.2–1.4×), then restores the demo policy. *(Apples-to-apples
  only — a mismatched tiny policy makes software look faster on clean text; the console
  enforces a deployable matched policy. Absolute req/s is a live point-in-time number that
  swings with shared-host load; the FPGA's lead and its CPU cost are the stable facts.)*
- **Efficiency panel** — the ~8-core software tax the FPGA offloads, as cores + %-of-box,
  **validated flat under load** (F2 held ~11.3/24 cores while sustaining ~27k req/s).

```bash
# 1) on the box that reaches the engines — leave this running (foreground)
ssh nol8-demo
cd /opt/nol8/nol8-validation
bash demos/showcase/console/run.sh          # deploys the policy, serves on 0.0.0.0:8770
```

**Then open it — two ways:**

- **Direct over the VPN (simplest):** in your Mac browser go to `http://10.8.10.40:8770`
  (the box's VPC IP; the console binds all interfaces). Requires the security group to
  allow inbound TCP 8770 from your VPN CIDR — if the page hangs, that's the SG, not the
  server.
- **SSH tunnel (always works, no SG change — recommended):** the blocked port doesn't
  matter because this rides SSH (port 22). One-liner, background tunnel, nothing to
  babysit:
  ```bash
  ssh -f -N -L 8770:localhost:8770 nol8-demo    # -f -N = runs quietly in the background
  open http://localhost:8770                      # browse the console
  # stop it later:  pkill -f '8770:localhost:8770'
  ```

(`CONSOLE_HOST=127.0.0.1 bash …/run.sh` restricts it to localhost / tunnel-only.)

In the console: choose **Pre-embedding / Pre-post-inference / Agent-to-agent** (or
edit your own message), toggle **Themis (FPGA)** vs **Aergia (RE2 software)**, hit
**Process**. Both engines return identical, oracle-verified output; the efficiency
panel shows the ~8-core software tax the FPGA offloads. `Ctrl-C` on `nol8-demo` stops it.

---

## Act 1 — The three use cases through `/v1/process`  (run on `nol8-demo`)

The customer-facing surface is a single synchronous HTTPS call — no SDK, no agent,
no API key in the request. Send a message, get the processed message back. The tour
runs all three use cases back-to-back, oracle-verifying each:

```bash
ssh nol8-demo
cd /opt/nol8/nol8-validation
bash demos/showcase/usecases-demo.sh               # Themis (FPGA, :443)
```

| # | Use case | Control point | Depth |
|---|---|---|---|
| 1 | **Pre-embedding** (RAG ingestion) | Redact before text is chunked and embedded — sensitive values never enter the vector store. | DP1 |
| 2 | **Pre/post-inference** (model boundary) | Redact before the prompt reaches the model — the LLM, its provider, and its logs never see them. | DP2 |
| 3 | **Agent-to-agent** (mesh hop) | Redact at the hop between agents — the receiving agent acts only on cleaned data. | DP3 |

Each prints **BEFORE / AFTER / ORACLE**; expected finish:

```
  TOUR COMPLETE — 3/3 use cases redacted and oracle-verified on Themis (FPGA)
```

**The oracle is derived from the policy itself** — for every governed value present
in the input, it checks the raw value is gone and the policy's token is present. A
green result means the engine's output provably matches the policy. (If a governed
value is split across a line break it can't match as a literal — the tool warns you
rather than silently miss it.)

**Match density is reported on every run** (`N matches in B bytes = X matches/KB`).
The stock scenarios sit at **~7–9 matches/KB** — a realistic density for messages of
this type. Density doesn't change the (deterministic) redaction result here; it's the
variable *software throughput* is sensitive to, which is why we surface it on every
run and stress it deliberately in the DP4 throughput work. To demo a denser message,
point `redact-demo.sh` at your own file with `MSG_FILE=`.

**Prove correctness parity** — run the identical tour through the software engine:

```bash
ENGINE=aergia bash demos/showcase/usecases-demo.sh   # RE2 software (:444)
```

Both engines return the **same** output. That sets up Act 2: *same correctness —
very different cost.*

**Focus on one, or make it theirs** — the single-message variant takes any file:

```bash
bash demos/showcase/redact-demo.sh                       # one SOC-alert example
MSG_FILE=/path/to/their-sample.txt bash demos/showcase/redact-demo.sh
```

**What to say:** "Same engine, same production call, three places a customer needs
it — before you embed, around the model, and between agents. The governed values
come back gone, deterministically, every time, and we just proved it against the
policy, not against my word. The FPGA and a standard software matcher produce
identical output. Now look at what each one costs to run."

---

## Act 2 — The efficiency contrast  (run on your laptop)

```bash
bash demos/showcase/efficiency-demo.sh
```

It samples the real cores each engine's data plane consumes on its host and prints:

```
  engine                     data-plane    matcher      TOTAL
  Themis (FPGA, :443)             11.3      FPGA/0      11.3
  Aergia (RE2 sw, :444)           11.2        8.2       19.4

  Software tax the FPGA eliminates:   ~8 CPU cores (the RE2 lexers)
  Cores per 1k req/s:  Themis 0.39   vs   Aergia 0.74   →  ~1.9x
```

Both engines share the same data plane (Apollo, ~11 cores) — that's common cost, so
it's a fair subtraction. The difference is the **~8 dedicated cores the RE2 lexers
burn** and the FPGA does not. Because both data planes are **DPDK poll-mode**, those
cores are consumed *continuously* — the software matcher is burning 8 cores in the
output above while serving **zero** live traffic. That is the standing cost, and it
does not improve under load.

**What to say:** "Same job, same correct output. The software path spends ~8 CPU
cores on the matching, all the time, whether or not requests are flowing. The FPGA
does it in silicon and hands those cores back. At fleet scale that's the power,
core, and dollar line on your bill — roughly half the host CPU per request."

---

## The one-liner

> Same deterministic result the customer can verify themselves — at roughly half
> the host CPU per request, because the FPGA does the matching in silicon instead
> of burning ~8 cores to do it in software.

## Where this sits

- **Correctness at depth:** DP1–DP3 (oracle-verified: replacement, parity, payload).
- **Throughput at load:** DP4 (`docs/DP4-THROUGHPUT-BRIEF.md`) — engines are close on
  raw req/s (FPGA ~1.09x on small); the real separation is the CPU cost shown here.
- **Scope & positioning memory:** listMatch-only today; substitution not enforcement.
