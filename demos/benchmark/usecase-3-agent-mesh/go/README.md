# Go Runner

The runner executes the deterministic agent-mesh benchmark.

Example:

```bash
GOCACHE=../.gocache go run . \
  --mode listmesh \
  --input ../data/tasks/sample_agent_tasks.jsonl \
  --policy-dir ../data/policies \
  --output-dir ../results
```
