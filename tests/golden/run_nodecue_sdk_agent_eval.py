"""Run NodeCue's real OpenAI Agents SDK geometry-node eval.

This runner uses a real model, real SDK function tools, headless Blender
execution, and writes a .blend artifact for manual review.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nodecue_agent import ProviderConfig, run_sdk_geometry_agent  # noqa: E402
from tests.golden.run_nodecue_scene_eval import (  # noqa: E402
    DEFAULT_SKILL_PATH,
    detect_scene_quality,
    load_scenarios,
)


DEFAULT_ARTIFACT_ROOT = ROOT / "tests" / "integration" / "debug_blends" / "nodecue_sdk_eval"


def _select_scenario(scenario_id: str) -> dict[str, Any]:
    for scenario in load_scenarios():
        if scenario.get("id") == scenario_id:
            return scenario
    raise SystemExit(f"scenario id not found: {scenario_id}")


def _provider_from_args(args: argparse.Namespace) -> ProviderConfig:
    return ProviderConfig(
        kind=args.provider,
        model=args.model or os.environ.get("NODECUE_AGENT_MODEL", ""),
        base_url=args.base_url or os.environ.get("NODECUE_AGENT_BASE_URL", ""),
        api_key_env=args.api_key_env or os.environ.get("NODECUE_AGENT_API_KEY_ENV", ""),
        timeout_seconds=args.timeout_seconds,
    )


def _artifact_dir(root: Path, scenario_id: str, model: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_model = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in model)
    path = root / stamp / scenario_id / safe_model
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if os.environ.get("NODECUE_RUN_SCENE_EVAL") != "1":
        raise SystemExit("set NODECUE_RUN_SCENE_EVAL=1 to run SDK scene eval")

    scenario = _select_scenario(args.scenario_id)
    provider = _provider_from_args(args)
    artifact_dir = _artifact_dir(args.artifact_root, args.scenario_id, provider.model)
    blend_path = artifact_dir / f"{args.scenario_id}.blend"

    stage = "completed"
    error = None
    sdk_result: dict[str, Any] = {}
    readback = None
    final_output = ""
    try:
        sdk_result = await run_sdk_geometry_agent(
            prompt=scenario["prompt"],
            mode=scenario.get("mode", "generate"),
            skill_path=args.skill_path,
            provider=provider,
            blend_path=blend_path,
            max_turns=args.max_turns,
        )
        if sdk_result.get("error"):
            stage = "sdk_agent_failure"
            error = str(sdk_result["error"])
        readback = sdk_result.get("readback")
        final_output = str(sdk_result.get("final_output") or "")
    except Exception as exc:
        stage = "sdk_agent_failure"
        error = str(exc)

    detector = detect_scene_quality(
        scenario,
        readback if isinstance(readback, dict) else None,
        final_explanation=final_output,
        execution_error=error if not isinstance(readback, dict) else None,
    )
    if error and "429" in error:
        detector["failure_categories"] = ["provider_rate_limit"]
    elif error and detector["status"] == "ERROR":
        detector["failure_categories"] = ["sdk_agent_failure"]
    elif error:
        detector["failure_categories"] = list(
            dict.fromkeys([*detector.get("failure_categories", []), "sdk_agent_incomplete"])
        )

    report = {
        "channel": "nodecue-sdk-internal",
        "stage": stage,
        "error": error,
        "provider": {
            "kind": provider.kind,
            "model": provider.model,
            "base_url": provider.resolved_base_url(),
        },
        "scenario": {
            "id": scenario["id"],
            "prompt": scenario["prompt"],
            "mode": scenario.get("mode"),
            "reference": scenario.get("reference"),
            "manual_review_fields": scenario.get("manual_review_fields") or [],
        },
        "detector": detector,
        "blend_path": str(blend_path) if blend_path.exists() else "",
        "report_path": str(artifact_dir / "report.json"),
        "final_output": final_output,
        "sdk_result": sdk_result,
    }
    (artifact_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--scenario-id", default="terrain_noise_displacement")
    parser.add_argument("--skill-path", type=Path, default=DEFAULT_SKILL_PATH)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument(
        "--provider",
        choices=("openrouter", "openai-compatible", "openai"),
        default=os.environ.get("NODECUE_AGENT_PROVIDER", "openrouter"),
    )
    parser.add_argument("--model", default=os.environ.get("NODECUE_AGENT_MODEL", ""))
    parser.add_argument("--base-url", default=os.environ.get("NODECUE_AGENT_BASE_URL", ""))
    parser.add_argument("--api-key-env", default=os.environ.get("NODECUE_AGENT_API_KEY_ENV", ""))
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=int(os.environ.get("NODECUE_AGENT_TIMEOUT_SECONDS", "120")),
    )
    parser.add_argument("--max-turns", type=int, default=20)
    args = parser.parse_args()

    report = asyncio.run(_run(args))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=== NodeCue SDK scene eval ===")
        print(f"Provider: {report['provider']['kind']} / {report['provider']['model']}")
        print(f"Scenario: {report['scenario']['id']}")
        print(f"Detector: {report['detector']['status']}")
        print(f"Blend: {report['blend_path']}")
        if report["error"]:
            print(f"Error: {report['error']}")
    return 0 if report["detector"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
