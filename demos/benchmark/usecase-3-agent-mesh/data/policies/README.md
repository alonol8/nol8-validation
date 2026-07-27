# Agent Mesh Policies

These lists drive the `listmesh` mode.

Current policy mapping:
- `payment_cards.txt`: mask
- `account_ids.txt`: mask
- `flagged_customers.txt`: route
- `denied_entities.txt`: route
- `internal_projects.txt`: block handoff to external action agent
- `blocked_tool_phrases.txt`: block external tool call
- `output_block_phrases.txt`: block final output
- `output_tag_phrases.txt`: tag final output
