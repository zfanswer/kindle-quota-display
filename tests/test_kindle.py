"""POSIX scripts run ONLY with fake HTTP/Wi-Fi/FBInk commands and local temp files."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from quota_display.render import frame
from test_pipeline import NOW, good

ROOT = Path(__file__).resolve().parents[1]


class KindleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name) / "app"
        self.base.mkdir()
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        self.state = Path(self.tmp.name) / "state"
        self.state.mkdir()
        for name in ("common.sh", "find-server.sh", "quota-dashboard.sh", "bootstrap.sh"):
            shutil.copyfile(ROOT / "kindle" / name, self.base / name)
            (self.base / name).chmod(0o755)
        self.png = Path(self.tmp.name) / "source.png"
        self.png.write_bytes(frame(good(), NOW))
        self.log = Path(self.tmp.name) / "calls"
        self.env = dict(os.environ, KQD_BASE=str(self.base), KQD_STATE=str(self.state),
                        MOCK_PNG=str(self.png), MOCK_LOG=str(self.log), MOCK_HOST="192.168.1.9",
                        PATH=str(self.bin) + ":/usr/bin:/bin")
        self.command("curl", """output=; url=
while [ "$#" -gt 0 ]; do
 case "$1" in -o) output=$2; shift;; http://*) url=$1;; esac
 shift
done
case "$url" in
 http://$MOCK_HOST:8486/healthz) printf 'EINK_QUOTA_V1\\nSERVER_ID=kqd-pw3\\n' > "$output";;
 http://$MOCK_HOST:8486/frame/kindle1.png) cp "$MOCK_PNG" "$output";;
 *) exit 1;;
esac""")
        self.command("sleep", 'if [ "${KQD_WATCHDOG:-0}" = 1 ]; then exec /bin/sleep "$@"; fi')
        self.env["KQD_POWER_STATE"] = str(self.state / "unavailable-power")
        self.env["KQD_RTC_ROOT"] = str(self.state / "unavailable-rtc")
        self.command("ip", "printf '    inet 192.168.1.52/24 brd 192.168.1.255 scope global wlan0\\n'")
        self.command("lipc-get-prop", "printf '1\\n'")
        self.command("lipc-set-prop", 'printf "lipc %s\\n" "$*" >> "$MOCK_LOG"')
        self.command("fbink", 'printf "fbink %s\\n" "$*" >> "$MOCK_LOG"; exit "${MOCK_FBINK_EXIT:-0}"')
        (self.state / "uptime").write_text("100.00 0")
        self.env["KQD_UPTIME"] = str(self.state / "uptime")
        self.conf()

    def command(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)

    def conf(self, extra="", ip="192.168.1.9"):
        config = (ROOT / "kindle/server.conf.example").read_text()
        config = config.replace("SERVER_IP=\n", f"SERVER_IP={ip}\n").replace("SERVER_HOST=MacBook.local", "SERVER_HOST=")
        config = config.replace("FBINK=/mnt/us/libkh/bin/fbink", "FBINK=" + str(self.bin / "fbink"))
        (self.base / "server.conf").write_text(config + extra)

    def run_script(self, name, *args):
        return subprocess.run(["/bin/sh", str(self.base / name), *args], env=self.env, capture_output=True, timeout=15)

    def tearDown(self):
        self.tmp.cleanup()

    def placeholder(self):
        shutil.copyfile(ROOT / "kindle/assets/bootstrap-frame.png", self.base / "bootstrap-frame.png")

    def test_valid_cache_has_priority_over_fixed_placeholder(self):
        self.placeholder()
        (self.state / "frame.png").write_bytes(self.png.read_bytes())
        result = self.run_script("quota-dashboard.sh", "show-cache")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().strip(), f"fbink -q -i {self.state}/frame.png")

    def test_missing_cache_offline_shows_fixed_placeholder_before_wifi(self):
        self.placeholder()
        self.command("curl", "exit 1")
        config = self.base / "server.conf"
        config.write_text(config.read_text().replace("ENABLE_SCAN=1", "ENABLE_SCAN=0"))
        result = self.run_script("bootstrap.sh")
        self.assertNotEqual(result.returncode, 0)
        calls = self.log.read_text()
        paints = [line for line in calls.splitlines() if line.startswith("fbink ")]
        self.assertEqual(paints, [f"fbink -q -i {self.base}/bootstrap-frame.png"])
        self.assertNotIn("wirelessEnable 1", calls)
        self.assertFalse((self.state / "frame.png").exists(), "Placeholder must not become a quota cache")

    def test_invalid_or_undecodable_cache_falls_back_to_placeholder(self):
        self.placeholder()
        for cache in (b"bad cache", frame(None, NOW)):
            (self.state / "frame.png").write_bytes(cache)
            self.command("fbink", '''printf "fbink %s\\n" "$*" >> "$MOCK_LOG"
case "$*" in */frame.png) exit 1;; *) exit 0;; esac''')
            result = self.run_script("bootstrap.sh")
            self.assertNotEqual(result.returncode, 0)  # No fake RTC capability.
            self.assertIn("bootstrap-frame.png", self.log.read_text())
            self.assertFalse((self.state / "frame.next.png").exists())

    def test_cached_server_and_identity(self):
        (self.base / "server.cache").write_text("192.168.1.9\n")
        result = self.run_script("find-server.sh", "--internal")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), b"192.168.1.9")
        self.command("curl", "exit 1")
        config = (self.base / "server.conf").read_text().replace("ENABLE_SCAN=1", "ENABLE_SCAN=0")
        (self.base / "server.conf").write_text(config)
        self.assertNotEqual(self.run_script("find-server.sh", "--internal").returncode, 0)

    def test_dhcp_recovery_on_actual_private_24(self):
        self.conf(ip="192.168.1.200")
        result = self.run_script("find-server.sh", "--internal", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.base / "server.cache").read_text().strip(), "192.168.1.9")

    def test_wifi_subnet_change_recovers_from_old_mac_ip(self):
        self.conf(ip="192.168.1.200")
        (self.base / "server.cache").write_text("192.168.1.200\n")
        self.env["MOCK_HOST"] = "10.23.8.9"
        self.command("ip", "printf '    inet 10.23.8.52/24 brd 10.23.8.255 scope global wlan0\\n'")
        result = self.run_script("find-server.sh", "--internal", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.base / "server.cache").read_text().strip(), "10.23.8.9")

    def test_large_and_public_network_never_scanned(self):
        self.conf(ip="")
        for cidr in ("192.168.1.52/16", "10.20.3.52/21", "172.20.10.2/31", "8.8.8.8/24"):
            self.command("ip", f"printf '    inet {cidr} scope global wlan0\\n'")
            result = self.run_script("find-server.sh", "--internal", "--force")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.base / "server.cache").exists())

    def test_22_discovers_server_outside_local_24(self):
        self.conf(ip="192.168.1.200")
        self.env["MOCK_HOST"] = "10.20.3.60"
        self.command("ip", "printf '    inet 10.20.2.52/22 scope global wlan0\\n'")
        result = self.run_script("find-server.sh", "--internal", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), b"10.20.3.60")

    def test_28_scan_stays_inside_actual_subnet(self):
        self.conf(ip="")
        self.command("ip", "printf '    inet 172.20.10.18/28 scope global wlan0\\n'")
        self.command("curl", '''output=; url=
while [ "$#" -gt 0 ]; do
 case "$1" in -o) output=$2; shift;; http://*) url=$1;; esac
 shift
done
printf '%s\\n' "$url" >> "$MOCK_LOG"
exit 1''')
        result = self.run_script("find-server.sh", "--internal", "--force")
        self.assertNotEqual(result.returncode, 0)
        urls = self.log.read_text().splitlines()
        expected = {f"http://172.20.10.{n}:8486/healthz" for n in range(17, 31) if n != 18}
        self.assertEqual(set(urls), expected)
        self.assertEqual(len(urls), len(expected))

    def test_automatic_discovery_deduplicates_and_never_scans(self):
        (self.base / "server.cache").write_text("192.168.1.9")
        config = self.base / "server.conf"
        config.write_text(config.read_text().replace("SERVER_HOST=", "SERVER_HOST=mac.example"))
        self.command("curl", 'printf "%s\\n" "$*" >> "$MOCK_LOG"; exit 1')
        for args in ((), ("--known-only",)):
            self.log.unlink(missing_ok=True)
            result = self.run_script("find-server.sh", "--internal", *args)
            self.assertNotEqual(result.returncode, 0)
            urls = self.log.read_text().splitlines()
            self.assertEqual(len(urls), 6)
            self.assertTrue(all("192.168.1.9:8486/healthz" in url or "mac.example:8486/healthz" in url for url in urls))

    def test_outer_timeout_bounds_hung_curl_and_wget_dns(self):
        for client in ("curl", "wget"):
            self.command(client, 'echo $$ > "$KQD_STATE/http-child"; exec /bin/sleep 30')
            env = self.env.copy()
            if client == "wget":
                # A PATH with the required utilities but no curl exercises fallback.
                minimal = self.state / "minimal-bin"
                minimal.mkdir()
                for name in ("awk", "sleep", "cat"):
                    (minimal / name).symlink_to(shutil.which(name))
                (minimal / "wget").symlink_to(self.bin / "wget")
                (minimal / "sleep").unlink()
                (minimal / "sleep").symlink_to(self.bin / "sleep")
                env["PATH"] = str(minimal)
            started = time.monotonic()
            result = subprocess.run(["/bin/sh", "-c", ' . "$KQD_BASE/common.sh"; trap cancel_command 0; network_begin 2; fetch http://known.test/frame "$KQD_STATE/next" 15'],
                                    env=env, capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertLess(time.monotonic() - started, 4)
            pid = int((self.state / "http-child").read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_no_ipv4_exhausts_one_budget_without_http_or_scan(self):
        self.virtual_device(wakes="180", rounds=1)
        self.command("ip", "exit 0")
        self.command("curl", 'echo unexpected >> "$MOCK_LOG"; exit 1')
        result = self.worker()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("unexpected", self.log.read_text())
        self.assertIn("rtc 180", self.log.read_text())
        self.assertEqual((self.state / "uptime").read_text().split('.')[0], "130")
        self.assertIn("failures=1 next_delay=180", (self.base / "power.log").read_text())

    def start_visible_worker(self):
        proc = self.state / "proc"
        proc.mkdir()
        self.env["KQD_PROC_ROOT"] = str(proc)
        (self.state / "lock").mkdir()
        log = self.state / "worker-test.log"
        with log.open("wb") as output:
            worker = subprocess.Popen(["/bin/sh", str(self.base / "quota-dashboard.sh"), "run"], env=self.env,
                                      stdout=output, stderr=subprocess.STDOUT)
        (proc / str(worker.pid)).mkdir()
        (proc / str(worker.pid) / "cmdline").write_text(f"/bin/sh {self.base}/quota-dashboard.sh run")
        deadline = time.monotonic() + 8
        while not (self.state / "ready").exists() and worker.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        if not (self.state / "ready").exists():
            if worker.poll() is None:
                worker.terminate()
            worker.wait(timeout=4)
            self.fail(f"Worker did not become ready (exit {worker.returncode}): {log.read_text()}")
        return worker

    def test_manual_request_interrupts_backoff_and_coalesces(self):
        self.conf(ip="192.168.1.200")
        self.command("ip", "printf ' inet 192.168.1.2/28 scope global wlan0\\n'")
        self.command("sleep", '''if [ "${KQD_WATCHDOG:-0}" = 1 ]; then exec /bin/sleep "$@"; fi
if [ "$1" -ge 180 ]; then echo waiting >> "$MOCK_LOG"; exec /bin/sleep 5; fi
exec /bin/sleep .02''')
        original = (self.bin / "curl").read_text()
        self.command("curl", 'case "$*" in *healthz*) /bin/sleep .1;; esac\n' + original.removeprefix("#!/bin/sh\n"))
        (self.state / "result").write_text("wrong-request success")
        worker = self.start_visible_worker()
        try:
            deadline = time.monotonic() + 3
            while (not self.log.exists() or "waiting" not in self.log.read_text()) and time.monotonic() < deadline:
                time.sleep(.01)
            command = ["/bin/sh", str(self.base / "quota-dashboard.sh"), "rediscover"]
            with subprocess.Popen(command, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as one, \
                 subprocess.Popen(command, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as two:
                for request in (one, two):
                    out, err = request.communicate(timeout=8)
                    self.assertEqual(request.returncode, 0, err)
                    self.assertIn(b"Rediscovered and refreshed", out)
            self.assertEqual((self.base / "server.cache").read_text().strip(), "192.168.1.9")
            self.assertIn("failures=0 next_delay=180", (self.base / "power.log").read_text())
            self.assertEqual(sum(line.endswith("frame.next.png") for line in self.log.read_text().splitlines()), 1)
        finally:
            self.run_script("quota-dashboard.sh", "stop")
            worker.wait(timeout=4)
        self.assertFalse((self.state / "lock").exists())

    def test_stop_interrupts_hung_probe_and_reaps_child(self):
        self.command("curl", 'echo $$ > "$KQD_STATE/http-child"; exec /bin/sleep 30')
        worker = self.start_visible_worker()
        try:
            deadline = time.monotonic() + 3
            while not (self.state / "http-child").exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue((self.state / "http-child").exists())
            child = int((self.state / "http-child").read_text())
            self.run_script("quota-dashboard.sh", "stop")
            worker.wait(timeout=4)
            with self.assertRaises(ProcessLookupError):
                os.kill(child, 0)
        finally:
            if worker.poll() is None:
                worker.terminate(); worker.wait(timeout=4)
        self.assertFalse((self.state / "lock").exists())
        self.assertFalse((self.state / "frame.png").exists())

    def test_manual_without_worker_is_one_shot(self):
        result = self.run_script("quota-dashboard.sh", "rediscover")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.state / "frame.png").exists())
        self.assertFalse((self.state / "lock").exists())
        self.assertFalse((self.state / "pid").exists())

    def test_health_wrong_server_id_rejected(self):
        config = (self.base / "server.conf").read_text().replace("SERVER_ID=kqd-pw3", "SERVER_ID=other").replace("ENABLE_SCAN=1", "ENABLE_SCAN=0")
        (self.base / "server.conf").write_text(config)
        self.assertNotEqual(self.run_script("find-server.sh", "--internal").returncode, 0)

    def test_config_is_data_no_execution(self):
        sentinel = Path(self.tmp.name) / "injected"
        self.conf(extra=f"SERVER_HOST=$(touch {sentinel})\n")
        self.assertNotEqual(self.run_script("find-server.sh", "--internal").returncode, 0)
        self.assertFalse(sentinel.exists())

    def test_refresh_paints_then_commits_cache_and_restores_wifi(self):
        result = self.run_script("quota-dashboard.sh", "refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.state / "frame.png").read_bytes(), self.png.read_bytes())
        calls = self.log.read_text()
        self.assertIn("fbink -q -f -i", calls)
        self.assertEqual(calls.count("wirelessEnable 1"), 2)
        self.assertFalse((self.state / "lock").exists())
        result = self.run_script("quota-dashboard.sh", "refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fbink -q -i", self.log.read_text())

    def test_failed_download_or_png_keeps_screen_and_cache(self):
        old = self.state / "frame.png"
        old.write_bytes(b"last good cache")
        self.png.write_bytes(b"<html>not a frame</html>" * 3)
        result = self.run_script("quota-dashboard.sh", "refresh")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(old.read_bytes(), b"last good cache")
        self.assertNotIn("fbink", self.log.read_text())

    def test_decoder_failure_does_not_promote_frame(self):
        (self.state / "frame.png").write_bytes(b"last good cache")
        self.env["MOCK_FBINK_EXIT"] = "1"
        self.assertNotEqual(self.run_script("quota-dashboard.sh", "refresh").returncode, 0)
        self.assertEqual((self.state / "frame.png").read_bytes(), b"last good cache")

    def test_active_lock_prevents_overlapping_refresh(self):
        (self.state / "lock").mkdir()
        self.assertNotEqual(self.run_script("quota-dashboard.sh", "refresh").returncode, 0)
        self.assertFalse(self.log.exists())

    def test_bootstrap_offline_shows_latest_cache_before_wifi(self):
        # A newer good frame exists while the installation snapshot is stale.
        last_good = self.png.read_bytes()
        (self.state / "frame.png").write_bytes(last_good)
        (self.base / "bootstrap-frame.png").write_bytes(frame(None, NOW))
        self.command("curl", "exit 1")
        config = self.base / "server.conf"
        config.write_text(config.read_text().replace("ENABLE_SCAN=1", "ENABLE_SCAN=0"))
        result = self.run_script("bootstrap.sh")
        self.assertNotEqual(result.returncode, 0)
        calls = self.log.read_text() if self.log.exists() else ""
        paints = [line for line in calls.splitlines() if line.startswith("fbink ")]
        self.assertEqual(paints, [f"fbink -q -i {self.state}/frame.png"])
        self.assertNotIn("wirelessEnable 1", calls)
        self.assertNotIn("bootstrap-frame.png", calls)
        self.assertEqual((self.state / "frame.png").read_bytes(), last_good)

    def test_bootstrap_offline_can_start_after_device_preflight(self):
        self.placeholder()
        power = self.state / "power"
        power.touch()
        rtc = self.state / "rtc/rtc0"
        rtc.mkdir(parents=True)
        (rtc / "wakealarm").write_text("0")
        (rtc / "since_epoch").write_text("1700000000")
        self.env.update(KQD_POWER_STATE=str(power), KQD_RTC_ROOT=str(rtc.parent))
        script = self.base / "quota-dashboard.sh"
        text = script.read_text().replace('    start)\n', '    start)\n        echo started > "$STATE/started"; exit 0\n')
        script.write_text(text)
        self.command("curl", "exit 1")
        result = self.run_script("bootstrap.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.state / "started").exists())
        self.assertIn("ALLOW_SUSPEND=1", (self.base / "server.conf").read_text())
        self.assertNotIn("wirelessEnable", self.log.read_text())
        self.assertFalse((self.state / "frame.png").exists())

    def test_show_cache_preserves_running_process_state(self):
        (self.state / "frame.png").write_bytes(self.png.read_bytes())
        (self.state / "lock").mkdir()
        (self.state / "pid").write_text("123\n")
        (self.state / "status").write_text("frame_ok\n")
        (self.state / "full-refresh").write_text("1234\n")
        result = self.run_script("quota-dashboard.sh", "show-cache")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().strip(), f"fbink -q -i {self.state}/frame.png")
        self.assertTrue((self.state / "lock").is_dir())
        self.assertEqual((self.state / "pid").read_text(), "123\n")
        self.assertEqual((self.state / "status").read_text(), "frame_ok\n")
        self.assertEqual((self.state / "full-refresh").read_text(), "1234\n")
        self.assertFalse((self.state / "display-lock").exists())

    def test_show_cache_skips_busy_display_without_removing_its_lock(self):
        self.placeholder()
        (self.state / "frame.png").write_bytes(self.png.read_bytes())
        (self.state / "display-lock").mkdir()
        result = self.run_script("quota-dashboard.sh", "show-cache")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.log.exists())
        self.assertTrue((self.state / "display-lock").is_dir())

    def test_bootstrap_already_running_still_shows_cache(self):
        (self.state / "frame.png").write_bytes(self.png.read_bytes())
        script = self.base / "quota-dashboard.sh"
        shutil.copyfile(script, self.base / "quota-dashboard-real.sh")
        (self.base / "quota-dashboard-real.sh").chmod(0o755)
        script.write_text('''#!/bin/sh
case "$1" in
 status) printf 'running pid=123\\nframe_ok\\n';;
 *) exec "$KQD_BASE/quota-dashboard-real.sh" "$@";;
esac
''')
        (self.state / "lock").mkdir()
        result = self.run_script("bootstrap.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().strip(), f"fbink -q -i {self.state}/frame.png")
        self.assertTrue((self.state / "lock").is_dir())

    def test_cache_preview_cannot_repaint_old_frame_during_promotion(self):
        (self.state / "frame.png").write_bytes(frame(None, NOW))
        # Interleave a preview exactly after drawing the new frame but before
        # committing its cache; it must skip rather than redraw the old cache.
        self.command("mv", '''if [ "$2" = "$KQD_STATE/frame.png" ]; then
 "$KQD_BASE/quota-dashboard.sh" show-cache || exit 1
fi
exec /bin/mv "$@"''')
        result = self.run_script("quota-dashboard.sh", "refresh")
        self.assertEqual(result.returncode, 0, result.stderr)
        paints = [line for line in self.log.read_text().splitlines() if line.startswith("fbink ")]
        self.assertEqual(paints, [f"fbink -q -f -i {self.state}/frame.next.png"])
        self.assertEqual((self.state / "frame.png").read_bytes(), self.png.read_bytes())
        self.assertFalse((self.state / "display-lock").exists())

    def test_bootstrap_missing_cache_offline_never_uses_install_frame(self):
        (self.base / "bootstrap-frame.png").write_bytes(self.png.read_bytes())
        self.command("curl", "exit 1")
        config = self.base / "server.conf"
        config.write_text(config.read_text().replace("ENABLE_SCAN=1", "ENABLE_SCAN=0"))
        result = self.run_script("bootstrap.sh")
        self.assertNotEqual(result.returncode, 0)
        calls = self.log.read_text() if self.log.exists() else ""
        self.assertNotIn("fbink", calls)

    def test_debug_run_restores_initial_wifi_and_screensaver(self):
        (self.state / "lock").mkdir()
        self.command("lipc-get-prop", "printf '0\\n'")
        self.command("sleep", 'if [ "${KQD_WATCHDOG:-0}" = 1 ]; then exec /bin/sleep "$@"; fi; if [ "$1" = 180 ]; then touch "$KQD_STATE/stop"; fi')
        result = self.run_script("quota-dashboard.sh", "run")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text()
        self.assertIn("wirelessEnable 1", calls)
        self.assertIn("wirelessEnable 0", calls)
        self.assertIn("preventScreenSaver 1", calls)
        self.assertIn("preventScreenSaver 0", calls)
        self.assertFalse((self.state / "lock").exists())
        self.assertFalse((self.state / "pid").exists())

    def virtual_device(self, wakes="180", rounds=2):
        """Real worker and RTC code, with only clocks/device commands simulated."""
        power = self.state / "power"
        power.write_text("")
        rtc = self.state / "rtc/rtc0"
        rtc.mkdir(parents=True)
        (rtc / "wakealarm").write_text("0")
        (rtc / "since_epoch").write_text("1700000000")
        (self.state / "uptime").write_text("100.00 0")
        self.env.update(KQD_POWER_STATE=str(power), KQD_RTC_ROOT=str(rtc.parent),
                        KQD_UPTIME=str(self.state / "uptime"), MOCK_WAKES=wakes,
                        MOCK_ROUNDS=str(rounds), MOCK_POWER=str(power))
        config = self.base / "server.conf"
        config.write_text(config.read_text().replace("ALLOW_SUSPEND=0", "ALLOW_SUSPEND=1"))
        self.command("sync", "exit 0")
        self.command("cat", '''case "$1" in
 */wakealarm)
  value=$(/bin/cat "$1")
  case "$value" in +*) now=$(/bin/cat "${1%/wakealarm}/since_epoch"); value=$((now + ${value#+})); printf '%s' "$value" > "$1"; printf '%s\\n' "$value";; *) printf '%s' "$value";; esac;;
 */since_epoch)
  now=$(/bin/cat "$1")
  if [ "$(/bin/cat "$MOCK_POWER")" = mem ]; then
   alarm=$(/bin/cat "${1%/since_epoch}/wakealarm")
   case "$alarm" in +*) delay=${alarm#+};; *) delay=$((alarm - now));; esac
   n=0; [ ! -f "$KQD_STATE/suspends" ] || n=$(/bin/cat "$KQD_STATE/suspends")
   n=$((n+1)); printf '%s' "$n" > "$KQD_STATE/suspends"
   wake=$(printf '%s' "$MOCK_WAKES" | cut -d, -f"$n")
   [ -n "$wake" ] || wake=$delay
   printf 'rtc %s\\n' "$delay" >> "$MOCK_LOG"
   now=$((now + wake)); printf '%s' "$now" > "$1"
   : > "$MOCK_POWER"
   [ "$n" -lt "$MOCK_ROUNDS" ] || touch "$KQD_STATE/stop"
  fi
  printf '%s' "$now";;
 *) exec /bin/cat "$@";;
esac''')
        self.command("sleep", '''if [ "${KQD_WATCHDOG:-0}" = 1 ]; then exec /bin/sleep "$@"; fi
printf 'sleep %s\\n' "$1" >> "$MOCK_LOG"
rtc="$KQD_RTC_ROOT/rtc0/since_epoch"
now=$(/bin/cat "$rtc"); printf '%s' "$((now + $1))" > "$rtc"
now=$(cut -d. -f1 "$KQD_UPTIME"); printf '%s.00 0' "$((now + $1))" > "$KQD_UPTIME"''')

    def worker(self):
        (self.state / "lock").mkdir()
        return self.run_script("quota-dashboard.sh", "run")

    def test_offline_backoff_caps_and_success_resets(self):
        self.virtual_device(wakes=",".join(["180", "360", "540", "720", "900", "900", "180", "180"]), rounds=8)
        original = (self.bin / "curl").read_text()
        self.command("lipc-set-prop", '''printf 'lipc %s\\n' "$*" >> "$MOCK_LOG"
case "$*" in *"wirelessEnable 1")
 n=0; [ ! -f "$KQD_STATE/attempts" ] || n=$(/bin/cat "$KQD_STATE/attempts")
 printf '%s' "$((n+1))" > "$KQD_STATE/attempts";; esac''')
        self.command("curl", '''n=$(/bin/cat "$KQD_STATE/attempts")
[ "$n" = 7 ] || exit 1
''' + original.removeprefix("#!/bin/sh\n"))
        result = self.worker()
        self.assertEqual(result.returncode, 0, result.stderr)
        waits = [int(line.split()[1]) for line in self.log.read_text().splitlines() if line.startswith("rtc ")]
        self.assertEqual(waits, [180, 360, 540, 720, 900, 900, 180, 180])
        self.assertEqual((self.state / "frame.png").read_bytes(), self.png.read_bytes())
        summaries = (self.base / "power.log").read_text()
        self.assertIn("failures=0 next_delay=180", summaries)
        self.assertIn("failures=1 next_delay=180", summaries.split("failures=0 next_delay=180")[1])

    def test_early_resume_rearms_remaining_with_wifi_off(self):
        self.virtual_device(wakes="17,143", rounds=2)
        result = self.worker()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text().splitlines()
        self.assertIn("rtc 180", calls)
        self.assertIn("sleep 20", calls)
        self.assertIn("rtc 143", calls)
        early = calls.index("rtc 180")
        again = calls.index("rtc 143")
        self.assertFalse(any("wirelessEnable 1" in call for call in calls[early:again]))
        self.assertEqual(sum(call.endswith("frame.next.png") for call in calls), 1)
        self.assertFalse((self.state / "lock").exists())

    def test_repeated_immediate_resume_exits_safely(self):
        self.virtual_device(wakes="0,0,0", rounds=99)
        result = self.worker()
        self.assertNotEqual(result.returncode, 0)
        events = [json.loads(line) for line in (self.base / "lifecycle.log").read_text().splitlines()]
        self.assertEqual(events[-1]["reason"], "suspend_failed")
        self.assertFalse((self.state / "lock").exists())
        self.assertEqual(sum("wirelessEnable 1" in call for call in self.log.read_text().splitlines()), 2)  # round + restore only

    def test_wall_clock_change_does_not_change_rtc_wait(self):
        self.virtual_device(wakes="180", rounds=1)
        self.command("date", "printf '1\\n'")
        result = self.worker()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("rtc 180", self.log.read_text())
        self.assertFalse((self.state / "lock").exists())

    def test_lifecycle_is_logged_when_server_is_offline_and_rotates(self):
        old = b"x" * 262144
        (self.base / "lifecycle.log").write_bytes(old)
        self.command("curl", "exit 1")
        result = subprocess.run(["/bin/sh", "-c", '. "$KQD_BASE/common.sh"; report resumed early_wake'],
                                env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.base / "lifecycle.previous.log").read_bytes(), old)
        event = json.loads((self.base / "lifecycle.log").read_text())
        self.assertEqual(event["stage"], "resumed")
        self.assertEqual(event["reason"], "early_wake")
        self.assertLess((self.base / "lifecycle.log").stat().st_size, 1024)

    def test_rtc_alarm_accepts_hardware_clock_older_than_system_clock(self):
        rtc_root = Path(self.tmp.name) / "rtc"
        rtc = rtc_root / "rtc0"
        rtc.mkdir(parents=True)
        (rtc / "wakealarm").write_text("")
        self.env["KQD_RTC_ROOT"] = str(rtc_root)
        self.command("cat", '''value=$(/bin/cat "$1")
case "$1:$value" in */wakealarm:+*) printf '1700000180\\n';; *) printf '%s' "$value";; esac''')
        result = subprocess.run(["/bin/sh", "-c", '. "$KQD_BASE/common.sh"; arm_rtc; printf "%s" "$ALARM"'], env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"1700000180")

    def test_rtc_does_not_overwrite_busy_alarm_and_tries_second_device(self):
        rtc_root = Path(self.tmp.name) / "rtc"
        for name in ["rtc0", "rtc1"]:
            (rtc_root / name).mkdir(parents=True)
        busy = rtc_root / "rtc0/wakealarm"
        busy.write_text("1900000000")
        (rtc_root / "rtc1/wakealarm").write_text("")
        self.env["KQD_RTC_ROOT"] = str(rtc_root)
        self.command("cat", '''value=$(/bin/cat "$1")
case "$1:$value" in */wakealarm:+*) printf '1700000180\\n';; *) printf '%s' "$value";; esac''')
        result = subprocess.run(["/bin/sh", "-c", '. "$KQD_BASE/common.sh"; arm_rtc; printf "%s" "$RTC"'], env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.endswith(b"rtc1/wakealarm"))
        self.assertEqual(busy.read_text(), "1900000000")

    def test_stale_pid_cannot_signal_an_unrelated_process(self):
        with subprocess.Popen(["/bin/sleep", "5"]) as unrelated:
            try:
                (self.state / "pid").write_text(str(unrelated.pid))
                result = self.run_script("quota-dashboard.sh", "stop")
                self.assertEqual(result.returncode, 0)
                self.assertIsNone(unrelated.poll())
            finally:
                unrelated.terminate()
                unrelated.wait()


if __name__ == "__main__":
    unittest.main()
