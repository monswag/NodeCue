from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.golden.run_nodecue_scene_eval import (
    SCENARIOS_PATH,
    detect_scene_quality,
    load_scenarios,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "golden" / "run_nodecue_scene_eval.py"
PATTERN_READBACK = (
    ROOT / "nodecue" / "skills" / "geometry-nodes" / "evals" / "gn_pattern_readbacks.json"
)


def test_scene_scenarios_are_real_reference_cases():
    scenarios = load_scenarios(SCENARIOS_PATH)
    assert len(scenarios) == 8
    ids = {scenario["id"] for scenario in scenarios}
    assert {
        "terrain_noise_displacement",
        "density_grass_scatter",
        "rocks_on_terrain",
        "curve_pipe_or_wall",
        "modular_cabin",
        "material_mask_handoff",
        "repeat_selection_expand",
        "pinned_mesh_relax",
    } == ids
    for scenario in scenarios:
        assert scenario["prompt"]
        assert scenario["mode"] in {"generate", "modify", "explain"}
        assert scenario["reference"]
        assert scenario["skill_files"]
        assert scenario["required_bl_idnames"]
        assert scenario["required_relationships"]
        assert scenario["manual_review_fields"]


def test_scene_eval_runner_lists_scenarios_without_real_model():
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--list-scenarios"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "terrain_noise_displacement" in proc.stdout
    assert "pinned_mesh_relax" in proc.stdout


def test_detector_accepts_verified_pattern_readbacks():
    payload = json.loads(PATTERN_READBACK.read_text(encoding="utf-8"))
    patterns = payload["patterns"]

    surface = detect_scene_quality(
        {
            "required_bl_idnames": ["GeometryNodeSetPosition", "ShaderNodeTexNoise"],
            "required_relationships": [
                "geometry_output",
                "displacement_offset",
                "field_to_consumer",
            ],
        },
        patterns["surface-displacement"],
    )
    assert surface["status"] == "PASS", surface

    scatter = detect_scene_quality(
        {
            "required_bl_idnames": [
                "GeometryNodeDistributePointsOnFaces",
                "GeometryNodeInstanceOnPoints",
            ],
            "required_relationships": [
                "geometry_output",
                "scatter_instances",
                "field_to_consumer",
            ],
        },
        patterns["density-controlled-scatter"],
    )
    assert scatter["status"] == "PASS", scatter

    material = detect_scene_quality(
        {
            "required_bl_idnames": ["GeometryNodeSetMaterialIndex"],
            "required_relationships": [
                "geometry_output",
                "material_handoff",
                "field_to_consumer",
            ],
        },
        patterns["material-attribute-handoff"],
    )
    assert material["status"] == "PASS", material


def test_detector_reports_missing_relationships():
    result = detect_scene_quality(
        {
            "required_bl_idnames": ["GeometryNodeSetPosition"],
            "required_relationships": ["geometry_output", "displacement_offset"],
        },
        {"nodes": [], "links": [], "frames": []},
    )
    assert result["status"] == "FAIL"
    assert result["missing_bl_idnames"] == ["GeometryNodeSetPosition"]
    assert result["missing_relationships"] == ["geometry_output", "displacement_offset"]


@pytest.mark.skipif(
    os.environ.get("NODECUE_RUN_SCENE_EVAL") != "1",
    reason="set NODECUE_RUN_SCENE_EVAL=1 to run real-model scene eval",
)
def test_scene_eval_internal_real_model_smoke():
    proc = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--json",
            "--channel",
            "internal",
            "--scenario-id",
            "terrain_noise_displacement",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + "\n" + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["summary"]["channels"]["internal"]["total"] == 1


@pytest.mark.skipif(
    os.environ.get("NODECUE_RUN_SCENE_EVAL") != "1"
    or os.environ.get("NODECUE_RUN_OFFICIAL_MCP_EVAL") != "1",
    reason="set scene and official MCP env vars to run external MCP scene eval",
)
def test_scene_eval_external_mcp_real_model_smoke():
    proc = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--json",
            "--channel",
            "external-mcp",
            "--scenario-id",
            "terrain_noise_displacement",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + "\n" + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["summary"]["channels"]["external-mcp"]["total"] == 1
