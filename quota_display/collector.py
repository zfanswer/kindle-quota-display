"""One-shot collection. Raw CLI stdout remains in bounded memory only."""
import argparse
import fcntl
import json
import os
import selectors
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from .model import PROVIDERS, SOURCES, PayloadError, failure, normalize, snapshot, timestamp, utcnow, validate_snapshot

MAX_BYTES = 1024 * 1024
# The scheduler is not exact: a run this close to a provider's interval counts as due.
INTERVAL_SLACK = 60


class CollectionError(Exception):
    pass


def run_cli(executable, provider, timeout):
    command = [executable, "usage", "--provider", provider, "--source", SOURCES[provider][0], "--format", "json", "--no-credits"]
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise CollectionError("cli_missing") from exc
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CollectionError("timeout")
                for key, _ in selector.select(min(remaining, 0.25)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        if len(output) > MAX_BYTES:
                            raise CollectionError("output_limit")
        try:
            code = proc.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise CollectionError("timeout") from exc
        if code:
            raise CollectionError("command_failed")
        try:
            return json.loads(output)
        except (ValueError, UnicodeError) as exc:
            raise CollectionError("invalid_payload") from exc
    finally:
        # Also reap descendants that may retain stdout or survive the parent.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        proc.stdout.close()


def read_snapshot(path):
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        return validate_snapshot(json.loads(path.read_text()))
    except (OSError, ValueError, TypeError, KeyError):
        return None


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".quota-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(validate_snapshot(data), f, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
            os.fchmod(f.fileno(), 0o644)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def due(old, attempt, interval):
    """Each Claude run launches the full Claude Code binary, so providers have their own cadence."""
    if not old or not interval or old["status"] != "ok":
        # A failed provider is retried on the next run instead of waiting out its interval.
        return True
    age = (attempt - timestamp(old["attempted_at"])).total_seconds()
    return age < 0 or age >= interval - INTERVAL_SLACK


def collect(previous, runner=run_cli, executable="codexbar", timeout=30, now=None, intervals=None):
    rows = {}
    for pid in PROVIDERS:
        attempt = now or utcnow()
        old = (previous or {}).get("providers", {}).get(pid)
        if not due(old, attempt, (intervals or {}).get(pid)):
            # Not attempted: the whole row, including attempted_at, stays as it was.
            rows[pid] = old
            continue
        try:
            raw = runner(executable, pid, timeout)
            rows[pid] = normalize(raw, pid, now or utcnow(), attempted_at=attempt)
        except CollectionError as exc:
            rows[pid] = failure(pid, str(exc), attempt, old)
        except (PayloadError, TypeError, KeyError, ValueError) as exc:
            code = "source_mismatch" if str(exc) == "source_mismatch" else "invalid_payload"
            rows[pid] = failure(pid, code, attempt, old)
    return snapshot(rows, now or utcnow())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("runtime/quota.json"))
    parser.add_argument("--cli", default=os.environ.get("CODEXBAR_BIN", "codexbar"))
    parser.add_argument("--config", type=Path, default=Path("config/providers.json"))
    parser.add_argument("--fixture-dir", type=Path, help="offline: never calls CodexBar")
    parser.add_argument("--fixture-now", help="fixed ISO timestamp; requires --fixture-dir")
    args = parser.parse_args()
    if args.fixture_now and not args.fixture_dir:
        parser.error("--fixture-now requires --fixture-dir")
    config = json.loads(args.config.read_text())
    if config.get("providers") != list(PROVIDERS) or config.get("sources") != {pid: SOURCES[pid][0] for pid in PROVIDERS}:
        parser.error("V1 requires codex + claude with explicit sources: codex oauth, claude cli")
    timeout = config["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 45:
        parser.error("timeout must be 1..45 seconds")
    intervals = config.get("interval_seconds")
    if not isinstance(intervals, dict) or set(intervals) != set(PROVIDERS) or any(
            isinstance(value, bool) or not isinstance(value, int) or not 60 <= value <= 86400 for value in intervals.values()):
        parser.error("interval_seconds must give 60..86400 for codex and claude")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with (args.output.parent / ".collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("collector already running")
            return 0
        runner = run_cli
        if args.fixture_dir:
            def runner(executable, pid, timeout):
                try:
                    return json.loads((args.fixture_dir / f"{pid}.json").read_text())
                except (OSError, ValueError) as exc:
                    raise CollectionError("invalid_payload") from exc
        previous = read_snapshot(args.output)
        # Fixtures always collect every provider; intervals apply to real runs only.
        data = collect(previous, runner, args.cli, timeout,
                       timestamp(args.fixture_now) if args.fixture_now else None,
                       None if args.fixture_dir else intervals)
        atomic_write(args.output, data)
        kept = {pid for pid, p in data["providers"].items() if previous and p is previous["providers"][pid]}
        print(" ".join(f"{pid}={p['status']}" + (":kept" if pid in kept else "") for pid, p in data["providers"].items()))
        return 0 if all(p["status"] == "ok" for p in data["providers"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
