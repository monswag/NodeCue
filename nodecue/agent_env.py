"""Sidecar environment composition, bpy-free so the contract stays testable.

API key priority, highest first:
1. the real OS environment (explicit per-session choice)
2. the API Key field in the addon preferences (the visible UI)
3. the optional Env File (background fallback for file-based setups)

The key must only travel via environment variables — never on the sidecar
command line (visible in `ps`) and never into reports or logs.
"""

from __future__ import annotations

from pathlib import Path


def load_env_values(path: str) -> dict[str, str]:
    env_path = Path(path).expanduser()
    if not path or not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip().strip('"').strip("'")
    return values


def compose_sidecar_env(
    base_env: dict[str, str],
    file_values: dict[str, str],
    *,
    api_key_env: str = "",
    prefs_api_key: str = "",
) -> dict[str, str]:
    env = dict(base_env)
    if api_key_env and prefs_api_key.strip():
        env.setdefault(api_key_env, prefs_api_key.strip())
    for key, value in file_values.items():
        env.setdefault(key, value)
    return env


def resolved_api_key(
    base_env: dict[str, str],
    file_values: dict[str, str],
    *,
    api_key_env: str,
    prefs_api_key: str = "",
) -> tuple[str, str]:
    """Return (key, source) following the priority contract; source is
    'environment', 'preferences', 'env-file', or ''."""
    if base_env.get(api_key_env, "").strip():
        return base_env[api_key_env].strip(), "environment"
    if prefs_api_key.strip():
        return prefs_api_key.strip(), "preferences"
    if file_values.get(api_key_env, "").strip():
        return file_values[api_key_env].strip(), "env-file"
    return "", ""
