"""Credential-free quota service plus bounded, non-authoritative device telemetry."""
import argparse
import hashlib
import json
import os
import re
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .collector import read_snapshot
from .model import utcnow
from .render import frame


class Dashboard:
    def __init__(self, path, server_id="kqd-pw3", tz="Asia/Shanghai", stale_seconds=600):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", server_id):
            raise ValueError("invalid server id")
        ZoneInfo(tz)
        self.path = Path(path)
        self.server_id = server_id
        self.tz = tz
        self.stale_seconds = stale_seconds
        self.cache_key = None
        self.cache_png = None
        self.device_status = None
        self.device_events = deque(maxlen=128)

    def receive_device_status(self, body, now=None):
        """Non-authoritative device telemetry; never accepts commands or quota data."""
        stages = {"bootstrap", "preflight_failed", "frame_ok", "refresh_failed", "suspend_armed", "resumed", "stopped"}
        reasons = {"none", "fbink_missing", "wifi_state_unknown", "screensaver_unknown", "rtc_unavailable", "rtc_busy", "rtc_invalid_alarm", "display_failed", "suspend_failed", "early_wake", "signal_int", "signal_term"}
        try:
            data = json.loads(body)
            required = {"stage", "reason", "interval", "cycles"}
            diagnostic = {"rtc_device", "rtc_epoch", "system_epoch", "alarm_epoch", "elapsed_seconds"}
            if not isinstance(data, dict) or not required <= set(data) or set(data) - required - diagnostic:
                raise ValueError()
            if data["stage"] not in stages or data["reason"] not in reasons:
                raise ValueError()
            if type(data["interval"]) is not int or not 60 <= data["interval"] <= 3600:
                raise ValueError()
            if type(data["cycles"]) is not int or not 0 <= data["cycles"] <= 1000000:
                raise ValueError()
            for key in set(data) & diagnostic:
                if type(data[key]) is not int or not 0 <= data[key] <= 100000000000:
                    raise ValueError()
            if data.get("rtc_device", 0) not in (0, 1):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            return 400
        from .model import iso
        data["received_at"] = iso(now or utcnow())
        data["evidence"] = "device_reported"
        self.device_status = data
        self.device_events.append(dict(data))
        print(json.dumps({"device_event": data}, ensure_ascii=True), flush=True)
        return 200

    def respond(self, target, now=None):
        now = now or utcnow()
        path = urlsplit(target).path
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        if path == "/healthz":
            headers["Content-Type"] = "text/plain; charset=utf-8"
            return 200, headers, f"EINK_QUOTA_V1\nSERVER_ID={self.server_id}\n".encode()
        if path == "/api/device/kindle1":
            headers["Content-Type"] = "application/json"
            return 200, headers, json.dumps(self.device_status or {"stage": "not_seen"}).encode()
        if path == "/api/device/kindle1/history":
            headers["Content-Type"] = "application/json"
            return 200, headers, json.dumps(list(self.device_events)).encode()
        if path not in ("/api/quota", "/frame/kindle1.png"):
            return 404, {**headers, "Content-Type": "text/plain"}, b"Not found\n"
        data = read_snapshot(self.path)
        if path == "/api/quota":
            headers["Content-Type"] = "application/json"
            if data is None:
                return 503, headers, b'{"error":"quota_unavailable"}\n'
            return 200, headers, json.dumps(data, allow_nan=False).encode()
        # Re-evaluate STALE and passed-reset state even if the data file is unchanged.
        key = (json.dumps(data, sort_keys=True), int(now.timestamp()) // 60)
        if key != self.cache_key:
            self.cache_png = frame(data, now.replace(second=0, microsecond=0), self.tz, self.stale_seconds)
            self.cache_key = key
        headers["Content-Type"] = "image/png"
        headers["ETag"] = '"' + hashlib.sha256(self.cache_png).hexdigest() + '"'
        return 200, headers, self.cache_png


def handler(dashboard):
    class Handler(BaseHTTPRequestHandler):
        def handle(self):
            self.connection.settimeout(5)
            super().handle()

        def do_GET(self):
            try:
                status, headers, body = dashboard.respond(self.path)
            except Exception:
                status, headers, body = 500, {"Content-Type": "text/plain"}, b"Frame unavailable\n"
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            if urlsplit(self.path).path != "/api/device/kindle1":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1024:
                    raise ValueError()
                status = dashboard.receive_device_status(self.rfile.read(size))
            except (ValueError, TimeoutError):
                status = 400
            body = b'{"accepted":true}\n' if status == 200 else b'{"accepted":false}\n'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            # No request URLs, upstream fields, or credential-bearing query strings in logs.
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8486)
    parser.add_argument("--input", type=Path, default=Path(os.environ.get("QUOTA_FILE", "runtime/quota.json")))
    args = parser.parse_args()
    app = Dashboard(args.input, os.environ.get("QUOTA_SERVER_ID", "kqd-pw3"), os.environ.get("QUOTA_TIMEZONE", "Asia/Shanghai"))
    with HTTPServer((args.host, args.port), handler(app)) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
