# Live Nol8 Integration Notes

This note is for the internal team when a real Nol8 engine endpoint is ready for Use Case 3.

The benchmark should keep the same dataset, expected actions, event contract, and report shape. The implementation detail that changes is the control mode behind the agent mesh.

## What should stay stable

Keep these stable so old and new runs can be compared:
- `data/tasks/sample_agent_tasks.jsonl`
- `expected_mesh_action`
- `expected_final_action`
- event fields from `02_agent_mesh_contract.md`
- CSV columns written to `results/run_all.csv`
- report sections and metric names

If the dataset changes, treat that as a new benchmark revision instead of silently replacing the current one.

## What should change

Add a real Nol8-backed mode beside the simulated mode.

Suggested mode name:
- `nol8_api_agent`

Keep `nol8sim_agent` in place until the real mode has enough successful runs to compare behavior and explain any differences.

The real mode should call Nol8 at the same decision points used by the deterministic harness:
- agent handoff
- external tool call
- final output

Each call should return or be mapped into one of the benchmark actions:
- `allow`
- `mask`
- `tag`
- `route`
- `block_handoff`
- `block_tool`
- `block`

## Configuration needed later

Do not hard-code endpoint details in the dataset or report.

Expected runtime configuration:
- `NOL8_API_BASE_URL`
- `NOL8_API_KEY`
- optional policy or tenant identifier
- optional timeout and retry settings

The runner should fail clearly if the real mode is requested and required configuration is missing.

## Report language

When `nol8_api_agent` is added, update the report language carefully:
- `nol8sim_agent` remains a behavior placeholder
- `nol8_api_agent` is measured engine behavior
- product claims should use only measured `nol8_api_agent` rows

Do not remove the simulated caveat until the report no longer includes simulated rows.

## First validation checklist

Before treating the real mode as comparable:
- Run the same 12-task dataset locally.
- Confirm the real mode writes the same event fields as the other modes.
- Confirm masked output does not leak original sensitive values.
- Confirm blocked handoffs do not continue into tool calls.
- Confirm routed tasks produce the intended controlled final response.
- Confirm `contract_alignment_count` can be explained row by row.
- Save the raw event JSONL for review before presenting summary metrics.
