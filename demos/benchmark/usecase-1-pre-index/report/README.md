# HTML Report

Generate a simple single-page HTML report plus structured report data from a benchmark CSV.

## Run
```bash
python generate_report.py ../results/run_01.csv report.html
```

This writes:
- `report.html`
- `report_data.json`

The HTML report is the human-readable artifact.

The structured source of truth is:
- `report_data.json`

Optional future artifact:
- `ai_summary.json`

If `ai_summary.json` exists, the HTML report will render an AI summary section above the deterministic tables.
