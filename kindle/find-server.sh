#!/bin/sh
set -eu
BASE=${KQD_BASE:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
. "$BASE/common.sh"
FORCE=0; INTERNAL=0
for arg in "$@"; do
    case "$arg" in --force) FORCE=1;; --internal) INTERNAL=1;; *) exit 2;; esac
done
WORK=$(mktemp -d /tmp/kqd-discover.XXXXXX)
cleanup() { rm -rf "$WORK"; [ "$INTERNAL" -eq 1 ] || wifi_restore; }
trap cleanup 0
trap 'exit 1' 1 2 15
[ "$INTERNAL" -eq 1 ] || wifi_begin
found() { save_server "$1"; printf '%s\n' "$1"; exit 0; }
if [ "$FORCE" -eq 0 ] && [ -f "$BASE/server.cache" ]; then
    cached=$(cat "$BASE/server.cache")
    if valid_host "$cached" && probe "$cached" "$WORK/health"; then found "$cached"; fi
fi
if [ -n "$SERVER_IP" ] && probe "$SERVER_IP" "$WORK/health"; then found "$SERVER_IP"; fi
if [ -n "$SERVER_HOST" ] && probe "$SERVER_HOST" "$WORK/health"; then found "$SERVER_HOST"; fi
[ "$ENABLE_SCAN" -eq 1 ] || exit 1
# Scan the actual private subnet, capped at /22 (1022 hosts). Prioritize the
# local /24 intersection, then the rest; never guess or broaden the mask.
cidr=$(ip -4 addr show dev wlan0 2>/dev/null | awk '$1=="inet" {print $2; exit}')
mask=${cidr##*/}
case "$mask" in 22|23|24|25|26|27|28|29|30) ;; *) echo 'Auto scan requires private IPv4 /22 through /30; configure SERVER_IP' >&2; exit 1;; esac
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
start=$(date +%s); n=0; batch=0; pids=''
while IFS= read -r candidate; do
    if [ "$batch" -eq 0 ] && [ "$(($(date +%s) - start))" -ge 90 ]; then
        echo 'Quota server scan time budget exhausted' >&2
        exit 1
    fi
    n=$((n + 1)); batch=$((batch + 1))
    (if probe "$candidate" "$WORK/probe.$n"; then printf '%s\n' "$candidate" > "$WORK/found.$n"; fi) &
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
