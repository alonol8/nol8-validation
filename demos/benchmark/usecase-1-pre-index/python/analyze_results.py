import csv
import json
import sys
from pathlib import Path

def pct(n, d):
    return 0.0 if d == 0 else (n / d) * 100.0

def load_resources(results_csv: Path):
    candidate = results_csv.parent / "resource_metrics.json"
    if candidate.exists():
        return json.loads(candidate.read_text())
    return {}

def main(path_str: str):
    path = Path(path_str)
    rows = list(csv.DictReader(path.open()))
    resources = load_resources(path)

    print(f"Loaded {len(rows)} benchmark rows from {path}\n")

    headers = [
        "mode",
        "chunks_total",
        "chunks_kept",
        "chunks_masked",
        "chunks_dropped",
        "chunks_routed",
        "tokens_in_est",
        "tokens_forwarded_est",
        "preprocess_ms",
        "chunks_per_sec",
    ]
    print(" | ".join(headers))
    print("-" * 120)
    for r in rows:
        print(" | ".join(str(r[h]) for h in headers))

    print("\nDerived metrics")
    print("-" * 120)
    baseline = next((r for r in rows if r["mode"] == "nofilter"), None)
    base_tokens = int(baseline["tokens_forwarded_est"]) if baseline else 0
    for r in rows:
        total = int(r["chunks_total"])
        tokens_in = int(r["tokens_in_est"])
        tokens_fwd = int(r["tokens_forwarded_est"])
        dropped = int(r["chunks_dropped"])
        routed = int(r.get("chunks_routed", 0))
        reduced = tokens_in - tokens_fwd
        reduction_vs_baseline = ((base_tokens - tokens_fwd) / base_tokens * 100.0) if base_tokens else 0.0
        print(
            f'{r["mode"]}: '
            f'drop_rate={pct(dropped, total):.1f}% | '
            f'route_rate={pct(routed, total):.1f}% | '
            f'token_reduction_vs_input={pct(reduced, tokens_in):.1f}% | '
            f'token_reduction_vs_baseline={reduction_vs_baseline:.1f}% | '
            f'forwarded_tokens={tokens_fwd}'
        )

    if resources:
        print("\nResource metrics")
        print("-" * 120)
        for mode, vals in resources.items():
            user = vals.get("user_cpu_seconds", 0.0)
            system = vals.get("system_cpu_seconds", 0.0)
            total_cpu = user + system
            print(
                f"{mode}: cpu_seconds={total_cpu:.3f} | "
                f"cpu_percent={vals.get('cpu_percent','')} | "
                f"elapsed_seconds={vals.get('elapsed_seconds', 0.0):.3f} | "
                f"max_rss_kb={vals.get('max_rss_kb', 0)}"
            )

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python analyze_results.py <results.csv>")
        raise SystemExit(1)
    main(sys.argv[1])
