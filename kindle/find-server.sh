#!/bin/sh
set -eu
BASE=${KQD_BASE:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
. "$BASE/common.sh"
FORCE=0; INTERNAL=0; KNOWN_ONLY=0
for arg in "$@"; do
    case "$arg" in --force) FORCE=1;; --known-only) KNOWN_ONLY=1;; --internal) INTERNAL=1;; *) exit 2;; esac
done
[ "$FORCE:$KNOWN_ONLY" != 1:1 ] || exit 2
mkdir -p "$STATE"
WORK=$(mktemp -d /tmp/kqd-discover.XXXXXX)
pids=''
cleanup() {
    cancel_command
    for scan_pid in $pids; do kill "$scan_pid" 2>/dev/null || true; done
    for scan_pid in $pids; do wait "$scan_pid" 2>/dev/null || true; done
    rm -rf "$WORK"
    [ "$INTERNAL" -eq 1 ] || wifi_restore
}
trap cleanup 0
trap 'exit 1' 1 2 15
if [ -z "${KQD_NET_DEADLINE:-}" ]; then
    if [ "$FORCE" -eq 1 ]; then network_begin 120; else network_begin 30; fi
fi
[ "$INTERNAL" -eq 1 ] || wifi_begin
found() { save_server "$1"; printf '%s\n' "$1"; exit 0; }
cached=
if [ "$FORCE" -eq 0 ] && [ -f "$BASE/server.cache" ]; then
    cached=$(cat "$BASE/server.cache")
fi
# Automatic calls never scan, even if ENABLE_SCAN=1. Deduplicate known hosts.
for pass in 1 2 3; do
    seen=' '
    for known in "$cached" "$SERVER_IP" "$SERVER_HOST"; do
        valid_host "$known" || continue
        case "$seen" in *" $known "*) continue;; esac
        seen="$seen$known "
        if probe "$known" "$WORK/health"; then found "$known"; fi
    done
    # IPv4 can appear before association/routing is usable after RTC resume.
    # These short retries share the original budget and never enable scanning.
    [ "$FORCE" -eq 0 ] && [ "$pass" -lt 3 ] || break
    retry_time=$(budget_timeout 3) || break
    [ "$retry_time" -gt 1 ] || break
    bounded "$retry_time" sleep "$((retry_time - 1))" || break
done
[ "$FORCE" -eq 1 ] || exit 1
[ "$ENABLE_SCAN" -eq 1 ] || exit 1
# Scan the actual private subnet, capped at /22 (1022 hosts). Prioritize the
# local /24 intersection, then the rest; never guess or broaden the mask.
cidr=$(ip -4 addr show dev wlan0 2>/dev/null | awk '$1=="inet" {print $2; exit}')
mask=${cidr##*/}
case "$mask" in 22|23|24|25|26|27|28|29|30) ;; *) echo 'Manual scan requires private IPv4 /22 through /30; configure SERVER_IP' >&2; exit 1;; esac
local_ip=${cidr%/*}
valid_ip "$local_ip" || exit 1
case "$local_ip" in
    10.*|192.168.*) ;;
    172.*) second=$(printf '%s' "$local_ip" | cut -d. -f2); [ "$second" -ge 16 ] && [ "$second" -le 31 ] || exit 1;;
    *) exit 1;;
esac
# AWK numbers represent IPv4 exactly, avoiding signed 32-bit shell overflow.
awk -v addr="$local_ip" -v mask="$mask" '
function dotted(n, a,b,c,d) {
    a=int(n/16777216); b=int(n/65536)%256; c=int(n/256)%256; d=n%256
    return sprintf("%d.%d.%d.%d",a,b,c,d)
}
BEGIN {
    split(addr,o,"."); me=o[1]*16777216+o[2]*65536+o[3]*256+o[4]
    size=2^(32-mask); first=int(me/size)*size+1; last=first+size-3
    nearby=int(me/256)*256
    for(pass=0;pass<2;pass++) for(n=first;n<=last;n++)
        if(n!=me && ((n>=nearby && n<nearby+256) == (pass==0))) print dotted(n)
}' > "$WORK/candidates"
scan_deadline=$(($(tick) + 90))
[ "$scan_deadline" -le "$KQD_NET_DEADLINE" ] || scan_deadline=$KQD_NET_DEADLINE
KQD_NET_DEADLINE=$scan_deadline; export KQD_NET_DEADLINE
n=0; batch=0
while IFS= read -r candidate; do
    if ! budget_timeout 1 >/dev/null; then
        echo 'Quota server scan time budget exhausted' >&2
        exit 1
    fi
    n=$((n + 1)); batch=$((batch + 1))
    (
        CHILD_PID= TIMER_PID=
        trap cancel_command 0
        trap 'exit 1' 1 2 15
        if probe "$candidate" "$WORK/probe.$n"; then printf '%s\n' "$candidate" > "$WORK/found.$n"; fi
    ) &
    pids="$pids $!"
    if [ "$batch" -lt 16 ]; then continue; fi
    for pid in $pids; do wait "$pid" || true; done
    for file in "$WORK"/found.*; do [ ! -f "$file" ] || found "$(cat "$file")"; done
    batch=0; pids=''
done < "$WORK/candidates"
for pid in $pids; do wait "$pid" || true; done
for file in "$WORK"/found.*; do [ ! -f "$file" ] || found "$(cat "$file")"; done
echo 'Quota server not found' >&2
exit 1
