from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "golden" / "run_nodecue_agent_prompts.py"
API_KEY_ENV = os.environ.get("NODECUE_AGENT_API_KEY_ENV", "OPENROUTER_API_KEY")

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("NODECUE_RUN_AGENT_EVAL") != "1",
        reason="set NODECUE_RUN_AGENT_EVAL=1 to run real-model agent eval",
    ),
    pytest.mark.skipif(
        not os.environ.get(API_KEY_ENV),
        reason=f"set {API_KEY_ENV} to run OpenRouter eval",
    ),
]


def test_nodecue_agent_archetype_prompts_eval():
    proc = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--json",
            "--provider",
            "openrouter",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + "\n" + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["summary"]["errors"] == 0, payload["summary"]
    assert payload["summary"]["total"] > 0, payload["summary"]
