#!/bin/sh
set -eu
BASE=${KQD_BASE:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
. "$BASE/common.sh"
active=$("$BASE/quota-dashboard.sh" status)
case "$active" in 'running pid='*) exit 0;; esac
report bootstrap
[ -x "$FBINK" ] || { report preflight_failed fbink_missing; exit 1; }
# A fresh, real-data bootstrap image is bundled by the installer, never a mock quota image.
if [ -f "$BASE/bootstrap-frame.png" ] && valid_png "$BASE/bootstrap-frame.png"; then
    "$FBINK" -q -f -i "$BASE/bootstrap-frame.png" || { report preflight_failed display_failed; exit 1; }
fi
# Perform a real manual fetch/decode and verify that cleanup restores state first.
original_wifi=$(lipc-get-prop com.lab126.cmd wirelessEnable 2>/dev/null) || original_wifi=$(lipc-get-prop com.lab126.wifid enable 2>/dev/null) || { report preflight_failed wifi_state_unknown; exit 1; }
original_saver=$(lipc-get-prop com.lab126.powerd preventScreenSaver 2>/dev/null) || { report preflight_failed screensaver_unknown; exit 1; }
case "$original_wifi:$original_saver" in 0:0|0:1|1:0|1:1) ;; *) report preflight_failed screensaver_unknown; exit 1;; esac
"$BASE/quota-dashboard.sh" refresh || { report preflight_failed display_failed; exit 1; }
restored_wifi=$(lipc-get-prop com.lab126.cmd wirelessEnable 2>/dev/null) || restored_wifi=$(lipc-get-prop com.lab126.wifid enable 2>/dev/null) || exit 1
restored_saver=$(lipc-get-prop com.lab126.powerd preventScreenSaver 2>/dev/null) || exit 1
[ "$original_wifi:$original_saver" = "$restored_wifi:$restored_saver" ] || { report preflight_failed screensaver_unknown; exit 1; }
[ -w /sys/power/state ] || { report preflight_failed rtc_unavailable; exit 1; }
rtc_ready=0
for rtc in /sys/class/rtc/rtc0/wakealarm /sys/class/rtc/rtc1/wakealarm; do
    [ -w "$rtc" ] || continue
    alarm=$(cat "$rtc")
    if [ -z "$alarm" ] || [ "$alarm" = 0 ]; then rtc_ready=1; break; fi
done
[ "$rtc_ready" -eq 1 ] || { report preflight_failed rtc_busy; exit 1; }
sed 's/^ALLOW_SUSPEND=0$/ALLOW_SUSPEND=1/' "$CONF" > "$CONF.next"
mv "$CONF.next" "$CONF"
exec "$BASE/quota-dashboard.sh" start
