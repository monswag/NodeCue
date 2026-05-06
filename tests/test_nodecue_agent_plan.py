import os

from nodecue_agent import (
    AgentPlan,
    HeadlessBlenderSession,
    NodeCueActionPlan,
    ProviderConfig,
    StageNodePropertySpec,
    SkillBundle,
    build_sdk_geometry_agent,
    build_sdk_model,
    coerce_stage_socket_value,
    plan_geometry_prompt,
    plan_nodecue_actions,
    should_skip_stage_arrange,
    stage_node_property_misuse_error,
)
from nodecue_agent.sdk_sidecar import _load_env_file


def test_agent_plan_parses_strict_json():
    plan = AgentPlan.from_json_text(
        '{"primary_archetype":"A1","bl_idnames":["GeometryNodeInstanceOnPoints"],"rationale":"scatter","confidence":0.8}'
    )
    assert plan.primary_archetype == "A1"
    assert plan.bl_idnames == ["GeometryNodeInstanceOnPoints"]
    assert plan.confidence == 0.8


def test_mock_planning_does_not_call_network():
    plan = plan_geometry_prompt(
        "在地形表面随机分布石头",
        "nodecue/skills/geometry-nodes",
        provider=ProviderConfig(kind="mock"),
    )
    assert plan.primary_archetype == "UNKNOWN"
    assert plan.bl_idnames == []


def test_action_plan_parses_only_supported_node_actions():
    plan = NodeCueActionPlan.from_json_text(
        """
        {
          "mode": "generate",
          "slices": [
            {
              "intent": "create shell",
              "actions": [
                {
                  "type": "create_node_tree",
                  "intent": "create GN tree",
                  "parameters": {"name": "NodeCue"},
                  "expected_readback": {"tree_name": "NodeCue"},
                  "failure_recovery": "select a mesh object"
                }
              ]
            }
          ],
          "final_explanation_goal": "teach the graph"
        }
        """
    )
    assert plan.mode == "generate"
    assert plan.slices[0].actions[0].type == "create_node_tree"


def test_action_plan_rejects_arbitrary_python_action():
    try:
        NodeCueActionPlan.from_json_text(
            '{"mode":"generate","slices":[{"intent":"bad","actions":[{"type":"execute_python","parameters":{"code":"import bpy"}}]}]}'
        )
    except ValueError as exc:
        assert "unsupported NodeCue action type" in str(exc)
    else:
        raise AssertionError("expected unsupported action to fail")


def test_mock_action_planner_returns_structured_node_actions():
    plan = plan_nodecue_actions(
        "生成一个可以调尺寸的立方体",
        "generate",
        "nodecue/skills/geometry-nodes",
        provider=ProviderConfig(kind="mock"),
    )
    assert plan.slices
    assert plan.slices[0].actions[0].type == "create_node_tree"


def test_provider_config_supports_local_openai_compatible_without_api_key():
    provider = ProviderConfig(kind="openai-compatible", model="local-model")
    assert provider.resolved_base_url().endswith("/v1")
    assert provider.resolved_api_key_env() == ""
    assert provider.requires_api_key is False


def test_provider_config_openrouter_defaults_to_openrouter_key():
    provider = ProviderConfig(kind="openrouter", model="anthropic/claude-sonnet-4.5")
    assert provider.resolved_base_url() == "https://openrouter.ai/api/v1"
    assert provider.resolved_api_key_env() == "OPENROUTER_API_KEY"
    assert provider.requires_api_key is True


def test_sdk_model_builder_uses_openrouter_chat_completions(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("NODECUE_AGENT_REASONING_EFFORT", "none")
    monkeypatch.setenv("NODECUE_AGENT_MAX_TOKENS", "4096")
    model, settings = build_sdk_model(
        ProviderConfig(kind="openrouter", model="moonshotai/kimi-k2.6")
    )
    assert type(model).__name__ == "OpenAIChatCompletionsModel"
    assert settings.max_tokens == 4096
    assert settings.parallel_tool_calls is False
    assert settings.include_usage is True
    assert settings.extra_body == {"reasoning": {"effort": "none", "exclude": True}}


def test_sdk_geometry_agent_exposes_trial_version_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    skill = SkillBundle.load("nodecue/skills/geometry-nodes")
    session = HeadlessBlenderSession(tmp_path / "eval.blend")

    agent = build_sdk_geometry_agent(
        skill,
        session,
        ProviderConfig(kind="openrouter", model="moonshotai/kimi-k2.6"),
    )

    tool_names = {tool.name for tool in agent.tools}
    assert "list_skill_files" in tool_names
    assert "read_skill_file" in tool_names
    assert "search_skill" in tool_names
    assert "execute_node_stage" in tool_names
    assert "read_active_node_tree" in tool_names
    assert "list_asset_node_groups" in tool_names
    assert "create_node" not in tool_names
    assert "connect" not in tool_names
    assert "add_group_socket" not in tool_names


def test_sdk_geometry_agent_uses_system_prompt_not_full_skill(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    skill = SkillBundle.load("nodecue/skills/geometry-nodes")
    session = HeadlessBlenderSession(tmp_path / "eval.blend")

    agent = build_sdk_geometry_agent(
        skill,
        session,
        ProviderConfig(kind="openrouter", model="moonshotai/kimi-k2.6"),
    )

    assert "Read skills first" in agent.instructions
    assert "NodeCue runtime:" in agent.instructions
    assert "Evidence Requirements" not in agent.instructions
    assert "Patterns Index" not in agent.instructions


def test_skill_bundle_safe_read_and_search():
    skill = SkillBundle.load("nodecue/skills/geometry-nodes")

    files = skill.list_files()
    assert "SKILL.md" in files["files"]
    assert "patterns/density-controlled-scatter.md" in files["files"]

    excerpt = skill.read_file("SKILL.md", start_line=1, max_lines=8)
    assert excerpt["path"] == "SKILL.md"
    assert excerpt["total_lines"] >= excerpt["end_line"]
    assert "Geometry Nodes" in excerpt["content"]

    matches = skill.search("density", max_results=20)
    paths = {match["path"] for match in matches["matches"]}
    assert "patterns/density-controlled-scatter.md" in paths


def test_skill_bundle_rejects_path_traversal():
    skill = SkillBundle.load("nodecue/skills/geometry-nodes")
    try:
        skill.read_file("../SKILL.md")
    except ValueError as exc:
        assert "relative to the skill root" in str(exc) or "escapes" in str(exc)
    else:
        raise AssertionError("expected traversal to fail")


def test_headless_session_execute_stage_maps_aliases_without_model_turns(tmp_path):
    session = HeadlessBlenderSession(tmp_path / "eval.blend")
    session.current_tree_name = "Tree"
    prepared_actions = []

    def fake_run(action):
        prepared_actions.append(action)
        if action["type"] == "create_node":
            return {"node_name": "Noise.001", "requested_name": "Noise", "bl_idname": "ShaderNodeTexNoise"}
        return {"ok": True}

    session._run_blender_action = fake_run  # type: ignore[method-assign]
    result = session.execute_stage(
        "Create and connect a noise field",
        [
            {"type": "create_node", "parameters": {"bl_idname": "ShaderNodeTexNoise", "name": "Noise"}},
            {
                "type": "connect",
                "parameters": {
                    "from_node": "Noise",
                    "from_socket": "Fac",
                    "to_node": "CombineZ",
                    "to_socket": "Z",
                },
            },
        ],
        readback_after=False,
    )

    assert result["ok"] is True
    assert result["raw_action_count"] == 2
    assert prepared_actions[1]["parameters"]["from_node"] == "Noise.001"
    assert len(session.stage_results) == 1


def test_headless_session_rejects_generate_stage_without_content_actions(tmp_path):
    session = HeadlessBlenderSession(tmp_path / "eval.blend")
    session.mode = "generate"

    result = session.execute_stage(
        "Only create a shell",
        [{"type": "create_node_tree", "parameters": {"name": "NodeCue"}}],
        readback_after=False,
    )

    assert result["ok"] is False
    assert "content node creation" in result["failed_action"]["error"]


def test_headless_session_injects_tree_name_and_maps_node_alias(tmp_path):
    session = HeadlessBlenderSession(tmp_path / "eval.blend")
    session.current_tree_name = "Tree"
    session.node_aliases["Height Noise"] = "Height Noise.001"
    action = session._prepare_action(
        "connect",
        {
            "from_node": "Height Noise",
            "from_socket": "Fac",
            "to_node": "Set Position",
            "to_socket": "Offset",
        },
    )
    assert action["parameters"]["tree_name"] == "Tree"
    assert action["parameters"]["from_node"] == "Height Noise.001"


def test_headless_session_replaces_empty_tree_name_with_current_tree(tmp_path):
    session = HeadlessBlenderSession(tmp_path / "eval.blend")
    session.current_tree_name = "Tree"
    action = session._prepare_action(
        "add_group_socket",
        {"tree_name": "", "name": "Height", "socket_type": "NodeSocketFloat"},
    )
    assert action["parameters"]["tree_name"] == "Tree"


def test_stage_property_guard_rejects_socket_default_shape():
    error = stage_node_property_misuse_error(
        [
            StageNodePropertySpec(
                node_name="Grid",
                property_name="inputs[0].default_value",
                value_json="2.0",
            )
        ]
    )

    assert error is not None
    assert "socket_defaults" in error["error"]


def test_stage_arrange_is_skipped_for_large_batches():
    assert should_skip_stage_arrange(19) is True
    assert should_skip_stage_arrange(18) is False


def test_stage_socket_value_coerces_quoted_numbers_but_not_string_sockets():
    assert coerce_stage_socket_value("1.0", socket_type="NodeSocketFloat") == 1.0
    assert coerce_stage_socket_value("3", socket_type="NodeSocketInt") == 3
    assert coerce_stage_socket_value("001", socket_type="NodeSocketString") == "001"


def test_headless_session_maps_appended_asset_group_node_alias(tmp_path):
    session = HeadlessBlenderSession(tmp_path / "eval.blend")
    session._update_context(
        {
            "type": "append_asset_node_group",
            "parameters": {"group_name": "Scatter on Surface"},
        },
        {"node_name": "Group"},
    )

    assert session.node_aliases["Scatter on Surface"] == "Group"


def test_headless_session_compacts_asset_list_results(tmp_path):
    session = HeadlessBlenderSession(tmp_path / "eval.blend")
    result = session._compact_result(
        {
            "node_groups": [
                {"name": f"Group {index}", "source_file": "/tmp/assets.blend"}
                for index in range(60)
            ],
            "count": 60,
        }
    )

    assert len(result["node_groups"]) == 50
    assert result["count"] == 60


def test_sidecar_env_file_loader_does_not_override_existing_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NODECUE_AGENT_MODEL=from-file\nNODECUE_AGENT_REASONING_EFFORT=none\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NODECUE_AGENT_MODEL", "from-env")
    monkeypatch.delenv("NODECUE_AGENT_REASONING_EFFORT", raising=False)

    _load_env_file(env_file)

    assert os.environ["NODECUE_AGENT_MODEL"] == "from-env"
    assert os.environ["NODECUE_AGENT_REASONING_EFFORT"] == "none"
