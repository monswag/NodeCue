"""Archetype + mechanic detector for reference node-group JSON exports.

Consumes `tests/golden/archetypes.yaml` and scans `references/*/*.json` files
produced by `extract_blend_groups_and_texts.py`. Emits a report comparing the
detector's labels to manual labels in `docs/archetype_candidates.md`.

Gate semantics (from archetypes.yaml):
  - `required`: every gate must pass (AND).
  - Each gate's `any_of` / `any_of_prefix` contributes an OR of bl_idnames.
  - `optional`: bonus nodes that lift confidence but are not required.
  - `structural`: named hooks implemented here (STRUCTURAL_HOOKS).

Confidence:
  - Start at 0.6 when all gates pass.
  - +0.05 per optional bl_idname present (unique bl_idnames, not node count).
  - +0.1 per passing structural hook.
  - Capped at 1.0.
  - 0.0 if any gate fails.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "tests" / "golden" / "archetypes.yaml"
REFS_DIR = ROOT / "references"


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _collect_nodes(data: dict) -> list[dict]:
    """Flatten unframed_nodes + frames[*].nodes into one list."""
    out: list[dict] = []
    for node in data.get("unframed_nodes", []) or []:
        out.append(node)
    for frame in data.get("frames", []) or []:
        for node in frame.get("nodes", []) or []:
            out.append(node)
    return out


def _bl_id_counter(nodes: list[dict]) -> Counter:
    return Counter(n.get("bl_idname", "") for n in nodes)


def _bl_id_counter_with_subgroups(
    data: dict,
    groups_by_name: dict[str, dict] | None,
    *,
    max_depth: int = 3,
) -> Counter:
    """Return bl_idname counts for this group unioned with bl_idnames from
    any GeometryNodeGroup sub-group it calls (recursively up to max_depth).

    Falls back to the local counter when groups_by_name is None or when the
    sub-group name is missing / self-referential.
    """
    local = _collect_nodes(data)
    counter = Counter(n.get("bl_idname", "") for n in local)
    if not groups_by_name:
        return counter

    visited: set[str] = set()

    def visit(sub_data: dict, depth: int) -> None:
        for node in _collect_nodes(sub_data):
            counter[node.get("bl_idname", "")] += 1
            if depth <= 0:
                continue
            if node.get("bl_idname") != "GeometryNodeGroup":
                continue
            target = node.get("node_tree")
            if not target or target in visited:
                continue
            target_data = groups_by_name.get(target)
            if target_data is None:
                continue
            visited.add(target)
            visit(target_data, depth - 1)

    for node in local:
        if node.get("bl_idname") != "GeometryNodeGroup":
            continue
        target = node.get("node_tree")
        if not target or target in visited:
            continue
        target_data = groups_by_name.get(target)
        if target_data is None:
            continue
        visited.add(target)
        visit(target_data, max_depth - 1)

    return counter


# ---------------------------------------------------------------------------
# Gate matching
# ---------------------------------------------------------------------------


def _match_any_of(members: list[str], bl_ids: Counter) -> list[str]:
    return [m for m in members if bl_ids.get(m, 0) > 0]


def _match_any_of_prefix(prefixes: list[str], bl_ids: Counter) -> list[str]:
    matched: list[str] = []
    for prefix in prefixes:
        for bl, cnt in bl_ids.items():
            if cnt > 0 and bl.startswith(prefix):
                matched.append(bl)
    return matched


def _gate_matches(gate: dict, bl_ids: Counter) -> tuple[bool, list[str]]:
    matched: list[str] = []
    if "any_of" in gate:
        matched.extend(_match_any_of(gate.get("any_of") or [], bl_ids))
    if "any_of_prefix" in gate:
        matched.extend(_match_any_of_prefix(gate.get("any_of_prefix") or [], bl_ids))
    return (len(matched) > 0, matched)


# ---------------------------------------------------------------------------
# Structural hooks
# ---------------------------------------------------------------------------


_ROUTING_BL_IDS = {
    "NodeReroute",
    "NodeFrame",
    "NodeGroupInput",
    "NodeGroupOutput",
}
_ASSEMBLY_BL_IDS = {
    "GeometryNodeJoinGeometry",
    "GeometryNodeGroup",
    "GeometryNodeTransform",
    "GeometryNodeSwitch",
    "GeometryNodeStoreNamedAttribute",
    "GeometryNodeSetMaterial",
    "GeometryNodeRealizeInstances",
} | _ROUTING_BL_IDS

_PRIMITIVE_PREFIXES = (
    "GeometryNodeMeshCube",
    "GeometryNodeMeshCone",
    "GeometryNodeMeshCylinder",
    "GeometryNodeMeshUVSphere",
    "GeometryNodeMeshIcoSphere",
    "GeometryNodeMeshGrid",
    "GeometryNodeMeshCircle",
    "GeometryNodeCurvePrimitive",
)


def _resolve_reroutes(links: list[dict], nodes_by_name: dict[str, dict]) -> dict[str, str]:
    """Map each node name to the ultimate non-reroute upstream node reached
    by walking backwards through reroutes. Used to decide whether a primitive
    reaches Group Output through reroutes alone."""
    # Build reverse edges: to_node <- from_node
    incoming: dict[str, list[str]] = {}
    for link in links:
        if link.get("is_muted"):
            continue
        incoming.setdefault(link["to_node"], []).append(link["from_node"])

    resolved: dict[str, str] = {}

    def walk(name: str, seen: set[str]) -> str:
        if name in resolved:
            return resolved[name]
        if name in seen:
            return name
        seen.add(name)
        node = nodes_by_name.get(name)
        if not node or node.get("bl_idname") != "NodeReroute":
            resolved[name] = name
            return name
        parents = incoming.get(name, [])
        if not parents:
            resolved[name] = name
            return name
        resolved[name] = walk(parents[0], seen)
        return resolved[name]

    for name in nodes_by_name:
        walk(name, set())
    return resolved


def _check_generate_mode_trunk(data: dict) -> bool:
    """True if the group operates in generate mode:
    (a) no outgoing link from Group Input's Geometry socket, OR
    (b) a primitive feeds Group Output via routing-only path.
    """
    nodes = _collect_nodes(data)
    nodes_by_name = {n.get("name", ""): n for n in nodes}
    links = [l for l in data.get("links", []) or [] if not l.get("is_muted")]

    group_input_names = {
        n.get("name") for n in nodes if n.get("bl_idname") == "NodeGroupInput"
    }
    group_output_names = {
        n.get("name") for n in nodes if n.get("bl_idname") == "NodeGroupOutput"
    }

    # (a) Group Input.Geometry has no downstream edge
    geometry_out_links = [
        l
        for l in links
        if l["from_node"] in group_input_names and l.get("from_socket") == "Geometry"
    ]
    if not geometry_out_links:
        return True

    # (b) A primitive reaches Group Output via routing-only hops
    resolved = _resolve_reroutes(links, nodes_by_name)
    for link in links:
        if link["to_node"] not in group_output_names:
            continue
        upstream = resolved.get(link["from_node"], link["from_node"])
        upstream_node = nodes_by_name.get(upstream)
        if not upstream_node:
            continue
        bl = upstream_node.get("bl_idname", "")
        if any(bl.startswith(p) for p in _PRIMITIVE_PREFIXES):
            return True
    return False


def _check_join_is_primary_verb(data: dict) -> bool:
    """Join is primary verb when any of:
    (a) ≥2 Join nodes AND assembly/routing nodes dominate, OR
    (b) a single Join node fans in ≥3 distinct geometry sources — the whole
        group's job is to merge those sources.
    """
    nodes = _collect_nodes(data)
    bl_ids = _bl_id_counter(nodes)
    join_count = bl_ids.get("GeometryNodeJoinGeometry", 0)
    if join_count == 0:
        return False

    # (b) fan-in style: one Join with many *distinct* upstream geometry
    # sources (reroutes resolved to the real node behind them).
    join_names = {
        n.get("name")
        for n in nodes
        if n.get("bl_idname") == "GeometryNodeJoinGeometry"
    }
    links = [l for l in (data.get("links") or []) if not l.get("is_muted")]
    nodes_by_name = {n.get("name", ""): n for n in nodes}
    resolved = _resolve_reroutes(links, nodes_by_name)
    fan_in: dict[str, set[str]] = {}
    for link in links:
        to = link.get("to_node")
        if to in join_names:
            upstream = resolved.get(link.get("from_node", ""), link.get("from_node", ""))
            up_node = nodes_by_name.get(upstream, {})
            if up_node.get("bl_idname") == "NodeGroupInput":
                # Group-input passthroughs aren't distinct "parts" being assembled.
                continue
            fan_in.setdefault(to, set()).add(upstream)
    if any(len(srcs) >= 3 for srcs in fan_in.values()):
        return True

    # (a) multi-Join assembly chain
    if join_count < 2:
        return False
    considered = [n for n in nodes if n.get("bl_idname") not in _ROUTING_BL_IDS]
    if not considered:
        return False
    assembly = sum(
        1 for n in considered if n.get("bl_idname") in _ASSEMBLY_BL_IDS
    )
    return (assembly / len(considered)) >= 0.5


def _check_a9_strong_assembly(data: dict) -> bool:
    """A9 is strongly supported when Join is heavily used OR many sub-groups
    are composed together. Handles the procedural-building / Tree House case
    where Join×14 + Group×22 clearly signals modular assembly."""
    bl_ids = _bl_id_counter(_collect_nodes(data))
    join = bl_ids.get("GeometryNodeJoinGeometry", 0)
    group = bl_ids.get("GeometryNodeGroup", 0)
    return join >= 4 or (join + group) >= 5


def _check_scatter_iop_present(data: dict) -> bool:
    """A1 scatter verb is unambiguous when a distribute-family node feeds an
    Instance-on-Points. Used to pin A1 above A2 when both gates pass."""
    bl_ids = _bl_id_counter(_collect_nodes(data))
    sources = sum(
        bl_ids.get(n, 0)
        for n in (
            "GeometryNodeDistributePointsOnFaces",
            "GeometryNodeDistributePointsInVolume",
            "GeometryNodeMeshToPoints",
            "GeometryNodeCurveToPoints",
        )
    )
    return sources >= 1 and bl_ids.get("GeometryNodeInstanceOnPoints", 0) >= 1


def _check_curve_swept_dominant(data: dict) -> bool:
    """Multiple CurveToMesh/FillCurve operations make curve-sweeping the
    dominant verb — pins A3 above A7 when a primitive is also present."""
    bl_ids = _bl_id_counter(_collect_nodes(data))
    return (
        bl_ids.get("GeometryNodeCurveToMesh", 0)
        + bl_ids.get("GeometryNodeFillCurve", 0)
    ) >= 2


STRUCTURAL_HOOKS = {
    "generate_mode_trunk": _check_generate_mode_trunk,
    "join_is_primary_verb": _check_join_is_primary_verb,
    "a9_strong_assembly": _check_a9_strong_assembly,
    "scatter_iop_present": _check_scatter_iop_present,
    "curve_swept_dominant": _check_curve_swept_dominant,
}


# ---------------------------------------------------------------------------
# Detection core
# ---------------------------------------------------------------------------


@dataclass
class ArchetypeMatch:
    id: str
    name: str
    confidence: float
    matched_required: list[list[str]] = field(default_factory=list)
    matched_optional: list[str] = field(default_factory=list)
    matched_structural: list[str] = field(default_factory=list)
    matched_subtypes: list[str] = field(default_factory=list)


@dataclass
class DetectionResult:
    blend: str
    group: str
    node_count: int
    link_count: int
    primary: str | None
    secondaries: list[str]
    mechanics: list[str]
    matches: list[ArchetypeMatch]
    cross_layer: bool = False
    notes: list[str] = field(default_factory=list)


def _match_subtypes(spec: dict, bl_ids: Counter) -> list[str]:
    out: list[str] = []
    for sub in spec.get("sub_types", []) or []:
        nodes = sub.get("required_nodes") or []
        if all(bl_ids.get(n, 0) > 0 for n in nodes):
            out.append(sub["id"])
    return out


def _score_archetype(
    arch_id: str,
    spec: dict,
    data: dict,
    groups_by_name: dict[str, dict] | None = None,
) -> ArchetypeMatch | None:
    # Unioned counts drive signature gate/optional matching so that top-level
    # wrapper groups (e.g. Tree Moss calling Moss) still surface the right
    # archetype. Structural hooks keep operating on the current group's own
    # wiring because they depend on local link topology.
    bl_ids = _bl_id_counter_with_subgroups(data, groups_by_name)

    matched_required: list[list[str]] = []
    for gate in spec.get("required") or []:
        ok, matched = _gate_matches(gate, bl_ids)
        if not ok:
            return None
        matched_required.append(matched)

    matched_optional = [
        bl for bl in (spec.get("optional") or []) if bl_ids.get(bl, 0) > 0
    ]

    matched_structural: list[str] = []
    for hook_name in spec.get("structural") or []:
        hook = STRUCTURAL_HOOKS.get(hook_name)
        if hook is None:
            continue
        if hook(data):
            matched_structural.append(hook_name)

    # A7 requires its structural hook (generate_mode_trunk). Other archetypes
    # that list structural hooks use them as confidence boosts, not gates.
    if arch_id == "A7" and "generate_mode_trunk" not in matched_structural:
        return None
    if arch_id == "A9" and "join_is_primary_verb" not in matched_structural:
        return None

    # Bonus hooks: optional, each adds its configured weight when passing.
    bonus_total = 0.0
    bonus_hits: list[str] = []
    bonuses = spec.get("structural_bonuses") or {}
    for hook_name, weight in bonuses.items():
        hook = STRUCTURAL_HOOKS.get(hook_name)
        if hook is None:
            continue
        if hook(data):
            bonus_hits.append(hook_name)
            bonus_total += float(weight or 0.0)

    priority_boost = float(spec.get("priority_boost", 0.0) or 0.0)
    confidence = (
        0.6
        + 0.05 * len(matched_optional)
        + 0.1 * len(matched_structural)
        + bonus_total
        + priority_boost
    )
    confidence = max(0.0, min(1.0, round(confidence, 3)))
    matched_structural = matched_structural + bonus_hits

    matched_subtypes = _match_subtypes(spec, bl_ids)

    return ArchetypeMatch(
        id=arch_id,
        name=spec.get("name", arch_id),
        confidence=confidence,
        matched_required=matched_required,
        matched_optional=matched_optional,
        matched_structural=matched_structural,
        matched_subtypes=matched_subtypes,
    )


def _detect_mechanics(
    data: dict,
    mechanics_spec: dict,
    primary_id: str | None,
    groups_by_name: dict[str, dict] | None = None,
) -> list[str]:
    bl_ids = _bl_id_counter_with_subgroups(data, groups_by_name)
    active: list[str] = []
    for mid, spec in (mechanics_spec or {}).items():
        node_list = spec.get("nodes") or []
        min_match = spec.get("min_match", 1)
        present = sum(1 for n in node_list if bl_ids.get(n, 0) > 0)
        if present < min_match:
            continue
        # M2 (Join-as-Glue) defers to A9 when A9 is primary
        if mid == "M2" and primary_id == "A9":
            continue
        active.append(mid)
    return active


def detect_group(
    data: dict,
    spec: dict,
    blend: str = "",
    groups_by_name: dict[str, dict] | None = None,
) -> DetectionResult:
    archetype_spec = spec.get("archetypes", {}) or {}

    # First pass: local signatures only, so sub-group contents don't dilute
    # the classification of a group that has clear local evidence.
    matches: list[ArchetypeMatch] = []
    for aid, aspec in archetype_spec.items():
        m = _score_archetype(aid, aspec, data, groups_by_name=None)
        if m is not None:
            matches.append(m)

    cross_layer_used = False
    # Fallback: if local signatures yield nothing, try unioning sub-group
    # bl_idnames. This rescues pure wrapper groups (Tree Moss calls Moss).
    if not matches and groups_by_name:
        for aid, aspec in archetype_spec.items():
            m = _score_archetype(aid, aspec, data, groups_by_name=groups_by_name)
            if m is not None:
                matches.append(m)
        cross_layer_used = bool(matches)

    matches.sort(key=lambda x: (-x.confidence, x.id))
    primary = matches[0].id if matches else None
    secondaries = [m.id for m in matches[1:]]
    mechanics = _detect_mechanics(
        data, spec.get("mechanics", {}) or {}, primary, groups_by_name
    )

    return DetectionResult(
        blend=blend,
        group=data.get("group", ""),
        node_count=data.get("node_count", 0),
        link_count=data.get("link_count", 0),
        primary=primary,
        secondaries=secondaries,
        mechanics=mechanics,
        matches=matches,
        cross_layer=cross_layer_used,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _iter_reference_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.rglob("*.json")):
        if p.name.endswith("-summary.json"):
            continue
        if "gn_kb" in p.parts:
            continue
        if "texts" in p.parts:
            continue
        out.append(p)
    return out


def _render_markdown(results: list[DetectionResult]) -> str:
    by_blend: dict[str, list[DetectionResult]] = {}
    for r in results:
        by_blend.setdefault(r.blend, []).append(r)

    lines = ["# Archetype detection report\n"]
    for blend in sorted(by_blend):
        lines.append(f"## {blend}")
        for r in sorted(by_blend[blend], key=lambda x: x.group):
            primary = r.primary or "—"
            secs = ", ".join(r.secondaries) if r.secondaries else "—"
            mechs = ", ".join(r.mechanics) if r.mechanics else "—"
            conf = r.matches[0].confidence if r.matches else 0.0
            sub_tags = []
            for m in r.matches:
                for s in m.matched_subtypes:
                    sub_tags.append(s)
            sub_str = f" [{', '.join(sub_tags)}]" if sub_tags else ""
            lines.append(
                f"- **{r.group}** ({r.node_count}n/{r.link_count}l): "
                f"primary=`{primary}`{sub_str} "
                f"(conf {conf:.2f}); secondaries=[{secs}]; mechanics=[{mechs}]"
            )
        lines.append("")
    return "\n".join(lines)


def _result_to_dict(r: DetectionResult) -> dict[str, Any]:
    d = asdict(r)
    return d


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spec",
        type=Path,
        default=SPEC_PATH,
        help="Path to archetypes.yaml",
    )
    parser.add_argument(
        "--refs",
        type=Path,
        default=REFS_DIR,
        help="Root directory to scan for reference JSONs",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=ROOT / "tests" / "golden" / "archetype_report.json",
        help="Where to write the structured JSON report",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=ROOT / "tests" / "golden" / "archetype_report.md",
        help="Where to write the markdown summary",
    )
    parser.add_argument(
        "--single",
        type=Path,
        help="Detect a single JSON file and print result to stdout",
    )
    args = parser.parse_args()

    spec = yaml.safe_load(args.spec.read_text(encoding="utf-8"))

    if args.single:
        payload = json.loads(args.single.read_text(encoding="utf-8"))
        data = payload.get("data") or payload
        result = detect_group(data, spec, blend=payload.get("blend_name", ""))
        print(json.dumps(_result_to_dict(result), indent=2, ensure_ascii=False))
        return

    # Phase 1: load every group, indexed per-blend so cross-layer unions
    # can look up sub-group contents by name.
    blend_groups: dict[str, dict[str, dict]] = {}
    entries: list[tuple[Path, dict, dict]] = []
    skipped: list[tuple[Path, str]] = []
    for json_file in _iter_reference_files(args.refs):
        try:
            payload = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as exc:
            skipped.append((json_file, str(exc)))
            continue
        data = payload.get("data")
        if not data:
            skipped.append((json_file, "missing 'data' key"))
            continue
        blend_name = payload.get("blend_name", json_file.parent.name)
        group_name = data.get("group", json_file.stem)
        blend_groups.setdefault(blend_name, {})[group_name] = data
        entries.append((json_file, payload, data))

    # Phase 2: detect archetypes with the cross-layer map in hand.
    results: list[DetectionResult] = []
    for json_file, payload, data in entries:
        blend_name = payload.get("blend_name", json_file.parent.name)
        groups_by_name = blend_groups.get(blend_name)
        result = detect_group(data, spec, blend=blend_name, groups_by_name=groups_by_name)
        results.append(result)

    args.out_json.write_text(
        json.dumps(
            {
                "count": len(results),
                "skipped": [(str(p), why) for p, why in skipped],
                "results": [_result_to_dict(r) for r in results],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    args.out_md.write_text(_render_markdown(results), encoding="utf-8")

    print(f"Detected {len(results)} groups. Skipped {len(skipped)}.")
    print(f"  JSON: {args.out_json}")
    print(f"  MD:   {args.out_md}")


if __name__ == "__main__":
    main()
