"""NodeCue SDK sidecar CLI for the Blender addon."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from nodecue_agent import (
    ProviderConfig,
    run_sdk_geometry_agent_on_socket,
)


def _load_env_file(path: str | Path) -> None:
    env_path = Path(path).expanduser()
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _provider_from_args(args: argparse.Namespace) -> ProviderConfig:
    if args.reasoning_effort:
        os.environ["NODECUE_AGENT_REASONING_EFFORT"] = args.reasoning_effort
    if args.max_tokens:
        os.environ["NODECUE_AGENT_MAX_TOKENS"] = str(args.max_tokens)
    return ProviderConfig(
        kind=args.provider,
        model=args.model or os.environ.get("NODECUE_AGENT_MODEL", ""),
        base_url=args.base_url or os.environ.get("NODECUE_AGENT_BASE_URL", ""),
        api_key_env=args.api_key_env or os.environ.get("NODECUE_AGENT_API_KEY_ENV", ""),
        timeout_seconds=args.timeout_seconds,
    )


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.env_file:
        _load_env_file(args.env_file)
    provider = _provider_from_args(args)
    result = await run_sdk_geometry_agent_on_socket(
        prompt=args.prompt,
        mode=args.mode,
        skill_path=args.skill_path,
        provider=provider,
        host=args.host,
        port=args.port,
        max_turns=args.max_turns,
    )
    return {
        "channel": "nodecue-plugin-sdk",
        "provider": {
            "kind": provider.kind,
            "model": provider.model,
            "base_url": provider.resolved_base_url(),
        },
        "mode": args.mode,
        "prompt": args.prompt,
        "stage": "completed" if not result.get("error") else "sdk_agent_failure",
        "error": result.get("error") or "",
        "final_output": result.get("final_output") or "",
        "sdk_result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--mode", choices=("generate", "explain", "modify"), default="generate")
    parser.add_argument("--skill-path", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9877)
    parser.add_argument("--provider", default=os.environ.get("NODECUE_AGENT_PROVIDER", "openrouter"))
    parser.add_argument("--model", default=os.environ.get("NODECUE_AGENT_MODEL", ""))
    parser.add_argument("--base-url", default=os.environ.get("NODECUE_AGENT_BASE_URL", ""))
    parser.add_argument("--api-key-env", default=os.environ.get("NODECUE_AGENT_API_KEY_ENV", ""))
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=int(os.environ.get("NODECUE_AGENT_TIMEOUT_SECONDS", "240")),
    )
    parser.add_argument("--max-turns", type=int, default=35)
    parser.add_argument(
        "--reasoning-effort",
        choices=("none", "minimal", "low", "medium", "high"),
        default=os.environ.get("NODECUE_AGENT_REASONING_EFFORT", "none"),
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(os.environ.get("NODECUE_AGENT_MAX_TOKENS", "4096")),
    )
    parser.add_argument("--env-file", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = asyncio.run(_run(args))
    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
