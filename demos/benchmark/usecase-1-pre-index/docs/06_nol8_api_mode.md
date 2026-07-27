# Nol8 API Mode

## Purpose

`nol8_api` allows the benchmark to call a real Nol8-compatible endpoint instead of using local simulation.

This makes it possible for another engineering team to run the same benchmark against a real Nol8 deployment.

---

## Request / response contract

### Request
```json
{
  "text": "chunk text"
}
```

### Response
```json
{
  "action": "keep | mask | drop | route",
  "text": "processed text"
}
```

---

## Environment variables

Required:
- `NOL8_ENDPOINT`

Optional:
- `NOL8_API_KEY`
- `NOL8_TIMEOUT_MS`

Example:

```bash
export NOL8_ENDPOINT="https://nol8.example/process"
export NOL8_API_KEY="replace-me"
export NOL8_TIMEOUT_MS=2000
export MODES="nofilter re2 nol8_api"
bash scripts/run_all.sh
```

---

## Mock server

A local mock server is provided for contract validation.

Start it:

```bash
python3 python/mock_nol8_server.py
```

Then in another shell:

```bash
export NOL8_ENDPOINT="http://127.0.0.1:8787/process"
export MODES="nofilter re2 nol8_api"
bash scripts/run_all.sh
```

---

## Important note

The mock server is **not** meant to represent real Nol8 performance.
It exists only so engineers can validate:
- request format
- response parsing
- end-to-end benchmark wiring
- report generation

For the full external execution workflow and required returned artifacts, see:
- `docs/08_external_nol8_execution.md`
