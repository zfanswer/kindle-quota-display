#!/bin/sh
# This library is sourced by our scripts. server.conf is strictly parsed as data.
BASE=${KQD_BASE:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
STATE=${KQD_STATE:-/tmp/kindle-quota-display}
CONF=$BASE/server.conf
SERVER_IP= SERVER_HOST= PORT=8486 SERVER_ID=kqd-pw3 ENABLE_SCAN=1
INTERVAL=180 FULL_REFRESH=1800 FBINK=/mnt/us/libkh/bin/fbink ALLOW_SUSPEND=0

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
    url=$1; output=$2; timeout=$3
    if command -v curl >/dev/null 2>&1; then
        curl -q --fail --silent --connect-timeout "$timeout" --max-time "$timeout" --max-filesize 262144 -o "$output" "$url"
    else
        wget -q -t 1 -T "$timeout" -O "$output" "$url"
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
wifi_begin() {
    WIFI_PREVIOUS=$(lipc-get-prop com.lab126.cmd wirelessEnable 2>/dev/null) || WIFI_PREVIOUS=$(lipc-get-prop com.lab126.wifid enable 2>/dev/null) || return 1
    case "$WIFI_PREVIOUS" in 0|1) ;; *) return 1;; esac
    lipc-set-prop com.lab126.cmd wirelessEnable 1 >/dev/null 2>&1 || return 1
    sleep 8
}
report() {
    # Fixed enums only. This telemetry cannot execute host commands or alter quota.
    report_host=$SERVER_IP
    [ ! -f "$BASE/server.cache" ] || report_host=$(cat "$BASE/server.cache")
    valid_host "$report_host" || return 0
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
    if command -v curl >/dev/null 2>&1; then
        curl -q --silent --fail --connect-timeout 2 --max-time 2 -H 'Content-Type: application/json' --data "$payload" "http://$report_host:$PORT/api/device/kindle1" >/dev/null 2>&1 || true
    else
        wget -q -t 1 -T 2 --post-data="$payload" -O /dev/null "http://$report_host:$PORT/api/device/kindle1" >/dev/null 2>&1 || true
    fi
}
wifi_restore() {
    case "${WIFI_PREVIOUS:-}" in 0|1) lipc-set-prop com.lab126.cmd wirelessEnable "$WIFI_PREVIOUS" >/dev/null 2>&1 || true;; esac
}
arm_rtc() {
    # RTC epoch can differ from the system clock. Validate a nonzero armed alarm,
    # and measure early wake using elapsed system time rather than comparing epochs.
    for rtc_dir in "${KQD_RTC_ROOT:-/sys/class/rtc}/rtc0" "${KQD_RTC_ROOT:-/sys/class/rtc}/rtc1"; do
        candidate=$rtc_dir/wakealarm
        [ -w "$candidate" ] || continue
        current=$(cat "$candidate" 2>/dev/null) || continue
        [ -z "$current" ] || [ "$current" = 0 ] || continue
        printf '0\n' > "$candidate" || continue
        if ! printf '+%s\n' "$INTERVAL" > "$candidate"; then
            # Older RTC drivers may support only an absolute hardware RTC epoch.
            rtc_now=$(cat "$rtc_dir/since_epoch" 2>/dev/null) || continue
            case "$rtc_now" in ''|*[!0-9]*) continue;; esac
            [ "${#rtc_now}" -le 11 ] || continue
            printf '%s\n' "$((rtc_now + INTERVAL))" > "$candidate" || continue
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
load_conf || { echo 'Invalid Kindle config' >&2; exit 2; }
