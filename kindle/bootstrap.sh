#!/bin/sh
set -eu
BASE=${KQD_BASE:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
. "$BASE/common.sh"
mkdir -p "$STATE"
trap cancel_command 0
trap 'exit 1' 1 2 15
# Cover the Library immediately with the latest successfully committed frame,
# even when the worker is already running; use the fixed message if no cache.
"$BASE/quota-dashboard.sh" show-cache || true
active=$("$BASE/quota-dashboard.sh" status)
case "$active" in 'running pid='*) exit 0;; esac
report bootstrap
[ -x "$FBINK" ] || { report preflight_failed fbink_missing; exit 1; }
# Preserve the cached preview until a live fetch has validated and decoded.
# bootstrap-frame.png is a fixed message, never a quota cache or old snapshot.
# Check device capabilities independently of whether the Mac is online.
wifi_capture || { report preflight_failed wifi_state_unknown; exit 1; }
original_wifi=$WIFI_PREVIOUS
bounded 3 lipc-get-prop com.lab126.powerd preventScreenSaver > "$STATE/saver-previous" 2>/dev/null || { report preflight_failed screensaver_unknown; exit 1; }
original_saver=$(cat "$STATE/saver-previous")
case "$original_wifi:$original_saver" in 0:0|0:1|1:0|1:1) ;; *) report preflight_failed screensaver_unknown; exit 1;; esac
[ -w "${KQD_POWER_STATE:-/sys/power/state}" ] || { report preflight_failed rtc_unavailable; exit 1; }
rtc_ready=0
for rtc in "${KQD_RTC_ROOT:-/sys/class/rtc}/rtc0/wakealarm" "${KQD_RTC_ROOT:-/sys/class/rtc}/rtc1/wakealarm"; do
    [ -w "$rtc" ] || continue
    alarm=$(cat "$rtc")
    if [ -z "$alarm" ] || [ "$alarm" = 0 ]; then
        rtc_epoch=$(cat "${rtc%/wakealarm}/since_epoch" 2>/dev/null) || continue
        case "$rtc_epoch" in ''|*[!0-9]*) continue;; esac
        [ "${#rtc_epoch}" -le 11 ] || continue
        rtc_ready=1; break
    fi
done
[ "$rtc_ready" -eq 1 ] || { report preflight_failed rtc_busy; exit 1; }
sed 's/^ALLOW_SUSPEND=0$/ALLOW_SUSPEND=1/' "$CONF" > "$CONF.next"
mv "$CONF.next" "$CONF"
exec "$BASE/quota-dashboard.sh" start
