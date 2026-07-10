#!/usr/bin/env python3
"""Copy NodeCue into a local Blender add-ons directory."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COPY_DIRS = ("nodecue", "nodecue_agent")


def default_addons_dir(version: str) -> Path:
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return home / "Library" / "Application Support" / "Blender" / version / "scripts" / "addons"
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Blender Foundation" / "Blender" / version / "scripts" / "addons"
    return home / ".config" / "blender" / version / "scripts" / "addons"


def copy_dir(src: Path, dest: Path, force: bool) -> None:
    if dest.exists():
        if not force:
            raise FileExistsError(f"{dest} already exists. Re-run with --force to replace it.")
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender-version", default="5.1")
    parser.add_argument("--addons-dir", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    addons_dir = Path(args.addons_dir).expanduser() if args.addons_dir else default_addons_dir(args.blender_version)
    addons_dir.mkdir(parents=True, exist_ok=True)

    for name in COPY_DIRS:
        copy_dir(REPO_ROOT / name, addons_dir / name, args.force)

    env_example = REPO_ROOT / ".env.example"
    if env_example.exists():
        shutil.copy2(env_example, addons_dir / "nodecue.env.example")

    print(f"Installed NodeCue add-on files to: {addons_dir}")
    print(f"Sidecar root in Blender preferences should be: {addons_dir}")
    print(f"Copy {addons_dir / 'nodecue.env.example'} to {addons_dir / '.env'} and add your provider key.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
