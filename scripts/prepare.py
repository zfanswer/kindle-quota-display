#!/usr/bin/env python3
"""Generate reviewable deployment artifacts only. Never installs or starts anything."""
import argparse
import hashlib
import ipaddress
import json
import plistlib
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def launchd(python, cli, output):
    for path in (python, cli):
        if not path.is_absolute() or not path.is_file():
            raise ValueError("python and cli must be existing absolute files")
    runtime = ROOT / "runtime"
    payload = {
        "Label": "com.eink-quota.collector",
        "ProgramArguments": [str(python), "-m", "quota_display.collector", "--cli", str(cli),
                             "--output", str(runtime / "quota.json"), "--config", str(ROOT / "config/providers.json")],
        "WorkingDirectory": str(ROOT), "StartInterval": 180, "RunAtLoad": True,
        "ProcessType": "Background", "LowPriorityIO": True,
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        "StandardOutPath": str(runtime / "collector.log"),
        "StandardErrorPath": str(runtime / "collector.error.log"),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(plistlib.dumps(payload))


def bundle(server, host, server_id, output):
    if server:
        ipaddress.IPv4Address(server)
    if host and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,252}", host):
        raise ValueError("invalid hostname")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", server_id):
        raise ValueError("invalid server id")
    if output.exists():
        raise ValueError("bundle output already exists; choose a fresh directory")
    app = output / "eink-dashboard"
    app.mkdir(parents=True)
    for name in ("common.sh", "find-server.sh", "quota-dashboard.sh", "bootstrap.sh"):
        shutil.copyfile(ROOT / "kindle" / name, app / name)
        (app / name).chmod(0o755)
    shutil.copyfile(ROOT / "kindle/assets/bootstrap-frame.png", app / "bootstrap-frame.png")
    config = (ROOT / "kindle/server.conf.example").read_text()
    config = config.replace("SERVER_IP=\n", f"SERVER_IP={server}\n").replace("SERVER_HOST=MacBook.local", f"SERVER_HOST={host}")
    config = config.replace("SERVER_ID=kqd-pw3", f"SERVER_ID={server_id}")
    (app / "server.conf").write_text(config)
    shutil.copytree(ROOT / "kindle/documents", output / "documents")
    for script in (output / "documents").glob("*.sh"):
        script.chmod(0o755)
    manifest = {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in output.rglob("*") if p.is_file()}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    launch = commands.add_parser("launchd")
    launch.add_argument("--python", type=Path, required=True)
    launch.add_argument("--cli", type=Path, required=True)
    launch.add_argument("--output", type=Path, default=ROOT / "build/com.eink-quota.collector.plist")
    kindle = commands.add_parser("kindle")
    kindle.add_argument("--server", default="")
    kindle.add_argument("--host", default="MacBook.local")
    kindle.add_argument("--server-id", default="kqd-pw3")
    kindle.add_argument("--output", type=Path, default=ROOT / "build/kindle")
    args = parser.parse_args()
    output = args.output.resolve()
    # Even explicit arguments may only generate local project artifacts, never write a USB mount or LaunchAgents.
    if not output.is_relative_to(ROOT) or output == ROOT:
        parser.error("output must be a child of the project directory")
    try:
        if args.command == "launchd":
            launchd(args.python, args.cli, output)
        else:
            bundle(args.server, args.host, args.server_id, output)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Prepared only: {output}")


if __name__ == "__main__":
    main()
