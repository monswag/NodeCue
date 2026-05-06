import ast
import json

import pytest

from nodecue.bpy_recipes import (
    execute_action_batch,
    official_mcp_code_for_action,
    normalize_action,
    supported_action_types,
)


def test_supported_actions_include_asset_and_node_core():
    actions = set(supported_action_types())
    assert "read_active_node_tree" in actions
    assert "create_node" in actions
    assert "connect" in actions
    assert "list_asset_node_groups" in actions
    assert "append_asset_node_group" in actions


def test_normalize_action_maps_historical_aliases_to_canonical_names():
    action = normalize_action(
        {
            "type": "set_input_default",
            "params": {"tree_name": "T", "node_name": "Value", "socket_name": "Value", "value": 1.0},
        }
    )
    assert action["type"] == "set_socket_default"
    assert action["parameters"]["tree_name"] == "T"


def test_normalize_action_maps_model_parameter_aliases():
    action = normalize_action(
        {
            "type": "create_node",
            "parameters": {
                "node_type": "ShaderNodeTexNoise",
                "location": [-100, 200],
            },
        }
    )
    assert action["parameters"]["bl_idname"] == "ShaderNodeTexNoise"
    assert action["parameters"]["location_x"] == -100
    assert action["parameters"]["location_y"] == 200

    frame = normalize_action(
        {"type": "add_frame", "parameters": {"nodes": ["Noise"], "label": "Height"}}
    )
    assert frame["parameters"]["node_names"] == ["Noise"]

    prop = normalize_action(
        {"type": "set_node_property", "parameters": {"property": "operation", "value": "SCALE"}}
    )
    assert prop["parameters"]["property_name"] == "operation"


def test_normalize_action_accepts_flat_stage_action_parameters():
    action = normalize_action(
        {
            "type": "create_node",
            "tree_name": "Tree",
            "bl_idname": "ShaderNodeTexNoise",
            "name": "Noise",
        }
    )
    assert action["parameters"]["tree_name"] == "Tree"
    assert action["parameters"]["bl_idname"] == "ShaderNodeTexNoise"
    assert action["parameters"]["name"] == "Noise"

    mixed = normalize_action(
        {
            "type": "create_node",
            "parameters": {},
            "tree_name": "Tree",
            "bl_idname": "ShaderNodeTexNoise",
        }
    )
    assert mixed["parameters"]["tree_name"] == "Tree"
    assert mixed["parameters"]["bl_idname"] == "ShaderNodeTexNoise"


def test_normalize_action_rejects_arbitrary_python():
    with pytest.raises(ValueError):
        normalize_action({"type": "execute_python", "parameters": {"code": "import bpy"}})


def test_execute_action_batch_rejects_unsupported_action_before_blender_import():
    result = execute_action_batch(
        [{"type": "execute_python", "parameters": {"code": "import bpy"}}],
        readback_after=False,
    )
    assert result["ok"] is False
    assert "unsupported NodeCue action type" in result["failed_action"]["error"]


def test_official_mcp_code_assigns_result_and_embeds_json_action():
    code = official_mcp_code_for_action(
        {
            "type": "read_active_tree",
            "parameters": {},
            "intent": "inspect active GN tree",
        }
    )
    assert "result = execute_action" in code
    embedded = code.split("json.loads(", 1)[1].split(")", 1)[0]
    payload = json.loads(ast.literal_eval(embedded))
    assert payload["type"] == "read_active_node_tree"
