import csv
import json
import sys
from pathlib import Path

INSTANCE_SPECS = {
    "c6i.2xlarge": {
        "vcpu": 8,
        "memory_gib": 16,
        "cpu_arch": "x86_64",
    }
}

MODE_METADATA = {
    "nofilter": {
        "role": "baseline",
        "is_measured": True,
        "is_simulated": False,
        "eligible_for_performance_claims": True,
    },
    "re2": {
        "role": "software_baseline",
        "is_measured": True,
        "is_simulated": False,
        "eligible_for_performance_claims": True,
    },
    "listmatch": {
        "role": "software_baseline",
        "is_measured": True,
        "is_simulated": False,
        "eligible_for_performance_claims": True,
    },
    "nol8sim": {
        "role": "behavioral_placeholder",
        "is_measured": False,
        "is_simulated": True,
        "eligible_for_performance_claims": False,
    },
    "nol8_api": {
        "role": "external_api_mode",
        "is_measured": False,
        "is_simulated": False,
        "eligible_for_performance_claims": False,
    },
    # Real product engines, measured over the network via the adapter. listMatch
    # (literal) policy on both; Themis is the FPGA path, Aergia the second engine.
    "themis_api": {
        "role": "measured_product",
        "is_measured": True,
        "is_simulated": False,
        "eligible_for_performance_claims": True,
    },
    "aergia_api": {
        "role": "measured_product",
        "is_measured": True,
        "is_simulated": False,
        "eligible_for_performance_claims": True,
    },
}


def num(value, default=0.0):
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def pct(numerator, denominator):
    if denominator == 0:
        return 0.0
    return (numerator / denominator) * 100.0


def pct_delta_lower_is_better(base, current):
    if base == 0:
        return 0.0
    return ((base - current) / base) * 100.0


def load_metadata(html_path: Path, metadata_path_str: str | None = None):
    candidates = []
    if metadata_path_str:
        candidates.append(Path(metadata_path_str))
    candidates.append(html_path.parent.parent / "benchmark_run_metadata.json")

    for candidate in candidates:
        if candidate.exists():
            metadata = json.loads(candidate.read_text())
            specs = INSTANCE_SPECS.get(metadata.get("instance_type", ""), {})
            if specs:
                metadata["instance_specs"] = specs
            return metadata
    return {}


def normalize_result_rows(rows):
    normalized = []
    for row in rows:
        normalized.append(
            {
                "mode": row["mode"],
                "chunks_total": int(row["chunks_total"]),
                "chunks_kept": int(row["chunks_kept"]),
                "chunks_masked": int(row["chunks_masked"]),
                "chunks_dropped": int(row["chunks_dropped"]),
                "chunks_routed": int(row.get("chunks_routed", 0)),
                "chars_in": int(row["chars_in"]),
                "chars_forwarded": int(row["chars_forwarded"]),
                "tokens_in_est": int(row["tokens_in_est"]),
                "tokens_forwarded_est": int(row["tokens_forwarded_est"]),
                "preprocess_ms": num(row["preprocess_ms"]),
                "chunks_per_sec": num(row["chunks_per_sec"]),
                "embed_cost_units_est": int(row["embed_cost_units_est"]),
            }
        )
    return normalized


def normalize_resources(raw_resources):
    normalized = {}
    for mode, values in raw_resources.items():
        user_cpu = num(values.get("user_cpu_seconds"))
        system_cpu = num(values.get("system_cpu_seconds"))
        total_cpu = user_cpu + system_cpu
        cpu_percent = values.get("cpu_percent", "")
        cpu_cores_used_est = num(str(cpu_percent).replace("%", "")) / 100.0 if cpu_percent else 0.0
        normalized[mode] = {
            "user_cpu_seconds": user_cpu,
            "system_cpu_seconds": system_cpu,
            "total_cpu_seconds": total_cpu,
            "elapsed_seconds": num(values.get("elapsed_seconds")),
            "cpu_percent": cpu_percent,
            "cpu_cores_used_est": cpu_cores_used_est,
            "max_rss_kb": int(values.get("max_rss_kb", 0)),
        }
    return normalized


def build_derived_metrics(results, resources):
    by_mode = {row["mode"]: row for row in results}
    baseline = by_mode.get("nofilter", {})
    re2 = by_mode.get("re2", {})

    baseline_tokens = baseline.get("tokens_forwarded_est", 0)
    baseline_chars = baseline.get("chars_forwarded", 0)
    re2_total_cpu = resources.get("re2", {}).get("total_cpu_seconds", 0.0)

    derived = {}
    for row in results:
        mode = row["mode"]
        total = row["chunks_total"]
        prevented = row["chunks_dropped"] + row["chunks_routed"]
        governed = prevented + row["chunks_masked"]
        total_cpu = resources.get(mode, {}).get("total_cpu_seconds", 0.0)

        derived[mode] = {
            "drop_rate_pct": round(pct(row["chunks_dropped"], total), 1),
            "route_rate_pct": round(pct(row["chunks_routed"], total), 1),
            "mask_rate_pct": round(pct(row["chunks_masked"], total), 1),
            "prevented_from_embedding_pct": round(pct(prevented, total), 1),
            "governed_share_pct": round(pct(governed, total), 1),
            "token_reduction_vs_baseline_pct": round(
                pct_delta_lower_is_better(baseline_tokens, row["tokens_forwarded_est"]), 1
            ),
            "payload_reduction_vs_baseline_pct": round(
                pct_delta_lower_is_better(baseline_chars, row["chars_forwarded"]), 1
            ),
            "estimated_embedding_cost_delta_vs_baseline_pct": round(
                pct_delta_lower_is_better(baseline.get("embed_cost_units_est", 0), row["embed_cost_units_est"]), 1
            ),
            "tokens_reduced_per_cpu_sec": round(
                max(0, baseline_tokens - row["tokens_forwarded_est"]) / total_cpu, 1
            )
            if total_cpu > 0
            else 0.0,
            "payload_reduced_per_cpu_sec": round(
                max(0, baseline_chars - row["chars_forwarded"]) / total_cpu, 1
            )
            if total_cpu > 0
            else 0.0,
            "chunks_processed_per_cpu_sec": round(total / total_cpu, 1) if total_cpu > 0 else 0.0,
            "cpu_multiple_vs_re2": round(total_cpu / re2_total_cpu, 2) if re2_total_cpu > 0 else None,
        }
    return derived


def build_interpretation_flags(results):
    mode_metadata = {}
    contains_simulated = False
    contains_real_nol8 = False

    for row in results:
        mode = row["mode"]
        metadata = MODE_METADATA.get(
            mode,
            {
                "role": "unknown",
                "is_measured": True,
                "is_simulated": False,
                "eligible_for_performance_claims": False,
            },
        )
        mode_metadata[mode] = metadata
        if metadata["is_simulated"]:
            contains_simulated = True
        if metadata["role"] == "measured_product" and metadata["is_measured"]:
            contains_real_nol8 = True

    return mode_metadata, {
        "contains_simulated_modes": contains_simulated,
        "contains_real_nol8_results": contains_real_nol8,
        "safe_for_product_claims": contains_real_nol8,
    }


def build_report_data(csv_path, html_path, resources_path_str=None, metadata_path_str=None):
    rows = list(csv.DictReader(csv_path.open()))
    results = normalize_result_rows(rows)

    raw_resources = {}
    if resources_path_str:
        resources_path = Path(resources_path_str)
        if resources_path.exists():
            raw_resources = json.loads(resources_path.read_text())
    resources = normalize_resources(raw_resources)
    metadata = load_metadata(html_path, metadata_path_str)
    mode_metadata, interpretation_flags = build_interpretation_flags(results)
    derived_metrics = build_derived_metrics(results, resources)

    dataset_metadata = {
        "dataset_path": "data/sample_chunks.jsonl",
        "chunks_total": results[0]["chunks_total"] if results else 0,
        "dataset_profile": "enterprise_listmatch_first_pass",
        "synthetic": True,
    }

    benchmark_metadata = {
        "benchmark_name": "Data Point 1 - Pre-Index Optimization",
        **metadata,
    }

    return {
        "benchmark_metadata": benchmark_metadata,
        "dataset_metadata": dataset_metadata,
        "mode_metadata": mode_metadata,
        "results": results,
        "resources": resources,
        "derived_metrics": derived_metrics,
        "interpretation_flags": interpretation_flags,
    }


def render_html(template_path: Path, html_path: Path, report_data: dict):
    template = template_path.read_text()
    report_json = json.dumps(report_data).replace("</", "<\\/")
    html = template.replace("__REPORT_DATA__", report_json)
    html_path.write_text(html)


def main(csv_path_str: str, html_path_str: str, resources_path_str: str | None = None, metadata_path_str: str | None = None):
    csv_path = Path(csv_path_str)
    html_path = Path(html_path_str)
    template_path = html_path.parent / "report_template.html"
    report_data_path = html_path.parent / "report_data.json"
    ai_summary_path = html_path.parent / "ai_summary.json"

    report_data = build_report_data(csv_path, html_path, resources_path_str, metadata_path_str)
    if ai_summary_path.exists():
        try:
            report_data["ai_summary"] = json.loads(ai_summary_path.read_text())
        except json.JSONDecodeError:
            report_data["ai_summary"] = None
    else:
        report_data["ai_summary"] = None
    report_data_path.write_text(json.dumps(report_data, indent=2))
    render_html(template_path, html_path, report_data)
    print(f"Report data ready: {report_data_path}")
    print(f"Report ready: {html_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python generate_report.py <input.csv> <output.html> [resource_metrics.json] [benchmark_run_metadata.json]")
        raise SystemExit(1)
    resources = sys.argv[3] if len(sys.argv) >= 4 else None
    metadata = sys.argv[4] if len(sys.argv) >= 5 else None
    main(sys.argv[1], sys.argv[2], resources, metadata)
