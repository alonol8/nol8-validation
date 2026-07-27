# Use Case 1 — Pre-Index Optimization

## Executive summary

Pre-index optimization is the control point where Nol8 evaluates text **before** it becomes embeddings.

That matters because once text has been embedded:
- you have already paid the compute cost
- you have already created storage overhead
- you have already allowed low-value or sensitive content into the retrieval system

The core idea is simple:

Only relevant, compliant, and useful content should become embeddings.

For the first benchmark pass, the most explainable enterprise use case is deterministic matching against known reference data:
- customer watchlists
- denied or sanctioned entities
- bad IP addresses
- compromised account identifiers
- payment-card values and related indicators

Plain-English version:

"Take a chunk of text and compare it against lists the customer already has. If the chunk contains a known bad value, drop it. If it contains something that should be reviewed, route it. If it contains a listed sensitive value, mask it. Otherwise keep it."

---

## Where Nol8 sits

```text
Chunk -> Nol8 -> Embed -> Store
```

Nol8 sits between chunking and embedding.

It does **not** replace:
- the embedding model
- the vector database
- retrieval
- the LLM

It acts as a control layer on text while the text is still interpretable and cheap to process.

---

## What Nol8 does here

At this point in the flow, Nol8 can perform deterministic operations such as:

- boilerplate removal
- disclaimer removal
- navigation/header/footer stripping
- masking sensitive values
- metadata extraction
- deterministic reference-list lookups
- keep / drop / route decisions

Example decisions:
- keep technical product text
- mask payment-card values
- route watchlist customers or denied entities to review instead of embedding
- drop known-bad indicators such as compromised accounts or bad IPs

The first-pass benchmark is intentionally this direct:
- not fuzzy matching
- not classification by inference
- not the full long-term Nol8 scope

It is the simplest defensible benchmark for the message:
enterprises already own lists of things they know matter, and software has to spend CPU to enforce those controls before embedding.

---

## Why this matters

This is the last clean point before cost compounds.

After this stage, cost begins to stack in multiple places:

- embedding compute
- vector storage
- retrieval noise
- token waste later in generation
- policy/compliance exposure

If you embed junk, you do not just pay once.
You pay repeatedly:
- during indexing
- during retrieval
- during downstream LLM prompt construction

That is why the underlying value proposition is bigger than filtering:
- reduce CPU dependence in the software control path
- preserve downstream GPU spend for embedding and inference work you actually want
- enforce privacy and compliance before data reaches expensive AI infrastructure

---

## Talking points

### Technical
- "A chunk is still plain text at this point, which means deterministic control is cheap and explainable."
- "Once embedded, raw structure is gone and cost has already been incurred."
- "Garbage indexed becomes garbage retrieved."
- "The software baseline proves this can be done on CPU. The Nol8 story is doing the same class of control in a much better compute envelope."

### Executive
- "This is where Nol8 reduces avoidable AI cost before it starts."
- "The value is not making AI smarter. The value is ensuring AI operates on the right data."
- "This is a control point for cost, quality, and compliance."
- "The first benchmark uses known enterprise lists because that is the simplest real control customers already have."

---

## What not to say

Do not say:
- "Nol8 is the RAG system"
- "Nol8 replaces the embedding pipeline"
- "Nol8 accelerates AI models"

Say instead:
- "Nol8 controls what data deserves to become embeddings."
- "Nol8 reduces what flows into expensive downstream AI steps."
- "Nol8 operates before data becomes expensive, irreversible, or risky."

---

## Benchmark hypothesis

If Nol8 is valuable at this stage, then compared with a no-filter baseline and a traditional software-only control stage, it should:

- reduce forwarded token volume
- reduce estimated embedding cost
- preserve useful content
- clearly explain what is kept, masked, dropped, or routed
- show credible throughput
- make the CPU cost of the incumbent software path visible

---

## Testable example

Input chunk:

```text
Customer review: Northwind Trading requested accelerated enablement for the Aurora Ledger workflow.
SOC alert: repeated failed sign-ins from 203.0.113.45 hit the customer support portal during the same 20-minute window.
Chargeback investigation note: the caller provided test card 4111 1111 1111 1111 during payment validation.
The analyst assistant should prioritize incident timelines, account context, and remediation notes over boilerplate.
```

Expected result after pre-index processing:

```text
[routed for review: Northwind Trading]
[dropped: 203.0.113.45]
Chargeback investigation note: the caller provided test card [MASKED_CARD] during payment validation.
The analyst assistant should prioritize incident timelines, account context, and remediation notes over boilerplate.
```

This demonstrates:
- list-driven routing
- list-driven dropping
- masking
- preservation of useful content
- reduced text sent to embedding
