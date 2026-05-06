"""Run real-scene NodeCue evaluations.

This compares two channels with the same prompt, skill, provider, and model:

- internal: model -> NodeCueActionPlan -> NodeCue bpy recipes in isolated Blender
- external-mcp: model -> Python code -> official Blender MCP on 127.0.0.1:9876

Real model execution is opt-in:
    NODECUE_RUN_SCENE_EVAL=1 conda run -n blender python tests/golden/run_nodecue_scene_eval.py --channel internal --json

Official MCP execution additionally requires:
    NODECUE_RUN_OFFICIAL_MCP_EVAL=1
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nodecue_agent import (  # noqa: E402
    ProviderConfig,
    SkillBundle,
    _model_chat_completion,
    plan_nodecue_actions,
)


SCENARIOS_PATH = ROOT / "tests" / "golden" / "nodecue_scene_scenarios.yaml"
DEFAULT_SKILL_PATH = ROOT / "nodecue" / "skills" / "geometry-nodes"
OFFICIAL_MCP_HOST = "127.0.0.1"
OFFICIAL_MCP_PORT = 9876


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_scenarios(path: Path = SCENARIOS_PATH) -> list[dict[str, Any]]:
    scenarios = _load_yaml(path).get("scenarios") or []
    if not isinstance(scenarios, list):
        raise ValueError("nodecue scene scenarios must be a list")
    return scenarios


def _select_scenarios(
    scenarios: list[dict[str, Any]],
    scenario_id: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    if scenario_id:
        scenarios = [entry for entry in scenarios if entry.get("id") == scenario_id]
        if not scenarios:
            raise SystemExit(f"scenario id not found: {scenario_id}")
    if limit is not None:
        scenarios = scenarios[:limit]
    return scenarios


def _provider_from_args(args: argparse.Namespace) -> ProviderConfig:
    return ProviderConfig(
        kind=args.provider,
        model=args.model or os.environ.get("NODECUE_AGENT_MODEL", ""),
        base_url=args.base_url or os.environ.get("NODECUE_AGENT_BASE_URL", ""),
        api_key_env=args.api_key_env or os.environ.get("NODECUE_AGENT_API_KEY_ENV", ""),
        timeout_seconds=args.timeout_seconds,
    )


def _node_entries(readback: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = readback.get("nodes")
    return nodes if isinstance(nodes, list) else []


def _link_entries(readback: dict[str, Any]) -> list[dict[str, Any]]:
    links = readback.get("links")
    return links if isinstance(links, list) else []


def _frames(readback: dict[str, Any]) -> list[dict[str, Any]]:
    frames = readback.get("frames")
    return frames if isinstance(frames, list) else []


def _node_bl_idnames(readback: dict[str, Any]) -> set[str]:
    return {
        str(node.get("bl_idname") or "")
        for node in _node_entries(readback)
        if node.get("bl_idname")
    }


def _node_names_for(readback: dict[str, Any], *bl_idnames: str) -> set[str]:
    wanted = set(bl_idnames)
    return {
        str(node.get("name") or "")
        for node in _node_entries(readback)
        if node.get("bl_idname") in wanted and node.get("name")
    }


def _links_to_node_socket(
    readback: dict[str, Any],
    bl_idname: str,
    socket_names: Iterable[str],
) -> list[dict[str, Any]]:
    node_names = _node_names_for(readback, bl_idname)
    sockets = {name.lower() for name in socket_names}
    return [
        link
        for link in _link_entries(readback)
        if link.get("to_node") in node_names
        and str(link.get("to_socket") or "").lower() in sockets
    ]


def _has_geometry_output(readback: dict[str, Any]) -> bool:
    output_nodes = _node_names_for(readback, "NodeGroupOutput")
    return any(
        link.get("to_node") in output_nodes
        and str(link.get("to_socket") or "").lower() == "geometry"
        for link in _link_entries(readback)
    )


def _has_field_to_consumer(readback: dict[str, Any]) -> bool:
    consumer_sockets = {
        "selection",
        "offset",
        "scale",
        "rotation",
        "density factor",
        "instance index",
        "material index",
        "value",
    }
    return any(
        str(link.get("to_socket") or "").lower() in consumer_sockets
        for link in _link_entries(readback)
    )


def _has_scatter_instances(readback: dict[str, Any]) -> bool:
    points_links = _links_to_node_socket(readback, "GeometryNodeInstanceOnPoints", ["Points"])
    instance_links = _links_to_node_socket(
        readback, "GeometryNodeInstanceOnPoints", ["Instance"]
    )
    point_sources = {
        "GeometryNodeDistributePointsOnFaces",
        "GeometryNodeDistributePointsInVolume",
        "GeometryNodeCurveToPoints",
        "GeometryNodeMeshToPoints",
    }
    point_source_names = {
        node.get("name")
        for node in _node_entries(readback)
        if node.get("bl_idname") in point_sources
    }
    return bool(points_links and instance_links) and any(
        link.get("from_node") in point_source_names for link in points_links
    )


def _has_displacement_offset(readback: dict[str, Any]) -> bool:
    return bool(_links_to_node_socket(readback, "GeometryNodeSetPosition", ["Offset"]))


def _has_material_handoff(readback: dict[str, Any]) -> bool:
    return bool(
        _node_bl_idnames(readback)
        & {
            "GeometryNodeSetMaterial",
            "GeometryNodeSetMaterialIndex",
            "GeometryNodeStoreNamedAttribute",
        }
    )


def _has_composition_join(readback: dict[str, Any]) -> bool:
    return "GeometryNodeJoinGeometry" in _node_bl_idnames(readback)


def _has_curve_to_mesh(readback: dict[str, Any]) -> bool:
    return "GeometryNodeCurveToMesh" in _node_bl_idnames(readback)


def _has_repeat_zone(readback: dict[str, Any]) -> bool:
    ids = _node_bl_idnames(readback)
    return {"GeometryNodeRepeatInput", "GeometryNodeRepeatOutput"} <= ids


def _has_teaching_frame_or_explanation(
    readback: dict[str, Any],
    final_explanation: str,
) -> bool:
    if final_explanation.strip():
        return True
    return any(str(frame.get("label") or "").strip() for frame in _frames(readback))


RELATIONSHIP_CHECKS = {
    "geometry_output": lambda rb, text: _has_geometry_output(rb),
    "field_to_consumer": lambda rb, text: _has_field_to_consumer(rb),
    "scatter_instances": lambda rb, text: _has_scatter_instances(rb),
    "displacement_offset": lambda rb, text: _has_displacement_offset(rb),
    "material_handoff": lambda rb, text: _has_material_handoff(rb),
    "composition_join": lambda rb, text: _has_composition_join(rb),
    "curve_to_mesh": lambda rb, text: _has_curve_to_mesh(rb),
    "repeat_zone": lambda rb, text: _has_repeat_zone(rb),
    "teaching_frame_or_explanation": lambda rb, text: _has_teaching_frame_or_explanation(
        rb, text
    ),
}


def detect_scene_quality(
    scenario: dict[str, Any],
    readback: dict[str, Any] | None,
    *,
    final_explanation: str = "",
    execution_error: str | None = None,
) -> dict[str, Any]:
    required_nodes = scenario.get("required_bl_idnames") or []
    required_relationships = scenario.get("required_relationships") or []

    if execution_error or readback is None:
        return {
            "status": "ERROR",
            "missing_bl_idnames": required_nodes,
            "missing_relationships": required_relationships,
            "node_coverage": 0.0,
            "relationship_coverage": 0.0,
            "failure_categories": ["execution_failure"],
            "error": execution_error,
        }

    node_ids = _node_bl_idnames(readback)
    missing_nodes = [node_id for node_id in required_nodes if node_id not in node_ids]
    missing_relationships = [
        rel
        for rel in required_relationships
        if rel not in RELATIONSHIP_CHECKS
        or not RELATIONSHIP_CHECKS[rel](readback, final_explanation)
    ]
    node_coverage = (
        (len(required_nodes) - len(missing_nodes)) / len(required_nodes)
        if required_nodes
        else 1.0
    )
    relationship_coverage = (
        (len(required_relationships) - len(missing_relationships))
        / len(required_relationships)
        if required_relationships
        else 1.0
    )
    categories: list[str] = []
    if missing_nodes or missing_relationships:
        categories.append("readback_verification_failure")
    if "teaching_frame_or_explanation" in missing_relationships:
        categories.append("explanation_weakness")
    return {
        "status": "PASS" if not missing_nodes and not missing_relationships else "FAIL",
        "missing_bl_idnames": missing_nodes,
        "missing_relationships": missing_relationships,
        "node_coverage": node_coverage,
        "relationship_coverage": relationship_coverage,
        "failure_categories": categories,
        "error": None,
    }


def _execution_script(root: Path, plan_path: Path, output_path: Path) -> str:
    return textwrap.dedent(
        f"""
        from __future__ import annotations
        import json
        import sys
        from pathlib import Path

        sys.path.insert(0, {str(root)!r})
        from nodecue.bpy_recipes import execute_action

        plan = json.loads(Path({str(plan_path)!r}).read_text(encoding='utf-8'))
        action_results = []
        final_readback = None
        for slice_ in plan.get('slices', []):
            for action in slice_.get('actions', []):
                result = execute_action(action)
                action_results.append({{'action': action, 'result': result}})
                if action.get('type') == 'read_active_node_tree':
                    final_readback = result.get('data') if result.get('ok') else result
        fallback = execute_action({{'type': 'read_active_node_tree', 'parameters': {{}}}})
        if fallback.get('ok'):
            final_readback = fallback.get('data')
        payload = {{
            'action_results': action_results,
            'final_readback': final_readback,
        }}
        Path({str(output_path)!r}).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        """
    )


def _execute_internal_plan_in_blender(plan: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="nodecue-scene-eval-") as tmp:
        tmp_path = Path(tmp)
        plan_path = tmp_path / "plan.json"
        output_path = tmp_path / "output.json"
        script_path = tmp_path / "execute_plan.py"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        script_path.write_text(
            _execution_script(ROOT, plan_path, output_path),
            encoding="utf-8",
        )
        proc = subprocess.run(
            ["conda", "run", "-n", "blender", "blender", "-b", "--python", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(ROOT),
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr + "\n" + proc.stdout)
        return json.loads(output_path.read_text(encoding="utf-8"))


def run_internal_channel(
    scenario: dict[str, Any],
    skill_path: Path,
    provider: ProviderConfig,
) -> dict[str, Any]:
    try:
        plan = plan_nodecue_actions(
            scenario["prompt"],
            scenario.get("mode", "generate"),
            skill_path,
            provider=provider,
            timeout_seconds=provider.timeout_seconds,
        )
        plan_payload = plan.as_dict()
    except Exception as exc:
        return {
            "status": "ERROR",
            "stage": "model_planning_failure",
            "error": str(exc),
            "plan": None,
            "readback": None,
            "final_explanation": "",
        }

    try:
        execution = _execute_internal_plan_in_blender(plan_payload)
        readback = execution.get("final_readback")
    except Exception as exc:
        return {
            "status": "ERROR",
            "stage": "execution_failure",
            "error": str(exc),
            "plan": plan_payload,
            "readback": None,
            "final_explanation": plan.final_explanation_goal,
        }

    return {
        "status": "OK",
        "stage": "completed",
        "error": None,
        "plan": plan_payload,
        "readback": readback,
        "final_explanation": plan.final_explanation_goal,
    }


def _external_mcp_messages(
    scenario: dict[str, Any],
    skill: SkillBundle,
) -> list[dict[str, str]]:
    required_nodes = ", ".join(scenario.get("required_bl_idnames") or [])
    relationships = ", ".join(scenario.get("required_relationships") or [])
    instructions = "\n\n".join(
        [
            "You are an external Blender agent using the official Blender MCP.",
            "Return strict JSON only: {\"code\":\"...\", \"explanation\":\"...\"}.",
            "The code must be Python for Blender and must assign a JSON-safe dict to a variable named result.",
            "Do not save files. Create a new temporary Geometry Nodes setup for this eval.",
            "The result dict must include {\"readback\": {\"tree_name\": ..., \"nodes\": [...], \"links\": [...], \"frames\": [...]}, \"explanation\": \"...\"}.",
            "Use the skill as guidance. Do not invent bl_idnames or socket names.",
            f"Scenario id: {scenario.get('id')}",
            f"Mode: {scenario.get('mode')}",
            f"Reference: {scenario.get('reference')}",
            f"Required nodes for detector: {required_nodes}",
            f"Required relationships for detector: {relationships}",
            "Skill excerpt:",
            skill.instruction_excerpt(limit=9000),
        ]
    )
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": scenario["prompt"]},
    ]


def _parse_json_object(text: str) -> dict[str, Any]:
    payload = json.loads(text.strip())
    if not isinstance(payload, dict):
        raise ValueError("model response JSON must be an object")
    return payload


def _send_official_mcp_execute(code: str, timeout_seconds: int) -> dict[str, Any]:
    request = {
        "type": "execute",
        "strict_json": True,
        "code": code,
    }
    with socket.create_connection(
        (OFFICIAL_MCP_HOST, OFFICIAL_MCP_PORT),
        timeout=timeout_seconds,
    ) as sock:
        sock.sendall(json.dumps(request).encode("utf-8") + b"\0")
        data = b""
        while not data.endswith(b"\0"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    if not data:
        raise RuntimeError("official MCP returned no data")
    return json.loads(data.rstrip(b"\0").decode("utf-8"))


def run_external_mcp_channel(
    scenario: dict[str, Any],
    skill_path: Path,
    provider: ProviderConfig,
    max_tokens: int,
) -> dict[str, Any]:
    try:
        skill = SkillBundle.load(skill_path)
        raw = _model_chat_completion(
            messages=_external_mcp_messages(scenario, skill),
            provider=provider,
            timeout_seconds=provider.timeout_seconds,
            max_tokens=max_tokens,
        )
        plan = _parse_json_object(raw)
        code = plan.get("code")
        if not isinstance(code, str) or "result" not in code:
            raise ValueError("external MCP model response must include code assigning result")
    except Exception as exc:
        return {
            "status": "ERROR",
            "stage": "model_planning_failure",
            "error": str(exc),
            "plan": None,
            "readback": None,
            "final_explanation": "",
        }

    try:
        response = _send_official_mcp_execute(code, provider.timeout_seconds)
        if response.get("status") != "ok":
            raise RuntimeError(json.dumps(response, ensure_ascii=False))
        result = response.get("result") or {}
        readback = result.get("readback") if isinstance(result, dict) else None
        final_explanation = ""
        if isinstance(result, dict):
            final_explanation = str(result.get("explanation") or plan.get("explanation") or "")
    except Exception as exc:
        return {
            "status": "ERROR",
            "stage": "execution_failure",
            "error": str(exc),
            "plan": plan,
            "readback": None,
            "final_explanation": str(plan.get("explanation") or ""),
        }

    return {
        "status": "OK",
        "stage": "completed",
        "error": None,
        "plan": plan,
        "readback": readback,
        "final_explanation": final_explanation,
    }


def _run_channel(
    channel: str,
    scenario: dict[str, Any],
    skill_path: Path,
    provider: ProviderConfig,
    max_tokens: int,
) -> dict[str, Any]:
    if channel == "internal":
        return run_internal_channel(scenario, skill_path, provider)
    if channel == "external-mcp":
        return run_external_mcp_channel(scenario, skill_path, provider, max_tokens)
    raise ValueError(f"unknown channel: {channel}")


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    channel_totals: dict[str, dict[str, Any]] = {}
    for row in rows:
        for channel, result in row["channels"].items():
            total = channel_totals.setdefault(
                channel,
                {"total": 0, "passes": 0, "failures": 0, "errors": 0},
            )
            total["total"] += 1
            detector_status = result.get("detector", {}).get("status")
            if detector_status == "PASS":
                total["passes"] += 1
            elif detector_status == "ERROR":
                total["errors"] += 1
            else:
                total["failures"] += 1
    return {"channels": channel_totals}


def _ensure_enabled(channel: str):
    if os.environ.get("NODECUE_RUN_SCENE_EVAL") != "1":
        raise SystemExit("set NODECUE_RUN_SCENE_EVAL=1 to run real-model scene eval")
    if channel in {"external-mcp", "both"} and os.environ.get("NODECUE_RUN_OFFICIAL_MCP_EVAL") != "1":
        raise SystemExit(
            "set NODECUE_RUN_OFFICIAL_MCP_EVAL=1 to run official MCP scene eval"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--list-scenarios", action="store_true", help="List scenario ids")
    parser.add_argument("--scenario-id", help="Run one scenario id")
    parser.add_argument("--limit", type=int, help="Run only the first N scenarios")
    parser.add_argument(
        "--channel",
        choices=("internal", "external-mcp", "both"),
        default="internal",
    )
    parser.add_argument(
        "--skill-path",
        type=Path,
        default=DEFAULT_SKILL_PATH,
        help="Path to the Geometry Nodes skill directory",
    )
    parser.add_argument(
        "--provider",
        choices=(
            "openrouter",
            "openai-compatible",
            "anthropic-compatible",
            "openai",
            "anthropic",
        ),
        default=os.environ.get("NODECUE_AGENT_PROVIDER", "openrouter"),
    )
    parser.add_argument("--model", default=os.environ.get("NODECUE_AGENT_MODEL", ""))
    parser.add_argument("--base-url", default=os.environ.get("NODECUE_AGENT_BASE_URL", ""))
    parser.add_argument(
        "--api-key-env",
        default=os.environ.get("NODECUE_AGENT_API_KEY_ENV", ""),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=int(os.environ.get("NODECUE_AGENT_TIMEOUT_SECONDS", "120")),
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(os.environ.get("NODECUE_SCENE_EVAL_MAX_TOKENS", "4000")),
        help="Max output tokens for external MCP Python code generation",
    )
    args = parser.parse_args()

    scenarios = _select_scenarios(load_scenarios(), args.scenario_id, args.limit)
    if args.list_scenarios:
        for scenario in scenarios:
            print(scenario["id"])
        return 0

    _ensure_enabled(args.channel)
    provider = _provider_from_args(args)
    channels = ["internal", "external-mcp"] if args.channel == "both" else [args.channel]

    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        channel_results: dict[str, Any] = {}
        for channel in channels:
            result = _run_channel(channel, scenario, args.skill_path, provider, args.max_tokens)
            detector = detect_scene_quality(
                scenario,
                result.get("readback"),
                final_explanation=result.get("final_explanation") or "",
                execution_error=result.get("error"),
            )
            if result.get("stage") == "model_planning_failure":
                detector["failure_categories"] = ["model_planning_failure"]
            channel_results[channel] = {
                "stage": result.get("stage"),
                "error": result.get("error"),
                "detector": detector,
                "plan": result.get("plan"),
                "readback": result.get("readback"),
                "final_explanation": result.get("final_explanation"),
            }
        rows.append(
            {
                "id": scenario["id"],
                "prompt": scenario["prompt"],
                "mode": scenario.get("mode"),
                "reference": scenario.get("reference"),
                "manual_review_fields": scenario.get("manual_review_fields") or [],
                "channels": channel_results,
            }
        )

    payload = {
        "provider": {
            "kind": provider.kind,
            "model": provider.model,
            "base_url": provider.resolved_base_url(),
        },
        "summary": _summarize(rows),
        "rows": rows,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("=== NodeCue scene eval ===")
        print(f"Provider: {provider.kind} / {provider.model}")
        for channel, stats in payload["summary"]["channels"].items():
            print(
                f"{channel}: pass={stats['passes']} fail={stats['failures']} "
                f"error={stats['errors']} total={stats['total']}"
            )
        for row in rows:
            for channel, result in row["channels"].items():
                detector = result["detector"]
                if detector["status"] != "PASS":
                    print(
                        f"- {channel} {row['id']}: {detector['status']} "
                        f"missing_nodes={detector['missing_bl_idnames']} "
                        f"missing_relationships={detector['missing_relationships']} "
                        f"error={result['error']}"
                    )

    return 0 if all(
        result["detector"]["status"] == "PASS"
        for row in rows
        for result in row["channels"].values()
    ) else 1


if __name__ == "__main__":
    sys.exit(main())
