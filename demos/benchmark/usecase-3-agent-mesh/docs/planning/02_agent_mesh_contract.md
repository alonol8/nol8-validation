# Agent Mesh Contract

## Input task

Each task record contains:
- `task_id`
- `category`
- `benchmark_group`
- `user_task`
- `intent_note`
- `expected_mesh_action`
- `expected_final_action`
- `agent_stub_profile`

## Agent path

The deterministic harness uses this path:

```text
triage -> research -> decision -> action -> final
```

## Control actions

Allowed actions:
- `allow`
- `mask`
- `tag`
- `route`
- `block_handoff`
- `block_tool`
- `block`

## Output event

Each mode writes event records with:
- task identity
- mode
- agent stage
- event type
- action
- source agent
- target agent
- tool name
- original text
- processed text

## Metrics

The report summarizes:
- tasks total
- agent messages total
- messages masked
- handoffs blocked
- tasks routed
- tool calls attempted
- tool calls blocked
- final outputs blocked
- final outputs tagged
- sensitive-context exposures prevented
- contract alignment against expected actions
