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

from .model import PROVIDERS, PayloadError, failure, normalize, snapshot, timestamp, utcnow, validate_snapshot

MAX_BYTES = 1024 * 1024


class CollectionError(Exception):
    pass


def run_cli(executable, provider, timeout):
    command = [executable, "usage", "--provider", provider, "--source", "oauth", "--format", "json", "--no-credits"]
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


def collect(previous, runner=run_cli, executable="codexbar", timeout=30, now=None):
    rows = {}
    for pid in PROVIDERS:
        attempt = now or utcnow()
        try:
            raw = runner(executable, pid, timeout)
            rows[pid] = normalize(raw, pid, now or utcnow(), attempted_at=attempt)
        except CollectionError as exc:
            rows[pid] = failure(pid, str(exc), attempt, (previous or {}).get("providers", {}).get(pid))
        except (PayloadError, TypeError, KeyError, ValueError) as exc:
            code = "source_mismatch" if str(exc) == "source_mismatch" else "invalid_payload"
            rows[pid] = failure(pid, code, attempt, (previous or {}).get("providers", {}).get(pid))
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
    if config.get("providers") != list(PROVIDERS) or config.get("source") != "oauth":
        parser.error("V1 requires codex + claude, explicit oauth")
    timeout = config["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 45:
        parser.error("timeout must be 1..45 seconds")
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
        data = collect(read_snapshot(args.output), runner, args.cli, timeout,
                       timestamp(args.fixture_now) if args.fixture_now else None)
        atomic_write(args.output, data)
        print(" ".join(f"{pid}={p['status']}" for pid, p in data["providers"].items()))
        return 0 if all(p["status"] == "ok" for p in data["providers"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
