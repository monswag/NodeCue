from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODES_PATH = ROOT / "references" / "gn_kb" / "nodes.json"
RULES_DIR = ROOT / "nodecue" / "skills" / "geometry-nodes" / "rules"
PATTERNS_DIR = ROOT / "nodecue" / "skills" / "geometry-nodes" / "patterns"
SKILL_PATH = ROOT / "nodecue" / "skills" / "geometry-nodes" / "SKILL.md"
PATTERN_READBACK_PATH = (
    ROOT / "tests" / "golden" / "skill_evals" / "gn_pattern_readbacks.json"
)

NODE_RULE_PREFIXES = {
    "workflow-",
    "concept-",
}
NODE_RULE_EXCLUDE = {"_sections.md", "_fallback.md"}
CONCEPT_RULE_FILES = {"node-role-catalog.md", "readback-repair.md"}


def _load_nodes() -> dict[str, dict]:
    data = json.loads(NODES_PATH.read_text(encoding="utf-8"))
    nodes = data["nodes"] if isinstance(data, dict) and "nodes" in data else data
    return {n["bl_idname"]: n for n in nodes if n.get("bl_idname")}


def _rule_files() -> list[Path]:
    return sorted(p for p in RULES_DIR.glob("*.md") if p.is_file() and not p.name.startswith("_"))


def _pattern_files() -> list[Path]:
    return sorted(p for p in PATTERNS_DIR.glob("*.md") if p.is_file() and not p.name.startswith("_"))


def _is_node_reference(path: Path) -> bool:
    if path.name in NODE_RULE_EXCLUDE:
        return False
    if path.name in CONCEPT_RULE_FILES:
        return False
    return not any(path.name.startswith(prefix) for prefix in NODE_RULE_PREFIXES)


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    payload = {}
    for line in parts[1].strip().splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        payload[k.strip()] = v.strip()
    return payload


def _extract_bl_ids(text: str) -> list[str]:
    return re.findall(r"`(GeometryNode[\w]+|FunctionNode[\w]+|ShaderNode[\w]+|Node[\w]+)`", text)


_NON_SOCKET_LABELS = {
    # Math/compare operations that appear in prose as Math(FLOOR), Compare(EQUAL), etc.
    "FLOOR", "CEIL", "ROUND", "MODULO", "DIVIDE", "MULTIPLY", "ADD", "SUBTRACT",
    "EQUAL", "LESS_THAN", "GREATER_THAN", "NOT_EQUAL",
    # Other uppercase tokens in parentheses that are not socket types
    "LMB", "RMB", "SHIFT", "CTRL", "ALT",
    "AUTO", "SHARP", "VECTOR_SMOOTH",
}


def _extract_socket_types(text: str) -> set[str]:
    return set(re.findall(r"\(([A-Z_]+)\)", text)) - _NON_SOCKET_LABELS


def test_every_rule_has_required_frontmatter_fields():
    for path in _rule_files():
        fm = _frontmatter(path.read_text(encoding="utf-8"))
        assert fm.get("title"), f"missing title: {path.name}"
        assert fm.get("section"), f"missing section: {path.name}"
        assert fm.get("tags"), f"missing tags: {path.name}"


def test_every_node_bl_idname_is_covered_in_node_reference_rules():
    kb = _load_nodes()
    seen = set()
    for path in _rule_files():
        if not _is_node_reference(path):
            continue
        seen.update(_extract_bl_ids(path.read_text(encoding="utf-8")))

    missing = sorted(set(kb) - seen)
    assert not missing, f"missing node references: {missing[:10]}"


def test_no_duplicate_bl_idname_across_node_reference_rules():
    owners: dict[str, list[str]] = {}
    for path in _rule_files():
        if not _is_node_reference(path):
            continue
        ids = set(_extract_bl_ids(path.read_text(encoding="utf-8")))
        for bl in ids:
            owners.setdefault(bl, []).append(path.name)

    dup = {k: v for k, v in owners.items() if len(v) > 1}
    assert not dup, f"duplicate node entries across files: {list(dup.items())[:5]}"


def test_socket_types_used_in_rules_are_known():
    allowed = {
        "GEOMETRY",
        "FLOAT",
        "INT",
        "BOOLEAN",
        "VECTOR",
        "ROTATION",
        "COLOR",
        "STRING",
        "OBJECT",
        "COLLECTION",
        "IMAGE",
        "MATERIAL",
        "MATRIX",
        "MENU",
        "UNKNOWN",
        "SDF",
        "CUSTOM",
    }

    used = set()
    for path in _rule_files():
        used.update(_extract_socket_types(path.read_text(encoding="utf-8")))

    bad = sorted(x for x in used if x not in allowed)
    assert not bad, f"unexpected socket type labels in rules: {bad}"


def test_skill_md_indexes_all_rule_files():
    text = SKILL_PATH.read_text(encoding="utf-8")
    missing = [p.name for p in _rule_files() if p.name.replace(".md", "") not in text]
    assert not missing, f"SKILL.md missing rules: {missing}"


def test_skill_md_indexes_all_pattern_files():
    text = SKILL_PATH.read_text(encoding="utf-8")
    missing = [p.name for p in _pattern_files() if p.name not in text]
    assert not missing, f"SKILL.md missing patterns: {missing}"


def test_patterns_include_evidence_sections():
    missing = [
        p.name
        for p in _pattern_files()
        if "## Evidence" not in p.read_text(encoding="utf-8")
    ]
    assert not missing, f"patterns missing evidence sections: {missing}"


def test_verified_pattern_readback_artifact_covers_new_patterns():
    payload = json.loads(PATTERN_READBACK_PATH.read_text(encoding="utf-8"))
    patterns = payload["patterns"]
    required = {
        "surface-displacement",
        "density-controlled-scatter",
        "material-attribute-handoff",
    }
    assert required <= set(patterns)
    for name in required:
        links = patterns[name]["links"]
        assert any(link["to_node"].startswith("Group Output") for link in links), name


def test_skill_markdown_bl_idnames_are_known():
    known = set(_load_nodes())
    files = [SKILL_PATH, *_rule_files(), *_pattern_files()]
    unknown: dict[str, list[str]] = {}
    for path in files:
        ids = set(_extract_bl_ids(path.read_text(encoding="utf-8")))
        bad = sorted(ids - known)
        if bad:
            unknown[path.name] = bad
    assert not unknown, f"unknown bl_idnames in skill markdown: {unknown}"


def test_skill_md_frontmatter_and_overview_are_agent_skill_friendly():
    text = SKILL_PATH.read_text(encoding="utf-8")
    fm = _frontmatter(text)
    assert fm.get("name") == "geometry-nodes"
    assert "Geometry Nodes" in fm.get("description", "")
    assert "readback" in fm.get("description", "")

    overview = text.split("## Overview", 1)[1].split("\n## ", 1)[0]
    assert len([line for line in overview.splitlines() if line.strip()]) <= 6
    assert "whatever Blender access path the host provides" in overview


def test_skill_md_keeps_ambiguity_handling_without_fixed_response_format():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "When wording is ambiguous" in text
    assert "competing interpretations" in text
    assert "materially changes topology" in text
    assert "## Recommended Planning Notes" in text
    assert "## Output Format For Agent Responses" not in text


def test_skill_md_contains_gn_mental_model_and_relationship_primitives():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "## Geometry Nodes Mental Model" in text
    assert "## Graph Relationship Rules" in text
    assert "## Prompt Translation" in text
    assert "## Build Loop" in text
    assert "## Reliability Rules" in text
    assert "## Evidence Requirements" in text
    assert "## Core Concepts" in text
    assert "## Role Lookup" in text
    assert "## Asset / Node Group Reuse" in text
    assert "geometry trunk" in text
    assert "Field lane" in text
    assert "Field producer -> consumer" in text
    assert "full-graph node list" in text
    assert "Generate" in text
    assert "Process" in text
    assert "slice mode is mandatory" in text
    assert "explicitly named interface controls only" in text
    assert "Reroutes are organization-only" in text
    assert "type-polymorphic" in text
    assert "Never fall back silently between socket defaults and node properties." in text
    assert "After each value write, verify the expected readback field changed" in text
    assert "If a create/connect/write operation fails" in text
    assert "rules/node-role-catalog.md" in text
    assert "rules/readback-repair.md" in text


def test_skill_md_does_not_expose_internal_or_transport_specific_api():
    text = SKILL_PATH.read_text(encoding="utf-8")
    banned = [
        "When Not To Use",
        "NodeCueActionPlan",
        "NodeCue internal",
        "official MCP",
        "gn_mcp_server",
        "create_node_tree",
        "set_socket_default",
        "append_asset_node_group",
    ]
    for phrase in banned:
        assert phrase not in text
