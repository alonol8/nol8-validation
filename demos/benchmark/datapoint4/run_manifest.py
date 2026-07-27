#!/usr/bin/env python3
"""Run manifest — provenance for every DP4 measurement (findings 011).

We reasoned incorrectly about cross-configuration comparisons twice by hand
(single-edge flatness read as parity; old-driver-box absolutes read against
new-driver-box absolutes). This mechanizes the fix: a JSON manifest emitted
beside every CSV, capturing the exact hardware + config a number was produced
on, plus a drift check against the previous run so a cross-config comparison is
impossible to make by accident later.

WHERE THIS RUNS: the SA laptop (Mac), NOT the box. The driver runs on the box
(nol8-demo) but the box cannot resolve the engine hosts (themis-demo /
aergia-demo are Mac-ssh-only). The Mac is the only control point that reaches
all three machines, so it orchestrates the manifest — exactly like
efficiency-measure.sh. The live path (wiring capture around the box sweeps and
scp'ing the CSV back) is the NEXT step; this file is build + retrofit only.

Subcommands
  reference   Snapshot the current hardware to a reference manifest (a baseline
              the first live run can drift-check against).
  capture     Live: gather issuing-host + engine-host + config facts, write
              <csv-basename>.manifest.json, drift-check vs --prev. Called at
              --phase start and --phase end of a run.
  retrofit    For the CSVs already in artifacts/evidence/, write whatever
              manifest fields are recoverable and mark the rest UNKNOWN, so an
              old absolute carries "issuing host unknown" rather than nothing.

Host aliases are the Mac's ssh config: DRIVER_ALIAS reaches the driver box,
THEMIS_ALIAS / AERGIA_ALIAS reach the engine hosts.
"""
import argparse
import csv
import json
import os
import subprocess
import sys

DRIVER_ALIAS = os.environ.get("DP4_DRIVER_ALIAS", "nol8-demo")
THEMIS_ALIAS = os.environ.get("DP4_THEMIS_ALIAS", "themis-demo")
AERGIA_ALIAS = os.environ.get("DP4_AERGIA_ALIAS", "aergia-demo")
BOX_DRIVER = os.environ.get(
    "DP4_BOX_DRIVER", "/opt/nol8/nol8-validation/demos/benchmark/datapoint4/results/dp4driver"
)
UNKNOWN = "UNKNOWN"

# A field value is a {value, provenance} pair so the epistemic status travels
# with the number. provenance is one of:
#   measured_now        read live from the host this run
#   recovered_from_csv  parsed out of the CSV being retrofitted
#   inferred_unchanged  a current fact that also held for an old run because the
#                       host has been up continuously since before that run
#   inferred            reasoned from external notes (e.g. Alon's PR), not read
#   unknown             not recorded at measurement time and not recoverable
def field(value, provenance):
    return {"value": value, "provenance": provenance}


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as e:  # noqa: BLE001 — a missing fact must not abort the run
        return f"ERROR: {e}"


def ssh(alias, remote):
    return sh(["ssh", "-o", "ConnectTimeout=10", alias, remote])


# ---------------------------------------------------------------------------
# Live host fact gatherers (used by `reference` and `capture`)
# ---------------------------------------------------------------------------
def _instance_type(alias):
    tok = ssh(
        alias,
        'curl -s -m3 -X PUT "http://169.254.169.254/latest/api/token" '
        '-H "X-aws-ec2-metadata-token-ttl-seconds: 60"',
    )
    it = ssh(
        alias,
        f'curl -s -m3 -H "X-aws-ec2-metadata-token: {tok}" '
        "http://169.254.169.254/latest/meta-data/instance-type",
    )
    if not it or it.startswith("ERROR"):
        it = ssh(alias, "curl -s -m3 http://169.254.169.254/latest/meta-data/instance-type")
    return it or UNKNOWN


def host_facts(alias, prov="measured_now"):
    """hostname, instance, vCPU, boot, kernel — the static shape of a machine."""
    return {
        "reachable_via": f"ssh {alias}",
        "hostname": field(ssh(alias, "hostname"), prov),
        "instance_type": field(_instance_type(alias), prov),
        # nproc alone reports CPUs available to the (possibly affinity-confined)
        # login shell — on aergia-demo that is 4, not the machine's 32. --all is
        # the installed count, which is the vCPU number we actually mean.
        "vcpu": field(ssh(alias, "nproc --all"), prov),
        "boot_time": field(ssh(alias, "uptime -s"), prov),
        "kernel": field(ssh(alias, "uname -r"), prov),
    }


def driver_facts(alias):
    f = host_facts(alias)
    # Repo root the driver is built from (parent of demos/...).
    repo = BOX_DRIVER.split("/demos/", 1)[0]
    src = "demos/benchmark/datapoint4/go"  # the driver's actual source subtree
    f["dp4driver"] = {
        "path": field(BOX_DRIVER, "measured_now"),
        "mtime": field(
            ssh(alias, f'stat -c "%y" {BOX_DRIVER} 2>/dev/null || echo {UNKNOWN}'), "measured_now"
        ),
        # Binary sha is RECORDED but is NOT a drift trigger: Go builds are not
        # reproducible without -trimpath, so the sha moves on every `go build`
        # from identical source. Source identity (below) is the trigger instead.
        "sha256": field(
            ssh(alias, f'sha256sum {BOX_DRIVER} 2>/dev/null | cut -d" " -f1 || echo {UNKNOWN}'),
            "measured_now",
        ),
        # The authoritative source identity: the commit the driver source sits at,
        # and whether that source subtree is clean. A sha change with an unchanged
        # commit and a clean tree is benign; a commit change or a dirty tree is not.
        "source_commit": field(
            ssh(alias, f'git -C {repo} rev-parse --short HEAD 2>/dev/null || echo {UNKNOWN}'),
            "measured_now",
        ),
        "source_clean": field(
            ssh(alias, f'[ -z "$(git -C {repo} status --porcelain -- {src} 2>/dev/null)" ] '
                       f'&& echo clean || echo dirty'),
            "measured_now",
        ),
    }
    f["go_version"] = field(
        ssh(alias, "$HOME/.local/go/bin/go version 2>/dev/null || go version 2>/dev/null"),
        "measured_now",
    )
    return f


def engine_facts(alias, procs):
    """Engine host: static shape + per-process identity, pinning, hugepages,
    and a live core-count sample. `procs` is the list of process names to look
    for (e.g. ['apollo'] for Themis, ['apollo','aergia.real'] for Aergia)."""
    f = host_facts(alias)
    f["hugepages"] = field(
        ssh(alias, "grep -E 'HugePages_Total|HugePages_Free|Hugepagesize' /proc/meminfo | tr '\\n' ' '"),
        "measured_now",
    )
    proc_list = []
    for name in procs:
        for pid in ssh(alias, f"pgrep -x {name} 2>/dev/null").split():
            proc_list.append(
                {
                    "name": name,
                    "pid": pid,
                    "start_time": ssh(alias, f'ps -o lstart= -p {pid} 2>/dev/null'),
                    "cpus_allowed": ssh(alias, f"awk '/Cpus_allowed_list/{{print $2}}' /proc/{pid}/status 2>/dev/null"),
                    "threads": ssh(alias, f"awk '/^Threads/{{print $2}}' /proc/{pid}/status 2>/dev/null"),
                    # exe sha only where readable without escalation
                    "exe_sha256": ssh(
                        alias,
                        f'sha256sum "$(readlink -f /proc/{pid}/exe 2>/dev/null)" 2>/dev/null '
                        f'| cut -d" " -f1 || echo {UNKNOWN}',
                    )
                    or UNKNOWN,
                }
            )
    f["processes"] = field(proc_list, "measured_now")
    f["core_counts_at_capture"] = field(_core_sample(alias, procs), "measured_now")
    return f


def _core_sample(alias, procs, window=4):
    """Average cores each named process consumes over `window` seconds."""
    out = {}
    for name in procs:
        r = ssh(
            alias,
            "pids=$(pgrep -x %s 2>/dev/null); [ -z \"$pids\" ] && { echo NA; exit 0; }; "
            "s=0; for p in $pids; do v=$(awk '{print $14+$15}' /proc/$p/stat); s=$((s+v)); done; "
            "sleep %d; "
            "e=0; for p in $pids; do v=$(awk '{print $14+$15}' /proc/$p/stat); e=$((e+v)); done; "
            "awk -v a=$s -v b=$e 'BEGIN{printf \"%%.2f\", (b-a)/(%d*100)}'" % (name, window, window),
        )
        out[name] = r
    return out


# ---------------------------------------------------------------------------
# CSV recovery (used by `retrofit`)
# ---------------------------------------------------------------------------
def recover_from_csv(path):
    """Pull whatever measurement config a DP4 CSV still carries in its columns."""
    rec = {"columns": UNKNOWN, "rows": 0}
    try:
        with open(path, newline="") as fh:
            # Skip leading `#` comment lines: superseded evidence CSVs carry a
            # one-line `# SUPERSEDED`/`# CAVEAT` header (annotate-in-place), which
            # must not be mistaken for the column header.
            reader = csv.reader(line for line in fh if not line.startswith("#"))
            header = next(reader, None)
            if not header:
                return rec
            rec["columns"] = header
            idx = {h: i for i, h in enumerate(header)}
            seen = {k: set() for k in
                    ("concurrency", "payload", "rule_count", "rep", "records_used", "duration_s")}
            abv = []
            n = 0
            for row in reader:
                if not row:
                    continue
                n += 1
                for k in seen:
                    if k in idx and idx[k] < len(row):
                        seen[k].add(row[idx[k]])
                if "avg_body_bytes" in idx and idx["avg_body_bytes"] < len(row):
                    try:
                        abv.append(float(row[idx["avg_body_bytes"]]))
                    except ValueError:
                        pass
            rec["rows"] = n
            for k, vals in seen.items():
                if vals:
                    rec[k] = sorted(vals)
            if abv:
                rec["avg_body_bytes_range"] = [min(abv), max(abv)]
            # harness generation: presence of error/stall accounting
            rec["has_error_accounting"] = "errors" in idx or "err_p99_ms" in idx
            rec["has_stall_accounting"] = "stall_seconds_total" in idx
            rec["has_issuing_host_column"] = any(
                h in idx for h in ("issuing_host", "driver_host", "driver_cpu_pct")
            )
    except FileNotFoundError:
        rec["error"] = "file not found"
    return rec


# What we genuinely know about each pre-existing evidence file, beyond its
# columns. Keyed by filename. argus = edge node count; era gives issuing-host
# status. Anything absent here falls through to UNKNOWN.
KNOWN = {
    # single-edge era (the flatness that was misread as parity)
    "rulecount-jul24-cliff.csv": {"argus": 1, "note": "single edge; contains Aergia@8k cliff"},
    "rulecount-jul25-clean.csv": {"argus": 1, "note": "single edge; flatness is edge ceiling, not parity"},
    "throughput_combined-fairrun.csv": {"argus": 1, "note": "original DP4 fair run; superseded for absolutes"},
    # 10-edge era, old 8-vCPU driver box
    "rulecount-10argus-jul25-partial.csv": {"argus": 10, "note": "partial 2k/4k/8k"},
    "rulecount-10argus-clean.csv": {"argus": 10, "note": "superseded as trend basis"},
    "concpush-8k-themis-10argus.csv": {"argus": 10, "note": "concurrency push, Themis"},
    "concpush-8k-aergia-10argus.csv": {"argus": 10, "note": "concurrency push, Aergia"},
    "rulecount-2k4k-clean-20260726.csv": {"argus": 10, "note": "clean re-run, fixed harness"},
    "mediumlarge-10edge-20260726.csv": {"argus": 10, "note": "medium/large @4k; bandwidth-bound"},
    "rulecount-2k4k6k8k-clean-20260726.csv": {"argus": 10, "note": "4-point trend basis (median)"},
    "large-rerun-4k-20260726.csv": {"argus": 10, "note": "large re-run @4k, 3 reps"},
    # efficiency — issued from the MAC, not the driver box; measured engine hosts
    "efficiency-idle-20260726.csv": {
        "argus": 1,
        "issued_from": "mac",
        "note": "idle core sampling from the SA laptop; PRE-morning-changes "
                "(before driver resize 06:44 and Aergia engine restart 09:36 on 2026-07-27)",
    },
}


def retrofit_manifest(path):
    """Partial manifest for one existing evidence CSV: recoverable fields filled,
    everything else explicitly UNKNOWN. All throughput absolutes here were issued
    from the OLD driver box, which no longer exists (resized 2026-07-27 06:44)."""
    name = os.path.basename(path)
    known = KNOWN.get(name, {})
    issued_from = known.get("issued_from", "driver_box")

    if issued_from == "mac":
        issuing = {
            "role": "sa_laptop",
            "note": field(known.get("note", ""), "inferred"),
            "instance_type": field("Mac laptop (not an instance)", "inferred"),
        }
    else:
        # every pre-2026-07-27 throughput number came off the OLD driver box
        issuing = {
            "role": "driver_box",
            "hostname": field(UNKNOWN, "unknown"),
            "instance_type": field(
                "UNKNOWN — old driver box (~8 vCPU per Alon PR note), "
                "REPLACED 2026-07-27T06:44 by c6a.8xlarge",
                "inferred",
            ),
            "vcpu": field("UNKNOWN — believed 8 (Alon PR note)", "inferred"),
            "boot_time": field(UNKNOWN, "unknown"),
            "dp4driver": {"sha256": field(UNKNOWN, "unknown")},
            "go_version": field(UNKNOWN, "unknown"),
        }

    # Engine HOSTS: the physical boxes have been up longer than any of these runs
    # (Themis up since 2026-07-16, Aergia since 2026-07-15), so their instance
    # shape is inferably unchanged. Engine PROCESSES are a different matter:
    engine_notes = field(
        "Engine BOXES unchanged since before these runs (Themis f2.6xlarge up "
        "2026-07-16; Aergia c8a.8xlarge up 2026-07-15) — instance shape inferred "
        "unchanged. Engine PROCESSES: Themis apollo current since 2026-07-25 18:38; "
        "Aergia engine RESTARTED 2026-07-27 09:36, so any run before that used a "
        "DIFFERENT Aergia process (pre-restart) — not individually verifiable here. "
        "Core pinning / hugepages at run time NOT recorded.",
        "inferred",
    )

    return {
        "manifest_version": 1,
        "phase": "retrofit",
        "generated_utc": field(UNKNOWN, "unknown"),  # retrofit has no run clock
        "run": {"csv": path, "basename": os.path.splitext(name)[0]},
        "issuing_host": issuing,
        "engine_hosts": {"_note": engine_notes},
        "measurement": {
            "argus_nodes": field(known.get("argus", UNKNOWN),
                                 "inferred" if "argus" in known else "unknown"),
            "policy": {"path": field(UNKNOWN, "unknown"),
                       "rule_count": field(UNKNOWN, "unknown"),
                       "sha256": field(UNKNOWN, "unknown"),
                       "deploy_utc": field(UNKNOWN, "unknown")},
            "corpus": {"dir": field(UNKNOWN, "unknown"),
                       "sha256_or_size": field(UNKNOWN, "unknown")},
            "recovered_from_csv": recover_from_csv(path),
            "density_coordinate": field(UNKNOWN, "unknown"),
            "utc_start": field(UNKNOWN, "unknown"),
            "utc_end": field(UNKNOWN, "unknown"),
        },
        "drift": {"prev_manifest": None, "changed_fields": [], "result": "n/a (retrofit)"},
        "unrecoverable": [
            "issuing host identity + dp4driver sha + go version",
            "engine core pinning / hugepages / core counts at run time",
            "policy sha + deploy timestamp; corpus sha; exact UTC start/end",
        ],
        "standing": "Absolutes describe a configuration that no longer exists "
                    "(old driver box). Ratios within one run may survive; "
                    "cross-run absolutes do not. Not banked.",
    }


# ---------------------------------------------------------------------------
# Live capture (reference + start/end) and drift check
# ---------------------------------------------------------------------------
def gather_live(phase, cfg):
    return {
        "manifest_version": 1,
        "phase": phase,
        "generated_utc": field(cfg.get("utc", UNKNOWN),
                               "measured_now" if cfg.get("utc") else "unknown"),
        "run": {"csv": cfg.get("csv"), "basename": cfg.get("basename")},
        "issuing_host": driver_facts(DRIVER_ALIAS),
        "engine_hosts": {
            "themis": engine_facts(THEMIS_ALIAS, ["apollo"]),
            "aergia": engine_facts(AERGIA_ALIAS, ["apollo", "aergia.real"]),
        },
        "measurement": {
            "argus_nodes": field(cfg.get("argus"), "provided" if cfg.get("argus") else "unknown"),
            "policy": {
                "path": field(cfg.get("policy"), "provided" if cfg.get("policy") else "unknown"),
                "rule_count": field(cfg.get("rule_count"), "provided"),
                "sha256": field(_local_sha(cfg.get("policy")), "measured_now"),
                "deploy_utc": field(cfg.get("deploy_utc"), "provided"),
            },
            "corpus": {
                "dir": field(cfg.get("corpus"), "provided"),
                "records": field(cfg.get("records"), "provided"),
                "avg_body_bytes": field(cfg.get("avg_body_bytes"), "provided"),
            },
            "density_coordinate": field(cfg.get("density"), "provided"),
            "concurrency": field(cfg.get("concurrency"), "provided"),
            "duration_s": field(cfg.get("duration"), "provided"),
            "payload": field(cfg.get("payload"), "provided"),
            "reps": field(cfg.get("reps"), "provided"),
            "utc_start": field(cfg.get("utc_start"), "provided"),
            "utc_end": field(cfg.get("utc_end"), "provided"),
        },
    }


def _local_sha(path):
    if not path or not os.path.exists(path):
        return UNKNOWN
    return sh(["shasum", "-a", "256", path]).split()[0] if sh(["shasum", "-a", "256", path]) else UNKNOWN


def _flatten(prefix, obj, out):
    """Flatten a manifest to dotted field->value, ignoring timestamps + live
    core samples (dynamic by design, not configuration drift)."""
    # Skipped from drift comparison (still recorded in the manifest): timestamps,
    # live core samples, and BINARY SHAS. A binary sha is a poor drift trigger
    # because Go builds are not reproducible without -trimpath, so it moves on
    # every build from identical source; source_commit + source_clean are the
    # trigger instead. `sha256` covers the dp4driver binary and any policy sha.
    SKIP = ("generated_utc", "utc", "utc_start", "utc_end", "deploy_utc",
            "core_counts_at_capture", "mtime", "start_time", "sha256")
    if isinstance(obj, dict):
        if set(obj.keys()) == {"value", "provenance"}:
            out[prefix] = obj["value"]
            return
        for k, v in obj.items():
            if k in SKIP:
                continue
            _flatten(f"{prefix}.{k}" if prefix else k, v, out)
    elif isinstance(obj, list):
        out[prefix] = json.dumps(obj, sort_keys=True)
    else:
        out[prefix] = obj


# A changed field is HARDWARE/RIG drift (the dangerous, cross-configuration kind
# the manifest exists to catch) if it names the issuing host, an engine host, a
# binary, or the edge topology. Everything else under measurement.* is a run
# PARAMETER that is meant to vary cell-to-cell in a sweep (concurrency, rule
# count, payload, reps) — recording it is useful, warning on it every cell is
# cry-wolf that would bury the one warning that matters.
#
# NOTE: this is a deliberate refinement of findings-011's literal "if any field
# differs other than timestamps, warn." Flagged in the report for veto.
def _is_hardware_field(k):
    if k.startswith(("issuing_host", "engine_hosts")):
        return True
    return k == "measurement.argus_nodes"  # edge topology is a rig property


def drift_check(current, prev_path):
    if not prev_path or not os.path.exists(prev_path):
        return {"prev_manifest": prev_path, "hardware_drift": [],
                "run_param_changes": [], "result": "no_prior"}
    with open(prev_path) as fh:
        prev = json.load(fh)
    a, b = {}, {}
    _flatten("", prev, a)
    _flatten("", current, b)
    hardware, run_param = [], []
    for k in sorted(set(a) | set(b)):
        if k.startswith(("run.", "measurement.utc", "phase", "drift")):
            continue
        pv, nv = a.get(k), b.get(k)
        # Drift is only established between two KNOWN values. A null/UNKNOWN on
        # either side (e.g. the hardware reference never recorded Argus count)
        # is "not comparable," not a change — otherwise the reference->first-run
        # boundary shows phantom drift.
        if pv in (None, UNKNOWN) or nv in (None, UNKNOWN):
            continue
        if pv != nv:
            entry = {"field": k, "prev": pv, "now": nv}
            (hardware if _is_hardware_field(k) else run_param).append(entry)
    return {
        "prev_manifest": prev_path,
        "hardware_drift": hardware,
        "run_param_changes": run_param,
        "result": "HARDWARE_DRIFT" if hardware else "clean",
    }


def write_manifest(obj, out_path):
    with open(out_path, "w") as fh:
        json.dump(obj, fh, indent=2)
    print(f">> wrote {out_path}")


# ---------------------------------------------------------------------------
def cmd_reference(args):
    m = gather_live("reference", {"utc": args.utc})
    out = args.out or os.path.join(args.evidence, "current-config.manifest.json")
    write_manifest(m, out)


def cmd_capture(args):
    cfg = {k: getattr(args, k) for k in
           ("csv", "argus", "policy", "rule_count", "deploy_utc", "corpus",
            "records", "avg_body_bytes", "density", "concurrency", "duration",
            "payload", "reps", "utc_start", "utc_end", "utc")}
    cfg["basename"] = os.path.splitext(os.path.basename(args.csv))[0] if args.csv else None
    m = gather_live(args.phase, cfg)
    m["drift"] = drift_check(m, args.prev)
    if m["drift"]["result"] == "HARDWARE_DRIFT":
        hw = m["drift"]["hardware_drift"]
        # Print a count header AND a footer so a pipeline that truncates the list
        # (`| head`) is self-evidently truncated — the last drift warning got past
        # both of us exactly because it was truncated without any sign it was.
        print(f"!! HARDWARE DRIFT vs previous run — the rig changed. Absolutes are NOT "
              f"comparable across this boundary. {len(hw)} field(s) drifted (full list):",
              file=sys.stderr)
        for c in hw:
            print(f"   {c['field']}: {c['prev']!r} -> {c['now']!r}", file=sys.stderr)
        print(f"!! end of {len(hw)} drifted field(s) — if you do not see this line the list was truncated",
              file=sys.stderr)
    for c in m["drift"].get("run_param_changes", []):
        print(f"   (run param) {c['field']}: {c['prev']!r} -> {c['now']!r}")
    out = args.out or f"{os.path.splitext(args.csv)[0]}.{args.phase}.manifest.json"
    write_manifest(m, out)


def cmd_retrofit(args):
    n = 0
    for name in sorted(os.listdir(args.evidence)):
        if not name.endswith(".csv"):
            continue
        path = os.path.join(args.evidence, name)
        out = os.path.join(args.evidence, os.path.splitext(name)[0] + ".manifest.json")
        write_manifest(retrofit_manifest(path), out)
        n += 1
    print(f">> retrofitted {n} CSV manifest(s) in {args.evidence}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("reference", help="snapshot current hardware")
    r.add_argument("--evidence", default="artifacts/evidence")
    r.add_argument("--out")
    r.add_argument("--utc")
    r.set_defaults(func=cmd_reference)

    c = sub.add_parser("capture", help="live start/end capture around a run")
    c.add_argument("--phase", choices=["start", "end"], required=True)
    c.add_argument("--csv", required=True)
    c.add_argument("--prev")
    c.add_argument("--out")
    for opt in ("argus", "policy", "rule-count", "deploy-utc", "corpus", "records",
                "avg-body-bytes", "density", "concurrency", "duration", "payload",
                "reps", "utc-start", "utc-end", "utc"):
        c.add_argument(f"--{opt}")
    c.set_defaults(func=cmd_capture)

    rf = sub.add_parser("retrofit", help="partial manifests for existing evidence")
    rf.add_argument("--evidence", default="artifacts/evidence")
    rf.set_defaults(func=cmd_retrofit)

    args = p.parse_args()
    # argparse turns --rule-count into rule_count etc.; normalize the few used positionally
    if getattr(args, "cmd", None) == "capture":
        args.rule_count = getattr(args, "rule_count", None)
        args.avg_body_bytes = getattr(args, "avg_body_bytes", None)
        args.utc_start = getattr(args, "utc_start", None)
        args.utc_end = getattr(args, "utc_end", None)
        args.deploy_utc = getattr(args, "deploy_utc", None)
    args.func(args)


if __name__ == "__main__":
    main()
