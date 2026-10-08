#!/usr/bin/env python3
"""Copy only the prepared project app and its launchers, with backup and hash verification."""
import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def is_mounted_kindle(info, mount):
    # macOS diskutil's plist provides MountPoint but may omit the text UI's Mounted field.
    return info.get("VolumeName") == "Kindle" and info.get("MountPoint") == str(mount.resolve()) and mount.is_dir() and not mount.is_symlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--mount", type=Path, default=Path("/Volumes/Kindle"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    if not bundle.is_relative_to(ROOT / "build"):
        parser.error("bundle must be under this project's build directory")
    info = plistlib.loads(subprocess.check_output(["diskutil", "info", "-plist", str(args.mount)]))
    if not is_mounted_kindle(info, args.mount):
        parser.error("target must be the mounted Kindle volume")
    manifest = json.loads((bundle / "manifest.json").read_text())
    for name, digest in manifest.items():
        path = bundle / name
        if not path.resolve().is_relative_to(bundle) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            parser.error("bundle manifest mismatch")
    if not args.apply:
        print("Verified bundle and Kindle mount; use --apply to install")
        return
    app = args.mount / "eink-dashboard"
    if app.is_symlink() or (args.mount / "documents").is_symlink():
        parser.error("refusing symbolic link destination")
    backup = ROOT / "runtime/backups/kindle-before-install"
    backup.mkdir(parents=True, exist_ok=True)
    if app.exists():
        if not (app / "quota-dashboard.sh").is_file():
            parser.error("existing directory is not this project")
        shutil.copytree(app, backup / "eink-dashboard", dirs_exist_ok=True)
    for script in (bundle / "documents").glob("*.sh"):
        target = args.mount / "documents" / script.name
        if target.is_symlink():
            parser.error("refusing symbolic link launcher")
        if target.exists():
            shutil.copyfile(target, backup / script.name)
    shutil.copytree(bundle / "eink-dashboard", app, dirs_exist_ok=True)
    for script in (bundle / "documents").glob("*.sh"):
        shutil.copyfile(script, args.mount / "documents" / script.name)
    for name, digest in manifest.items():
        path = args.mount / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
    print("Installed and verified", len(manifest), "project files on", args.mount)


if __name__ == "__main__":
    main()
