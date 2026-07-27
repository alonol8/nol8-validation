#!/usr/bin/env bash
# Efficiency measurement with REPEATS -> committed CSV (findings 009 item 2/5).
#
# Samples the cores each engine's data plane consumes on the engine hosts, N times,
# and writes one CSV row per (rep, host, process). The ~8-core software tax and the
# cores-per-req ratio are the durable, payload-independent half of the DP4 story, so
# they need repeats + spread like every other number, not a single stdout sample.
#
# Both data planes are DPDK poll-mode: the cores spin continuously by design, so IDLE
# sampling should equal UNDER-LOAD sampling. Run --load idle with Argus at 1 (engine
# hosts are up regardless of the edge); run --load under-load in the morning with the
# fleet at 10 and a driver pushing the published throughput, and compare.
#
#   bash demos/showcase/efficiency-measure.sh --load idle
#   bash demos/showcase/efficiency-measure.sh --load under-load
#
# Runs from the SA laptop (ssh config has themis-demo + aergia-demo).
set -uo pipefail

THEMIS_HOST="${THEMIS_HOST:-themis-demo}"
AERGIA_HOST="${AERGIA_HOST:-aergia-demo}"
REPS="${REPS:-5}"
WINDOW="${WINDOW:-4}"
LOAD="idle"
[ "${1:-}" = "--load" ] && LOAD="${2:-idle}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${OUT:-$ROOT/artifacts/evidence/efficiency-${LOAD}-20260726.csv}"

# Average cores for a named process over WINDOW seconds, entirely on the remote host.
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

echo "load,rep,host,engine,process,cores" > "$OUT"
echo ">> efficiency sampling: load=$LOAD reps=$REPS window=${WINDOW}s -> $OUT"
for rep in $(seq 1 "$REPS"); do
  th_apollo=$(remote_cores "$THEMIS_HOST" apollo)
  ae_apollo=$(remote_cores "$AERGIA_HOST" apollo)
  ae_lexers=$(remote_cores "$AERGIA_HOST" aergia.real)
  [ "$th_apollo" = "NA" ] && th_apollo=0
  [ "$ae_apollo" = "NA" ] && ae_apollo=0
  [ "$ae_lexers" = "NA" ] && ae_lexers=0
  printf '%s,%s,%s,themis,apollo,%s\n'      "$LOAD" "$rep" "$THEMIS_HOST" "$th_apollo" >> "$OUT"
  printf '%s,%s,%s,aergia,apollo,%s\n'      "$LOAD" "$rep" "$AERGIA_HOST" "$ae_apollo" >> "$OUT"
  printf '%s,%s,%s,aergia,aergia.real,%s\n' "$LOAD" "$rep" "$AERGIA_HOST" "$ae_lexers" >> "$OUT"
  echo "   rep $rep/$REPS: themis apollo=$th_apollo | aergia apollo=$ae_apollo lexers=$ae_lexers"
done

echo ">> summary (median across reps):"
awk -F, 'NR>1{k=$4" "$5; v[k]=v[k]" "$6}
END{for(k in v){n=split(v[k],a," ",""); asort(a); m=(n%2)?a[(n+1)/2]:(a[n/2]+a[n/2+1])/2;
  printf "   %-22s median %.2f cores\n", k, m}}' "$OUT" 2>/dev/null || cat "$OUT"
echo ">> wrote $OUT"
