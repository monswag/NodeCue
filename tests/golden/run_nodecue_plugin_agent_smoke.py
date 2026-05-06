"""Run the real NodeCue Blender addon agent path.

This launches Blender, enables the addon, invokes the UI operator, waits for
the SDK sidecar to finish, and emits the plugin report plus saved .blend path.

Opt in with:
    NODECUE_RUN_PLUGIN_AGENT_EVAL=1 conda run -n blender python tests/golden/run_nodecue_plugin_agent_smoke.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.golden.run_nodecue_scene_eval import (  # noqa: E402
    DEFAULT_SKILL_PATH,
    detect_scene_quality,
    load_scenarios,
)


DEFAULT_ARTIFACT_ROOT = ROOT / "tests" / "integration" / "debug_blends" / "nodecue_plugin_runs"


def _select_scenario(scenario_id: str) -> dict[str, Any]:
    for scenario in load_scenarios():
        if scenario.get("id") == scenario_id:
            return scenario
    raise SystemExit(f"scenario id not found: {scenario_id}")


def _blender_script(args: argparse.Namespace, output_path: Path, prompt: str, mode: str) -> str:
    return textwrap.dedent(
        f"""
        from __future__ import annotations
        import json
        import os
        import sys
        from pathlib import Path

        ROOT = Path({str(ROOT)!r})
        sys.path.insert(0, str(ROOT))
        for name in list(sys.modules):
            if name == "nodecue" or name.startswith("nodecue.") or name == "nodecue_agent" or name.startswith("nodecue_agent."):
                sys.modules.pop(name, None)

        import bpy

        bpy.ops.preferences.addon_enable(module="nodecue")
        prefs = bpy.context.preferences.addons["nodecue"].preferences
        prefs.agent_provider = {args.provider!r}
        prefs.agent_model = {args.model!r}
        prefs.agent_base_url = {args.base_url!r}
        prefs.agent_api_key_env = {args.api_key_env!r}
        prefs.agent_python = {args.agent_python!r}
        prefs.agent_sidecar_root = str(ROOT)
        prefs.agent_env_file = {str(args.env_file)!r}
        prefs.agent_timeout_seconds = {args.timeout_seconds}
        prefs.agent_max_turns = {args.max_turns}
        prefs.agent_reasoning_effort = {args.reasoning_effort!r}
        prefs.agent_max_tokens = {args.max_tokens}
        prefs.agent_artifact_root = {str(args.artifact_root)!r}
        prefs.agent_save_blend_copy = True
        prefs.skill_path = {str(args.skill_path)!r}

        if {args.setup_active_tree!r}:
            from nodecue.bpy_recipes import execute_action
            setup_actions = [
                {{"type": "create_node_tree", "parameters": {{"name": "NodeCueFixtureTerrain"}}}},
                {{"type": "create_node", "parameters": {{"tree_name": "NodeCueFixtureTerrain", "bl_idname": "GeometryNodeMeshGrid", "name": "Grid", "location_x": -500, "location_y": 0}}}},
                {{"type": "create_node", "parameters": {{"tree_name": "NodeCueFixtureTerrain", "bl_idname": "GeometryNodeSetPosition", "name": "SetPosition", "location_x": 0, "location_y": 0}}}},
                {{"type": "create_node", "parameters": {{"tree_name": "NodeCueFixtureTerrain", "bl_idname": "ShaderNodeTexNoise", "name": "Noise", "location_x": -300, "location_y": 150}}}},
                {{"type": "create_node", "parameters": {{"tree_name": "NodeCueFixtureTerrain", "bl_idname": "ShaderNodeCombineXYZ", "name": "CombineZ", "location_x": -100, "location_y": 150}}}},
                {{"type": "create_node", "parameters": {{"tree_name": "NodeCueFixtureTerrain", "bl_idname": "GeometryNodeInputPosition", "name": "Position", "location_x": -500, "location_y": 150}}}},
                {{"type": "connect", "parameters": {{"tree_name": "NodeCueFixtureTerrain", "from_node": "Grid", "from_socket": "Mesh", "to_node": "SetPosition", "to_socket": "Geometry"}}}},
                {{"type": "connect", "parameters": {{"tree_name": "NodeCueFixtureTerrain", "from_node": "SetPosition", "from_socket": "Geometry", "to_node": "Group Output", "to_socket": "Geometry"}}}},
                {{"type": "connect", "parameters": {{"tree_name": "NodeCueFixtureTerrain", "from_node": "Position", "from_socket": "Position", "to_node": "Noise", "to_socket": "Vector"}}}},
                {{"type": "connect", "parameters": {{"tree_name": "NodeCueFixtureTerrain", "from_node": "Noise", "from_socket": "Fac", "to_node": "CombineZ", "to_socket": "Z"}}}},
                {{"type": "connect", "parameters": {{"tree_name": "NodeCueFixtureTerrain", "from_node": "CombineZ", "from_socket": "Vector", "to_node": "SetPosition", "to_socket": "Offset"}}}},
                {{"type": "add_frame", "parameters": {{"tree_name": "NodeCueFixtureTerrain", "node_names": ["Noise", "CombineZ", "Position"], "label": "Noise height control"}}}},
                {{"type": "arrange_nodes", "parameters": {{"tree_name": "NodeCueFixtureTerrain"}}}},
            ]
            for action in setup_actions:
                execute_action(action)

        props = bpy.context.scene.gn_ai_props
        props.mode = {mode!r}
        props.prompt = {prompt!r}

        started = bpy.ops.gn_ai.run_agent_prototype()
        deadline = __import__("time").time() + {args.timeout_seconds + 60}

        def finish(payload):
            Path({str(output_path)!r}).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            bpy.ops.wm.quit_blender()
            return None

        def poll():
            import time
            status = props.status
            done = any(
                marker in status.lower()
                for marker in ("finished", "failed", "canceled", "configuration failed")
            )
            if done or time.time() > deadline:
                report = {{}}
                report_path = props.agent_report_path
                if report_path and Path(report_path).exists():
                    try:
                        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
                    except Exception as exc:
                        report = {{"report_read_error": str(exc)}}
                return finish(
                    {{
                        "operator_result": list(started),
                        "status": status,
                        "agent_output": props.agent_output,
                        "report_path": report_path,
                        "blend_path": props.agent_blend_path,
                        "timed_out": time.time() > deadline,
                        "report": report,
                    }}
                )
            return 1.0

        bpy.app.timers.register(poll, first_interval=1.0)
        """
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    if os.environ.get("NODECUE_RUN_PLUGIN_AGENT_EVAL") != "1":
        raise SystemExit("set NODECUE_RUN_PLUGIN_AGENT_EVAL=1 to run plugin agent smoke")

    scenario = _select_scenario(args.scenario_id)
    prompt = args.prompt or scenario["prompt"]
    mode = args.mode or scenario.get("mode", "generate")

    with tempfile.TemporaryDirectory(prefix="nodecue-plugin-smoke-") as tmp:
        tmp_path = Path(tmp)
        output_path = tmp_path / "output.json"
        script_path = tmp_path / "run_plugin.py"
        script_path.write_text(
            _blender_script(args, output_path, prompt, mode),
            encoding="utf-8",
        )
        proc = subprocess.run(
            args.blender_command + ["--factory-startup", "--python", str(script_path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=args.timeout_seconds + 120,
        )
        payload: dict[str, Any]
        if output_path.exists():
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        else:
            payload = {
                "status": "runner_failed",
                "report": {},
                "report_path": "",
                "blend_path": "",
            }
        payload["returncode"] = proc.returncode
        payload["stdout_tail"] = proc.stdout[-4000:]
        payload["stderr_tail"] = proc.stderr[-4000:]
        payload["scenario"] = {
            "id": scenario["id"],
            "mode": mode,
            "prompt": prompt,
            "reference": scenario.get("reference"),
        }
        report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
        sdk_result = report.get("sdk_result") if isinstance(report.get("sdk_result"), dict) else {}
        readback = sdk_result.get("readback") if isinstance(sdk_result.get("readback"), dict) else None
        payload["detector"] = detect_scene_quality(
            scenario,
            readback,
            final_explanation=str(report.get("final_output") or ""),
            execution_error=str(report.get("error") or "") or None,
        )
        return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--scenario-id", default="terrain_noise_displacement")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--mode", choices=("generate", "explain", "modify"))
    parser.add_argument("--skill-path", type=Path, default=DEFAULT_SKILL_PATH)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--provider", default=os.environ.get("NODECUE_AGENT_PROVIDER", "openrouter"))
    parser.add_argument("--model", default=os.environ.get("NODECUE_AGENT_MODEL", ""))
    parser.add_argument("--base-url", default=os.environ.get("NODECUE_AGENT_BASE_URL", ""))
    parser.add_argument("--api-key-env", default=os.environ.get("NODECUE_AGENT_API_KEY_ENV", ""))
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT / ".env",
    )
    parser.add_argument(
        "--agent-python",
        default="/Users/sj/miniconda3/envs/blender/bin/python",
    )
    parser.add_argument(
        "--blender-command",
        nargs="+",
        default=["conda", "run", "-n", "blender", "blender"],
    )
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--max-turns", type=int, default=35)
    parser.add_argument(
        "--setup-active-tree",
        action="store_true",
        help="Create a verified Geometry Nodes fixture before running explain/modify.",
    )
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
    args = parser.parse_args()

    payload = run(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("=== NodeCue plugin agent smoke ===")
        print(f"Status: {payload.get('status')}")
        print(f"Detector: {payload.get('detector', {}).get('status')}")
        print(f"Report: {payload.get('report_path')}")
        print(f"Blend: {payload.get('blend_path')}")
    report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    return 0 if (
        payload.get("returncode") == 0
        and report.get("stage") == "completed"
        and payload.get("detector", {}).get("status") != "ERROR"
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
