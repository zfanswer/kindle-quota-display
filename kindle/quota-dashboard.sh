#!/bin/sh
set -eu
BASE=${KQD_BASE:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
. "$BASE/common.sh"
RTC=/sys/class/rtc/rtc0/wakealarm
POWER=/sys/power/state
ACTION=${1:-start}
WAIT_PID=
CYCLES=0
STOP_REASON=none

pause() {
    sleep "$1" &
    WAIT_PID=$!
    wait "$WAIT_PID" || true
    WAIT_PID=
}

refresh() {
    server=$("$BASE/find-server.sh" --internal) || return 1
    next=$STATE/frame.next.png
    fetch "http://$server:$PORT/frame/kindle1.png" "$next" 15 || { rm -f "$next"; return 1; }
    valid_png "$next" || { rm -f "$next"; return 1; }
    now=$(date +%s); last=0
    [ ! -f "$STATE/full-refresh" ] || last=$(cat "$STATE/full-refresh")
    case "$last" in ''|*[!0-9]*) last=0;; esac
    # FBInk decodes before displaying. Never clear the screen before decoding a successful fetch.
    if [ "$((now - last))" -ge "$FULL_REFRESH" ] || [ "$now" -lt "$last" ]; then
        "$FBINK" -q -f -i "$next" || { rm -f "$next"; return 1; }
        printf '%s\n' "$now" > "$STATE/full-refresh"
    else
        "$FBINK" -q -i "$next" || { rm -f "$next"; return 1; }
    fi
    mv "$next" "$STATE/frame.png"
}
cleanup() {
    if [ -n "$WAIT_PID" ]; then kill "$WAIT_PID" 2>/dev/null || true; wait "$WAIT_PID" 2>/dev/null || true; fi
    [ "${ALARM_OWNED:-0}" -eq 0 ] || printf '0\n' > "$RTC" || true
    case "${SCREENSAVER_PREVIOUS:-}" in 0|1) lipc-set-prop com.lab126.powerd preventScreenSaver "$SCREENSAVER_PREVIOUS" >/dev/null 2>&1 || true;; esac
    case "${WIFI_PREVIOUS:-}" in
        0|1)
            if [ "$STOP_REASON" != none ]; then
                lipc-set-prop com.lab126.cmd wirelessEnable 1 >/dev/null 2>&1 || true
                sleep 8
            fi
            ;;
    esac
    report stopped "$STOP_REASON"
    wifi_restore
    printf 'stopped\n' > "$STATE/status"
    rm -f "$STATE/pid" "$STATE/stop" "$STATE/frame.next.png"
    rmdir "$STATE/lock" 2>/dev/null || true
}
owned_pid() {
    [ -f "$STATE/pid" ] || return 1
    pid=$(cat "$STATE/pid")
    case "$pid" in ''|*[!0-9]*) return 1;; esac
    [ -r "/proc/$pid/cmdline" ] || return 1
    command=$(tr '\000' ' ' < "/proc/$pid/cmdline")
    case "$command" in *"$BASE/quota-dashboard.sh run"*) kill -0 "$pid" 2>/dev/null;; *) return 1;; esac
}
mkdir -p "$STATE"
case "$ACTION" in
    start)
        [ -x "$FBINK" ] || { echo 'FBInk missing' >&2; exit 1; }
        if ! mkdir "$STATE/lock" 2>/dev/null; then
            owned_pid && exit 0
            echo 'Lock exists; check active refresh/run before removing stale lock' >&2; exit 1
        fi
        rm -f "$STATE/stop"
        if command -v setsid >/dev/null 2>&1; then
            setsid "$BASE/quota-dashboard.sh" run </dev/null >>"$BASE/run.log" 2>&1 &
        else
            "$BASE/quota-dashboard.sh" run </dev/null >>"$BASE/run.log" 2>&1 &
        fi
        ;;
    run)
        [ -d "$STATE/lock" ] || exit 1
        printf '%s\n' "$$" > "$STATE/pid"
        trap cleanup 0
        trap '' 1
        trap 'STOP_REASON=signal_int; exit 0' 2
        trap 'STOP_REASON=signal_term; exit 0' 15
        SCREENSAVER_PREVIOUS=$(lipc-get-prop com.lab126.powerd preventScreenSaver) || exit 1
        case "$SCREENSAVER_PREVIOUS" in 0|1) ;; *) exit 1;; esac
        wifi_begin || exit 1
        lipc-set-prop com.lab126.powerd preventScreenSaver 1 || exit 1
        while [ ! -f "$STATE/stop" ]; do
            if refresh; then
                CYCLES=$((CYCLES + 1)); printf 'frame_ok\n' > "$STATE/status"; report frame_ok
                # Recovery entry is our generated installer hook, no longer needed after two good cycles.
                if [ "$CYCLES" -ge 2 ]; then rm -f "$BASE/../documents/Recover Agent Quota.sh"; fi
            else printf 'refresh_failed\n' > "$STATE/status"; report refresh_failed; fi
            [ ! -f "$STATE/stop" ] || break
            if [ "$ALLOW_SUSPEND" -eq 1 ]; then
                [ -w "$POWER" ] || { STOP_REASON=rtc_unavailable; report preflight_failed "$STOP_REASON"; exit 1; }
                arm_rtc || { STOP_REASON=rtc_invalid_alarm; report preflight_failed "$STOP_REASON"; exit 1; }
                report suspend_armed
                lipc-set-prop com.lab126.cmd wirelessEnable 0 || exit 1
                sync
                suspend_started=$(date +%s)
                printf 'mem\n' > "$POWER" || { STOP_REASON=suspend_failed; exit 1; }
                printf '0\n' > "$RTC"; ALARM_OWNED=0
                lipc-set-prop com.lab126.cmd wirelessEnable 1 || exit 1
                sleep 8
                # An early power-button/USB wake returns control to normal reading.
                elapsed=$(($(date +%s) - suspend_started))
                if [ "$elapsed" -lt "$((INTERVAL - 30))" ]; then STOP_REASON=early_wake; report resumed "$STOP_REASON"; break; fi
                report resumed
            else
                # Debug mode keeps Wi-Fi on and never writes power/RTC sysfs.
                pause "$INTERVAL"
            fi
        done
        ;;
    refresh)
        mkdir "$STATE/lock" 2>/dev/null || { echo 'Dashboard already active' >&2; exit 1; }
        trap cleanup 0
        trap 'exit 1' 1 2 15
        [ -x "$FBINK" ] || exit 1
        wifi_begin || exit 1
        refresh
        ;;
    stop)
        : > "$STATE/stop"
        if owned_pid; then kill "$pid"; else echo 'No verified dashboard process'; fi
        ;;
    status)
        if owned_pid; then printf 'running pid=%s\n' "$pid"; else printf 'not running\n'; fi
        [ ! -f "$STATE/status" ] || cat "$STATE/status"
        ;;
    *) echo 'Usage: quota-dashboard.sh {start|refresh|stop|status}' >&2; exit 2;;
esac
