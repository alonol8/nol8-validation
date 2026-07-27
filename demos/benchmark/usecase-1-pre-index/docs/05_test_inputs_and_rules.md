# Test Inputs and Rules

## Small sample from the included dataset

```text
Welcome to Acme Corp Internal Portal
Contact: john.doe@acme.com
SSN: 123-45-6789
Elastic provides a distributed search and analytics engine that supports large-scale querying across logs, metrics, and application telemetry.
Legal Disclaimer: This document is confidential and intended only for internal use.
```

## Expected transformation outcome

```text
Contact: [MASKED]@acme.com
SSN: XXX-XX-6789
Elastic provides a distributed search and analytics engine that supports large-scale querying across logs, metrics, and application telemetry.
```

## Regex / pattern rules used in the benchmark

### Email masking
```regex
([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})
```

Replacement:
```text
[MASKED]@$2
```

### SSN masking
```regex
\b(\d{3})-(\d{2})-(\d{4})\b
```

Replacement:
```text
XXX-XX-$3
```

### Phone masking
```regex
\b(\d{3})-(\d{3})-(\d{4})\b
```

Replacement:
```text
XXX-XXX-$3
```

### Account ID masking
```regex
\bACC-\d{4}-\d{4}\b
```

Replacement:
```text
[MASKED_ACCOUNT_ID]
```

### Drop rules
```regex
(?im)^Welcome to .*
(?im)^Navigation:.*
(?im)^Footer:.*
(?im)^Legal Disclaimer:.*
(?im)^Cookie Notice:.*
```

## Why these rules were chosen

They are intentionally simple and defensible:
- common enterprise boilerplate
- common sensitive identifiers
- deterministic behavior
- easy to explain to engineers and executives

## What this proves

This benchmark is meant to show:
- how much junk can be removed before embedding
- how much sensitive data can be masked before embedding
- how much payload and token volume can be avoided
- what resource cost is required to do that work

## Reference-list matching used in the benchmark

The `listmatch` path is simpler than the regex path:

- load known values from plain-text files under `data/reference_lists/`
- compare each chunk against those known values
- apply one deterministic action per chunk

Current list-driven action mapping:
- `customers.txt` -> `route`
- `denied_entities.txt` -> `route`
- `bad_ips.txt` -> `drop`
- `compromised_accounts.txt` -> `drop`
- `payment_cards.txt` -> `mask`

Per-chunk action priority:
1. `drop`
2. `route`
3. `mask`
4. `keep`

That means:
- a chunk with a bad IP is dropped even if it also contains a customer name
- a chunk with a customer name is routed before any payment-card masking would matter
- a chunk with only a listed payment-card value is masked and still forwarded

This is the first-pass enterprise use case because it is:
- easy to explain
- based on real customer-owned inputs
- deterministic
- a credible software baseline for later real Nol8 comparison
