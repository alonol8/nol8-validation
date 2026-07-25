# NOL8 Showcase Demo — SA Runbook

A self-contained, SA-runnable demo you can drive live. Two short acts:

1. **It works, provably** — deterministic redaction of known sensitive values
   through the real customer API (`/v1/process`), verified against an oracle.
2. **Why the hardware matters** — the FPGA does that matching in silicon, freeing
   ~8 CPU cores the software approach has to burn continuously.

No Grafana, no external load generator, no cloud dashboard — just the live engines
and two scripts. Everything here is measured, not asserted.

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

## Act 1 — Live redaction through `/v1/process`  (run on `nol8-demo`)

The customer-facing surface is a single synchronous HTTPS call — no SDK, no agent,
no API key in the request. Send a message, get the processed message back.

```bash
ssh nol8-demo
cd /opt/nol8/nol8-validation
bash demos/showcase/redact-demo.sh                 # Themis (FPGA, :443)
```

It deploys the known-values policy, sends `sample-message.txt` (a realistic SOC
alert containing a watched customer, a payment card, a blocked IP, a sanctioned
entity, a compromised account, and an internal project), and prints **BEFORE /
AFTER / ORACLE**. Expected finish:

```
  6/6 governed values redacted and verified.
  Deterministic literal replacement confirmed against the oracle.
```

**The oracle is derived from the policy itself** — for every governed value present
in the input, it checks the raw value is gone and the policy's token is present. A
green result means the engine's output provably matches the policy.

**Prove correctness parity** — run the identical message through the software engine:

```bash
ENGINE=aergia bash demos/showcase/redact-demo.sh   # RE2 software (:444)
```

Both return the **same** output. That sets up Act 2: *same correctness — very
different cost.*

**Make it theirs:** point it at any message.

```bash
MSG_FILE=/path/to/their-sample.txt bash demos/showcase/redact-demo.sh
```

**What to say:** "This is the actual production call. The values that come back
are gone, deterministically, every time — and we just proved it against the policy,
not against my word. The FPGA and a standard software matcher produce identical
output. Now look at what each one costs to run."

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
