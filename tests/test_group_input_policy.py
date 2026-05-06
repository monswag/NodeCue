from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "nodecue" / "skills" / "geometry-nodes" / "SKILL.md"
RULES_DIR = ROOT / "nodecue" / "skills" / "geometry-nodes" / "rules"


def test_skill_does_not_force_group_input_trunk():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "Geometry trunk: `Group Input -> ... -> Group Output`." not in text
    assert "Group Output" in text and "Geometry" in text
    assert "## Group Input Policy" in text
    assert "Process" in text and "Generate" in text
    assert "Only expose parameters the user" in text


def test_rules_do_not_hard_require_group_input_source_link():
    for path in RULES_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert "`Group Input.Geometry ->" not in text, f"hard Group Input link remains in {path.name}"
