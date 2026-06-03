#!/usr/bin/env python3
"""Build a NodeCue alpha release bundle zip."""

from __future__ import annotations

import argparse
from pathlib import Path
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "dist" / "nodecue-alpha-bundle.zip"

INCLUDE_DIRS = (
    "nodecue",
    "nodecue_agent",
    "docs",
    "scripts",
)

INCLUDE_FILES = (
    ".env.example",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "requirements-agent.txt",
)

SKIP_NAMES = {".DS_Store", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
SKIP_SUFFIXES = (".pyc", ".blend", ".blend1")


def should_skip(path: Path) -> bool:
    return any(part in SKIP_NAMES for part in path.parts) or path.name.endswith(SKIP_SUFFIXES)


def add_file(zf: zipfile.ZipFile, source: Path, root_name: str) -> None:
    rel = source.relative_to(REPO_ROOT)
    if should_skip(rel):
        return
    zf.write(source, Path(root_name) / rel)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--root-name", default="NodeCue")
    args = parser.parse_args()

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in INCLUDE_FILES:
            add_file(zf, REPO_ROOT / name, args.root_name)
        for dirname in INCLUDE_DIRS:
            for source in sorted((REPO_ROOT / dirname).rglob("*")):
                if source.is_file():
                    add_file(zf, source, args.root_name)

    print(f"Built release bundle: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
