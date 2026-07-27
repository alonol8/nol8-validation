# Agent Task Dataset

`sample_agent_tasks.jsonl` contains synthetic enterprise agent workflow tasks.

Each row represents one user task that moves through:

```text
triage -> research -> decision -> action -> final
```

The expected action fields define the target benchmark contract for `nol8sim_agent`.
