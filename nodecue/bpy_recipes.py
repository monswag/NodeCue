"""Canonical NodeCue bpy action recipes.

This module is import-safe outside Blender. Actual execution happens lazily and
delegates to the existing Blender-side command handlers, so internal NodeCue
agents and official-MCP snippets can share one action vocabulary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping


ACTION_TO_COMMAND: dict[str, str] = {
    "read_active_node_tree": "read_active_tree",
    "create_node_tree": "create_node_tree",
    "create_node": "create_node",
    "connect": "connect",
    "set_socket_default": "set_input_default",
    "set_node_property": "set_node_property",
    "add_group_socket": "add_group_interface_socket",
    "remove_group_socket": "remove_group_interface_socket",
    "add_frame": "add_frame",
    "arrange_nodes": "arrange_nodes",
    "list_asset_node_groups": "list_asset_node_groups",
    "append_asset_node_group": "append_asset_node_group",
}

ACTION_ALIASES: dict[str, str] = {
    "read_active_tree": "read_active_node_tree",
    "set_input_default": "set_socket_default",
    "add_group_interface_socket": "add_group_socket",
    "remove_group_interface_socket": "remove_group_socket",
    "list_authorized_asset_node_groups": "list_asset_node_groups",
    "append_authorized_asset_group": "append_asset_node_group",
}

READ_ONLY_ACTIONS = frozenset(
    {
        "read_active_node_tree",
        "list_asset_node_groups",
    }
)

APPROVAL_REQUIRED_ACTIONS = frozenset(
    {
        "remove_group_socket",
    }
)


@dataclass(frozen=True)
class ActionSpec:
    """Static metadata for a NodeCue action."""

    type: str
    command: str
    read_only: bool = False
    requires_approval: bool = False


ACTION_SPECS: dict[str, ActionSpec] = {
    action_type: ActionSpec(
        type=action_type,
        command=command,
        read_only=action_type in READ_ONLY_ACTIONS,
        requires_approval=action_type in APPROVAL_REQUIRED_ACTIONS,
    )
    for action_type, command in ACTION_TO_COMMAND.items()
}


def supported_action_types() -> tuple[str, ...]:
    return tuple(sorted(ACTION_TO_COMMAND))


def normalize_action(action: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize an action dict to `{type, parameters, ...}`.

    The action vocabulary is intentionally node-specific. It is not a generic
    Python execution surface.
    """

    raw_type = str(action.get("type") or action.get("action") or "").strip()
    action_type = ACTION_ALIASES.get(raw_type, raw_type)
    if action_type not in ACTION_TO_COMMAND:
        raise ValueError(f"unsupported NodeCue action type: {raw_type}")

    reserved = {
        "type",
        "action",
        "intent",
        "expected_readback",
        "failure_recovery",
        "approved",
    }
    flat_parameters = {key: value for key, value in action.items() if key not in reserved}
    raw_parameters = action.get("parameters") or action.get("params")
    if raw_parameters is None:
        raw_parameters = flat_parameters
    if not isinstance(raw_parameters, Mapping):
        raise ValueError("NodeCue action parameters must be an object")
    parameters = dict(flat_parameters)
    parameters.update(dict(raw_parameters))

    if "node_type" in parameters and "bl_idname" not in parameters:
        parameters["bl_idname"] = parameters.pop("node_type")
    location = parameters.pop("location", None)
    if isinstance(location, (list, tuple)) and len(location) >= 2:
        parameters.setdefault("location_x", location[0])
        parameters.setdefault("location_y", location[1])
    if "nodes" in parameters and "node_names" not in parameters:
        parameters["node_names"] = parameters.pop("nodes")
    if "property" in parameters and "property_name" not in parameters:
        parameters["property_name"] = parameters.pop("property")

    return {
        "type": action_type,
        "intent": str(action.get("intent") or "").strip(),
        "parameters": parameters,
        "expected_readback": action.get("expected_readback") or {},
        "failure_recovery": str(action.get("failure_recovery") or "").strip(),
        "approved": bool(action.get("approved", False)),
    }


def json_safe(value: Any) -> Any:
    """Convert Blender-ish values to JSON-safe values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    try:
        return [json_safe(v) for v in value]
    except TypeError:
        return repr(value)


def execute_action(action: Mapping[str, Any]) -> dict[str, Any]:
    """Execute a normalized NodeCue action inside Blender.

    This function is suitable for NodeCue internal execution and for official
    Blender MCP code snippets when NodeCue is installed.
    """

    normalized = normalize_action(action)
    spec = ACTION_SPECS[normalized["type"]]
    if spec.requires_approval and not normalized["approved"]:
        return {
            "error": f"action '{spec.type}' requires explicit approval",
            "requires_approval": True,
        }

    from nodecue import socket_server

    handler = socket_server._COMMANDS.get(spec.command)  # noqa: SLF001 - shared internal recipe layer.
    if handler is None:
        return {"error": f"NodeCue command '{spec.command}' is not registered"}
    return json_safe(handler(normalized["parameters"]))


def execute_action_batch(
    actions: list[Mapping[str, Any]],
    *,
    readback_after: bool = True,
    stop_on_error: bool = True,
) -> dict[str, Any]:
    """Execute a stage of normalized NodeCue actions inside Blender."""

    if not isinstance(actions, list):
        return {"error": "actions must be a list"}

    results: list[dict[str, Any]] = []
    failed_action: dict[str, Any] | None = None
    for raw_action in actions:
        try:
            normalized = normalize_action(raw_action)
            result = execute_action(normalized)
        except Exception as exc:
            failed_action = {"raw_action": json_safe(raw_action), "error": str(exc)}
            results.append(failed_action)
            if stop_on_error:
                break
            continue

        payload = {"action": normalized, "result": result}
        results.append(payload)
        if isinstance(result, Mapping) and result.get("error"):
            failed_action = payload
            if stop_on_error:
                break

    readback = None
    if readback_after:
        readback = execute_action({"type": "read_active_node_tree", "parameters": {}})
    return json_safe(
        {
            "ok": failed_action is None,
            "results": results,
            "failed_action": failed_action,
            "readback": readback,
        }
    )


def official_mcp_code_for_action(action: Mapping[str, Any]) -> str:
    """Return official-MCP-compatible Python code for a NodeCue action.

    Official Blender MCP requires Python code that assigns a JSON-serializable
    dict to `result`. This helper uses NodeCue when installed; the skill docs
    also describe direct bpy recipes for agents that do not have NodeCue.
    """

    payload = json.dumps(normalize_action(action), ensure_ascii=False)
    return (
        "import json\n"
        "from nodecue.bpy_recipes import execute_action\n"
        f"result = execute_action(json.loads({payload!r}))\n"
    )
