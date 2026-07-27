# Go Benchmark

This benchmark compares:

- `nofilter`
- `re2`
- `listmatch`
- `nol8sim`

## Run

```bash
go run . ../data/sample_chunks.jsonl ../results/run_01.csv
```

`listmatch` loads deterministic reference lists from `../data/reference_lists/` by default.

Optional override:

```bash
REFERENCE_LIST_DIR=../data/reference_lists go run . ../data/sample_chunks.jsonl ../results/run_01.csv listmatch
```

## Notes

Go `regexp` uses RE2 syntax and linear-time matching behavior.
That makes it a strong traditional software baseline for deterministic pattern handling.
