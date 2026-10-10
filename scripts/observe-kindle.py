#!/usr/bin/env python3
"""Observe bounded device telemetry and preserve evidence; never sends device commands."""
import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def summarize(events, cycles, min_duration, since):
    """Evidence of received frames in one observed session, not physical sleep."""
    current = [event for event in events if datetime.fromisoformat(event["received_at"].replace("Z", "+00:00")) >= since]
    frames, resumes = [], []
    for event in current:
        if event["stage"] in ("bootstrap", "stopped"):
            frames, resumes = [], []
        if event["stage"] == "frame_ok" and event["cycles"] > 0:
            if frames and event["cycles"] <= frames[-1]["cycles"]:
                frames, resumes = [], []
            frames.append(event)
        if event["stage"] == "resumed":
            resumes.append(event)
    if current and current[-1]["stage"] in ("preflight_failed", "stopped"):
        return {"verdict": "device_stopped", "last_event": current[-1]}
    duration = 0
    if frames:
        first = datetime.fromisoformat(frames[0]["received_at"].replace("Z", "+00:00"))
        last = datetime.fromisoformat(frames[-1]["received_at"].replace("Z", "+00:00"))
        duration = (last - first).total_seconds()
    return {"verdict": "passed" if len(frames) >= cycles and duration >= min_duration else "observing",
            "evidence": "received_frames", "frames": len(frames), "last_cycle": frames[-1]["cycles"] if frames else 0,
            "resumes": len(resumes), "duration_seconds": duration}


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
    since = datetime.now(timezone.utc)
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
            summary = dict(summarize(events, args.cycles, args.min_duration, since), directory=str(out))
            if summary["verdict"] in ("passed", "device_stopped"):
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
