# Data

## Included dataset

- `sample_chunks.jsonl`
- `reference_lists/`

This starter dataset is intended to model a first-pass enterprise listmatch benchmark with:
- keepable technical/business content
- support, fraud, and compliance notes
- regex-detectable sensitive patterns
- customer/watchlist examples
- bad IP indicators
- compromised account identifiers
- payment-card test values
- mixed-content chunks and near-misses

## Format

Each line is JSON:
- `id`
- `category`
- `text`

## Reference-list mode

The `reference_lists/` folder supports the `listmatch` benchmark mode.

Included lists:
- `customers.txt`
- `bad_ips.txt`
- `denied_entities.txt`
- `compromised_accounts.txt`
- `payment_cards.txt`
- `internal_projects.txt`
- `regulated_datasets.txt`

Default action policy:
- customers: `route`
- denied entities: `route`
- bad IPs: `drop`
- compromised accounts: `drop`
- payment cards: `mask`

## Larger datasets

Use `generate_dataset.py` to create larger datasets for benchmarking.

Examples:

```bash
python generate_dataset.py --count 1000 --output sample_1k.jsonl
python generate_dataset.py --count 10000 --output sample_10k.jsonl
python generate_dataset.py --count 100000 --output sample_100k.jsonl
```
