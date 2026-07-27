# Agentic RAG Overlay — Where Nol8 Fits

## Purpose

This document captures the exact positioning narrative for Nol8 in RAG and Agentic RAG.

It is intentionally disciplined:
- Nol8 is not the model
- Nol8 is not the vector database
- Nol8 is not the orchestrator

Nol8 is a data-in-motion control layer.

---

## Agentic RAG structure

Traditional RAG is generally linear:

```text
Query -> Retrieve -> Augment -> Generate
```

Agentic RAG is iterative:

```text
Plan -> Retrieve -> Evaluate -> Refine -> Retrieve -> Generate -> Validate -> Repeat
```

This introduces repeated decisions, repeated retrieval, and repeated model calls.

That means:
- cost can compound faster
- retrieval mistakes can compound faster
- policy mistakes can compound faster

---

## Nol8 control points

Nol8 fits at three specific control points.

### 1. Pre-Index (Offline path)

```text
Chunk -> Nol8 -> Embed -> Store
```

Function:
- control what becomes embeddings

Responsibilities:
- remove boilerplate
- mask or remove sensitive data
- normalize content
- enrich metadata
- decide whether content should be indexed
- route or tag known entities and governed datasets before indexing

Talking points:
- "This is the last point where data is cheap and fully interpretable."
- "Once embedded, you have already paid the cost."
- "Garbage indexed becomes garbage retrieved."
- "The first enterprise benchmark is list-driven because customers already have watchlists, sanctioned entities, bad-IP feeds, and governed data sources."

---

### 2. Retrieval Control (Inside the agent loop)

```text
Retrieve -> Nol8 -> Agent
```

Function:
- shape retrieved context before the agent consumes it

Responsibilities:
- remove irrelevant chunks
- deduplicate results
- enforce policy constraints
- prioritize better context
- suppress restricted content
- preserve routing and classification signals created earlier in the data path

Talking points:
- "Agents reason on what they see."
- "Bad retrieval compounds across loops."
- "Each iteration must improve context quality, not degrade it."

---

### 3. Pre-Inference Control (Every model call)

```text
Agent -> Nol8 -> LLM
```

Function:
- shape the final prompt before every model invocation

Responsibilities:
- remove sensitive values
- reduce token volume
- enforce guardrails
- apply model-routing decisions if needed
- honor upstream tags and compliance classifications created before embedding

Talking points:
- "Every LLM call has cost."
- "Agentic systems multiply that cost."
- "This is the last gate before tokens become dollars."

---

## Summary statement

Nol8 does not make AI systems smarter.

It ensures that:
- the data entering AI systems is correct
- the data circulating inside AI systems is controlled
- the data sent to models is efficient and compliant
- expensive CPU and GPU stages are reserved for work that deserves to proceed

---

## Core positioning statement

Nol8 operates at the last possible moment before data becomes expensive, irreversible, or risky.
