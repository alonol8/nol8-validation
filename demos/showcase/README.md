# demos/showcase — the customer-facing NOL8 demo

A self-contained, SA-runnable end-to-end demo. Read **[RUNBOOK.md](RUNBOOK.md)** —
it's the whole thing (narrative, commands, what to say). No Grafana, no external
load generator, no cloud dashboard; just the live engines and two scripts.

| File | What it is |
|---|---|
| `RUNBOOK.md` | The SA guide — two acts, where to run each, expected output, talk track. |
| `usecases-demo.sh` | **Act 1** — the three use cases (pre-embedding / pre-post-inference / agent-to-agent) through `/v1/process`, each oracle-verified. Run on `nol8-demo`. |
| `scenarios/*.txt` | One realistic message per use case (real governed values, so the oracle verifies). |
| `redact-demo.sh` / `redact-demo.py` | Single-message variant of Act 1 — point it at any file with `MSG_FILE=`. Oracle + line-wrap near-miss warning built in. |
| `efficiency-demo.sh` | **Act 2** — the FPGA-vs-software CPU cost, sampled on the engine hosts. Run on your laptop (needs `themis-demo` + `aergia-demo` in `~/.ssh/config`). |
| `sample-message.txt` | The single-message default (a SOC alert). |

**The story:** one capability at three control points — same deterministic,
customer-verifiable result from the FPGA and a standard software matcher — at
roughly half the host CPU per request, because the FPGA does the matching in
silicon instead of burning ~8 cores in software.

Scope: listMatch (literal) replacement only; substitution, not enforcement.
Companion: `docs/DP4-THROUGHPUT-BRIEF.md` (throughput) and DP1–DP3 (correctness).
