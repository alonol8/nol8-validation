#!/usr/bin/env bash
# Showcase: the FPGA's real advantage — CPU cost, measured on the engine hosts.
#
# Run from a machine whose ~/.ssh/config has `themis-demo` and `aergia-demo`
# (the SA laptop). It samples the actual cores each engine's data plane consumes
# and prints the contrast. No load generator, no Grafana, no F2 cost: both data
# planes are DPDK *poll-mode*, so the cores are consumed continuously by design —
# what you see at rest is the standing operating cost, and it does not change under
# load (the matcher threads are pinned and already spin at 100%).
#
#   bash demos/showcase/efficiency-demo.sh
#
# Throughput figures for the cores-per-throughput math come from the DP4 rule-count
# sweep (small payloads, median of 3); override if you re-measure.
set -uo pipefail

THEMIS_HOST="${THEMIS_HOST:-themis-demo}"
AERGIA_HOST="${AERGIA_HOST:-aergia-demo}"
# Corrected throughput: DP4 10-Argus clean sweep, 8k rules, conc 256 (medians).
# The old 28,600/26,300 were EDGE-limited (single Argus) — see DP4 brief. Cores are
# poll-mode → verified flat idle→load (Themis apollo 10.91→11.29, Aergia apollo
# 10.97→11.23 / lexers 8.17→8.01 under conc-256 load), so idle sampling is valid.
THEMIS_RPS="${THEMIS_RPS:-76600}"
AERGIA_RPS="${AERGIA_RPS:-56900}"
WINDOW="${WINDOW:-4}"               # seconds to average core usage over

# Sum utime+stime (fields 14,15) across all PIDs matching a name, twice, WINDOW
# apart, and print (delta_jiffies / (WINDOW*100)) = average cores consumed.
# Emits: "<cores> <total_jiffies_now>" — runs entirely on the remote host.
remote_cores() {
  local host="$1" name="$2"
  ssh -o ConnectTimeout=10 "$host" "
    pids=\$(pgrep -x '$name' 2>/dev/null); [ -z \"\$pids\" ] && { echo 'NA'; exit 0; }
    s=0; for p in \$pids; do v=\$(awk '{print \$14+\$15}' /proc/\$p/stat 2>/dev/null); s=\$((s+v)); done
    sleep $WINDOW
    e=0; for p in \$pids; do v=\$(awk '{print \$14+\$15}' /proc/\$p/stat 2>/dev/null); e=\$((e+v)); done
    awk -v a=\$s -v b=\$e -v w=$WINDOW 'BEGIN{printf \"%.2f\", (b-a)/(w*100)}'
  " 2>/dev/null
}

echo ">> sampling engine-host CPU over ${WINDOW}s (both idle — poll-mode makes this representative)"

TH_APOLLO=$(remote_cores "$THEMIS_HOST" apollo)
TH_MATCH=$(remote_cores "$THEMIS_HOST" aergia.real)   # expected NA on the FPGA box
AE_APOLLO=$(remote_cores "$AERGIA_HOST" apollo)
AE_MATCH=$(remote_cores "$AERGIA_HOST" aergia.real)

[ "$TH_MATCH" = "NA" ] && TH_MATCH=0
th_total=$(awk -v a="$TH_APOLLO" -v b="$TH_MATCH" 'BEGIN{printf "%.2f", a+b}')
ae_total=$(awk -v a="$AE_APOLLO" -v b="$AE_MATCH" 'BEGIN{printf "%.2f", a+b}')
tax=$(awk -v a="$ae_total" -v b="$th_total" 'BEGIN{printf "%.1f", a-b}')
th_cpk=$(awk -v c="$th_total" -v r="$THEMIS_RPS" 'BEGIN{printf "%.2f", c/(r/1000)}')
ae_cpk=$(awk -v c="$ae_total" -v r="$AERGIA_RPS" 'BEGIN{printf "%.2f", c/(r/1000)}')
ratio=$(awk -v a="$ae_cpk" -v b="$th_cpk" 'BEGIN{printf "%.2f", a/b}')

bar="────────────────────────────────────────────────────────────────────"
printf '\n%s\n  ENGINE CPU COST  (cores consumed on the engine host, at rest)\n%s\n' "$bar" "$bar"
printf '  %-26s %10s %10s %10s\n' "engine" "data-plane" "matcher" "TOTAL"
printf '  %-26s %10s %10s %10s\n' "Themis (FPGA, :443)"  "$TH_APOLLO" "FPGA/0" "$th_total"
printf '  %-26s %10s %10s %10s\n' "Aergia (RE2 sw, :444)" "$AE_APOLLO" "$AE_MATCH" "$ae_total"
printf '\n%s\n  WHAT IT MEANS\n%s\n' "$bar" "$bar"
printf '  Software tax the FPGA eliminates:   ~%s CPU cores (the RE2 lexers)\n' "$tax"
printf '  Cores per 1k req/s:  Themis %s   vs   Aergia %s   →  %sx\n' "$th_cpk" "$ae_cpk" "$ratio"
printf '  Both data planes are poll-mode: these cores burn continuously, serving\n'
printf '  traffic or not. The FPGA does the matching in silicon — those ~%s cores\n' "$tax"
printf '  stay free for other work.\n\n'
