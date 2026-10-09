import copy
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import timedelta
from pathlib import Path

from PIL import Image

from quota_display.collector import CollectionError, atomic_write, collect, read_snapshot, run_cli
from quota_display.model import PayloadError, normalize, timestamp, validate_snapshot
from quota_display.render import frame, placeholder_frame
from quota_display.server import Dashboard, handler

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

    def test_invalid_and_future_timestamps(self):
        for value in ("2026-10-07T12:00:00", "nonsense", "2026-10-07T13:00:00Z", None):
            raw = fixture("codex")
            raw[0]["usage"]["updatedAt"] = value
            with self.subTest(value=value), self.assertRaises(PayloadError):
                normalize(raw, "codex", NOW)

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
