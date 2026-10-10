#!/usr/bin/env python3
"""Copy only the prepared project app and its launchers, with backup and hash verification."""
import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_FILES = {f"eink-dashboard/{name}" for name in
             ("common.sh", "find-server.sh", "quota-dashboard.sh", "bootstrap.sh", "bootstrap-frame.png", "server.conf")}
LAUNCHERS = {f"documents/{name}" for name in
             ("AI Quota Dashboard.sh", "Refresh AI Quota.sh", "Stop AI Quota Dashboard.sh",
              "Find Quota Server.sh", "Recover Agent Quota.sh")}


def verified_manifest(bundle):
    bundle = bundle.resolve()
    manifest = json.loads((bundle / "manifest.json").read_text())
    if not isinstance(manifest, dict) or set(manifest) != APP_FILES | LAUNCHERS:
        raise ValueError("unexpected bundle file list")
    for name, digest in manifest.items():
        path = bundle / name
        if path.is_symlink() or not path.resolve().is_relative_to(bundle) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("bundle manifest mismatch")
    return manifest


def install(bundle, mount, backup, *, update=False):
    bundle = bundle.resolve()
    manifest = verified_manifest(bundle)
    app = mount / "eink-dashboard"
    if app.is_symlink() or (mount / "documents").is_symlink():
        raise ValueError("refusing symbolic link destination")
    if app.exists() and not (app / "quota-dashboard.sh").is_file():
        raise ValueError("existing directory is not this project")
    if update and not (app / "server.conf").is_file():
        raise ValueError("update requires an existing project config")
    if app.exists() and not update:
        raise ValueError("existing project: use --update to preserve its configuration")
    selected = {name: digest for name, digest in manifest.items()
                if not update or name not in {"eink-dashboard/server.conf", "documents/Recover Agent Quota.sh"}}
    # Validate every destination before writing; never follow a file symlink.
    for name in selected:
        if (mount / name).is_symlink():
            raise ValueError("refusing symbolic link project file")
    preserved = {}
    for name in ("server.conf", "server.cache"):
        path = app / name
        if path.is_symlink():
            raise ValueError("refusing symbolic link config/cache")
        if update and path.is_file():
            preserved[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    backup.mkdir(parents=True, exist_ok=False)
    for name in selected:
        target = mount / name
        if target.exists():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target, saved)
    # Stage each file on the same volume, fsync, then replace atomically. Stop the
    # running dashboard before USB update; this is not a whole-bundle transaction.
    for name in selected:
        target = mount / name
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, staged = tempfile.mkstemp(prefix=".kqd-update-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write((bundle / name).read_bytes())
                output.flush()
                os.fsync(output.fileno())
            os.chmod(staged, 0o755 if name.endswith(".sh") else 0o644)
            os.replace(staged, target)
        finally:
            Path(staged).unlink(missing_ok=True)
    for name, digest in selected.items():
        if hashlib.sha256((mount / name).read_bytes()).hexdigest() != digest:
            raise ValueError("installed hash mismatch")
    for name, digest in preserved.items():
        if hashlib.sha256((app / name).read_bytes()).hexdigest() != digest:
            raise ValueError("preserved config/cache changed")
    report = {"mode": "update" if update else "install", "files": selected,
              "preserved_hashes": preserved, "backup": str(backup)}
    (backup / "installation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def is_mounted_kindle(info, mount):
    # macOS diskutil's plist provides MountPoint but may omit the text UI's Mounted field.
    return info.get("VolumeName") == "Kindle" and info.get("MountPoint") == str(mount.resolve()) and mount.is_dir() and not mount.is_symlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--mount", type=Path, default=Path("/Volumes/Kindle"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--update", action="store_true", help="preserve device config/cache; skip temporary recovery launcher")
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    if not bundle.is_relative_to(ROOT / "build"):
        parser.error("bundle must be under this project's build directory")
    info = plistlib.loads(subprocess.check_output(["diskutil", "info", "-plist", str(args.mount)]))
    if not is_mounted_kindle(info, args.mount):
        parser.error("target must be the mounted Kindle volume")
    try:
        verified_manifest(bundle)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if not args.apply:
        print("Verified bundle and Kindle mount; use --apply to install")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup = ROOT / "runtime/backups" / f"kindle-{stamp}"
    try:
        report = install(bundle, args.mount, backup, update=args.update)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print("Installed and verified", len(report["files"]), "project files on", args.mount)


if __name__ == "__main__":
    main()
