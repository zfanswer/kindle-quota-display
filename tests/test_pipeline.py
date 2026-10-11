import copy
import fcntl
import hashlib
import http.client
import importlib.util
import io
import json
import os
import plistlib
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from datetime import timedelta
from pathlib import Path

from PIL import Image, ImageDraw

from quota_display.collector import CollectionError, atomic_write, collect, read_snapshot, run_cli
from quota_display.model import PayloadError, normalize, timestamp, validate_snapshot
from quota_display.render import frame, labels, placeholder_frame
from quota_display.server import Dashboard, handler, make_server

ROOT = Path(__file__).resolve().parents[1]
NOW = timestamp("2026-10-07T12:00:00Z")


def fixture(pid):
    return json.loads((ROOT / f"tests/fixtures/{pid}.json").read_text())


def good():
    return collect(None, lambda _, pid, timeout: fixture(pid), now=NOW)


class PipelineTests(unittest.TestCase):
    def test_fixed_placeholder_png_contract(self):
        data = placeholder_frame()
        image = Image.open(io.BytesIO(data))
        self.assertEqual(image.size, (1072, 1448))
        self.assertEqual(image.mode, "L")
        self.assertLessEqual(len(image.getcolors(maxcolors=256)), 16)
        self.assertEqual(image.info, {"kqd-placeholder": "refresh-v1"})
        marker = b"kqd-placeholder\x00refresh-v1"
        self.assertEqual(data[33:67], len(marker).to_bytes(4, "big") + b"tEXt" + marker)

    def test_prepared_bundle_includes_fixed_placeholder(self):
        (ROOT / "build").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            bundle = Path(tmp) / "bundle"
            result = subprocess.run([sys.executable, str(ROOT / "scripts/prepare.py"), "kindle",
                                     "--host", "", "--output", str(bundle)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            asset = (ROOT / "kindle/assets/bootstrap-frame.png").read_bytes()
            self.assertEqual((bundle / "eink-dashboard/bootstrap-frame.png").read_bytes(), asset)
            manifest = json.loads((bundle / "manifest.json").read_text())
            self.assertEqual(manifest["eink-dashboard/bootstrap-frame.png"], hashlib.sha256(asset).hexdigest())

    def test_timestamp_is_black_in_header_and_keeps_original_sample(self):
        data = good()
        data["providers"]["claude"]["status"] = "error"
        calls = []
        original = ImageDraw.ImageDraw.text
        def record(draw, xy, value, *args, **kwargs):
            calls.append((xy, value, kwargs))
            return original(draw, xy, value, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, "text", record):
            frame(data, NOW + timedelta(days=2))
        updates = [(xy, value, options) for xy, value, options in calls if value.startswith("数据更新")]
        self.assertEqual(len(updates), 2)
        for xy, value, options in updates:
            self.assertEqual(value, "数据更新 2026-10-07 19:59")
            self.assertEqual(options["fill"], 0)
            self.assertEqual(options["font"].size, 26)
            self.assertLess(xy[0] + options["font"].getlength(value), 993)
            # Keep enough space after even the longer provider name.
            title = next((pos, val, opts) for pos, val, opts in calls
                         if val in ("Codex", "Claude Code") and pos[1] == xy[1] - 12)
            self.assertGreater(xy[0], title[0][0] + title[2]["font"].getlength(title[1]) + 20)
        statuses = [(xy, value) for xy, value, _ in calls if "过期" in value]
        self.assertEqual(len(statuses), 2)
        self.assertTrue(all(xy[0] == 80 for xy, _ in statuses))

    def test_update_installer_preserves_config_cache_and_unrelated_files(self):
        spec = importlib.util.spec_from_file_location("install_kindle", ROOT / "scripts/install-kindle.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bundle = base / "bundle"
            # The generator is independently exercised through its guarded CLI.
            prepare_spec = importlib.util.spec_from_file_location("prepare", ROOT / "scripts/prepare.py")
            prepare = importlib.util.module_from_spec(prepare_spec)
            prepare_spec.loader.exec_module(prepare)
            prepare.bundle("", "", "kqd-pw3", bundle)
            mount = base / "mount"
            app = mount / "eink-dashboard"
            app.mkdir(parents=True)
            (mount / "documents").mkdir()
            (mount / "documents/user-note.txt").write_text("keep")
            (app / "quota-dashboard.sh").write_text("previous worker")
            (app / "server.conf").write_bytes(b"device-owned config")
            (app / "server.cache").write_bytes(b"192.0.2.7")
            report = module.install(bundle, mount, base / "backup", update=True)
            self.assertEqual(len(report["files"]), 9)
            self.assertEqual((app / "server.conf").read_bytes(), b"device-owned config")
            self.assertEqual((app / "server.cache").read_bytes(), b"192.0.2.7")
            self.assertEqual((mount / "documents/user-note.txt").read_text(), "keep")
            self.assertFalse((mount / "documents/Recover Agent Quota.sh").exists())
            self.assertEqual((base / "backup/eink-dashboard/quota-dashboard.sh").read_text(), "previous worker")
            with self.assertRaisesRegex(ValueError, "--update"):
                module.install(bundle, mount, base / "other-backup")
            manifest = json.loads((bundle / "manifest.json").read_text())
            manifest["documents/user-note.txt"] = "injected"
            (bundle / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "file list"):
                module.install(bundle, mount, base / "bad-backup", update=True)
            self.assertFalse((base / "bad-backup").exists())

    def test_percentage_and_reset_mapping(self):
        p = normalize(fixture("codex"), "codex", NOW)
        self.assertEqual(p["windows"][0]["remaining_percent"], 58)
        self.assertEqual(p["windows"][0]["reset_at"], "2026-10-07T14:31:00Z")

    def test_secret_allowlist(self):
        raw = fixture("codex")
        raw[0]["account"] = "private@example.invalid"
        raw[0]["diagnostic"] = "SECRET"
        raw[0]["usage"]["identity"] = {"token": "SECRET"}
        raw[0]["usage"]["primary"]["resetDescription"] = "SECRET"
        result = json.dumps(normalize(raw, "codex", NOW))
        self.assertNotIn("SECRET", result)
        self.assertNotIn("private@", result)

    def test_bad_percentages(self):
        for bad in (True, "42", -1, float("nan"), float("inf"), 10 ** 400):
            raw = fixture("codex")
            raw[0]["usage"]["primary"]["usedPercent"] = bad
            with self.subTest(value=bad), self.assertRaises(PayloadError):
                normalize(raw, "codex", NOW)

    def test_over_quota_is_preserved_and_remaining_clamped(self):
        raw = fixture("codex")
        raw[0]["usage"]["primary"]["usedPercent"] = 125
        p = normalize(raw, "codex", NOW)
        self.assertEqual(p["windows"][0]["used_percent"], 125)
        self.assertEqual(p["windows"][0]["remaining_percent"], 0)

    def test_synthetic_and_missing_windows(self):
        raw = fixture("claude")
        raw[0]["usage"]["primary"]["isSyntheticPlaceholder"] = True
        p = normalize(raw, "claude", NOW)
        self.assertEqual([w["id"] for w in p["windows"]], ["secondary"])

    def test_tertiary_no_duration_or_reset(self):
        raw = fixture("claude")
        raw[0]["usage"]["tertiary"] = {"usedPercent": 5}
        p = normalize(raw, "claude", NOW)
        self.assertIsNone(p["windows"][-1]["reset_at"])
        self.assertIsNone(p["windows"][-1]["window_minutes"])

    def test_source_and_account_guard(self):
        raw = fixture("codex")
        raw[0]["source"] = "web"
        with self.assertRaisesRegex(PayloadError, "source_mismatch"):
            normalize(raw, "codex", NOW)
        with self.assertRaises(PayloadError):
            normalize(fixture("codex") * 2, "codex", NOW)
        # Claude is collected through Claude Code; CodexBar labels that source "claude".
        raw = fixture("claude")
        self.assertEqual(normalize(raw, "claude", NOW)["source"], "cli")
        self.assertEqual(normalize(fixture("codex"), "codex", NOW)["source"], "oauth")
        raw[0]["source"] = "oauth"
        with self.assertRaisesRegex(PayloadError, "source_mismatch"):
            normalize(raw, "claude", NOW)
        legacy = good()
        legacy["providers"]["claude"]["source"] = "oauth"
        with self.assertRaises(PayloadError):
            validate_snapshot(legacy)

    def test_invalid_and_future_timestamps(self):
        for value in ("2026-10-07T12:00:00", "nonsense", "2026-10-07T13:00:00Z", None):
            raw = fixture("codex")
            raw[0]["usage"]["updatedAt"] = value
            with self.subTest(value=value), self.assertRaises(PayloadError):
                normalize(raw, "codex", NOW)

    def test_out_of_range_timestamps_fail_one_provider_only(self):
        for value in ("0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59", "9999-12-31T20:00:00Z"):
            def runner(_, pid, timeout, value=value):
                raw = fixture(pid)
                if pid == "codex":
                    raw[0]["usage"]["primary"]["resetsAt"] = value
                return raw
            with self.subTest(value=value):
                data = collect(None, runner, now=NOW)
                self.assertEqual(data["providers"]["codex"]["error_code"], "invalid_payload")
                self.assertEqual(data["providers"]["claude"]["status"], "ok")
                stored = good()
                stored["providers"]["codex"]["windows"][0]["reset_at"] = value
                with self.assertRaises(PayloadError):
                    validate_snapshot(stored)

    def test_partial_failure_keeps_original_sample_time(self):
        prior = good()
        def runner(_, pid, timeout):
            if pid == "claude":
                raise CollectionError("timeout")
            return fixture(pid)
        result = collect(prior, runner, now=NOW + timedelta(minutes=20))
        p = result["providers"]["claude"]
        self.assertEqual(p["windows"], prior["providers"]["claude"]["windows"])
        self.assertEqual(p["sampled_at"], prior["providers"]["claude"]["sampled_at"])
        self.assertEqual(p["status"], "error")
        self.assertEqual(result["providers"]["codex"]["status"], "ok")

    def test_first_run_failure(self):
        def fail(*args):
            raise CollectionError("command_failed")
        data = collect(None, fail, now=NOW)
        self.assertIsNone(data["providers"]["codex"]["sampled_at"])
        self.assertEqual(validate_snapshot(data), data)

    def test_real_collection_uses_each_provider_completion_time(self):
        moments = [NOW, NOW + timedelta(seconds=45), NOW + timedelta(seconds=46),
                   NOW + timedelta(seconds=90), NOW + timedelta(seconds=91)]
        def runner(_, pid, timeout):
            raw = fixture(pid)
            raw[0]["usage"]["updatedAt"] = "2026-10-07T12:00:45Z" if pid == "codex" else "2026-10-07T12:01:30Z"
            return raw
        with patch("quota_display.collector.utcnow", side_effect=moments):
            data = collect(None, runner)
        self.assertEqual(data["providers"]["claude"]["status"], "ok")
        self.assertEqual(data["providers"]["claude"]["attempted_at"], "2026-10-07T12:00:46Z")
        self.assertEqual(data["providers"]["claude"]["last_success_at"], "2026-10-07T12:01:30Z")
        self.assertEqual(data["updated_at"], "2026-10-07T12:01:31Z")

    def test_each_provider_is_collected_at_its_own_interval(self):
        intervals = {"codex": 300, "claude": 900}
        calls = []
        def runner(_, pid, timeout):
            calls.append(pid)
            raw = fixture(pid)
            raw[0]["usage"]["updatedAt"] = "2026-10-07T12:00:00Z"
            return raw
        def later(previous, seconds, run=runner):
            calls.clear()
            return collect(previous, run, now=NOW + timedelta(seconds=seconds), intervals=intervals)
        first = later(None, 0)
        self.assertEqual(calls, ["codex", "claude"])
        kept = later(first, 200)
        self.assertEqual(calls, [])
        self.assertEqual(kept["providers"], first["providers"])
        self.assertEqual(kept["updated_at"], "2026-10-07T12:03:20Z")
        # A run within 60 seconds of the interval counts as due.
        second = later(first, 245)
        self.assertEqual(calls, ["codex"])
        self.assertEqual(second["providers"]["claude"], first["providers"]["claude"])
        self.assertEqual(second["providers"]["codex"]["attempted_at"], "2026-10-07T12:04:05Z")
        self.assertEqual(later(second, 845)["providers"]["claude"]["attempted_at"], "2026-10-07T12:14:05Z")
        self.assertEqual(calls, ["codex", "claude"])
        # A failed provider keeps its old windows and is retried on the very next run.
        def fail(*args):
            calls.append(args[1])
            raise CollectionError("timeout")
        failed = later(first, 900, fail)
        self.assertEqual(len(failed["providers"]["claude"]["windows"]), 2)
        recovered = later(failed, 960)
        self.assertEqual(calls, ["codex", "claude"])
        self.assertEqual(recovered["providers"]["claude"]["status"], "ok")
        # A clock that moved backwards must not postpone collection indefinitely.
        later(first, -3600)
        self.assertEqual(calls, ["codex", "claude"])

    def test_collector_cli_sources_config_and_intervals_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            exe = tmp / "fake-cli"
            # Echo the fixture only for the exact fixed command of each provider.
            exe.write_text(f'''#!/bin/sh
echo "$*" >> "{tmp}/calls"
case "$*" in
  "usage --provider codex --source oauth --format json --no-credits") cat "{ROOT}/tests/fixtures/codex.json";;
  "usage --provider claude --source cli --format json --no-credits") cat "{ROOT}/tests/fixtures/claude.json";;
  *) exit 2;;
esac
''')
            exe.chmod(0o755)
            config = {"providers": ["codex", "claude"], "sources": {"codex": "oauth", "claude": "cli"},
                      "interval_seconds": {"codex": 300, "claude": 900}, "timeout_seconds": 30}
            def run(config, *args):
                (tmp / "config.json").write_text(json.dumps(config))
                return subprocess.run([sys.executable, "-m", "quota_display.collector", "--config", str(tmp / "config.json"),
                                       "--output", str(tmp / "quota.json"), *args], cwd=ROOT, capture_output=True)
            result = run(config, "--cli", str(exe))
            self.assertEqual((result.returncode, result.stdout), (0, b"codex=ok claude=ok\n"), result.stderr)
            stored = read_snapshot(tmp / "quota.json")
            self.assertEqual({pid: p["source"] for pid, p in stored["providers"].items()}, {"codex": "oauth", "claude": "cli"})
            result = run(config, "--cli", str(exe))
            self.assertEqual((result.returncode, result.stdout), (0, b"codex=ok:kept claude=ok:kept\n"))
            self.assertEqual(read_snapshot(tmp / "quota.json")["providers"], stored["providers"])
            self.assertEqual(len((tmp / "calls").read_text().splitlines()), 2)
            # Fixtures ignore intervals; anything but the fixed sources and bounded intervals is rejected.
            offline = ("--fixture-dir", "tests/fixtures", "--fixture-now", "2026-10-07T12:00:00Z")
            self.assertEqual(run(config, *offline).stdout, b"codex=ok claude=ok\n")
            for bad in ({"sources": {"codex": "oauth", "claude": "oauth"}}, {"sources": None, "source": "oauth"},
                        {"interval_seconds": {"codex": 30, "claude": 900}}, {"interval_seconds": {"codex": 300}},
                        {"interval_seconds": {"codex": True, "claude": 900}}):
                with self.subTest(bad=bad):
                    self.assertEqual(run({**config, **bad}, *offline).returncode, 2)

    def test_atomic_snapshot_and_http_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quota.json"
            data = good()
            data["token"] = "SECRET"
            data["providers"]["claude"]["account"] = "SECRET"
            atomic_write(path, data)
            self.assertNotIn("SECRET", path.read_text())
            self.assertEqual(read_snapshot(path), good())
            app = Dashboard(path)
            status, headers, body = app.respond("/api/quota", NOW)
            self.assertEqual(status, 200)
            self.assertNotIn(b"SECRET", body)
            path.write_text('broken')
            self.assertEqual(app.respond("/api/quota", NOW)[0], 503)

    def test_http_identity_missing_data_and_routes(self):
        app = Dashboard(Path("does-not-exist"), "test-pw3")
        self.assertEqual(app.respond("/healthz", NOW)[2], b"EINK_QUOTA_V1\nSERVER_ID=test-pw3\n")
        self.assertEqual(app.respond("/frame/kindle1.png", NOW)[0], 200)
        self.assertEqual(app.respond("/../../.env", NOW)[0], 404)
        self.assertEqual(app.respond("/api/quota", NOW)[0], 503)

    def test_http_handler_wire_format_without_listening_socket(self):
        class FakeSocket:
            def __init__(self, request):
                self.input = io.BytesIO(request)
                self.output = bytearray()
            def makefile(self, mode, *args):
                return self.input
            def sendall(self, data):
                self.output.extend(data)
            def settimeout(self, timeout):
                self.timeout = timeout
        app = Dashboard(Path("missing-snapshot"))
        request = FakeSocket(b"GET /healthz HTTP/1.1\r\nHost: local\r\nConnection: close\r\n\r\n")
        handler(app)(request, ("127.0.0.1", 1234), None)
        headers, body = bytes(request.output).split(b"\r\n\r\n", 1)
        self.assertIn(b"200 OK", headers)
        self.assertIn(b"Content-Length: " + str(len(body)).encode(), headers)
        self.assertIn(b"Cache-Control: no-store", headers)
        self.assertEqual(body, b"EINK_QUOTA_V1\nSERVER_ID=kqd-pw3\n")
        request = FakeSocket(b"POST /api/quota HTTP/1.1\r\nHost: local\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
        handler(app)(request, ("127.0.0.1", 1234), None)
        self.assertIn(b"404", request.output.split(b"\r\n", 1)[0])

    def test_idle_connection_does_not_delay_health_probe(self):
        try:
            server = make_server(Dashboard(Path("missing-snapshot")), "127.0.0.1", 0)
        except OSError as exc:
            self.skipTest(f"loopback listener unavailable: {exc}")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            port = server.server_address[1]
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                # The Kindle probe allows one second for the whole request.
                probe = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                probe.request("GET", "/healthz")
                self.assertEqual(probe.getresponse().read(), b"EINK_QUOTA_V1\nSERVER_ID=kqd-pw3\n")
                probe.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_device_telemetry_rejects_commands_and_never_changes_quota(self):
        app = Dashboard(Path("missing-snapshot"))
        body = {"stage": "frame_ok", "reason": "none", "interval": 180, "cycles": 1}
        self.assertEqual(app.receive_device_status(json.dumps(body).encode(), NOW), 200)
        self.assertEqual(json.loads(app.respond("/api/device/kindle1", NOW)[2])["evidence"], "device_reported")
        bad = dict(body, command="touch /tmp/injected")
        self.assertEqual(app.receive_device_status(json.dumps(bad).encode(), NOW), 400)
        self.assertEqual(app.receive_device_status(b'{"stage":"exec"}', NOW), 400)
        self.assertEqual(app.respond("/api/quota", NOW)[0], 503)
        self.assertEqual(app.device_status["stage"], "frame_ok")

    def test_png_format_and_stale_cache_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quota.json"
            atomic_write(path, good())
            app = Dashboard(path)
            first = app.respond("/frame/kindle1.png", NOW)
            later = app.respond("/frame/kindle1.png", NOW + timedelta(hours=1))
            self.assertNotEqual(first[1]["ETag"], later[1]["ETag"])
            image = Image.open(io.BytesIO(first[2]))
            self.assertEqual(image.size, (1072, 1448))
            self.assertEqual(image.mode, "L")
            self.assertLessEqual(len(image.getcolors()), 16)

    def test_windows_of_equal_length_get_distinct_labels(self):
        def named(*lanes):
            return labels([{"id": slot, "window_minutes": minutes} for slot, minutes in lanes])
        self.assertEqual(named(("primary", 300), ("secondary", 10080), ("tertiary", 10080)),
                         ["5小时额度", "每周额度", "每周额度 · 第三窗口"])
        self.assertEqual(named(("primary", 300), ("secondary", 10080), ("tertiary", None)), ["5小时额度", "每周额度", "第三窗口"])
        self.assertEqual(named(("primary", 300), ("secondary", 300)), ["5小时额度", "5小时额度 · 第二窗口"])
        data = good()
        data["providers"]["claude"]["windows"].append({"id": "tertiary", "used_percent": 88, "remaining_percent": 12,
                                                        "window_minutes": 10080, "reset_at": None})
        same_length = Image.open(io.BytesIO(frame(data, NOW)))
        data["providers"]["claude"]["windows"][2]["window_minutes"] = None
        self.assertNotEqual(same_length.tobytes(), Image.open(io.BytesIO(frame(data, NOW))).tobytes())

    def test_stale_limit_is_three_collection_intervals_per_provider(self):
        def state_changes(minutes):
            # Samples are at 11:59:00 (Codex) and 11:59:20 (Claude).
            return frame(good(), NOW + timedelta(minutes=minutes)) != frame(good(), NOW + timedelta(minutes=minutes - 1))
        self.assertEqual([m for m in range(1, 50) if state_changes(m)], [14, 45])

    def test_launchd_plist_runs_every_five_minutes(self):
        (ROOT / "build").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            output = Path(tmp) / "collector.plist"
            result = subprocess.run([sys.executable, str(ROOT / "scripts/prepare.py"), "launchd", "--python", sys.executable,
                                     "--cli", sys.executable, "--output", str(output)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            plist = plistlib.loads(output.read_bytes())
            self.assertEqual(plist["StartInterval"], 300)
            # Background throttling makes the Claude Code launch outlast the collection timeout.
            self.assertFalse({"ProcessType", "LowPriorityIO"} & set(plist))
            self.assertIn("--cli", plist["ProgramArguments"])

    def test_cli_timeout_exit_and_output_limits_with_fake_program(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "fake-cli"
            for script, expected in (("sleep 5", "timeout"), ("exit 2", "command_failed"),
                                     ("head -c 1048577 /dev/zero", "output_limit"), ("printf nope", "invalid_payload")):
                exe.write_text("#!/bin/sh\n" + script + "\n")
                exe.chmod(0o755)
                with self.subTest(expected=expected), self.assertRaisesRegex(CollectionError, expected):
                    run_cli(str(exe), "codex", 0.1 if expected == "timeout" else 3)

    def test_prepare_cannot_install_outside_project(self):
        result = subprocess.run(["python3", str(ROOT / "scripts/prepare.py"), "kindle", "--output", "/tmp/should-not-install"], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"child of the project", result.stderr)

    def test_usb_install_guard_uses_actual_diskutil_mountpoint(self):
        spec = importlib.util.spec_from_file_location("install_kindle", ROOT / "scripts/install-kindle.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            mount = Path(tmp)
            info = {"VolumeName": "Kindle", "MountPoint": str(mount.resolve())}
            self.assertTrue(module.is_mounted_kindle(info, mount))
            self.assertFalse(module.is_mounted_kindle(dict(info, MountPoint="/other/mount"), mount))
            self.assertFalse(module.is_mounted_kindle(dict(info, VolumeName="Other"), mount))

    def test_observer_counts_new_session_frames_without_requiring_online_resumes(self):
        spec = importlib.util.spec_from_file_location("observe", ROOT / "scripts/observe-kindle.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        def event(minutes, cycle):
            return {"stage": "frame_ok", "reason": "none", "cycles": cycle,
                    "received_at": (NOW + timedelta(minutes=minutes)).isoformat()}
        frames = [event(1, 10), event(4, 11), event(7, 12)]
        self.assertEqual(module.summarize(frames, 3, 360, NOW)["verdict"], "passed")
        self.assertEqual(module.summarize(frames, 3, 360, NOW + timedelta(minutes=8))["frames"], 0)
        frames.append(event(10, 1))
        self.assertEqual(module.summarize(frames, 3, 360, NOW)["frames"], 1)
        self.assertEqual(module.summarize(frames, 3, 360, NOW)["verdict"], "observing")

    def test_collector_lock_prevents_overlapping_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quota.json"
            path.write_text("unchanged")
            with (Path(tmp) / ".collector.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = subprocess.run(["python3", "-m", "quota_display.collector", "--fixture-dir", "tests/fixtures", "--output", str(path)], cwd=ROOT, capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn(b"already running", result.stdout)
            self.assertEqual(path.read_text(), "unchanged")


if __name__ == "__main__":
    unittest.main()
