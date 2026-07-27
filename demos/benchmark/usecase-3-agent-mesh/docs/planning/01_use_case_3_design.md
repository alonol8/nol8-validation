# Use Case 3 Design

## Core question

What should be allowed to move between agents, tools, and final output?

## Why this is different from Use Case 2

Use Case 2 controls a single model boundary.

Use Case 3 controls a workflow where information moves through multiple agent roles:
- triage
- research
- decision
- action
- final response

Each hop can leak, amplify, or misuse context.

## Benchmark story

The benchmark models an enterprise agent mesh that handles support, fraud, compliance, and operations tasks.

The control layer should decide:
- whether a message can move to the next agent
- whether sensitive values must be masked
- whether a task should route to a controlled workflow
- whether a tool call should be blocked
- whether final output can be released

## First-pass modes

- `nocontrol`: no agent-to-agent controls
- `re2_mesh`: pattern-driven software controls
- `listmesh`: exact enterprise policy-list controls
- `nol8sim_agent`: target behavior placeholder based on the benchmark contract

## Later real Nol8 path

The future measured path should send the same task/event contract to a real Nol8 endpoint and return the same event fields.

Until that exists, `nol8sim_agent` remains a behavior placeholder.
