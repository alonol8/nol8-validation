# Use Case 2 — Pre/Post-Inference Control

## Purpose

This document defines the proposed benchmark for **Use Case 2: Pre/Post-Inference Control**.

Use Case 1 asks:
- what should become embeddings?

Use Case 2 asks:
- what should be allowed to reach the model?
- what should be allowed to leave the model?

This benchmark is meant to show how deterministic control can reduce wasted inference work, constrain privacy/compliance exposure, and create a clearer path to a future Nol8 control plane around model interaction.

## Core benchmark question

Can a deterministic control layer:
- block or reroute prompts before they reach the model
- mask or suppress sensitive prompt content before inference
- block, mask, or tag unsafe/sensitive outputs after inference
- do so with an understandable software baseline and measurable resource cost

## Why this matters

This use case is the next logical stage after pre-index optimization.

Pre-index control protects:
- embedding spend
- vector storage
- retrieval quality

Pre/post-inference control protects:
- model invocation spend
- prompt privacy
- output compliance
- downstream human and system consumers

The broader Nol8 platform story remains the same:
- reduce expensive general-purpose CPU dependence
- protect expensive AI infrastructure
- enforce deterministic privacy/compliance controls around data in motion

## First-pass benchmark scope

This benchmark should stay narrowly scoped to deterministic pre/post-inference controls.

It is **not** yet:
- full red teaming
- full jailbreak research
- semantic moderation research
- model-quality evaluation
- agentic mesh behavior

The benchmark should focus on control points around a model boundary.

## Explainability standard

This benchmark must remain explainable to customers, prospects, and internal stakeholders.

That means benchmark rows should represent recognizable governance scenarios, not obscure implementation tricks.

For every test we add, we should be able to explain:
- what real control problem it represents
- why the expected control action is reasonable
- what tradeoff the row helps illustrate

If a test only makes sense as an internal implementation edge case, it should stay out of the main benchmark set or be moved into a separate engineering-only overlay.

## Proposed benchmark flow

```text
Prompt/Input -> Pre-Inference Control -> Model Stub or Simulated Model -> Post-Inference Control -> Final Output
```

The benchmark should treat the model itself as outside the proof target.

The goal is to measure the control layer around the model, not model quality.

## Benchmark objective

Compared with a no-control baseline and a traditional software baseline, the benchmark should show:
- how many prompts are blocked or rerouted before inference
- how much prompt content is masked before inference
- how many outputs are blocked, masked, or tagged after inference
- how much downstream prompt/output token volume is avoided
- what CPU cost the software path incurs to enforce those controls
