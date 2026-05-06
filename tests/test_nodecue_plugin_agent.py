from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "golden" / "run_nodecue_plugin_agent_smoke.py"


def test_plugin_agent_smoke_runner_has_cli():
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "NODECUE_RUN_PLUGIN_AGENT_EVAL" in proc.stdout


@pytest.mark.skipif(
    os.environ.get("NODECUE_RUN_PLUGIN_AGENT_EVAL") != "1",
    reason="set NODECUE_RUN_PLUGIN_AGENT_EVAL=1 to run Blender plugin agent smoke",
)
def test_plugin_agent_real_model_smoke():
    proc = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--json",
            "--scenario-id",
            "terrain_noise_displacement",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=420,
    )
    assert proc.returncode == 0, proc.stderr + "\n" + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["report"]["stage"] == "completed"
    assert Path(payload["blend_path"]).exists()
    assert payload["report"]["sdk_result"]["action_results"]
