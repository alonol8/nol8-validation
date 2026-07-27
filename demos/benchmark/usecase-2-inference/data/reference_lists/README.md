# Reference Lists

These files drive the `listguard` mode for Use Case 2.

They represent first-pass deterministic controls around the model boundary:
- values that should be masked before inference
- entities or phrases that should cause routing
- phrases that should block model access
- internal references that should be tagged

Current files:
- `payment_cards.txt`
- `account_ids.txt`
- `flagged_customers.txt`
- `denied_entities.txt`
- `internal_projects.txt`
- `block_phrases.txt`
- `route_phrases.txt`
- `output_block_phrases.txt`
- `output_tag_phrases.txt`
