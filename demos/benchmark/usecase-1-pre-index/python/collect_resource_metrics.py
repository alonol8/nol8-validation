import json
import re
import sys
from pathlib import Path

USER_RE = re.compile(r"User time \(seconds\):\s+([0-9.]+)")
SYSTEM_RE = re.compile(r"System time \(seconds\):\s+([0-9.]+)")
CPU_RE = re.compile(r"Percent of CPU this job got:\s+([0-9%]+)")
ELAPSED_RE = re.compile(r"Elapsed \(wall clock\) time .*:\s+(.+)")
RSS_RE = re.compile(r"Maximum resident set size \(kbytes\):\s+(\d+)")
BSD_TIME_RE = re.compile(
    r"^\s*([0-9.]+)\s+real\s+([0-9.]+)\s+user\s+([0-9.]+)\s+sys\s*$",
    re.MULTILINE,
)

def elapsed_to_seconds(text: str) -> float:
    text = text.strip()
    parts = text.split(":")
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0

def parse_time_file(path: Path):
    raw = path.read_text()
    user = USER_RE.search(raw)
    system = SYSTEM_RE.search(raw)
    cpu = CPU_RE.search(raw)
    elapsed = ELAPSED_RE.search(raw)
    rss = RSS_RE.search(raw)
    bsd_time = BSD_TIME_RE.search(raw)

    if bsd_time:
        return {
            "user_cpu_seconds": float(bsd_time.group(2)),
            "system_cpu_seconds": float(bsd_time.group(3)),
            "cpu_percent": "",
            "elapsed_seconds": float(bsd_time.group(1)),
            "max_rss_kb": 0,
        }

    return {
        "user_cpu_seconds": float(user.group(1)) if user else 0.0,
        "system_cpu_seconds": float(system.group(1)) if system else 0.0,
        "cpu_percent": cpu.group(1) if cpu else "",
        "elapsed_seconds": elapsed_to_seconds(elapsed.group(1)) if elapsed else 0.0,
        "max_rss_kb": int(rss.group(1)) if rss else 0,
    }

def main():
    if len(sys.argv) < 4:
        print("usage: python collect_resource_metrics.py <output.json> <mode=timefile> <mode=timefile> ...")
        raise SystemExit(1)

    output = Path(sys.argv[1])
    result = {}

    for arg in sys.argv[2:]:
        mode, file_path = arg.split("=", 1)
        result[mode] = parse_time_file(Path(file_path))

    output.write_text(json.dumps(result, indent=2))
    print(f"Wrote {output}")

if __name__ == "__main__":
    main()
