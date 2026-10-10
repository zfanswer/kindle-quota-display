#!/bin/sh
# This library is sourced by our scripts. server.conf is strictly parsed as data.
BASE=${KQD_BASE:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
STATE=${KQD_STATE:-/tmp/kindle-quota-display}
CONF=$BASE/server.conf
SERVER_IP= SERVER_HOST= PORT=8486 SERVER_ID=kqd-pw3 ENABLE_SCAN=1
INTERVAL=180 FULL_REFRESH=1800 FBINK=/mnt/us/libkh/bin/fbink ALLOW_SUSPEND=0
CHILD_PID= CHILD_GROUP=0 TIMER_PID= NETWORK_OK=0

# /proc/uptime avoids wall-clock corrections in a short awake network budget.
tick() {
    awk '{split($1,a,"."); if(a[1] ~ /^[0-9]+$/) print a[1]; else exit 1}' "${KQD_UPTIME:-/proc/uptime}"
}
network_begin() {
    KQD_NET_DEADLINE=$(($(tick) + $1)); export KQD_NET_DEADLINE
    NETWORK_OK=0
}
budget_timeout() {
    budget_cap=$1
    if [ -n "${KQD_NET_DEADLINE:-}" ]; then
        budget_left=$((KQD_NET_DEADLINE - $(tick)))
        [ "$budget_left" -gt 0 ] || return 1
        [ "$budget_cap" -le "$budget_left" ] || budget_cap=$budget_left
    fi
    printf '%s\n' "$budget_cap"
}
cancel_command() {
    if [ -n "$CHILD_PID" ]; then
        signal_child TERM
        # Do not leave a stopped worker waiting for the original 30/120s budget.
        (
            cancel_sleep=
            trap 'kill "$cancel_sleep" 2>/dev/null || true; wait "$cancel_sleep" 2>/dev/null || true; exit 0' 1 2 15
            KQD_WATCHDOG=1 sleep 1 & cancel_sleep=$!
            wait "$cancel_sleep" || exit 0
            signal_child KILL
        ) & cancel_pid=$!
        wait "$CHILD_PID" 2>/dev/null || true
        kill "$cancel_pid" 2>/dev/null || true
        wait "$cancel_pid" 2>/dev/null || true
        CHILD_PID=
    fi
    if [ -n "$TIMER_PID" ]; then
        kill "$TIMER_PID" 2>/dev/null || true
        wait "$TIMER_PID" 2>/dev/null || true
        TIMER_PID=
    fi
}
signal_child() {
    if [ "$CHILD_GROUP" -eq 1 ]; then kill -"$1" "-$CHILD_PID" 2>/dev/null || true
    else kill -"$1" "$CHILD_PID" 2>/dev/null || true; fi
}
bounded() {
    # curl/wget DNS and the complete request are bounded, including wget builds
    # where -T only covers individual I/O. Callers own child cleanup on signals.
    bounded_seconds=$1; shift
    CHILD_GROUP=0
    if [ "${KQD_IN_COMMAND_GROUP:-0}" -eq 0 ] && command -v setsid >/dev/null 2>&1; then
        # Nested discovery requests stay in this owned group; they must not
        # escape a parent's forced timeout by creating another session.
        KQD_IN_COMMAND_GROUP=1 setsid "$@" & CHILD_PID=$!; CHILD_GROUP=1
    else
        "$@" & CHILD_PID=$!
    fi
    (
        timer_sleep=
        trap 'if [ -n "$timer_sleep" ]; then kill "$timer_sleep" 2>/dev/null || true; wait "$timer_sleep" 2>/dev/null || true; fi; exit 0' 1 2 15
        KQD_WATCHDOG=1 sleep "$bounded_seconds" & timer_sleep=$!
        wait "$timer_sleep" || exit 0
        timer_sleep=
        signal_child TERM
        KQD_WATCHDOG=1 sleep 1 & timer_sleep=$!
        wait "$timer_sleep" || exit 0
        timer_sleep=
        signal_child KILL
    ) & TIMER_PID=$!
    bounded_result=0
    # USR1 can interrupt wait without terminating the network command.
    while :; do
        wait "$CHILD_PID" && bounded_result=0 || bounded_result=$?
        [ "$bounded_result" -ge 128 ] || break
        kill -0 "$CHILD_PID" 2>/dev/null || break
    done
    CHILD_PID=
    kill "$TIMER_PID" 2>/dev/null || true
    wait "$TIMER_PID" 2>/dev/null || true
    TIMER_PID=
    return "$bounded_result"
}
bounded_log() {
    if [ -f "$1" ] && [ "$(wc -c < "$1")" -ge 262144 ]; then
        mv "$1" "${1%.log}.previous.log" 2>/dev/null || true
    fi
    printf '%s\n' "$2" >> "$1" 2>/dev/null || true
}

valid_ip() {
    printf '%s\n' "$1" | awk -F. 'NF!=4{exit 1} {for(i=1;i<=4;i++) if($i !~ /^[0-9]+$/ || length($i)>3 || $i+0>255) exit 1}'
}
valid_host() {
    [ -n "$1" ] && [ "${#1}" -le 253 ] || return 1
    case "$1" in *[!A-Za-z0-9._-]*|-*|.*) return 1;; esac
}
valid_uint() {
    case "$1" in ''|*[!0-9]*|0*) return 1;; esac
    [ "${#1}" -le 6 ] && [ "$1" -ge "$2" ] && [ "$1" -le "$3" ]
}
load_conf() {
    [ -f "$CONF" ] || { echo 'Missing server.conf' >&2; return 1; }
    # Reject duplicate/unknown keys; no eval, exports, variable expansion, or commands.
    seen=' '
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in ''|\#*) continue;; esac
        key=${line%%=*}; value=${line#*=}
        case "$seen" in *" $key "*) echo 'Duplicate config key' >&2; return 1;; esac
        seen="$seen$key "
        case "$key" in
            SERVER_IP) [ -z "$value" ] || valid_ip "$value" || return 1; SERVER_IP=$value;;
            SERVER_HOST) [ -z "$value" ] || valid_host "$value" || return 1; SERVER_HOST=$value;;
            PORT) valid_uint "$value" 1 65535 || return 1; PORT=$value;;
            SERVER_ID) case "$value" in ''|*[!A-Za-z0-9_-]*) return 1;; esac; [ "${#value}" -le 48 ] || return 1; SERVER_ID=$value;;
            ENABLE_SCAN) case "$value" in 0|1) ENABLE_SCAN=$value;; *) return 1;; esac;;
            INTERVAL) valid_uint "$value" 60 3600 || return 1; INTERVAL=$value;;
            FULL_REFRESH) valid_uint "$value" 60 86400 || return 1; FULL_REFRESH=$value;;
            FBINK) case "$value" in /*) ;; *) return 1;; esac; case "$value" in *[!A-Za-z0-9_./-]*) return 1;; esac; FBINK=$value;;
            ALLOW_SUSPEND) case "$value" in 0|1) ALLOW_SUSPEND=$value;; *) return 1;; esac;;
            *) echo 'Unknown config key' >&2; return 1;;
        esac
    done < "$CONF"
    [ "$FULL_REFRESH" -ge "$INTERVAL" ] || return 1
}
fetch() {
    url=$1; output=$2
    timeout=$(budget_timeout "$3") || return 1
    if command -v curl >/dev/null 2>&1; then
        bounded "$timeout" curl -q --fail --silent --connect-timeout "$timeout" --max-time "$timeout" --max-filesize 262144 -o "$output" "$url"
    else
        bounded "$timeout" wget -q -t 1 -T "$timeout" -O "$output" "$url"
    fi
}
probe() {
    host=$1; target=$2
    fetch "http://$host:$PORT/healthz" "$target" 1 || return 1
    [ "$(wc -c < "$target")" -le 128 ] || return 1
    expected=$(printf 'EINK_QUOTA_V1\nSERVER_ID=%s' "$SERVER_ID")
    [ "$(cat "$target")" = "$expected" ]
}
save_server() {
    # Separate mutable cache from reviewed server.conf.
    if [ -f "$BASE/server.cache" ] && [ "$(cat "$BASE/server.cache")" = "$1" ]; then return 0; fi
    printf '%s\n' "$1" > "$BASE/.server-cache.$$" && mv "$BASE/.server-cache.$$" "$BASE/server.cache"
}
valid_png() {
    [ -f "$1" ] || return 1
    size=$(wc -c < "$1")
    [ "$size" -gt 33 ] && [ "$size" -le 262144 ] || return 1
    header=$(dd if="$1" bs=1 count=26 2>/dev/null | od -An -tx1 | tr -d ' \n')
    # PNG, 13-byte IHDR, 1072 x 1448, 8-bit grayscale (L), no alpha.
    [ "$header" = '89504e470d0a1a0a0000000d4948445200000430000005a80800' ]
}
valid_placeholder() {
    valid_png "$1" || return 1
    # Canonical tEXt chunk directly after IHDR: kqd-placeholder=refresh-v1.
    # A legacy quota snapshot at the same filename has no marker and is skipped.
    marker=$(dd if="$1" bs=1 skip=33 count=34 2>/dev/null | od -An -tx1 | tr -d ' \n')
    [ "$marker" = '0000001a744558746b71642d706c616365686f6c64657200726566726573682d7631' ]
}
wifi_capture() {
    bounded 3 lipc-get-prop com.lab126.cmd wirelessEnable > "$STATE/wifi-previous" 2>/dev/null ||
        bounded 3 lipc-get-prop com.lab126.wifid enable > "$STATE/wifi-previous" 2>/dev/null || return 1
    WIFI_PREVIOUS=$(cat "$STATE/wifi-previous")
    case "$WIFI_PREVIOUS" in 0|1) ;; *) return 1;; esac
}
wifi_begin() {
    [ -n "${WIFI_PREVIOUS:-}" ] || wifi_capture || return 1
    timeout=$(budget_timeout 3) || return 1
    bounded "$timeout" lipc-set-prop com.lab126.cmd wirelessEnable 1 >/dev/null 2>&1 || return 1
    while budget_timeout 1 >/dev/null; do
        timeout=$(budget_timeout 2) || return 1
        bounded "$timeout" ip -4 addr show dev wlan0 > "$STATE/wifi-address" 2>/dev/null || true
        wifi_ip=$(awk '$1=="inet" {split($2,a,"/"); print a[1]; exit}' "$STATE/wifi-address")
        if valid_ip "$wifi_ip" && [ "$wifi_ip" != 0.0.0.0 ]; then return 0; fi
        sleep 1
    done
    return 1
}
report() {
    # Fixed enums only. This telemetry cannot execute host commands or alter quota.
    report_host=$SERVER_IP
    [ ! -f "$BASE/server.cache" ] || report_host=$(cat "$BASE/server.cache")
    report_rtc=${RTC:-/sys/class/rtc/rtc0/wakealarm}
    rtc_device=0; case "$report_rtc" in */rtc1/wakealarm) rtc_device=1;; esac
    rtc_epoch=$(cat "${report_rtc%/wakealarm}/since_epoch" 2>/dev/null) || rtc_epoch=0
    system_epoch=$(date +%s)
    alarm_epoch=${ALARM:-0}; elapsed_seconds=${elapsed:-0}
    case "$rtc_epoch" in ''|*[!0-9]*) rtc_epoch=0;; esac
    case "$system_epoch" in ''|*[!0-9]*) system_epoch=0;; esac
    case "$alarm_epoch" in ''|*[!0-9]*) alarm_epoch=0;; esac
    case "$elapsed_seconds" in ''|*[!0-9]*) elapsed_seconds=0;; esac
    payload=$(printf '{"stage":"%s","reason":"%s","interval":%s,"cycles":%s,"rtc_device":%s,"rtc_epoch":%s,"system_epoch":%s,"alarm_epoch":%s,"elapsed_seconds":%s}' "$1" "${2:-none}" "$INTERVAL" "${CYCLES:-0}" "$rtc_device" "$rtc_epoch" "$system_epoch" "$alarm_epoch" "$elapsed_seconds")
    # Preserve fixed lifecycle evidence even when the server is unavailable.
    # Keep at most two ~256 KiB files; never include upstream/network payloads.
    bounded_log "$BASE/lifecycle.log" "$payload"
    [ "$NETWORK_OK" -eq 1 ] || return 0
    valid_host "$report_host" || return 0
    timeout=$(budget_timeout 2) || return 0
    if command -v curl >/dev/null 2>&1; then
        bounded "$timeout" curl -q --silent --fail --connect-timeout "$timeout" --max-time "$timeout" -H 'Content-Type: application/json' --data "$payload" "http://$report_host:$PORT/api/device/kindle1" >/dev/null 2>&1 || true
    else
        bounded "$timeout" wget -q -t 1 -T "$timeout" --post-data="$payload" -O /dev/null "http://$report_host:$PORT/api/device/kindle1" >/dev/null 2>&1 || true
    fi
}
wifi_restore() {
    case "${WIFI_PREVIOUS:-}" in 0|1) bounded 3 lipc-set-prop com.lab126.cmd wirelessEnable "$WIFI_PREVIOUS" >/dev/null 2>&1 || true;; esac
}
arm_rtc() {
    rtc_delay=${1:-$INTERVAL}
    valid_uint "$rtc_delay" 1 3600 || return 1
    for rtc_dir in "${KQD_RTC_ROOT:-/sys/class/rtc}/rtc0" "${KQD_RTC_ROOT:-/sys/class/rtc}/rtc1"; do
        candidate=$rtc_dir/wakealarm
        [ -w "$candidate" ] || continue
        current=$(cat "$candidate" 2>/dev/null) || continue
        [ -z "$current" ] || [ "$current" = 0 ] || continue
        printf '0\n' > "$candidate" || continue
        if ! printf '+%s\n' "$rtc_delay" > "$candidate"; then
            # Older RTC drivers may support only an absolute hardware RTC epoch.
            rtc_now=$(cat "$rtc_dir/since_epoch" 2>/dev/null) || continue
            case "$rtc_now" in ''|*[!0-9]*) continue;; esac
            [ "${#rtc_now}" -le 11 ] || continue
            printf '%s\n' "$((rtc_now + rtc_delay))" > "$candidate" || continue
        fi
        alarm=$(cat "$candidate" 2>/dev/null) || alarm=
        case "$alarm" in ''|*[!0-9]*) printf '0\n' > "$candidate" || true; continue;; esac
        if [ "${#alarm}" -le 11 ] && [ "$alarm" -gt 0 ]; then
            RTC=$candidate; ALARM=$alarm; ALARM_OWNED=1
            return 0
        fi
        printf '0\n' > "$candidate" || true
    done
    return 1
}
clear_rtc() {
    # An alarm replaced by another owner must not be cleared during cleanup.
    if [ "${ALARM_OWNED:-0}" -eq 1 ]; then
        rtc_current=$(cat "$RTC" 2>/dev/null) || rtc_current=
        [ "$rtc_current" != "$ALARM" ] || printf '0\n' > "$RTC" || true
        ALARM_OWNED=0
    fi
}
load_conf || { echo 'Invalid Kindle config' >&2; exit 2; }
