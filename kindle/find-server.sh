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
pids=''; FOUND=; checked=0
cleanup() {
    cancel_command
    for scan_pid in $pids; do kill "$scan_pid" 2>/dev/null || true; done
    for scan_pid in $pids; do wait "$scan_pid" 2>/dev/null || true; done
    rm -rf "$WORK"
    [ "$INTERNAL" -eq 1 ] || wifi_restore
}
trap cleanup 0
trap 'exit 1' 1 2 15
# Progress goes to stderr and only for a manual search: the launcher shows it
# on screen. Automatic rounds stay silent. stdout carries the address alone.
note() { [ "$FORCE" -eq 0 ] || printf '%s\n' "$1" >&2; }
if [ -z "${KQD_NET_DEADLINE:-}" ]; then
    if [ "$FORCE" -eq 1 ]; then network_begin 180; else network_begin 30; fi
fi
[ "$INTERNAL" -eq 1 ] || wifi_begin
found() { save_server "$1"; note "Found the quota server at $1 (saved)."; printf '%s\n' "$1"; exit 0; }
collect() {
    for pid in $pids; do wait "$pid" || true; done
    pids=''
    for file in "$WORK"/found.*; do
        [ ! -f "$file" ] || { FOUND=$(cat "$file"); return 0; }
    done
    rm -f "$WORK"/probe.*
    return 1
}
# Probe every address in file $1, at most $2 at once ($3 = how many there are).
# Sets FOUND and returns 0 for the first batch with an answer; returns 1 when
# none answered or the shared network budget ran out (then OUT_OF_TIME=1).
probe_all() {
    batch=0; OUT_OF_TIME=0
    while IFS= read -r candidate; do
        if ! budget_timeout 1 >/dev/null; then OUT_OF_TIME=1; break; fi
        checked=$((checked + 1)); batch=$((batch + 1))
        (
            CHILD_PID= TIMER_PID=
            trap cancel_command 0
            trap 'exit 1' 1 2 15
            if probe "$candidate" "$WORK/probe.$checked"; then printf '%s\n' "$candidate" > "$WORK/found.$checked"; fi
        ) &
        pids="$pids $!"
        [ "$batch" -ge "$2" ] || continue
        collect && return 0
        batch=0
        [ "$((checked % 128))" -ne 0 ] || note "  checked $checked of $3"
    done < "$1"
    collect
}
# Known addresses: every server found before (most recent first), then the
# configured addresses and host name. They are probed together, so a longer
# list does not keep the device awake longer.
: > "$WORK/known"
remember() {
    valid_host "$1" || return 0
    [ "$(wc -l < "$WORK/known")" -lt 12 ] || return 0
    grep -qxF -e "$1" "$WORK/known" || printf '%s\n' "$1" >> "$WORK/known"
}
if [ -f "$BASE/server.cache" ]; then
    while IFS= read -r line || [ -n "$line" ]; do remember "$line"; done < "$BASE/server.cache"
fi
for known in $(printf '%s' "$SERVER_IP" | tr ',' ' '); do remember "$known"; done
remember "$SERVER_HOST"
known_count=$(wc -l < "$WORK/known" | tr -d ' ')
note "Trying $known_count known address(es)..."
for pass in 1 2 3 4 5; do
    checked=0
    if probe_all "$WORK/known" 12 "$known_count"; then found "$FOUND"; fi
    # After an RTC resume with the radio left on, wlan0 can still show its old
    # address while the link is re-established. These short retries share the
    # original budget and never enable scanning.
    [ "$FORCE" -eq 0 ] && [ "$pass" -lt 5 ] || break
    retry_time=$(budget_timeout 3) || break
    [ "$retry_time" -gt 1 ] || break
    bounded "$retry_time" sleep "$((retry_time - 1))" || break
done
[ "$FORCE" -eq 1 ] || exit 1
note 'None of them answered.'
[ "$ENABLE_SCAN" -eq 1 ] || { note 'Scanning is disabled (ENABLE_SCAN=0); set SERVER_IP.'; exit 1; }
# Scan the actual private subnet, capped at /22 (1022 hosts); never guess or
# broaden the mask.
cidr=$(ip -4 addr show dev wlan0 2>/dev/null | awk '$1=="inet" {print $2; exit}')
mask=${cidr##*/}
case "$mask" in 22|23|24|25|26|27|28|29|30) ;; *) echo "Manual scan requires private IPv4 /22 through /30 (this network: ${cidr:-none}); configure SERVER_IP" >&2; exit 1;; esac
local_ip=${cidr%/*}
valid_ip "$local_ip" || exit 1
case "$local_ip" in
    10.*|192.168.*) ;;
    172.*) second=$(printf '%s' "$local_ip" | cut -d. -f2); [ "$second" -ge 16 ] && [ "$second" -le 31 ] || { echo 'Manual scan requires a private network; configure SERVER_IP' >&2; exit 1; };;
    *) echo 'Manual scan requires a private network; configure SERVER_IP' >&2; exit 1;;
esac
# Order: this device's /24, then the /24 of every known address inside this
# subnet (a server usually stays in its neighbourhood), then the rest.
# AWK numbers represent IPv4 exactly, avoiding signed 32-bit shell overflow.
awk -v addr="$local_ip" -v mask="$mask" '
function number(text, o) { split(text,o,"."); return o[1]*16777216+o[2]*65536+o[3]*256+o[4] }
function dotted(n, a,b,c,d) {
    a=int(n/16777216); b=int(n/65536)%256; c=int(n/256)%256; d=n%256
    return sprintf("%d.%d.%d.%d",a,b,c,d)
}
function rank(n) { return int(n/256)==int(me/256) ? 0 : (int(n/256) in near ? 1 : 2) }
/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ { near[int(number($0)/256)]=1 }
END {
    me=number(addr)
    size=2^(32-mask); first=int(me/size)*size+1; last=first+size-3
    for(pass=0;pass<3;pass++) for(n=first;n<=last;n++)
        if(n!=me && rank(n)==pass) print dotted(n)
}' "$WORK/known" > "$WORK/candidates"
total=$(wc -l < "$WORK/candidates" | tr -d ' ')
scan_deadline=$(($(tick) + 150))
[ "$scan_deadline" -le "$KQD_NET_DEADLINE" ] || scan_deadline=$KQD_NET_DEADLINE
KQD_NET_DEADLINE=$scan_deadline; export KQD_NET_DEADLINE
note "Scanning $total addresses on $cidr (up to $((scan_deadline - $(tick)))s)..."
checked=0
if probe_all "$WORK/candidates" 32 "$total"; then found "$FOUND"; fi
if [ "$OUT_OF_TIME" -eq 1 ]; then
    echo "Quota server scan time budget exhausted after $checked of $total addresses" >&2
else
    echo "Quota server not found: none of $total addresses answered" >&2
fi
exit 1
