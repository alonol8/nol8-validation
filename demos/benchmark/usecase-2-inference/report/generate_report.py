#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


MODE_METADATA = {
    "nocontrol": {
        "label": "nocontrol (Baseline)",
        "role": "baseline",
        "is_simulated": False,
    },
    "re2_guard": {
        "label": "re2_guard (Software Baseline)",
        "role": "software_baseline",
        "is_simulated": False,
    },
    "listguard": {
        "label": "listguard (Reference Lists)",
        "role": "software_baseline",
        "is_simulated": False,
    },
    "nol8sim_infer": {
        "label": "nol8sim_infer (Behavior Placeholder)",
        "role": "behavioral_placeholder",
        "is_simulated": True,
    },
    "nol8_api_infer": {
        "label": "nol8_api_infer (Measured API Mode)",
        "role": "measured_mode",
        "is_simulated": False,
    },
}


INT_FIELDS = {
    "prompts_total",
    "prompts_allowed",
    "prompts_masked",
    "prompts_blocked",
    "prompts_routed",
    "prompts_tagged",
    "inference_calls_made",
    "inference_calls_avoided",
    "prompt_tokens_in_est",
    "prompt_tokens_forwarded_est",
    "outputs_total",
    "outputs_allowed",
    "outputs_masked",
    "outputs_blocked",
    "outputs_tagged",
    "output_tokens_raw_est",
    "output_tokens_released_est",
}


FLOAT_FIELDS = {
    "preprocess_ms",
    "postprocess_ms",
    "total_control_ms",
    "records_per_sec",
}


def read_results(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            parsed = {"mode": row["mode"]}
            for key, value in row.items():
                if key == "mode":
                    continue
                if key in INT_FIELDS:
                    parsed[key] = int(value)
                elif key in FLOAT_FIELDS:
                    parsed[key] = float(value)
                else:
                    parsed[key] = value
            rows.append(parsed)
    return rows


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def pct(part: float, whole: float) -> float:
    if not whole:
        return 0.0
    return (part / whole) * 100.0


def build_contract_analysis(prompt_records: list[dict], results_dir: Path, modes: list[str]) -> dict:
    prompt_map = {record["prompt_id"]: record for record in prompt_records}
    group_names = list(dict.fromkeys(record.get("benchmark_group", "unknown") for record in prompt_records))
    action_names = list(dict.fromkeys(record.get("expected_pre_action", "unknown") for record in prompt_records))
    analysis: dict[str, dict] = {}

    for mode in modes:
        output_path = results_dir / f"{mode}_output.jsonl"
        if not output_path.exists():
            continue

        records = read_jsonl(output_path)
        exact_matches = 0
        missed_governed = 0
        over_governed = 0
        governed_matches = 0
        governed_expected = 0
        action_counts = Counter()
        expected_action_totals = Counter()
        action_breakdown: dict[str, dict] = {}
        group_breakdown: dict[str, dict] = {}

        for group_name in group_names:
            group_breakdown[group_name] = {
                "total": 0,
                "expected_match_count": 0,
                "expected_match_pct": 0.0,
                "pre_actions": {},
                "post_actions": {},
            }

        for action_name in action_names:
            action_breakdown[action_name] = {
                "expected_total": 0,
                "matched_count": 0,
                "matched_pct": 0.0,
            }

        for record in records:
            prompt = prompt_map.get(record["prompt_id"])
            if prompt is None:
                continue

            group_name = prompt.get("benchmark_group", "unknown")
            expected_action = prompt.get("expected_pre_action", "unknown")
            actual_action = record.get("pre_action", "unknown")
            matches = actual_action == expected_action

            action_counts[actual_action] += 1
            expected_action_totals[expected_action] += 1
            group_breakdown[group_name]["total"] += 1
            group_breakdown[group_name]["pre_actions"][actual_action] = (
                group_breakdown[group_name]["pre_actions"].get(actual_action, 0) + 1
            )
            post_action = record.get("post_action", "unknown")
            group_breakdown[group_name]["post_actions"][post_action] = (
                group_breakdown[group_name]["post_actions"].get(post_action, 0) + 1
            )
            action_breakdown[expected_action]["expected_total"] += 1
            if matches:
                exact_matches += 1
                group_breakdown[group_name]["expected_match_count"] += 1
                action_breakdown[expected_action]["matched_count"] += 1

            if expected_action != "allow":
                governed_expected += 1
                if actual_action == expected_action:
                    governed_matches += 1
                if actual_action == "allow":
                    missed_governed += 1
            elif actual_action != "allow":
                over_governed += 1

        for values in group_breakdown.values():
            values["expected_match_pct"] = pct(values["expected_match_count"], values["total"])
        for action_name in action_names:
            action_breakdown[action_name]["matched_pct"] = pct(
                action_breakdown[action_name]["matched_count"],
                action_breakdown[action_name]["expected_total"],
            )

        analysis[mode] = {
            "pre_action_alignment_count": exact_matches,
            "pre_action_alignment_pct": pct(exact_matches, len(records)),
            "contract_miss_count": len(records) - exact_matches,
            "contract_miss_pct": pct(len(records) - exact_matches, len(records)),
            "missed_governed_count": missed_governed,
            "missed_governed_pct": pct(missed_governed, len(records)),
            "over_governed_allow_count": over_governed,
            "over_governed_allow_pct": pct(over_governed, len(records)),
            "governed_action_match_count": governed_matches,
            "governed_action_match_pct": pct(governed_matches, governed_expected),
            "pre_action_counts": dict(action_counts),
            "expected_action_totals": dict(expected_action_totals),
            "action_breakdown": action_breakdown,
            "benchmark_groups": group_breakdown,
        }

    return analysis


def build_report_data(rows: list[dict], input_path: str, results_dir: Path) -> dict:
    by_mode = {row["mode"]: row for row in rows}
    baseline = by_mode["nocontrol"]
    derived = {}
    prompt_records = read_jsonl(Path(input_path))
    group_counts = Counter(record.get("benchmark_group", "unknown") for record in prompt_records)
    category_counts = Counter(record.get("category", "unknown") for record in prompt_records)
    expected_action_counts = Counter(record.get("expected_pre_action", "unknown") for record in prompt_records)
    group_expected_action_counts: dict[str, dict[str, int]] = {}
    for group_name in group_counts:
        group_expected_action_counts[group_name] = dict(
            Counter(
                record.get("expected_pre_action", "unknown")
                for record in prompt_records
                if record.get("benchmark_group", "unknown") == group_name
            )
        )

    for row in rows:
        mode = row["mode"]
        derived[mode] = {
            "inference_avoided_pct": pct(row["inference_calls_avoided"], row["prompts_total"]),
            "governed_prompt_share_pct": pct(
                row["prompts_masked"] + row["prompts_blocked"] + row["prompts_routed"] + row["prompts_tagged"],
                row["prompts_total"],
            ),
            "governed_output_share_pct": pct(
                row["outputs_masked"] + row["outputs_blocked"] + row["outputs_tagged"],
                row["outputs_total"],
            ),
            "prompt_tokens_reduced_vs_baseline": baseline["prompt_tokens_forwarded_est"] - row["prompt_tokens_forwarded_est"],
            "prompt_tokens_reduced_vs_baseline_pct": pct(
                baseline["prompt_tokens_forwarded_est"] - row["prompt_tokens_forwarded_est"],
                baseline["prompt_tokens_forwarded_est"],
            ),
            "output_tokens_reduced_vs_baseline": baseline["output_tokens_released_est"] - row["output_tokens_released_est"],
            "output_tokens_reduced_vs_baseline_pct": pct(
                baseline["output_tokens_released_est"] - row["output_tokens_released_est"],
                baseline["output_tokens_released_est"],
            ),
            "prompt_tokens_reduced_per_inference_avoided": (
                (baseline["prompt_tokens_forwarded_est"] - row["prompt_tokens_forwarded_est"]) / row["inference_calls_avoided"]
                if row["inference_calls_avoided"]
                else 0.0
            ),
            "output_tokens_reduced_per_inference_avoided": (
                (baseline["output_tokens_released_est"] - row["output_tokens_released_est"]) / row["inference_calls_avoided"]
                if row["inference_calls_avoided"]
                else 0.0
            ),
        }

    contains_simulated = any(MODE_METADATA.get(row["mode"], {}).get("is_simulated") for row in rows)
    contains_real_nol8 = any(row["mode"] == "nol8_api_infer" for row in rows)
    contract_analysis = build_contract_analysis(
        prompt_records,
        results_dir,
        [row["mode"] for row in rows if row["mode"] != "nocontrol"],
    )
    return {
        "benchmark_metadata": {
            "benchmark_name": "Data Point 2 - Pre/Post-Inference Control",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "input_path": input_path,
            "prompts_total": len(prompt_records),
        },
        "dataset_metadata": {
            "benchmark_groups": dict(group_counts),
            "categories": dict(category_counts),
            "expected_pre_actions": dict(expected_action_counts),
            "benchmark_group_expected_pre_actions": group_expected_action_counts,
        },
        "mode_metadata": MODE_METADATA,
        "results": rows,
        "derived_metrics": derived,
        "contract_analysis": contract_analysis,
        "interpretation_flags": {
            "contains_simulated_modes": contains_simulated,
            "contains_real_nol8_results": contains_real_nol8,
            "safe_for_product_claims": contains_real_nol8 and not contains_simulated,
        },
    }


def fmt_signed_int(value: int) -> str:
    return f"{value:+d}"


def fmt_pct(value: float) -> str:
    return f"{value:.1f}%"


def fmt_fewer(value: int) -> str:
    if value == 0:
        return "0"
    return f"{value} fewer"


def render_html(data: dict, template_text: str) -> str:
    rows = data["results"]
    by_mode = {row["mode"]: row for row in rows}
    derived = data["derived_metrics"]
    contract = data.get("contract_analysis", {})
    flags = data["interpretation_flags"]
    dataset = data["dataset_metadata"]
    re2 = by_mode.get("re2_guard", {})
    re2_derived = derived.get("re2_guard", {})
    re2_contract = contract.get("re2_guard", {})
    listguard = by_mode.get("listguard", {})
    listguard_derived = derived.get("listguard", {})
    listguard_contract = contract.get("listguard", {})
    nol8sim = by_mode.get("nol8sim_infer", {})
    nol8sim_derived = derived.get("nol8sim_infer", {})
    nol8sim_contract = contract.get("nol8sim_infer", {})
    nol8api = by_mode.get("nol8_api_infer", {})
    nol8api_derived = derived.get("nol8_api_infer", {})
    nol8api_contract = contract.get("nol8_api_infer", {})

    group_order = list(dataset["benchmark_groups"].keys())
    governed_expected_total = sum(
        count for action, count in dataset.get("expected_pre_actions", {}).items() if action != "allow"
    )

    def summarize_actions(action_counts: dict[str, int]) -> str:
        if not action_counts:
            return "none"
        ordered = ["allow", "mask", "route", "tag", "block"]
        parts = [f"{action}: {action_counts[action]}" for action in ordered if action in action_counts]
        for action, count in action_counts.items():
            if action not in ordered:
                parts.append(f"{action}: {count}")
        return ", ".join(parts)

    def action_match(mode_contract: dict, action: str) -> str:
        action_data = mode_contract.get("action_breakdown", {}).get(action, {})
        return (
            f"{action_data.get('matched_count', 0)} / {action_data.get('expected_total', 0)} "
            f"({fmt_pct(action_data.get('matched_pct', 0.0))})"
        )

    measured_card_html = ""
    if nol8api:
        measured_card_html = f"""
      <div class="card">
        <h3>nol8_api_infer</h3>
        <div class="metric">{fmt_pct(nol8api_derived.get("inference_avoided_pct", 0.0))}</div>
        <div class="subtle">{nol8api.get("inference_calls_avoided", 0)} of {nol8api.get("prompts_total", 0)} prompts avoided inference.</div>
        <div class="subtle">{fmt_fewer(int(nol8api_derived.get("prompt_tokens_reduced_vs_baseline", 0)))} prompt tokens forwarded vs baseline.</div>
        <div class="subtle">{fmt_pct(nol8api_contract.get("pre_action_alignment_pct", 0.0))} pre-action match to expected contract.</div>
      </div>
        """

    cards_html = f"""
    <section class="cards">
      <div class="card">
        <h3>re2_guard</h3>
        <div class="metric">{fmt_pct(re2_derived.get("inference_avoided_pct", 0.0))}</div>
        <div class="subtle">{re2.get("inference_calls_avoided", 0)} of {re2.get("prompts_total", 0)} prompts avoided inference.</div>
        <div class="subtle">{fmt_fewer(int(re2_derived.get("prompt_tokens_reduced_vs_baseline", 0)))} prompt tokens forwarded vs baseline.</div>
        <div class="subtle">{fmt_pct(re2_contract.get("pre_action_alignment_pct", 0.0))} pre-action match to expected contract.</div>
      </div>
      <div class="card">
        <h3>listguard</h3>
        <div class="metric">{fmt_pct(listguard_derived.get("inference_avoided_pct", 0.0))}</div>
        <div class="subtle">{listguard.get("inference_calls_avoided", 0)} of {listguard.get("prompts_total", 0)} prompts avoided inference.</div>
        <div class="subtle">{fmt_fewer(int(listguard_derived.get("prompt_tokens_reduced_vs_baseline", 0)))} prompt tokens forwarded vs baseline.</div>
        <div class="subtle">{fmt_pct(listguard_contract.get("pre_action_alignment_pct", 0.0))} pre-action match to expected contract.</div>
      </div>
      <div class="card">
        <h3>nol8sim_infer</h3>
        <div class="metric">{fmt_pct(nol8sim_derived.get("inference_avoided_pct", 0.0))}</div>
        <div class="subtle">{nol8sim.get("inference_calls_avoided", 0)} of {nol8sim.get("prompts_total", 0)} prompts avoided inference.</div>
        <div class="subtle">{fmt_fewer(int(nol8sim_derived.get("prompt_tokens_reduced_vs_baseline", 0)))} prompt tokens forwarded vs baseline.</div>
        <div class="subtle">{fmt_pct(nol8sim_contract.get("pre_action_alignment_pct", 0.0))} pre-action match to expected contract.</div>
      </div>
      {measured_card_html}
      <div class="card">
        <h3>Contract Gap</h3>
        <div class="metric">{re2_contract.get("contract_miss_count", 0)} / {data['benchmark_metadata']['prompts_total']}</div>
        <div class="subtle"><span class="mono">re2_guard</span> misses {re2_contract.get("missed_governed_count", 0)} governed prompts by leaving them as <span class="mono">allow</span>.</div>
        <div class="subtle"><span class="mono">listguard</span> also avoids false positives on benign rows, but still leaves {listguard_contract.get("missed_governed_count", 0)} governed prompts untouched.</div>
      </div>
    </section>
    """

    measured_takeaway = ""
    if nol8api:
        measured_takeaway = f"<li><strong><span class=\"mono\">nol8_api_infer</span></strong>: Measured API row is present and should be used as the engineering truth source ahead of the simulated placeholder.</li>"

    takeaway_html = f"""
    <section class="panel note">
      <h2>Top-Line Takeaway</h2>
      <ul>
        <li><strong><span class="mono">re2_guard</span></strong>: Strongest on broad pattern masking, but weaker on explainable precedence and workflow-routing decisions.</li>
        <li><strong><span class="mono">listguard</span></strong>: Closes much of the governance gap and matches 9 of 10 mixed-priority rows, but over-governs the stakeholder-readable false-positive-pressure slice.</li>
        <li><strong><span class="mono">nol8sim_infer</span></strong>: Contract target that holds both sides of the benchmark at once in this dataset, but still simulated.</li>
        {measured_takeaway}
      </ul>
      <table>
        <tr>
          <th>Mode</th>
          <th>Contract Alignment</th>
          <th>Mixed-Priority Match</th>
          <th>False-Positive Pressure</th>
        </tr>
        <tr>
          <td><strong>re2_guard</strong></td>
          <td>{fmt_pct(re2_contract.get("pre_action_alignment_pct", 0.0))}</td>
          <td>{fmt_pct(re2_contract.get("benchmark_groups", {}).get("mixed_priority", {}).get("expected_match_pct", 0.0))}</td>
          <td>{fmt_pct(re2_contract.get("benchmark_groups", {}).get("false_positive_pressure", {}).get("expected_match_pct", 0.0))}</td>
        </tr>
        <tr>
          <td><strong>listguard</strong></td>
          <td>{fmt_pct(listguard_contract.get("pre_action_alignment_pct", 0.0))}</td>
          <td>{fmt_pct(listguard_contract.get("benchmark_groups", {}).get("mixed_priority", {}).get("expected_match_pct", 0.0))}</td>
          <td>{fmt_pct(listguard_contract.get("benchmark_groups", {}).get("false_positive_pressure", {}).get("expected_match_pct", 0.0))}</td>
        </tr>
        <tr>
          <td><strong>nol8sim_infer</strong></td>
          <td>{fmt_pct(nol8sim_contract.get("pre_action_alignment_pct", 0.0))}</td>
          <td>{fmt_pct(nol8sim_contract.get("benchmark_groups", {}).get("mixed_priority", {}).get("expected_match_pct", 0.0))}</td>
          <td>{fmt_pct(nol8sim_contract.get("benchmark_groups", {}).get("false_positive_pressure", {}).get("expected_match_pct", 0.0))}</td>
        </tr>
      </table>
    </section>
    """

    composition_rows = []
    for label, values in [
        ("Prompt Groups", dataset["benchmark_groups"]),
        ("Prompt Categories", dataset["categories"]),
        ("Expected Pre-Actions", dataset["expected_pre_actions"]),
    ]:
        composition_rows.append(
            f"<tr><td>{html.escape(label)}</td><td>" +
            ", ".join(f"{html.escape(k)}: {v}" for k, v in values.items()) +
            "</td></tr>"
        )
    composition_html = (
        "<section class='panel note'><details>"
        "<summary>Prompt Set Composition</summary>"
        "<p class='subtle'>This dataset is intentionally mixed to separate pattern matching, list-driven controls, target contract behavior, and near-miss precision checks.</p>"
        "<table><tr><th>Slice</th><th>Distribution</th></tr>" +
        "".join(composition_rows) +
        "</table></details></section>"
    )

    comparison_note = """
    <section class="panel note">
      <h2>Current Dataset Note</h2>
      <p>This prompt set is intentionally designed to make the guarded modes diverge.</p>
      <ul>
        <li><strong><span class="mono">re2_guard</span></strong>: Catches broad patterns such as previously unseen account IDs and card formats.</li>
        <li><strong><span class="mono">listguard</span></strong>: Catches known entities and phrases from enterprise-owned lists.</li>
        <li><strong><span class="mono">nol8sim_infer</span></strong>: Applies the target contract behavior from the benchmark design, but remains a behavior placeholder rather than a measured product result.</li>
      </ul>
    </section>
    """
    if flags["contains_real_nol8_results"]:
        comparison_note = """
    <section class="panel note">
      <h2>Current Dataset Note</h2>
      <p>This prompt set is intentionally designed to make the guarded modes diverge.</p>
      <ul>
        <li><strong><span class="mono">re2_guard</span></strong>: Catches broad patterns such as previously unseen account IDs and card formats.</li>
        <li><strong><span class="mono">listguard</span></strong>: Catches known entities and phrases from enterprise-owned lists.</li>
        <li><strong><span class="mono">nol8sim_infer</span></strong>: Preserves the target contract framing as a behavior placeholder.</li>
        <li><strong><span class="mono">nol8_api_infer</span></strong>: Provides the measured endpoint path when real Nol8 results are included.</li>
      </ul>
    </section>
    """

    contrast_html = f"""
    <section class="panel">
      <h2>Mode Contrast</h2>
      <table>
        <tr>
          <th>Mode</th>
          <th>What It Is Best At In This Dataset</th>
          <th>Visible Result</th>
          <th>Tradeoff</th>
        </tr>
        <tr class="mode-software">
          <td><strong>re2_guard</strong></td>
          <td>Broad pattern matching across unseen card/account formats.</td>
          <td>{re2.get("prompts_masked", 0)} prompts masked, {re2.get("inference_calls_avoided", 0)} inference calls avoided.</td>
          <td>Much weaker than the other guarded modes on known-phrase routing and mixed-priority precedence decisions.</td>
        </tr>
        <tr class="mode-software">
          <td><strong>listguard</strong></td>
          <td>Known-value and known-phrase enterprise controls from reference lists.</td>
          <td>{listguard.get("prompts_routed", 0)} routed, {listguard.get("prompts_blocked", 0)} blocked, {listguard.get("prompts_tagged", 0)} tagged.</td>
          <td>Handles precedence much better than <span class="mono">re2_guard</span>, but is now visibly vulnerable to explainable false positives on near-match list terms.</td>
        </tr>
        <tr class="mode-placeholder">
          <td><strong>nol8sim_infer</strong></td>
          <td>Target contract behavior where policy semantics are broader than current software baselines.</td>
          <td>{nol8sim.get("inference_calls_avoided", 0)} inference calls avoided, {fmt_fewer(int(nol8sim_derived.get("prompt_tokens_reduced_vs_baseline", 0)))} prompt tokens forwarded vs baseline.</td>
          <td>Simulated semantics only. Useful for target behavior framing, not product-performance claims.</td>
        </tr>
      </table>
    </section>
    """

    alignment_table = "<section class='panel'><h2>Contract Alignment</h2><table><tr><th>Mode</th><th>Expected Pre-Action Match</th><th>Primary Pattern</th><th>Near-Miss Precision</th></tr>"
    alignment_rows = [
        (
            "re2_guard",
            re2_contract,
            "Perfect on regex-favoring prompts; weak on list-only and semantic-policy prompts.",
        ),
        (
            "listguard",
            listguard_contract,
            "Strong on known entities and explicit enterprise phrases; weak on unseen format variants.",
        ),
        (
            "nol8sim_infer",
            nol8sim_contract,
            "Matches the full benchmark contract, including semantic routing and block cases.",
        ),
    ]
    for mode, mode_contract, pattern_note in alignment_rows:
        near_miss = mode_contract.get("benchmark_groups", {}).get("near_miss", {})
        alignment_table += (
            f"<tr><td><strong>{html.escape(mode)}</strong></td>"
            f"<td>{mode_contract.get('pre_action_alignment_count', 0)} / {data['benchmark_metadata']['prompts_total']} "
            f"({fmt_pct(mode_contract.get('pre_action_alignment_pct', 0.0))})</td>"
            f"<td>{html.escape(pattern_note)}</td>"
            f"<td>{near_miss.get('expected_match_count', 0)} / {near_miss.get('total', 0)} correct "
            f"({fmt_pct(near_miss.get('expected_match_pct', 0.0))})</td></tr>"
        )
    alignment_table += "</table></section>"

    action_table = "<section class='panel'><h2>Expected Action Coverage</h2><table><tr><th>Expected Action</th><th>re2_guard</th><th>listguard</th><th>nol8sim_infer</th></tr>"
    for action in ["allow", "mask", "route", "tag", "block"]:
        action_table += (
            f"<tr><td><strong>{html.escape(action)}</strong></td>"
            f"<td>{html.escape(action_match(re2_contract, action))}</td>"
            f"<td>{html.escape(action_match(listguard_contract, action))}</td>"
            f"<td>{html.escape(action_match(nol8sim_contract, action))}</td></tr>"
        )
    action_table += "</table></section>"

    risk_table = "<section class='panel'><h2>Governance Risk Lens</h2><table><tr><th>Mode</th><th>Missed Governed Prompts</th><th>Over-Governed Benign Prompts</th><th>Governed Action Match</th></tr>"
    for mode, mode_contract in [
        ("re2_guard", re2_contract),
        ("listguard", listguard_contract),
        ("nol8sim_infer", nol8sim_contract),
    ]:
        risk_table += (
            f"<tr><td><strong>{html.escape(mode)}</strong></td>"
            f"<td>{mode_contract.get('missed_governed_count', 0)} / {data['benchmark_metadata']['prompts_total']} "
            f"({fmt_pct(mode_contract.get('missed_governed_pct', 0.0))})</td>"
            f"<td>{mode_contract.get('over_governed_allow_count', 0)} / {data['benchmark_metadata']['prompts_total']} "
            f"({fmt_pct(mode_contract.get('over_governed_allow_pct', 0.0))})</td>"
            f"<td>{mode_contract.get('governed_action_match_count', 0)} / {governed_expected_total} "
            f"({fmt_pct(mode_contract.get('governed_action_match_pct', 0.0))})</td></tr>"
        )
    risk_table += "</table></section>"

    mixed_priority_html = ""
    if "mixed_priority" in group_order:
        re2_mixed = re2_contract.get("benchmark_groups", {}).get("mixed_priority", {})
        listguard_mixed = listguard_contract.get("benchmark_groups", {}).get("mixed_priority", {})
        nol8sim_mixed = nol8sim_contract.get("benchmark_groups", {}).get("mixed_priority", {})
        mixed_priority_html = f"""
        <section class="panel">
          <h2>Mixed-Priority Precedence</h2>
          <p class="subtle">These rows force more than one reasonable control to compete. They are intentionally easy to explain in customer terms: block should outrank route when the request is unsafe, and route should outrank simple masking or tagging when escalation is the safer workflow.</p>
          <table>
            <tr>
              <th>Mode</th>
              <th>Observed Pre-Actions</th>
              <th>Expected Match</th>
            </tr>
            <tr>
              <td><strong>re2_guard</strong></td>
              <td>{html.escape(summarize_actions(re2_mixed.get('pre_actions', {})))}</td>
              <td>{re2_mixed.get('expected_match_count', 0)} / {re2_mixed.get('total', 0)} ({fmt_pct(re2_mixed.get('expected_match_pct', 0.0))})</td>
            </tr>
            <tr>
              <td><strong>listguard</strong></td>
              <td>{html.escape(summarize_actions(listguard_mixed.get('pre_actions', {})))}</td>
              <td>{listguard_mixed.get('expected_match_count', 0)} / {listguard_mixed.get('total', 0)} ({fmt_pct(listguard_mixed.get('expected_match_pct', 0.0))})</td>
            </tr>
            <tr>
              <td><strong>nol8sim_infer</strong></td>
              <td>{html.escape(summarize_actions(nol8sim_mixed.get('pre_actions', {})))}</td>
              <td>{nol8sim_mixed.get('expected_match_count', 0)} / {nol8sim_mixed.get('total', 0)} ({fmt_pct(nol8sim_mixed.get('expected_match_pct', 0.0))})</td>
            </tr>
          </table>
        </section>
        """

    false_positive_html = ""
    if "false_positive_pressure" in group_order:
        re2_false = re2_contract.get("benchmark_groups", {}).get("false_positive_pressure", {})
        listguard_false = listguard_contract.get("benchmark_groups", {}).get("false_positive_pressure", {})
        nol8sim_false = nol8sim_contract.get("benchmark_groups", {}).get("false_positive_pressure", {})
        false_positive_html = f"""
        <section class="panel">
          <h2>False-Positive Pressure</h2>
          <p class="subtle">These rows are intentionally stakeholder-readable near-match cases. They should stay allowed, which makes them useful for explaining precision tradeoffs without relying on implementation jargon.</p>
          <table>
            <tr>
              <th>Mode</th>
              <th>Observed Pre-Actions</th>
              <th>Expected-Allow Match</th>
            </tr>
            <tr>
              <td><strong>re2_guard</strong></td>
              <td>{html.escape(summarize_actions(re2_false.get('pre_actions', {})))}</td>
              <td>{re2_false.get('expected_match_count', 0)} / {re2_false.get('total', 0)} ({fmt_pct(re2_false.get('expected_match_pct', 0.0))})</td>
            </tr>
            <tr>
              <td><strong>listguard</strong></td>
              <td>{html.escape(summarize_actions(listguard_false.get('pre_actions', {})))}</td>
              <td>{listguard_false.get('expected_match_count', 0)} / {listguard_false.get('total', 0)} ({fmt_pct(listguard_false.get('expected_match_pct', 0.0))})</td>
            </tr>
            <tr>
              <td><strong>nol8sim_infer</strong></td>
              <td>{html.escape(summarize_actions(nol8sim_false.get('pre_actions', {})))}</td>
              <td>{nol8sim_false.get('expected_match_count', 0)} / {nol8sim_false.get('total', 0)} ({fmt_pct(nol8sim_false.get('expected_match_pct', 0.0))})</td>
            </tr>
          </table>
        </section>
        """

    output_control_html = ""
    if "output_control" in group_order:
        re2_output = re2_contract.get("benchmark_groups", {}).get("output_control", {})
        listguard_output = listguard_contract.get("benchmark_groups", {}).get("output_control", {})
        nol8sim_output = nol8sim_contract.get("benchmark_groups", {}).get("output_control", {})
        output_control_html = f"""
        <section class="panel">
          <h2>Output-Control Slice</h2>
          <p class="subtle">These rows are prompt-side allows by design. They exist to show that output blocking and tagging still matter after a request is permitted to reach inference.</p>
          <table>
            <tr>
              <th>Mode</th>
              <th>Observed Post-Actions</th>
              <th>Inference Calls Made</th>
            </tr>
            <tr>
              <td><strong>re2_guard</strong></td>
              <td>{html.escape(summarize_actions(re2_output.get('post_actions', {})))}</td>
              <td>{re2_output.get('post_actions', {}).get('allow', 0) + re2_output.get('post_actions', {}).get('block', 0) + re2_output.get('post_actions', {}).get('mask', 0) + re2_output.get('post_actions', {}).get('tag', 0)} / {re2_output.get('total', 0)}</td>
            </tr>
            <tr>
              <td><strong>listguard</strong></td>
              <td>{html.escape(summarize_actions(listguard_output.get('post_actions', {})))}</td>
              <td>{listguard_output.get('post_actions', {}).get('allow', 0) + listguard_output.get('post_actions', {}).get('block', 0) + listguard_output.get('post_actions', {}).get('mask', 0) + listguard_output.get('post_actions', {}).get('tag', 0)} / {listguard_output.get('total', 0)}</td>
            </tr>
            <tr>
              <td><strong>nol8sim_infer</strong></td>
              <td>{html.escape(summarize_actions(nol8sim_output.get('post_actions', {})))}</td>
              <td>{nol8sim_output.get('post_actions', {}).get('allow', 0) + nol8sim_output.get('post_actions', {}).get('block', 0) + nol8sim_output.get('post_actions', {}).get('mask', 0) + nol8sim_output.get('post_actions', {}).get('tag', 0)} / {nol8sim_output.get('total', 0)}</td>
            </tr>
          </table>
        </section>
        """

    slice_table = "<section class='panel'><h2>Benchmark Group Breakdown</h2><table><tr><th>Group</th><th>Expected Action Mix</th><th>re2_guard</th><th>listguard</th><th>nol8sim_infer</th></tr>"
    for group_name in group_order:
        expected_mix = summarize_actions(
            dataset.get("benchmark_group_expected_pre_actions", {}).get(group_name, {})
        )
        re2_group = re2_contract.get("benchmark_groups", {}).get(group_name, {})
        listguard_group = listguard_contract.get("benchmark_groups", {}).get(group_name, {})
        nol8sim_group = nol8sim_contract.get("benchmark_groups", {}).get(group_name, {})
        slice_table += (
            f"<tr><td><strong>{html.escape(group_name)}</strong><br><span class='subtle'>{dataset['benchmark_groups'][group_name]} prompts</span></td>"
            f"<td>{html.escape(expected_mix)}</td>"
            f"<td>{html.escape(summarize_actions(re2_group.get('pre_actions', {})))}"
            f"<br><span class='subtle'>match: {re2_group.get('expected_match_count', 0)} / {re2_group.get('total', 0)} "
            f"({fmt_pct(re2_group.get('expected_match_pct', 0.0))})</span></td>"
            f"<td>{html.escape(summarize_actions(listguard_group.get('pre_actions', {})))}"
            f"<br><span class='subtle'>match: {listguard_group.get('expected_match_count', 0)} / {listguard_group.get('total', 0)} "
            f"({fmt_pct(listguard_group.get('expected_match_pct', 0.0))})</span></td>"
            f"<td>{html.escape(summarize_actions(nol8sim_group.get('pre_actions', {})))}"
            f"<br><span class='subtle'>match: {nol8sim_group.get('expected_match_count', 0)} / {nol8sim_group.get('total', 0)} "
            f"({fmt_pct(nol8sim_group.get('expected_match_pct', 0.0))})</span></td></tr>"
        )
    slice_table += "</table></section>"

    executive_html = f"""
    <section class="panel">
      <h2>Executive Readout</h2>
      <p><strong>Regex baseline:</strong> <span class="mono">re2_guard</span> is exact on regex-favoring prompts and preserves all near-miss rows, but it matches only {fmt_pct(re2_contract.get("pre_action_alignment_pct", 0.0))} of the full prompt contract and leaves {re2_contract.get("missed_governed_count", 0)} governed prompts as plain <span class="mono">allow</span>.</p>
      <p><strong>Enterprise list baseline:</strong> <span class="mono">listguard</span> improves contract fit to {fmt_pct(listguard_contract.get("pre_action_alignment_pct", 0.0))} and matches {listguard_contract.get("benchmark_groups", {}).get("mixed_priority", {}).get("expected_match_count", 0)} of {listguard_contract.get("benchmark_groups", {}).get("mixed_priority", {}).get("total", 0)} mixed-priority rows, but the false-positive-pressure slice now shows it over-governing all 4 of 4 stakeholder-readable near-match rows.</p>
      <p><strong>Target behavior placeholder:</strong> <span class="mono">nol8sim_infer</span> is the only mode that matches the entire prompt contract, avoiding {nol8sim.get("inference_calls_avoided", 0)} inference calls and reducing forwarded prompt tokens by {fmt_pct(nol8sim_derived.get("prompt_tokens_reduced_vs_baseline_pct", 0.0))} versus <span class="mono">nocontrol</span>, but it remains simulated.</p>
    </section>
    """
    if nol8api:
        executive_html = f"""
    <section class="panel">
      <h2>Executive Readout</h2>
      <p><strong>Regex baseline:</strong> <span class="mono">re2_guard</span> is exact on regex-favoring prompts and preserves all near-miss rows, but it matches only {fmt_pct(re2_contract.get("pre_action_alignment_pct", 0.0))} of the full prompt contract and leaves {re2_contract.get("missed_governed_count", 0)} governed prompts as plain <span class="mono">allow</span>.</p>
      <p><strong>Enterprise list baseline:</strong> <span class="mono">listguard</span> improves contract fit to {fmt_pct(listguard_contract.get("pre_action_alignment_pct", 0.0))} and matches {listguard_contract.get("benchmark_groups", {}).get("mixed_priority", {}).get("expected_match_count", 0)} of {listguard_contract.get("benchmark_groups", {}).get("mixed_priority", {}).get("total", 0)} mixed-priority rows, but the false-positive-pressure slice now shows it over-governing all 4 of 4 stakeholder-readable near-match rows.</p>
      <p><strong>Measured API mode:</strong> <span class="mono">nol8_api_infer</span> is present in this report with {fmt_pct(nol8api_contract.get("pre_action_alignment_pct", 0.0))} contract alignment. When this row is available, it should be treated as the engineering reference point for live Nol8 behavior.</p>
      <p><strong>Target behavior placeholder:</strong> <span class="mono">nol8sim_infer</span> remains useful for contract framing, but it should no longer be treated as the only stand-in once measured API results are available.</p>
    </section>
    """

    how_to_read_html = """
    <section class="panel note">
      <details>
        <summary>How To Read This Benchmark</summary>
        <ul>
          <li><strong>nocontrol</strong> sends every prompt to the model stub and returns every output.</li>
          <li><strong>re2_guard</strong> is the traditional software baseline using deterministic regex-style matching.</li>
          <li><strong>listguard</strong> is the first-pass enterprise control case using known values and phrases from reference lists.</li>
          <li><strong>nol8sim_infer</strong> is a behavior placeholder for target Nol8-style control semantics, not a measured production result.</li>
        </ul>
      </details>
    </section>
    """

    caveat_html = ""
    if flags["contains_simulated_modes"] and not flags["contains_real_nol8_results"]:
        caveat_html = """
        <section class="panel warn">
          <details open>
            <summary>Measured vs Simulated Caveat</summary>
            <p>This report includes a simulated Nol8 behavior placeholder for control semantics only. It does not include measured production Nol8 execution, and it is not safe to make product-performance claims from the <span class="mono">nol8sim_infer</span> row.</p>
          </details>
        </section>
        """

    derived_rows = []
    derived_defs = [
        ("Inference Avoided %", "inference_avoided_pct"),
        ("Governed Prompt Share %", "governed_prompt_share_pct"),
        ("Governed Output Share %", "governed_output_share_pct"),
        ("Prompt Tokens Reduced vs nocontrol", "prompt_tokens_reduced_vs_baseline"),
        ("Prompt Token Reduction % vs nocontrol", "prompt_tokens_reduced_vs_baseline_pct"),
        ("Output Tokens Reduced vs nocontrol", "output_tokens_reduced_vs_baseline"),
        ("Output Token Reduction % vs nocontrol", "output_tokens_reduced_vs_baseline_pct"),
        ("Prompt Tokens Reduced per Avoided Inference", "prompt_tokens_reduced_per_inference_avoided"),
        ("Output Tokens Reduced per Avoided Inference", "output_tokens_reduced_per_inference_avoided"),
    ]
    modes = [row["mode"] for row in rows]
    for label, key in derived_defs:
        cells = []
        for mode in modes:
            value = derived[mode][key]
            if isinstance(value, float) and "pct" in key:
                cells.append(fmt_pct(value))
            elif isinstance(value, float):
                cells.append(f"{value:.1f}")
            else:
                cells.append(str(value))
        derived_rows.append((label, cells))

    derived_table = "<section class='panel'><h2>Derived Metrics</h2><table><tr><th>Metric</th>" + "".join(
        f"<th>{html.escape(MODE_METADATA[mode]['label'])}</th>" for mode in modes
    ) + "</tr>"
    for label, cells in derived_rows:
        derived_table += f"<tr><td>{html.escape(label)}</td>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in cells) + "</tr>"
    derived_table += "</table></section>"

    results_table = "<section class='panel'><h2>Mode Results</h2><table><tr><th>Mode</th><th>Prompts Total</th><th>Masked</th><th>Blocked</th><th>Routed</th><th>Tagged</th><th>Inference Made</th><th>Inference Avoided</th><th>Prompt Tokens Forwarded</th><th>Outputs Total</th><th>Outputs Masked</th><th>Outputs Blocked</th><th>Outputs Tagged</th><th>Output Tokens Released</th></tr>"
    role_class = {
        "baseline": "mode-baseline",
        "software_baseline": "mode-software",
        "behavioral_placeholder": "mode-placeholder",
        "measured_mode": "mode-software",
    }
    for row in rows:
        meta = MODE_METADATA[row["mode"]]
        results_table += (
            f"<tr class='{role_class.get(meta['role'], '')}'>"
            f"<td>{html.escape(meta['label'])}</td>"
            f"<td>{row['prompts_total']}</td>"
            f"<td>{row['prompts_masked']}</td>"
            f"<td>{row['prompts_blocked']}</td>"
            f"<td>{row['prompts_routed']}</td>"
            f"<td>{row['prompts_tagged']}</td>"
            f"<td>{row['inference_calls_made']}</td>"
            f"<td>{row['inference_calls_avoided']}</td>"
            f"<td>{row['prompt_tokens_forwarded_est']}</td>"
            f"<td>{row['outputs_total']}</td>"
            f"<td>{row['outputs_masked']}</td>"
            f"<td>{row['outputs_blocked']}</td>"
            f"<td>{row['outputs_tagged']}</td>"
            f"<td>{row['output_tokens_released_est']}</td>"
            "</tr>"
        )
    results_table += "</table></section>"

    perf_table = "<section class='panel'><h2>Timing</h2><table><tr><th>Mode</th><th>Preprocess ms</th><th>Postprocess ms</th><th>Total control ms</th><th>Records / sec</th></tr>"
    for row in rows:
        meta = MODE_METADATA[row["mode"]]
        perf_table += (
            f"<tr><td>{html.escape(meta['label'])}</td>"
            f"<td>{row['preprocess_ms']:.3f}</td>"
            f"<td>{row['postprocess_ms']:.3f}</td>"
            f"<td>{row['total_control_ms']:.3f}</td>"
            f"<td>{row['records_per_sec']:.2f}</td></tr>"
        )
    perf_table += "</table></section>"

    body = f"""
    <header>
      <h1>Data Point 2 — Pre/Post-Inference Control</h1>
      <p class="lede">This benchmark compares a no-control path, a regex-style software guard, a list-driven enterprise guard, and a simulated Nol8 behavior placeholder around a model boundary. The goal is to show which prompts reach inference, which outputs are governed, and how much prompt/output token flow is avoided.</p>
    </header>
    <section class="panel">
      <h2>Run Context</h2>
      <p><strong>Generated:</strong> {html.escape(data['benchmark_metadata']['generated_at_utc'])}</p>
      <p><strong>Input:</strong> <span class="mono">{html.escape(data['benchmark_metadata']['input_path'])}</span></p>
    </section>
    {how_to_read_html}
    {caveat_html}
    {comparison_note}
    {takeaway_html}
    {composition_html}
    {cards_html}
    {executive_html}
    {contrast_html}
    {alignment_table}
    {action_table}
    {risk_table}
    {mixed_priority_html}
    {false_positive_html}
    {output_control_html}
    {slice_table}
    {derived_table}
    {results_table}
    {perf_table}
    <section class="panel note">
      <details>
        <summary>Metric Definitions</summary>
        <ul>
          <li><strong>Inference Avoided</strong> means the prompt was blocked or routed before the model stub was called.</li>
          <li><strong>Governed Prompt Share</strong> includes masked, blocked, routed, and tagged prompts.</li>
          <li><strong>Governed Output Share</strong> includes masked, blocked, and tagged outputs after inference.</li>
          <li><strong>Prompt/Output Token Reduction vs nocontrol</strong> compares forwarded or released token counts to the no-control baseline.</li>
        </ul>
      </details>
    </section>
    """
    return template_text.replace("__BODY__", body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-csv", required=True)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--input-path", required=True)
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    results_csv_path = Path(args.results_csv)
    rows = read_results(results_csv_path)
    data = build_report_data(rows, args.input_path, results_csv_path.parent)

    report_json = report_dir / "report_data.json"
    report_json.write_text(json.dumps(data, indent=2) + "\n")

    template_text = (report_dir / "report_template.html").read_text()
    report_html = render_html(data, template_text)
    (report_dir / "report.html").write_text(report_html)


if __name__ == "__main__":
    main()
