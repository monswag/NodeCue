"""Sidecar dependency management without a user-managed virtualenv.

The sidecar needs a few third-party packages (openai, openai-agents,
pydantic). Instead of asking users to create a virtualenv in a terminal,
NodeCue installs them with the configured sidecar Python (Blender's
bundled interpreter by default) into a NodeCue-owned directory that is
added to the sidecar's PYTHONPATH. This module is bpy-free so the logic
stays testable outside Blender.
"""

from __future__ import annotations

import os
from pathlib import Path

# Top-level import names provided by the runtime requirements.
REQUIRED_IMPORTS = ("agents", "openai", "pydantic")

# Runs in the sidecar Python: bootstraps pip if the interpreter ships
# without it, then installs the runtime requirements into the target
# directory. argv: [target_dir, requirements_file]
_PIP_DRIVER = """\
import subprocess, sys
target, requirements = sys.argv[1], sys.argv[2]
probe = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True)
if probe.returncode != 0:
    subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], check=True)
subprocess.run(
    [
        sys.executable, "-m", "pip", "install",
        "--disable-pip-version-check", "--upgrade",
        "--target", target, "-r", requirements,
    ],
    check=True,
)
"""


def requirements_path() -> Path:
    return Path(__file__).resolve().parent / "requirements-agent.txt"


def deps_dir(user_scripts_dir: str | Path | None = None) -> Path:
    env_dir = os.environ.get("NODECUE_AGENT_DEPS_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()
    if user_scripts_dir:
        return Path(user_scripts_dir).expanduser() / "nodecue-deps"
    return Path.home() / ".nodecue" / "deps"


def deps_installed(target: str | Path) -> bool:
    root = Path(target).expanduser()
    return all((root / name).is_dir() for name in REQUIRED_IMPORTS)


def pip_install_command(
    python: str | Path,
    target: str | Path,
    requirements: str | Path | None = None,
) -> list[str]:
    req = Path(requirements).expanduser() if requirements else requirements_path()
    return [str(python), "-c", _PIP_DRIVER, str(Path(target).expanduser()), str(req)]
