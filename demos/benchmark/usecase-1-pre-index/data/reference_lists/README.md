# Reference Lists

These files drive the `listmatch` benchmark mode.

Each file is a plain-text list with one entry per line.

Current action mapping:
- `customers.txt`: `route`
- `denied_entities.txt`: `route`
- `bad_ips.txt`: `drop`
- `compromised_accounts.txt`: `drop`
- `payment_cards.txt`: `mask`
- `internal_projects.txt`: future tagging / routing support
- `regulated_datasets.txt`: future tagging / routing support

These lists are packaged inside the benchmark pack so the AWS harness can copy and run the full test case without any external dependencies.
