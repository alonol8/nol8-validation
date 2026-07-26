# Bring-Your-Own-Data POC

**A load generator is not a POC.** A customer evaluating NOL8 wants their three
questions answered with *their* inputs, not ours:

1. **Does it redact MY data correctly?** — oracle-verified on their documents.
2. **What does it cost at MY scale?** — the ~8-core software tax the FPGA offloads.
3. **Does it hold up at MY volume?** — a load pass on their own corpus.

This runs the full pipeline visibly on the customer's data:

> **ingest → build policy → build corpus → deploy (confirm applied) →
> correctness (both engines, oracle) → load (both engines) → summary**

Everything is deterministic literal replacement (listMatch). Same policy, same
data, same driver to both engines — divergence is reported honestly, never rigged.

## Run it

```bash
# on nol8-demo (reaches the engines)
cd /opt/nol8/nol8-validation
bash demos/showcase/byo-poc/run-byo-poc.sh                 # bundled sample, full pipeline
bash demos/showcase/byo-poc/run-byo-poc.sh <dir> --skip-load   # correctness + cost only, fast
```

## Give it a customer's data

Point it at a directory laid out like the bundled `sample/`:

```
<customer-dir>/
  values/
    watched_customers.txt      # one governed value per line; filename -> token
    account_ids.txt            #   e.g. account_ids.txt -> [ACCOUNT_IDS]
    card_numbers.txt
    ...                        # add as many category files as they have
  documents/
    *.txt / *.md               # their sample documents, OR
    corpus.jsonl               # a single .jsonl of {"message": "..."} records
```

- **Tokens** are derived from each filename, capped at 15 chars (runtime limit),
  and de-duped automatically.
- **Safety guards** (from our own findings): values contained inside other values
  are dropped-and-reported rather than deployed (overlapping literals corrupt
  output — ISSUE-004); tokens over 15 chars would truncate (ISSUE-005). The policy
  we deploy is always safe.
- **Cache-fairness:** the load pass warns if the corpus has fewer than a few
  thousand distinct documents — a tiny working set lets a *software* engine serve
  repeats warm from CPU cache, which flatters it. For a fair volume number, supply
  a representative sample.

## What "good" looks like

- **Correctness:** every in-scope governed value gone, its token present, on both
  engines — and both engines return *identical* output.
- **Cost:** the software path burns ~8 CPU cores on the RE2 lexers that the FPGA
  does in silicon (run `demos/showcase/efficiency-demo.sh` for the live core count).
- **Volume:** throughput/latency on *their* corpus, both engines, with the FPGA's
  lead reported honestly for their data.

The bundled `sample/` is fictional ("Meridian Financial") and safe to demo as-is.
