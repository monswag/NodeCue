#!/usr/bin/env python3
"""Build a Blender-installable NodeCue add-on zip."""

from __future__ import annotations

import argparse
from pathlib import Path
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "dist" / "nodecue-blender-addon.zip"
ADDON_DIR = "nodecue"

PACKAGE_FILES = {
    ".env.example": f"{ADDON_DIR}/nodecue.env.example",
    "CHANGELOG.md": f"{ADDON_DIR}/CHANGELOG.md",
    "LICENSE": f"{ADDON_DIR}/LICENSE",
    "README.md": f"{ADDON_DIR}/README.md",
    "requirements-agent.txt": f"{ADDON_DIR}/requirements-agent.txt",
}

PACKAGE_DIRS = {
    "nodecue": ADDON_DIR,
    "nodecue_agent": f"{ADDON_DIR}/nodecue_agent",
    "docs": f"{ADDON_DIR}/docs",
}

SKIP_NAMES = {".DS_Store", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
SKIP_SUFFIXES = (".pyc", ".blend", ".blend1")


def should_skip(path: Path) -> bool:
    return any(part in SKIP_NAMES for part in path.parts) or path.name.endswith(SKIP_SUFFIXES)


def add_file(zf: zipfile.ZipFile, source: Path, dest: str | Path) -> None:
    dest_path = Path(dest)
    if should_skip(source.relative_to(REPO_ROOT)) or should_skip(dest_path):
        return
    zf.write(source, dest_path)


def add_tree(zf: zipfile.ZipFile, source_dir: Path, dest_dir: str | Path) -> None:
    for source in sorted(source_dir.rglob("*")):
        if source.is_file():
            add_file(zf, source, Path(dest_dir) / source.relative_to(source_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for source_name, dest_name in PACKAGE_FILES.items():
            add_file(zf, REPO_ROOT / source_name, dest_name)
        for source_name, dest_name in PACKAGE_DIRS.items():
            add_tree(zf, REPO_ROOT / source_name, dest_name)

    print(f"Built Blender add-on zip: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
