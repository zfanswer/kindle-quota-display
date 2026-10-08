#!/usr/bin/env python3
"""Reproduce every synthetic preview without any service or device access."""
import copy
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quota_display.collector import CollectionError, collect, read_snapshot
from quota_display.model import timestamp
from quota_display.render import frame


def main():
    data = read_snapshot(ROOT / "build/preview/quota.json")
    if data is None:
        raise SystemExit("Generate build/preview/quota.json with offline fixtures first")
    now = timestamp("2026-10-07T12:00:00Z")
    output = ROOT / "docs/assets"
    output.mkdir(parents=True, exist_ok=True)
    (output / "preview.png").write_bytes(frame(data, now))
    (output / "stale.png").write_bytes(frame(data, now + timedelta(hours=14)))
    (output / "unavailable.png").write_bytes(frame(None, now))

    def fail(*args):
        raise CollectionError("timeout")

    later = now + timedelta(minutes=3)
    (output / "cached-error.png").write_bytes(frame(collect(data, fail, now=later), later))
    third = copy.deepcopy(data)
    third["providers"]["claude"]["windows"].append({"id": "tertiary", "used_percent": 88,
        "remaining_percent": 12, "window_minutes": None, "reset_at": None})
    (output / "third-window.png").write_bytes(frame(third, now))
    print("Generated 5 synthetic Chinese previews")


if __name__ == "__main__":
    main()
