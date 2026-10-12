#!/bin/sh
set -eu
BASE=${KQD_BASE:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
. "$BASE/common.sh"
RTC=/sys/class/rtc/rtc0/wakealarm
POWER=${KQD_POWER_STATE:-/sys/power/state}
ACTION=${1:-start}
WAIT_PID=
CYCLES=0
STOP_REASON=none
DISPLAY_OWNED=0
FAILURES=0
NEXT_DELAY=$INTERVAL
REQUEST_ID=

acquire_display() {
    mkdir "$STATE/display-lock" 2>/dev/null || return 1
    DISPLAY_OWNED=1
}
release_display() {
    if [ "$DISPLAY_OWNED" -eq 1 ]; then
        rmdir "$STATE/display-lock" 2>/dev/null || true
        DISPLAY_OWNED=0
    fi
}

pause() {
    sleep "$1" & WAIT_PID=$!
    wait "$WAIT_PID" && pause_result=0 || pause_result=$?
    [ "$pause_result" -lt 128 ] || kill "$WAIT_PID" 2>/dev/null || true
    wait "$WAIT_PID" 2>/dev/null || true
    WAIT_PID=
}

pending_request() {
    [ -f "$STATE/request" ] || return 1
    REQUEST_ID=$(cat "$STATE/request")
    case "$REQUEST_ID" in ''|*[!0-9-]*) return 1;; esac
    [ "${#REQUEST_ID}" -le 40 ]
}
finish_request() {
    [ -n "$REQUEST_ID" ] || return 0
    printf '%s %s\n' "$REQUEST_ID" "$1" > "$STATE/result.next"
    mv "$STATE/result.next" "$STATE/result"
    [ "$(cat "$STATE/request" 2>/dev/null)" != "$REQUEST_ID" ] || rm -f "$STATE/request"
    REQUEST_ID=
}
next_delay() {
    if [ "$1" = success ]; then FAILURES=0; NEXT_DELAY=$INTERVAL
    else
        [ "$FAILURES" -ge 5 ] || FAILURES=$((FAILURES + 1))
        # Back off in steps of the refresh interval (at least 3 minutes) up to
        # 15 minutes, and never retry sooner than a successful round would.
        backoff_step=$INTERVAL
        [ "$backoff_step" -ge 180 ] || backoff_step=180
        NEXT_DELAY=$((FAILURES * backoff_step))
        [ "$NEXT_DELAY" -le 900 ] || NEXT_DELAY=900
        [ "$NEXT_DELAY" -ge "$INTERVAL" ] || NEXT_DELAY=$INTERVAL
    fi
}
refresh() {
    discovery_mode=${1:---known-only}
    timeout=$(budget_timeout 95) || return 1
    bounded "$timeout" "$BASE/find-server.sh" --internal "$discovery_mode" > "$STATE/server.next" || return 1
    server=$(cat "$STATE/server.next")
    valid_host "$server" || return 1
    NETWORK_OK=1
    next=$STATE/frame.next.png
    fetch "http://$server:$PORT/frame/kindle1.png" "$next" 15 || { NETWORK_OK=0; rm -f "$next"; return 1; }
    valid_png "$next" || { rm -f "$next"; return 1; }
    acquire_display || { rm -f "$next"; return 1; }
    now=$(date +%s); last=0
    [ ! -f "$STATE/full-refresh" ] || last=$(cat "$STATE/full-refresh")
    case "$last" in ''|*[!0-9]*) last=0;; esac
    if [ "$((now - last))" -ge "$FULL_REFRESH" ] || [ "$now" -lt "$last" ]; then
        bounded 10 "$FBINK" -q -f -i "$next" || { release_display; rm -f "$next"; return 1; }
        printf '%s\n' "$now" > "$STATE/full-refresh" || { release_display; rm -f "$next"; return 1; }
    else
        bounded 10 "$FBINK" -q -i "$next" || { release_display; rm -f "$next"; return 1; }
    fi
    # Drawing and cache promotion are one transaction, also for startup preview.
    mv "$next" "$STATE/frame.png" || { release_display; rm -f "$next"; return 1; }
    release_display
}
round() {
    mode=--known-only; seconds=30; REQUEST_ID=
    if pending_request; then mode=--force; seconds=120; fi
    network_begin "$seconds"
    # net tells a later reader why a round failed: no address at all, an
    # address but no server/frame, or the server was reached.
    round_result=failed; round_net=no_ip
    if wifi_begin; then
        round_net=no_server
        if refresh "$mode"; then round_result=success; fi
        [ "$NETWORK_OK" -eq 0 ] || round_net=ok
    fi
    if [ "$round_result" = success ]; then
        CYCLES=$((CYCLES + 1)); next_delay success
        printf 'frame_ok\n' > "$STATE/status"; report frame_ok
        if [ "$CYCLES" -ge 2 ]; then rm -f "$BASE/../documents/Recover Agent Quota.sh"; fi
    else
        next_delay failure
        printf 'refresh_failed\n' > "$STATE/status"; report refresh_failed
    fi
    bounded_log "$BASE/power.log" "round failures=$FAILURES next_delay=$NEXT_DELAY cycles=$CYCLES net=$round_net"
    if [ -f "$BASE/run.log" ] && [ "$(wc -c < "$BASE/run.log")" -ge 262144 ]; then
        mv "$BASE/run.log" "$BASE/run.previous.log"
        exec >> "$BASE/run.log" 2>&1
    fi
    # Publish completion after diagnostics, so a successful request means the
    # complete round (including reset backoff) has been committed.
    finish_request "$round_result"
}
rtc_now() {
    rtc_value=$(cat "${RTC%/wakealarm}/since_epoch" 2>/dev/null) || return 1
    case "$rtc_value" in ''|*[!0-9]*) return 1;; esac
    [ "${#rtc_value}" -le 11 ] || return 1
    printf '%s\n' "$rtc_value"
}
rtc_wait() {
    [ -w "$POWER" ] || { STOP_REASON=rtc_unavailable; return 1; }
    [ ! -f "$STATE/stop" ] || return 0
    pending_request && return 0
    arm_rtc "$NEXT_DELAY" || { STOP_REASON=rtc_invalid_alarm; return 1; }
    deadline=$ALARM
    suspend_started=$(rtc_now) || { STOP_REASON=rtc_unavailable; return 1; }
    report suspend_armed
    # Wireless is deliberately left enabled through the suspend; see wifi_begin.
    NETWORK_OK=0
    bounded 10 sync || { STOP_REASON=suspend_failed; return 1; }
    printf 'mem\n' > "$POWER" || { STOP_REASON=suspend_failed; return 1; }
    resumed_at=$(rtc_now) || { STOP_REASON=suspend_failed; return 1; }
    clear_rtc
    elapsed=$((resumed_at - suspend_started))
    [ "$elapsed" -ge 0 ] || { STOP_REASON=suspend_failed; return 1; }
    [ ! -f "$STATE/stop" ] || return 0
    pending_request && return 0
    if [ "$((deadline - resumed_at))" -gt 2 ]; then
        # Woken before the alarm: the power button, USB, or another wake source.
        # The user is taking the device back, so stop instead of suspending under
        # their fingers; the marker keeps install hooks from restarting the loop.
        report resumed early_wake
        STOP_REASON=early_wake
        : > "$STATE/stop"
        return 0
    fi
    bounded 3 lipc-set-prop com.lab126.powerd preventScreenSaver 1 || return 1
    report resumed
}
cleanup() {
    cancel_command
    release_display
    if [ -n "$WAIT_PID" ]; then kill "$WAIT_PID" 2>/dev/null || true; wait "$WAIT_PID" 2>/dev/null || true; fi
    clear_rtc
    NETWORK_OK=0
    report stopped "$STOP_REASON"
    pending_request || true
    finish_request cancelled
    case "${SCREENSAVER_PREVIOUS:-}" in 0|1) bounded 3 lipc-set-prop com.lab126.powerd preventScreenSaver "$SCREENSAVER_PREVIOUS" >/dev/null 2>&1 || true;; esac
    wifi_restore
    printf 'stopped\n' > "$STATE/status"
    # The stop marker outlives the worker: it keeps install hooks from
    # restarting the loop and is cleared only by an explicit start.
    rm -f "$STATE/pid" "$STATE/ready" "$STATE/frame.next.png" "$STATE/server.next" "$STATE/wifi-address" "$STATE/wifi-current"
    rmdir "$STATE/lock" 2>/dev/null || true
}
owned_pid() {
    [ -f "$STATE/pid" ] || return 1
    pid=$(cat "$STATE/pid")
    case "$pid" in ''|*[!0-9]*) return 1;; esac
    [ "$(cat "$STATE/ready" 2>/dev/null)" = "$pid" ] || return 1
    [ -r "${KQD_PROC_ROOT:-/proc}/$pid/cmdline" ] || return 1
    command=$(tr '\000' ' ' < "${KQD_PROC_ROOT:-/proc}/$pid/cmdline")
    case "$command" in *"$BASE/quota-dashboard.sh run"*) kill -0 "$pid" 2>/dev/null;; *) return 1;; esac
}
mkdir -p "$STATE"
case "$ACTION" in
    show-cache)
        # This operation never touches the worker lock/PID, Wi-Fi, or RTC.
        # Prefer the successful quota cache; otherwise show the fixed message.
        # A busy display or missing/bad images never blocks the live fetch.
        trap 'cancel_command; release_display' 0
        trap 'exit 1' 1 2 15
        acquire_display || exit 0
        [ -x "$FBINK" ] || exit 1
        if valid_png "$STATE/frame.png" && bounded 10 "$FBINK" -q -i "$STATE/frame.png"; then
            exit 0
        fi
        if valid_placeholder "$BASE/bootstrap-frame.png"; then
            bounded 10 "$FBINK" -q -i "$BASE/bootstrap-frame.png"
        fi
        ;;
    start)
        [ -x "$FBINK" ] || { echo 'FBInk missing' >&2; exit 1; }
        if ! mkdir "$STATE/lock" 2>/dev/null; then
            owned_pid && exit 0
            echo 'Lock exists; check active refresh/run before removing stale lock' >&2; exit 1
        fi
        rm -f "$STATE/stop" "$STATE/request" "$STATE/result" "$STATE/ready"
        if command -v setsid >/dev/null 2>&1; then
            setsid "$BASE/quota-dashboard.sh" run </dev/null >>"$BASE/run.log" 2>&1 &
        else
            "$BASE/quota-dashboard.sh" run </dev/null >>"$BASE/run.log" 2>&1 &
        fi
        ;;
    run)
        [ -d "$STATE/lock" ] || exit 1
        trap cleanup 0
        trap '' 1
        trap 'STOP_REASON=signal_int; exit 0' 2
        trap 'STOP_REASON=signal_term; exit 0' 15
        trap ':' USR1
        # Publish only after signal handlers exist. ready is the request handshake.
        printf '%s\n' "$$" > "$STATE/pid"
        bounded 3 lipc-get-prop com.lab126.powerd preventScreenSaver > "$STATE/saver-previous" || exit 1
        SCREENSAVER_PREVIOUS=$(cat "$STATE/saver-previous")
        case "$SCREENSAVER_PREVIOUS" in 0|1) ;; *) exit 1;; esac
        wifi_capture || exit 1
        bounded 3 lipc-set-prop com.lab126.powerd preventScreenSaver 1 || exit 1
        printf '%s\n' "$$" > "$STATE/ready.next"; mv "$STATE/ready.next" "$STATE/ready"
        settled=0
        while [ ! -f "$STATE/stop" ]; do
            round
            [ ! -f "$STATE/stop" ] || break
            pending_request && continue
            if [ "$settled" -eq 0 ]; then
                # The Library repaints itself after the launcher entry returns,
                # often just after the first frame was drawn. Let it finish, then
                # put the dashboard back before the device sleeps under it.
                settled=1
                pause 8
                [ ! -f "$STATE/stop" ] || break
                pending_request && continue
                "$BASE/quota-dashboard.sh" show-cache || true
            fi
            if [ "$ALLOW_SUSPEND" -eq 1 ]; then
                rtc_wait || { report preflight_failed "$STOP_REASON"; exit 1; }
            else
                # Explicit development mode; production bootstrap enables RTC.
                pause "$NEXT_DELAY"
            fi
        done
        ;;
    refresh|rediscover)
        if [ "$ACTION" = rediscover ] && owned_pid; then
            # Coalesce concurrent clicks, publish a fixed ID, then notify only a
            # ready verified worker. A signal cannot wake a suspended device.
            publication_tries=0
            until mkdir "$STATE/request-lock" 2>/dev/null; do
                publication_tries=$((publication_tries + 1))
                [ "$publication_tries" -lt 3 ] || { echo 'Request publication busy'; exit 1; }
                sleep 1
            done
            trap 'rmdir "$STATE/request-lock" 2>/dev/null || true' 0
            if ! pending_request; then
                REQUEST_ID=$$-$(tick)
                printf '%s\n' "$REQUEST_ID" > "$STATE/request.next"
                mv "$STATE/request.next" "$STATE/request"
            fi
            wanted=$REQUEST_ID
            rmdir "$STATE/request-lock"; trap - 0
            owned_pid || { echo 'Worker stopped before request'; exit 1; }
            kill -USR1 "$pid"
            until_tick=$(($(tick) + 130))
            while [ "$(tick)" -lt "$until_tick" ]; do
                result=$(cat "$STATE/result" 2>/dev/null) || result=
                case "$result" in "$wanted success") echo 'Rediscovered and refreshed'; exit 0;; "$wanted "*) echo "$result"; exit 1;; esac
                owned_pid || { echo 'Worker stopped'; exit 1; }
                sleep 1
            done
            echo 'Request timed out'; exit 1
        fi
        mkdir "$STATE/lock" 2>/dev/null || { echo 'Dashboard already active or stale lock; do not remove blindly' >&2; exit 1; }
        trap cleanup 0
        trap 'exit 1' 1 2 15
        [ -x "$FBINK" ] || exit 1
        seconds=30; mode=--known-only
        [ "$ACTION" != rediscover ] || { seconds=120; mode=--force; }
        network_begin "$seconds"
        wifi_begin && refresh "$mode"
        ;;
    stop)
        : > "$STATE/stop"
        if owned_pid; then kill "$pid"; else echo 'No verified dashboard process'; fi
        ;;
    status)
        if owned_pid; then printf 'running pid=%s\n' "$pid"; else printf 'not running\n'; fi
        [ ! -f "$STATE/status" ] || cat "$STATE/status"
        ;;
    *) echo 'Usage: quota-dashboard.sh {start|refresh|rediscover|show-cache|stop|status}' >&2; exit 2;;
esac
