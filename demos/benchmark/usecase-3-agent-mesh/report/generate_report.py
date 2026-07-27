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
    "re2_mesh": {
        "label": "re2_mesh (Software Baseline)",
        "role": "software_baseline",
        "is_simulated": False,
    },
    "listmesh": {
        "label": "listmesh (Policy Lists)",
        "role": "software_baseline",
        "is_simulated": False,
    },
    "nol8sim_agent": {
        "label": "nol8sim_agent (Behavior Placeholder)",
        "role": "behavioral_placeholder",
        "is_simulated": True,
    },
}


INT_FIELDS = {
    "tasks_total",
    "agent_messages_total",
    "messages_masked",
    "handoffs_blocked",
    "tasks_routed",
    "tool_calls_attempted",
    "tool_calls_blocked",
    "final_outputs_total",
    "final_outputs_blocked",
    "final_outputs_tagged",
    "final_outputs_masked",
    "sensitive_exposures_prevented",
    "contract_alignment_count",
}

FLOAT_FIELDS = {
    "preprocess_ms",
    "events_per_sec",
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


def fmt_pct(value: float) -> str:
    return f"{value:.1f}%"


def summarize_counts(values: dict) -> str:
    if not values:
        return "none"
    return ", ".join(f"{html.escape(str(k))}: {v}" for k, v in values.items())


def build_report_data(rows: list[dict], input_path: str) -> dict:
    tasks = read_jsonl(Path(input_path))
    groups = Counter(task.get("benchmark_group", "unknown") for task in tasks)
    categories = Counter(task.get("category", "unknown") for task in tasks)
    expected_mesh_actions = Counter(task.get("expected_mesh_action", "unknown") for task in tasks)
    expected_final_actions = Counter(task.get("expected_final_action", "unknown") for task in tasks)

    derived = {}
    for row in rows:
        mode = row["mode"]
        derived[mode] = {
            "contract_alignment_pct": pct(row["contract_alignment_count"], row["tasks_total"]),
            "tool_block_rate_pct": pct(row["tool_calls_blocked"], row["tool_calls_attempted"]),
            "handoff_block_rate_pct": pct(row["handoffs_blocked"], row["agent_messages_total"]),
            "governed_task_signal_count": (
                row["messages_masked"]
                + row["handoffs_blocked"]
                + row["tasks_routed"]
                + row["tool_calls_blocked"]
                + row["final_outputs_blocked"]
                + row["final_outputs_tagged"]
                + row["final_outputs_masked"]
            ),
            "sensitive_exposures_prevented_pct": pct(
                row["sensitive_exposures_prevented"],
                row["tasks_total"],
            ),
        }

    contains_simulated = any(MODE_METADATA.get(row["mode"], {}).get("is_simulated") for row in rows)
    return {
        "benchmark_metadata": {
            "benchmark_name": "Data Point 3 - Agent-to-Agent Control",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "input_path": input_path,
            "tasks_total": len(tasks),
        },
        "dataset_metadata": {
            "benchmark_groups": dict(groups),
            "categories": dict(categories),
            "expected_mesh_actions": dict(expected_mesh_actions),
            "expected_final_actions": dict(expected_final_actions),
        },
        "mode_metadata": MODE_METADATA,
        "results": rows,
        "derived_metrics": derived,
        "interpretation_flags": {
            "contains_simulated_modes": contains_simulated,
            "contains_real_nol8_results": False,
            "safe_for_product_claims": False,
        },
    }


def mode_class(mode: str) -> str:
    if mode == "nocontrol":
        return "mode-baseline"
    if mode == "nol8sim_agent":
        return "mode-placeholder"
    return "mode-software"


def render_html(data: dict, template_text: str) -> str:
    rows = data["results"]
    by_mode = {row["mode"]: row for row in rows}
    derived = data["derived_metrics"]
    dataset = data["dataset_metadata"]
    re2 = by_mode.get("re2_mesh", {})
    listmesh = by_mode.get("listmesh", {})
    nol8sim = by_mode.get("nol8sim_agent", {})
    re2d = derived.get("re2_mesh", {})
    listd = derived.get("listmesh", {})
    nold = derived.get("nol8sim_agent", {})

    how_to_read = """
    <section class="panel note">
      <details>
        <summary>How To Read This Benchmark</summary>
        <ul>
          <li><strong><span class="mono">nocontrol</span></strong>: Sends every task through every agent handoff, allows every tool call, and releases every final output.</li>
          <li><strong><span class="mono">re2_mesh</span></strong>: Software baseline using deterministic regex-style matching across agent handoffs, tool calls, and final output.</li>
          <li><strong><span class="mono">listmesh</span></strong>: Enterprise policy-list baseline using known customer, project, entity, and blocked-tool phrases.</li>
          <li><strong><span class="mono">nol8sim_agent</span></strong>: Behavior placeholder for target Nol8-style agent-mesh semantics, not a measured production result.</li>
        </ul>
      </details>
    </section>
    """

    caveat = """
    <section class="panel warn">
      <details open>
        <summary>Measured vs Simulated Caveat</summary>
        <p>The <span class="mono">nol8sim_agent</span> row is simulated target behavior. It is not measured production Nol8 execution and is not safe for product-performance claims.</p>
      </details>
    </section>
    """

    executive_readout = f"""
    <section class="panel">
      <h2>Executive Readout</h2>
      <p><strong>Regex mesh baseline:</strong> <span class="mono">re2_mesh</span> reaches {fmt_pct(re2d.get("contract_alignment_pct", 0.0))} contract alignment and is useful for broad pattern masking and phrase blocking, but it is weaker where the expected behavior depends on enterprise-specific workflow semantics.</p>
      <p><strong>Policy-list mesh baseline:</strong> <span class="mono">listmesh</span> also reaches {fmt_pct(listd.get("contract_alignment_pct", 0.0))} contract alignment and makes known enterprise policy behavior easier to explain, but it is still bounded by the exact policy lists provided to the benchmark.</p>
      <p><strong>Target behavior placeholder:</strong> <span class="mono">nol8sim_agent</span> reaches {fmt_pct(nold.get("contract_alignment_pct", 0.0))} contract alignment in this dataset because it applies the benchmark contract directly. It frames the intended control story until a live Nol8 agent-mesh mode is available.</p>
    </section>
    """

    mode_contrast = f"""
    <section class="panel">
      <h2>Mode Contrast</h2>
      <table>
        <tr>
          <th>Mode</th>
          <th>What It Is Best At In This Dataset</th>
          <th>Visible Result</th>
          <th>Tradeoff</th>
        </tr>
        <tr class="mode-baseline">
          <td><strong>nocontrol</strong></td>
          <td>Baseline visibility into what happens when no mesh controls are applied.</td>
          <td>{by_mode.get("nocontrol", {}).get("agent_messages_total", 0)} agent messages, {by_mode.get("nocontrol", {}).get("tool_calls_attempted", 0)} tool calls attempted, and no governed actions.</td>
          <td>Useful as a comparison point, but it allows sensitive context and risky actions to move through the workflow.</td>
        </tr>
        <tr class="mode-software">
          <td><strong>re2_mesh</strong></td>
          <td>Broad deterministic matching for cards, account IDs, high-risk phrases, and output phrases.</td>
          <td>{re2.get("messages_masked", 0)} messages masked, {re2.get("tool_calls_blocked", 0)} tool calls blocked, {re2.get("final_outputs_blocked", 0)} final outputs blocked.</td>
          <td>Easy to inspect, but less expressive for agent workflow context and customer-specific policy meaning.</td>
        </tr>
        <tr class="mode-software">
          <td><strong>listmesh</strong></td>
          <td>Known enterprise policy controls for flagged customers, denied entities, internal projects, and blocked tool phrases.</td>
          <td>{listmesh.get("tasks_routed", 0)} routed tasks, {listmesh.get("handoffs_blocked", 0)} blocked handoffs, {listmesh.get("tool_calls_blocked", 0)} blocked tool calls.</td>
          <td>More explainable for owned policy lists, but still dependent on the list contents and exact matching strategy.</td>
        </tr>
        <tr class="mode-placeholder">
          <td><strong>nol8sim_agent</strong></td>
          <td>Target benchmark contract across handoffs, tools, routing, and final release decisions.</td>
          <td>{nol8sim.get("contract_alignment_count", 0)} of {nol8sim.get("tasks_total", 0)} tasks align with the expected mesh and final-output contract.</td>
          <td>Simulated semantics only. Useful for target framing, not product-performance claims.</td>
        </tr>
      </table>
    </section>
    """

    cards = f"""
    <section class="cards">
      <div class="card">
        <h3>re2_mesh</h3>
        <div class="metric">{fmt_pct(re2d.get("contract_alignment_pct", 0.0))}</div>
        <div class="subtle">Contract alignment across agent tasks.</div>
        <div class="subtle">{re2.get("tool_calls_blocked", 0)} tool calls blocked.</div>
      </div>
      <div class="card">
        <h3>listmesh</h3>
        <div class="metric">{fmt_pct(listd.get("contract_alignment_pct", 0.0))}</div>
        <div class="subtle">Contract alignment across agent tasks.</div>
        <div class="subtle">{listmesh.get("sensitive_exposures_prevented", 0)} sensitive exposures prevented.</div>
      </div>
      <div class="card">
        <h3>nol8sim_agent</h3>
        <div class="metric">{fmt_pct(nold.get("contract_alignment_pct", 0.0))}</div>
        <div class="subtle">Target contract behavior placeholder.</div>
        <div class="subtle">{nol8sim.get("sensitive_exposures_prevented", 0)} sensitive exposures prevented.</div>
      </div>
      <div class="card">
        <h3>Agent Handoff Risk</h3>
        <div class="metric">{listmesh.get("handoffs_blocked", 0)}</div>
        <div class="subtle"><span class="mono">listmesh</span> blocked handoffs before context reached the wrong agent.</div>
      </div>
    </section>
    """

    derived_rows = ""
    for mode in [row["mode"] for row in rows]:
        d = derived.get(mode, {})
        meta = MODE_METADATA.get(mode, {"label": mode})
        derived_rows += (
            f"<tr class='{mode_class(mode)}'>"
            f"<td><strong>{html.escape(meta['label'])}</strong></td>"
            f"<td>{fmt_pct(d.get('contract_alignment_pct', 0.0))}</td>"
            f"<td>{fmt_pct(d.get('tool_block_rate_pct', 0.0))}</td>"
            f"<td>{fmt_pct(d.get('handoff_block_rate_pct', 0.0))}</td>"
            f"<td>{d.get('governed_task_signal_count', 0)}</td>"
            f"<td>{fmt_pct(d.get('sensitive_exposures_prevented_pct', 0.0))}</td>"
            f"</tr>"
        )

    derived_table = f"""
    <section class="panel">
      <h2>Derived Metrics</h2>
      <table>
        <tr>
          <th>Mode</th>
          <th>Contract Alignment</th>
          <th>Tool Block Rate</th>
          <th>Handoff Block Rate</th>
          <th>Governed Signal Count</th>
          <th>Exposures Prevented Share</th>
        </tr>
        {derived_rows}
      </table>
    </section>
    """

    timing_rows = ""
    for row in rows:
        meta = MODE_METADATA.get(row["mode"], {"label": row["mode"]})
        timing_rows += (
            f"<tr>"
            f"<td><strong>{html.escape(meta['label'])}</strong></td>"
            f"<td>{row['preprocess_ms']:.3f}</td>"
            f"<td>{row['events_per_sec']:.2f}</td>"
            f"</tr>"
        )

    timing_table = f"""
    <section class="panel">
      <h2>Timing</h2>
      <table>
        <tr>
          <th>Mode</th>
          <th>Control Runtime ms</th>
          <th>Events / sec</th>
        </tr>
        {timing_rows}
      </table>
    </section>
    """

    rows_html = ""
    for row in rows:
        mode = row["mode"]
        meta = MODE_METADATA.get(mode, {"label": mode})
        d = derived.get(mode, {})
        rows_html += (
            f"<tr class='{mode_class(mode)}'>"
            f"<td><strong>{html.escape(meta['label'])}</strong></td>"
            f"<td>{row['tasks_total']}</td>"
            f"<td>{row['messages_masked']}</td>"
            f"<td>{row['handoffs_blocked']}</td>"
            f"<td>{row['tasks_routed']}</td>"
            f"<td>{row['tool_calls_blocked']}</td>"
            f"<td>{row['final_outputs_blocked']}</td>"
            f"<td>{row['final_outputs_tagged']}</td>"
            f"<td>{row['sensitive_exposures_prevented']}</td>"
            f"<td>{fmt_pct(d.get('contract_alignment_pct', 0.0))}</td>"
            f"</tr>"
        )

    metrics_table = f"""
    <section class="panel">
      <h2>Agent Mesh Metrics</h2>
      <table>
        <tr>
          <th>Mode</th>
          <th>Tasks</th>
          <th>Messages Masked</th>
          <th>Handoffs Blocked</th>
          <th>Tasks Routed</th>
          <th>Tool Calls Blocked</th>
          <th>Final Outputs Blocked</th>
          <th>Final Outputs Tagged</th>
          <th>Exposures Prevented</th>
          <th>Contract Alignment</th>
        </tr>
        {rows_html}
      </table>
    </section>
    """

    composition = f"""
    <section class="panel note">
      <details>
        <summary>Task Set Composition</summary>
        <table>
          <tr><th>Slice</th><th>Distribution</th></tr>
          <tr><td>Benchmark Groups</td><td>{summarize_counts(dataset["benchmark_groups"])}</td></tr>
          <tr><td>Categories</td><td>{summarize_counts(dataset["categories"])}</td></tr>
          <tr><td>Expected Mesh Actions</td><td>{summarize_counts(dataset["expected_mesh_actions"])}</td></tr>
          <tr><td>Expected Final Actions</td><td>{summarize_counts(dataset["expected_final_actions"])}</td></tr>
        </table>
      </details>
    </section>
    """

    group_rows = ""
    for group_name, total in dataset["benchmark_groups"].items():
        group_rows += (
            f"<tr>"
            f"<td><strong>{html.escape(group_name)}</strong></td>"
            f"<td>{total}</td>"
            f"</tr>"
        )

    group_breakdown = f"""
    <section class="panel">
      <h2>Benchmark Group Breakdown</h2>
      <p class="subtle">These slices make the agent-control story easier to inspect: benign work, maskable sensitive values, risky tools, blocked handoffs, routing, output control, and near-miss precision.</p>
      <table>
        <tr>
          <th>Group</th>
          <th>Tasks</th>
        </tr>
        {group_rows}
      </table>
    </section>
    """

    body = f"""
    <header>
      <h1>Data Point 3 - Agent-to-Agent Control</h1>
      <p class="lede">This benchmark models a deterministic agent workflow and measures which messages, handoffs, tool calls, and final outputs are governed across the mesh.</p>
    </header>
    <section class="panel">
      <h2>Run Context</h2>
      <p><strong>Generated:</strong> {html.escape(data['benchmark_metadata']['generated_at_utc'])}</p>
      <p><strong>Input:</strong> <span class="mono">{html.escape(data['benchmark_metadata']['input_path'])}</span></p>
    </section>
    {how_to_read}
    {caveat}
    <section class="panel note">
      <h2>Current Dataset Note</h2>
      <p>This task set is intentionally designed to make agent handoff, tool-call, and output controls visible.</p>
      <ul>
        <li><strong><span class="mono">re2_mesh</span></strong>: Catches broad patterns and high-risk phrases with deterministic regex-style controls.</li>
        <li><strong><span class="mono">listmesh</span></strong>: Uses enterprise-owned policy lists to route, mask, block handoffs, and block tool calls.</li>
        <li><strong><span class="mono">nol8sim_agent</span></strong>: Applies the target benchmark contract as a behavior placeholder, not a measured product result.</li>
      </ul>
    </section>
    <section class="panel note">
      <h2>Top-Line Takeaway</h2>
      <ul>
        <li><strong><span class="mono">re2_mesh</span></strong>: Useful for broad masking and phrase blocking, but weaker on enterprise-specific workflow semantics.</li>
        <li><strong><span class="mono">listmesh</span></strong>: Shows how known policies can stop risky handoffs and tool calls across agents.</li>
        <li><strong><span class="mono">nol8sim_agent</span></strong>: Represents the target agent-to-agent control contract until a real Nol8 endpoint is available.</li>
      </ul>
    </section>
    {cards}
    {executive_readout}
    {mode_contrast}
    {metrics_table}
    {derived_table}
    {group_breakdown}
    {composition}
    {timing_table}
    <section class="panel note">
      <details>
        <summary>Metric Definitions</summary>
        <ul>
          <li><strong>Handoffs Blocked</strong>: Agent messages stopped before reaching the next agent.</li>
          <li><strong>Tool Calls Blocked</strong>: External tool actions stopped before execution.</li>
          <li><strong>Exposures Prevented</strong>: Route, handoff-block, or tool-block decisions that prevented sensitive context from moving farther through the mesh.</li>
          <li><strong>Contract Alignment</strong>: Share of tasks where mode behavior matched both expected mesh action and expected final action.</li>
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

    rows = read_results(Path(args.results_csv))
    data = build_report_data(rows, args.input_path)
    (report_dir / "report_data.json").write_text(json.dumps(data, indent=2) + "\n")
    template_text = (report_dir / "report_template.html").read_text()
    (report_dir / "report.html").write_text(render_html(data, template_text))


if __name__ == "__main__":
    main()
