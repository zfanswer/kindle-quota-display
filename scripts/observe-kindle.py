#!/usr/bin/env python3
"""Observe bounded device telemetry and preserve evidence; never sends device commands."""
import argparse
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8486")
    parser.add_argument("--minutes", type=float, default=70)
    parser.add_argument("--cycles", type=int, default=20)
    parser.add_argument("--min-duration", type=int, default=3600)
    args = parser.parse_args()
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S")
    out = ROOT / "runtime/observations" / stamp
    out.mkdir(parents=True)
    events, seen = [], set()
    end = time.monotonic() + args.minutes * 60
    summary = {"verdict": "waiting", "directory": str(out)}
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(args.url + "/api/device/kindle1/history", timeout=5) as response:
                latest = json.load(response)
            for event in latest:
                key = (event["received_at"], event["stage"], event["cycles"])
                if key not in seen:
                    seen.add(key)
                    events.append(event)
                    print(json.dumps(event), flush=True)
            (out / "events.json").write_text(json.dumps(events, indent=2) + "\n")
            frames = [event for event in events if event["stage"] == "frame_ok" and event["cycles"] > 0]
            resumes = [event for event in events if event["stage"] == "resumed" and event["reason"] == "none"]
            if events and events[-1]["stage"] in ("preflight_failed", "stopped") and events[-1]["reason"] != "none":
                summary = {"verdict": "device_stopped", "last_event": events[-1], "directory": str(out)}
                break
            if frames:
                first = datetime.fromisoformat(frames[0]["received_at"].replace("Z", "+00:00"))
                last = datetime.fromisoformat(frames[-1]["received_at"].replace("Z", "+00:00"))
                duration = (last - first).total_seconds()
                summary = {"verdict": "observing", "frames": len(frames), "last_cycle": frames[-1]["cycles"],
                           "resumes": len(resumes), "duration_seconds": duration, "directory": str(out)}
                if frames[-1]["cycles"] >= args.cycles and duration >= args.min_duration and resumes:
                    summary["verdict"] = "passed"
                    break
            (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        except (OSError, ValueError, KeyError) as exc:
            print(json.dumps({"observer": "temporary_unavailable", "type": type(exc).__name__}), flush=True)
        time.sleep(5)
    else:
        summary["verdict"] = "timeout"
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    return 0 if summary["verdict"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
