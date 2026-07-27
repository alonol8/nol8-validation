#!/usr/bin/env bash
# driver-cpu-probe.sh — per-cell driver-host CPU headroom (findings 011 step 2).
#
# "This is how we stop the load generator being the answer again." Sampled per
# CELL, not per run: a cell where the driver box is near CPU saturation is
# potentially driver-limited, and the engine number underneath it is suspect.
# The manifest captures static rig config; this captures the dynamic headroom
# that belongs beside errors and stall in the CSV.
#
# Prints two numbers:  <overall_busy_pct> <busiest_single_core_pct>
# "the load generator was the limit" has two shapes and this catches both:
#   overall_busy_pct        whole box saturating (GOMAXPROCS spread over cores)
#   busiest_single_core_pct one hot goroutine pinning a core while the average
#                           still looks calm (verified: 2 spinners on a 32-core
#                           box read 6.3% overall / 100% busiest)
#
# HOST-SCOPED BY CONSTRUCTION. /proc/stat aggregates every CPU regardless of the
# reader's affinity — unlike `nproc`, which is caller-affinity-scoped (the bug
# that read aergia-demo as 4 cores). The busy% is host truth even if the shell
# were confined. Read-only, zero test impact — the headless per-cell counterpart
# of watch-load.sh.
#
# Two modes:
#   --window N     sample N seconds, print once. Ad-hoc / self-test.
#   --tail N       sample at 1 Hz until SIGTERM, then report busy% over the LAST
#                  N seconds of samples. This is the one to WIRE IN: a driver
#                  invocation is [corpus-load][warmup][measure], and the measure
#                  window is always the final `duration` seconds before it exits,
#                  so tailing is robust to variable corpus-load time in a way that
#                  "sleep the warmup then sample" is not.
#
# Wiring (runs ON the driver box, one probe per single-cell driver invocation):
#   bash driver-cpu-probe.sh --tail "$DURATION" > cpu.tmp & P=$!
#   "$DRIVER" ... --duration "$DURATION" ...
#   kill -TERM "$P"; wait "$P"; read -r OVERALL MAXCORE < cpu.tmp
set -uo pipefail

MODE=""; N=5
case "${1:-}" in
  --window) MODE=window; N="${2:-5}" ;;
  --tail)   MODE=tail;   N="${2:-15}" ;;
  *) echo "usage: $0 --window N | --tail N" >&2; exit 2 ;;
esac

# One /proc/stat snapshot: "<cpukey> <busy_jiffies> <total_jiffies>" per line.
# fields after label: user nice system idle iowait irq softirq steal ...
# idle_all = idle+iowait; busy = total - idle_all.
snap() {
  awk '/^cpu[0-9]* / || /^cpu / {
         tot=0; for (i=2;i<=NF;i++) tot+=$i;
         idle=$5+$6; printf "%s %d %d\n", $1, tot-idle, tot
       }' /proc/stat
}

# busy% between two snapshots: overall (the `cpu` aggregate) and busiest core.
reduce() {
  paste <(printf '%s\n' "$1") <(printf '%s\n' "$2") | awk '
    { key=$1; db=$5-$2; dt=$6-$3; pct=(dt>0)?100*db/dt:0;
      if (key=="cpu") overall=pct; else if (pct>maxc) maxc=pct }
    END { printf "%.1f %.1f\n", overall, maxc }'
}

if [ "$MODE" = window ]; then
  A=$(snap); sleep "$N"; B=$(snap); reduce "$A" "$B"
  exit 0
fi

# --tail: ring buffer of 1 Hz snapshots; on SIGTERM diff the snapshot ~N seconds
# back against the latest so the reported window is the measure window.
declare -a RING
STOP=0
trap 'STOP=1' TERM INT
while [ "$STOP" -eq 0 ]; do
  RING+=("$(snap)")
  # keep at most N+2 snapshots
  while [ "${#RING[@]}" -gt $((N + 2)) ]; do RING=("${RING[@]:1}"); done
  sleep 1 &
  wait $! 2>/dev/null || true      # interruptible sleep so SIGTERM is prompt
done
L=${#RING[@]}
if [ "$L" -ge 2 ]; then
  start=$((L - 1 - N)); [ "$start" -lt 0 ] && start=0
  reduce "${RING[$start]}" "${RING[$((L - 1))]}"
else
  echo "NA NA"
fi
