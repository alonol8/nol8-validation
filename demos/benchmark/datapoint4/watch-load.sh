#!/usr/bin/env bash
# DP4 live backpressure / choke-point watch.
#
# Run this ON the driver box (EC2) WHILE a throughput sweep is driving, to SEE
# where the pipe backs up. It reads only (ss + nstat + /proc) - zero impact on
# the test, so run it as much as you like.
#
#   bash demos/benchmark/datapoint4/watch-load.sh            # summary, refresh 1s
#   bash demos/benchmark/datapoint4/watch-load.sh 2          # summary, refresh 2s
#   bash demos/benchmark/datapoint4/watch-load.sh 1 detail   # + per-socket cwnd/rtt/retrans
#
# From your Mac:  ssh nol8-demo 'bash /opt/nol8/nol8-validation/demos/benchmark/datapoint4/watch-load.sh'
#
# HOW TO READ IT
#   Send-Q climbing  -> our send buffers are full: the EDGE isn't draining what we
#                       send => the choke is DOWNSTREAM of the driver (edge / FPGA).
#                       This is the "we back up at Apollo/argus" smoking gun.
#   Recv-Q climbing  -> responses arriving faster than the driver reads them
#                       => driver-side (rare here).
#   retrans/s > 0    -> packet loss on the wire => the network link, not the engine.
#   load >> cores    -> the DRIVER box itself is CPU-bound (it, not the engine, is
#                       the limit) - don't over-read the engine numbers then.
set -euo pipefail

INTERVAL="${1:-1}"
MODE="${2:-summary}"
FILTER='( dport = :443 or dport = :444 )'
CORES="$(nproc 2>/dev/null || echo '?')"

retrans_total() { nstat -az 2>/dev/null | awk '/TcpRetransSegs/{print $2; exit}'; }
prev_retrans="$(retrans_total || echo 0)"; prev_retrans="${prev_retrans:-0}"

while true; do
  now="$(date '+%H:%M:%S')"
  # aggregate Recv-Q/Send-Q per engine port
  agg="$(ss -Htn state established "$FILTER" 2>/dev/null | awk '
    { peer=$NF; k=split(peer,a,":"); port=a[k];
      rq[port]+=$1; sq[port]+=$2; c[port]++; trq+=$1; tsq+=$2; tot++ }
    END {
      printf "  :443 themis   conns=%-6d Recv-Q=%-12d Send-Q=%-12d\n", c["443"]+0, rq["443"]+0, sq["443"]+0
      printf "  :444 aergia   conns=%-6d Recv-Q=%-12d Send-Q=%-12d\n", c["444"]+0, rq["444"]+0, sq["444"]+0
      printf "  TOTAL         conns=%-6d Recv-Q=%-12d Send-Q=%-12d\n", tot+0, trq+0, tsq+0
    }')"
  # retrans delta over the interval
  cur_retrans="$(retrans_total || echo "$prev_retrans")"; cur_retrans="${cur_retrans:-$prev_retrans}"
  d_retrans=$(( cur_retrans - prev_retrans )); prev_retrans="$cur_retrans"
  rps=$(awk -v d="$d_retrans" -v i="$INTERVAL" 'BEGIN{printf "%.0f", (i>0)? d/i : d}')
  load="$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null)"

  clear 2>/dev/null || printf '\n\n'
  echo "DP4 backpressure watch  ${now}   (refresh ${INTERVAL}s, ${CORES} cores)"
  echo "-------------------------------------------------------------------------"
  echo "$agg"
  echo "-------------------------------------------------------------------------"
  echo "  retrans/s=${rps}    loadavg=${load}   (load >> ${CORES} => driver is the limit)"
  echo "  Send-Q up => choke downstream (edge/FPGA).  Recv-Q up => driver-side."

  if [ "$MODE" = "detail" ]; then
    echo "-------------------------------------------------------------------------"
    echo "  top sockets (Recv-Q Send-Q Peer + cwnd/rtt/retrans):"
    ss -tin state established "$FILTER" 2>/dev/null | head -24 | sed 's/^/    /'
  fi

  sleep "$INTERVAL"
done
