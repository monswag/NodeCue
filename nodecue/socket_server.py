"""TCP socket server running inside Blender for MCP bridge communication.

Listens on localhost:9877 (configurable). Commands arrive as JSON over a simple
length-prefixed protocol: 4-byte big-endian length header + UTF-8 JSON body.
Responses use the same framing.

All bpy operations are executed on the main thread via bpy.app.timers.
"""

from __future__ import annotations

import difflib
import json
import logging
import socket
import struct
import threading
import traceback
import ast
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
# Package-relative so the skill resolves in every install layout
# (zip install, sibling install, dev repo).
_PACKAGE_DIR = Path(__file__).resolve().parent
_SKILL_RULES_DIR = _PACKAGE_DIR / "skills" / "geometry-nodes" / "rules"

# Node-tree-capable types outside the GeometryNode/FunctionNode/ShaderNode prefixes.
_EXTRA_NODE_TYPE_NAMES = ("NodeGroupInput", "NodeGroupOutput", "NodeFrame", "NodeReroute")
_KNOWN_GN_NODE_CANDIDATES: list[dict[str, str]] | None = None

# Lazy imports — only available inside Blender.
_bpy = None


def _get_bpy():
    global _bpy
    if _bpy is None:
        import bpy

        _bpy = bpy
    return _bpy


_NUMERIC_TYPES = {"VALUE", "INT", "FLOAT"}
_SOCKET_ALIASES: dict[str, str] = {
    "fac": "Factor",
    "output": "Result",
    "val": "Value",
    "color": "Color",
    "vec": "Vector",
    "pos": "Position",
    "geo": "Geometry",
    "geom": "Geometry",
    "normal": "Normal",
    "instances": "Instances",
    "mesh": "Mesh",
    "offset": "Offset",
    "scale": "Scale",
    "radius": "Radius",
}

_INTERFACE_SOCKET_TYPE_ALIASES: dict[str, str] = {
    "VALUE": "NodeSocketFloat",
    "FLOAT": "NodeSocketFloat",
    "INT": "NodeSocketInt",
    "INTEGER": "NodeSocketInt",
    "BOOLEAN": "NodeSocketBool",
    "BOOL": "NodeSocketBool",
    "VECTOR": "NodeSocketVector",
    "ROTATION": "NodeSocketRotation",
    "COLOR": "NodeSocketColor",
    "RGBA": "NodeSocketColor",
    "STRING": "NodeSocketString",
    "OBJECT": "NodeSocketObject",
    "COLLECTION": "NodeSocketCollection",
    "IMAGE": "NodeSocketImage",
    "MATERIAL": "NodeSocketMaterial",
    "GEOMETRY": "NodeSocketGeometry",
}

_GENERIC_NODE_PROPERTY_IDS = {
    "color",
    "dimensions",
    "height",
    "hide",
    "label_size",
    "location",
    "mute",
    "parent",
    "select",
    "show_options",
    "show_preview",
    "show_texture",
    "use_custom_color",
    "warning_propagation",
    "width",
    "width_hidden",
}


def _types_compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    if a in _NUMERIC_TYPES and b in _NUMERIC_TYPES:
        return True
    if (a in _NUMERIC_TYPES and b == "VECTOR") or (a == "VECTOR" and b in _NUMERIC_TYPES):
        return True
    return False


def _is_geometry_like_socket_name(name: str) -> bool:
    raw = str(name or "").strip()
    if not raw:
        return True
    canonical = _SOCKET_ALIASES.get(raw.lower(), raw)
    return str(canonical).lower() == "geometry"


def _humanize_bl_idname(bl_idname: str) -> str:
    text = re.sub(r"^(GeometryNode|FunctionNode|ShaderNode|Node)", "", bl_idname or "")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return text.strip() or bl_idname


def _load_gn_node_candidates_from_rules() -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    if not _SKILL_RULES_DIR.exists():
        return candidates

    pattern = re.compile(
        r"^###\s+(?P<label>.+?)\s+—\s+`(?P<bl_idname>(?:GeometryNode|FunctionNode|ShaderNode|Node)[^`]+)`",
        re.MULTILINE,
    )
    for path in sorted(_SKILL_RULES_DIR.glob("*.md")):
        if path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            candidates.append(
                {
                    "bl_idname": match.group("bl_idname").strip(),
                    "label": match.group("label").strip(),
                }
            )
    return candidates


def _load_gn_node_candidates_from_bpy() -> list[dict[str, str]]:
    """Enumerate registered node types from the running Blender.

    Always matches the user's actual Blender version, unlike any shipped
    snapshot. Returns [] outside Blender so callers can fall back.
    """
    try:
        bpy = _get_bpy()
        type_names = [
            name
            for name in dir(bpy.types)
            if name.startswith(("GeometryNode", "FunctionNode", "ShaderNode"))
        ]
        type_names.extend(_EXTRA_NODE_TYPE_NAMES)
        candidates: list[dict[str, str]] = []
        for type_name in type_names:
            cls = getattr(bpy.types, type_name, None)
            if cls is None:
                continue
            label = str(
                getattr(getattr(cls, "bl_rna", None), "name", "")
                or _humanize_bl_idname(type_name)
            ).strip()
            candidates.append({"bl_idname": type_name, "label": label})
        return candidates
    except Exception:
        return []


def _load_gn_node_candidates() -> list[dict[str, str]]:
    global _KNOWN_GN_NODE_CANDIDATES
    if _KNOWN_GN_NODE_CANDIDATES is not None:
        return _KNOWN_GN_NODE_CANDIDATES

    candidates = _load_gn_node_candidates_from_bpy()
    if not candidates:
        candidates = _load_gn_node_candidates_from_rules()

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        bl_idname = candidate.get("bl_idname", "")
        if not bl_idname or bl_idname in seen:
            continue
        seen.add(bl_idname)
        deduped.append(
            {
                "bl_idname": bl_idname,
                "label": candidate.get("label", "") or _humanize_bl_idname(bl_idname),
            }
        )

    _KNOWN_GN_NODE_CANDIDATES = deduped
    return _KNOWN_GN_NODE_CANDIDATES


def _suggest_bl_idnames(candidate: str, limit: int = 5) -> list[dict[str, str]]:
    if not candidate:
        return []
    known = _load_gn_node_candidates()
    if not known:
        return []
    by_id = {entry["bl_idname"]: entry for entry in known}
    matches = difflib.get_close_matches(candidate, list(by_id), n=limit, cutoff=0.5)
    return [by_id[match] for match in matches]


def _serialize_socket_spec(sock, *, include_has_default: bool) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "name": sock.name,
        "identifier": getattr(sock, "identifier", sock.name),
        "type": getattr(sock, "type", ""),
    }
    if include_has_default:
        spec["has_default"] = hasattr(sock, "default_value")
    return spec


def _serialize_socket_specs(sockets, *, include_has_default: bool) -> list[dict[str, Any]]:
    return [_serialize_socket_spec(sock, include_has_default=include_has_default) for sock in sockets]


def _node_base_property_ids(bpy) -> set[str]:
    ids = set(_GENERIC_NODE_PROPERTY_IDS)
    try:
        props = getattr(getattr(bpy.types, "Node", None), "bl_rna", None)
        props = getattr(props, "properties", []) if props is not None else []
        ids.update(getattr(meta, "identifier", "") for meta in props if getattr(meta, "identifier", ""))
    except Exception:
        pass
    return ids


def _serialize_property_spec(meta) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "identifier": getattr(meta, "identifier", ""),
        "name": getattr(meta, "name", "") or getattr(meta, "identifier", ""),
        "type": getattr(meta, "type", ""),
    }
    if spec["type"] == "ENUM":
        spec["valid_values"] = [item.identifier for item in getattr(meta, "enum_items", [])]
    return spec


def _settable_property_specs(bpy, node) -> list[dict[str, Any]]:
    try:
        props = list(getattr(node.bl_rna, "properties", []))
    except Exception:
        return []

    generic_ids = _node_base_property_ids(bpy)
    out: list[dict[str, Any]] = []
    for meta in props:
        identifier = getattr(meta, "identifier", "")
        if not identifier or identifier in generic_ids:
            continue
        if getattr(meta, "is_hidden", False) or getattr(meta, "is_readonly", False):
            continue
        out.append(_serialize_property_spec(meta))
    return out


def _socket_missing_hint(node_name: str, socket_name: str, in_out: str) -> str | None:
    if node_name == "Group Input" and not _is_geometry_like_socket_name(socket_name):
        return (
            "Group Input parameter socket is missing. "
            "Create it first via MCP add_group_socket(tree_name, name, socket_type, in_out='INPUT')."
        )
    if node_name == "Group Output" and not _is_geometry_like_socket_name(socket_name):
        return (
            "Group Output parameter socket is missing. "
            "Create it first via MCP add_group_socket(tree_name, name, socket_type, in_out='OUTPUT')."
        )
    if in_out == "INPUT":
        return "Call get_tree_info and use exact input socket names/identifiers."
    return "Call get_tree_info and use exact output socket names/identifiers."


def _find_socket_in_list(sockets, name: str, *, allow_geometry_fallback: bool = True):
    if not sockets:
        return None
    for s in sockets:
        if s.name == name:
            return s
    for s in sockets:
        if getattr(s, "identifier", None) == name:
            return s
    name_lower = name.lower()
    for s in sockets:
        if s.name.lower() == name_lower:
            return s
    for s in sockets:
        identifier = getattr(s, "identifier", None)
        if isinstance(identifier, str) and identifier.lower() == name_lower:
            return s
    canonical = _SOCKET_ALIASES.get(name_lower)
    if canonical:
        for s in sockets:
            if s.name == canonical:
                return s
        for s in sockets:
            if getattr(s, "identifier", None) == canonical:
                return s
    if allow_geometry_fallback:
        for s in sockets:
            if getattr(s, "type", "") == "GEOMETRY":
                return s
    return None


def _find_output_socket(node, name: str, *, allow_geometry_fallback: bool = True):
    return _find_socket_in_list(node.outputs, name, allow_geometry_fallback=allow_geometry_fallback)


def _find_input_socket(node, name: str, *, allow_geometry_fallback: bool = True):
    return _find_socket_in_list(node.inputs, name, allow_geometry_fallback=allow_geometry_fallback)


def _socket_has_incoming_link(tree, socket_obj) -> bool:
    for link in tree.links:
        if getattr(link, "to_socket", None) == socket_obj:
            return True
    return False


def _prefer_unlinked_duplicate_input_socket(tree, node, requested_name: str, resolved_socket):
    """When multiple input sockets share one display name, pick an unlinked one first.

    If caller specifies an identifier explicitly (e.g. Value_001), keep that exact socket.
    """
    if resolved_socket is None:
        return None

    raw = str(requested_name or "").strip()
    if not raw:
        return resolved_socket

    raw_lower = raw.lower()
    canonical = _SOCKET_ALIASES.get(raw_lower)
    candidates = []
    for s in node.inputs:
        if s.name == raw or s.name.lower() == raw_lower:
            candidates.append(s)
            continue
        if canonical and (s.name == canonical or s.name.lower() == canonical.lower()):
            candidates.append(s)

    if len(candidates) > 1 and resolved_socket in candidates:
        for candidate in candidates:
            if not _socket_has_incoming_link(tree, candidate):
                return candidate
        return resolved_socket

    for s in node.inputs:
        identifier = getattr(s, "identifier", None)
        if isinstance(identifier, str) and (identifier == raw or identifier.lower() == raw_lower):
            return resolved_socket

    if len(candidates) <= 1 or resolved_socket not in candidates:
        return resolved_socket
    return resolved_socket


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _resolve_node_property(node, key: str):
    props = getattr(getattr(node, "bl_rna", None), "properties", None)
    if props is None:
        return key, None

    prop = props.get(key)
    if prop is not None:
        return key, prop

    key_lower = key.lower()
    for p in props:
        if getattr(p, "identifier", "").lower() == key_lower:
            return p.identifier, p

    normalized = _normalize_key(key)
    for p in props:
        pid = getattr(p, "identifier", "")
        pname = getattr(p, "name", "")
        if _normalize_key(pid) == normalized or _normalize_key(pname) == normalized:
            return pid, p

    return key, None


def _collect_enum_properties(node) -> dict[str, dict[str, Any]]:
    """Collect readable enum-like properties for node diagnostics."""
    props = getattr(getattr(node, "bl_rna", None), "properties", None)
    if props is None:
        return {}

    out: dict[str, dict[str, Any]] = {}
    for prop in props:
        pid = getattr(prop, "identifier", "")
        if not pid or pid in {"rna_type"}:
            continue
        if getattr(prop, "type", "") != "ENUM":
            continue
        if getattr(prop, "is_hidden", False):
            continue
        try:
            value = getattr(node, pid)
        except Exception:
            continue
        items = [it.identifier for it in getattr(prop, "enum_items", [])]
        out[pid] = {"value": _serialize_value(value), "items": items}
    return out


def _resolve_id_pointer_value(bpy, fixed_type: str, value: Any):
    if value is None:
        return None
    if not isinstance(value, str):
        return value

    if fixed_type == "Object":
        return bpy.data.objects.get(value)
    if fixed_type == "Material":
        return bpy.data.materials.get(value)
    if fixed_type == "Collection":
        return bpy.data.collections.get(value)
    if fixed_type == "Image":
        return bpy.data.images.get(value)
    if fixed_type == "Texture":
        return bpy.data.textures.get(value) if hasattr(bpy.data, "textures") else None
    if fixed_type == "Text":
        return bpy.data.texts.get(value) if hasattr(bpy.data, "texts") else None
    return value


def _match_enum_item(enum_items: list[str], value: str) -> str | None:
    if value in enum_items:
        return value
    value_lower = value.lower()
    for item in enum_items:
        if item.lower() == value_lower:
            return item
    normalized = _normalize_key(value)
    for item in enum_items:
        if _normalize_key(item) == normalized:
            return item
    return None


def _extract_enum_options_from_error(error_text: str) -> list[str]:
    marker = "not found in "
    idx = error_text.find(marker)
    if idx < 0:
        return []
    raw = error_text[idx + len(marker):].strip()
    try:
        parsed = ast.literal_eval(raw)
    except Exception:
        return []
    if not isinstance(parsed, tuple):
        return []
    return [str(x) for x in parsed]


def _coerce_socket_default_value(bpy, sock, value: Any):
    meta = None
    try:
        meta = sock.bl_rna.properties.get("default_value")
    except Exception:
        meta = None
    if meta is None:
        return value

    ptype = getattr(meta, "type", "")
    if ptype == "POINTER":
        fixed_type = getattr(getattr(meta, "fixed_type", None), "identifier", "")
        return _resolve_id_pointer_value(bpy, fixed_type, value)
    if ptype == "ENUM":
        items = [it.identifier for it in getattr(meta, "enum_items", [])]
        if items and isinstance(value, str):
            matched = _match_enum_item(items, value)
            if matched is not None:
                return matched
    if ptype == "BOOLEAN" or getattr(sock, "type", "") == "BOOLEAN":
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)

    # Coerce numeric types — agents often send strings like "0.5" or "10"
    sock_type = getattr(sock, "type", "")
    if ptype == "FLOAT" or sock_type == "VALUE":
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                pass
        elif isinstance(value, (int, bool)):
            return float(value)
    if ptype == "INT" or sock_type == "INT":
        if isinstance(value, str):
            try:
                return int(float(value))
            except ValueError:
                pass
        elif isinstance(value, float):
            return int(value)

    # Coerce vector types — scalar to 3-vector, string elements to float
    if sock_type == "VECTOR":
        if isinstance(value, (int, float)):
            v = float(value)
            return (v, v, v)
        if isinstance(value, (list, tuple)) and len(value) == 3:
            try:
                return tuple(float(x) for x in value)
            except (ValueError, TypeError):
                pass

    return value


def _coerce_property_value(bpy, node, prop, value: Any):
    ptype = getattr(prop, "type", "")
    if ptype == "ENUM":
        valid_items = [it.identifier for it in getattr(prop, "enum_items", [])]
        if getattr(prop, "is_enum_flag", False):
            if isinstance(value, str):
                values = [value]
            elif isinstance(value, (list, tuple, set)):
                values = list(value)
            else:
                raise ValueError(f"enum flag property '{prop.identifier}' requires string or list of strings")
            out = set()
            for item in values:
                if not isinstance(item, str):
                    raise ValueError(f"enum flag property '{prop.identifier}' contains non-string value")
                matched = _match_enum_item(valid_items, item)
                if matched is None:
                    raise ValueError(f"invalid enum value '{item}' for '{prop.identifier}'")
                out.add(matched)
            return out

        if not isinstance(value, str):
            raise ValueError(f"enum property '{prop.identifier}' requires string value")
        matched = _match_enum_item(valid_items, value)
        if matched is None:
            raise ValueError(f"invalid enum value '{value}' for '{prop.identifier}'")
        return matched

    if ptype == "POINTER":
        fixed_type = getattr(getattr(prop, "fixed_type", None), "identifier", "")
        return _resolve_id_pointer_value(bpy, fixed_type, value)

    return value


def _normalize_interface_socket_type(socket_type: str) -> str:
    if not socket_type:
        return "NodeSocketFloat"
    if socket_type.startswith("NodeSocket"):
        return socket_type
    return _INTERFACE_SOCKET_TYPE_ALIASES.get(socket_type.upper(), socket_type)


# ---------------------------------------------------------------------------
# Protocol helpers
# ---------------------------------------------------------------------------

_HEADER_FMT = "!I"  # 4-byte unsigned int, big-endian
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_MAX_MSG_SIZE = 16 * 1024 * 1024  # 16 MB


def _recv_msg(conn: socket.socket) -> dict | None:
    header = b""
    while len(header) < _HEADER_SIZE:
        chunk = conn.recv(_HEADER_SIZE - len(header))
        if not chunk:
            return None
        header += chunk
    (length,) = struct.unpack(_HEADER_FMT, header)
    if length > _MAX_MSG_SIZE:
        return None
    data = b""
    while len(data) < length:
        chunk = conn.recv(length - len(data))
        if not chunk:
            return None
        data += chunk
    return json.loads(data.decode("utf-8"))


def _send_msg(conn: socket.socket, obj: dict) -> None:
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    conn.sendall(struct.pack(_HEADER_FMT, len(body)) + body)


# ---------------------------------------------------------------------------
# Command handlers — each returns a result dict (executed on main thread)
# ---------------------------------------------------------------------------


def _cmd_ping(_params: dict) -> dict:
    return {"message": "pong"}


def _cmd_create_node_tree(params: dict) -> dict:
    bpy = _get_bpy()
    name = params.get("name", "NodeCue")

    # Guard: warn if a tree with this name already exists.
    existing = bpy.data.node_groups.get(name)
    if existing is not None:
        return {
            "ok": True,
            "warning": f"Tree '{name}' already exists. Returning existing tree instead of creating a duplicate.",
            "tree_name": existing.name,
            "already_existed": True,
        }

    obj = bpy.context.active_object
    if obj is None:
        # Create a default mesh object.
        bpy.ops.mesh.primitive_plane_add()
        obj = bpy.context.active_object

    if obj.type != "MESH":
        return {"error": f"active object type is {obj.type}, expected MESH"}

    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")

    # Add geometry interface sockets.
    if hasattr(tree, "interface"):
        tree.interface.new_socket(
            name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
        )
        tree.interface.new_socket(
            name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
        )

    # Create Group Input/Output nodes.
    group_in = tree.nodes.new("NodeGroupInput")
    group_out = tree.nodes.new("NodeGroupOutput")
    group_in.location = (-700, 0)
    group_out.location = (700, 0)

    # Connect input geometry to output geometry.
    out_sock = _find_output_socket(group_in, "Geometry")
    in_sock = _find_input_socket(group_out, "Geometry")
    if out_sock and in_sock:
        tree.links.new(out_sock, in_sock)

    mod = obj.modifiers.new(name=name, type="NODES")
    mod.node_group = tree

    return {
        "tree_name": tree.name,
        "modifier_name": mod.name,
        "object_name": obj.name,
    }


def _cmd_create_node(params: dict) -> dict:
    bpy = _get_bpy()
    tree_name = params.get("tree_name", "")
    bl_idname = params.get("bl_idname", "")
    requested_name = str(params.get("name", "")).strip()
    label = str(params.get("label", "")).strip()
    loc_x = params.get("location_x", 0)
    loc_y = params.get("location_y", 0)

    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        return {"error": f"node tree '{tree_name}' not found"}

    try:
        node = tree.nodes.new(bl_idname)
    except Exception as exc:
        result: dict[str, Any] = {"error": f"failed to create node '{bl_idname}': {exc}"}
        suggestions = _suggest_bl_idnames(bl_idname)
        result["details"] = {
            "requested_bl_idname": bl_idname,
            "suggestions": suggestions,
            "hint": "bl_idname not recognized; try one of the suggestions or look it up in the skill rules.",
        }
        return result

    node.location = (loc_x, loc_y)
    if requested_name:
        node.name = requested_name
    if label:
        node.label = label

    return {
        "node_name": node.name,
        "requested_name": requested_name,
        "bl_idname": node.bl_idname,
        "label": node.label,
        "location": [node.location.x, node.location.y],
        "inputs": [{"name": s.name, "identifier": getattr(s, "identifier", s.name), "type": s.type} for s in node.inputs],
        "outputs": [
            {
                "name": s.name,
                "identifier": getattr(s, "identifier", s.name),
                "type": s.type,
                "default_value": _serialize_value(getattr(s, "default_value", None)),
            }
            for s in node.outputs
        ],
    }


def _cmd_connect(params: dict) -> dict:
    bpy = _get_bpy()
    tree_name = params.get("tree_name", "")
    from_node_name = params.get("from_node", "")
    from_socket_name = params.get("from_socket", "")
    to_node_name = params.get("to_node", "")
    to_socket_name = params.get("to_socket", "")
    validate_only = bool(params.get("validate_only", False))

    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        return {"error": f"node tree '{tree_name}' not found"}

    from_node = tree.nodes.get(from_node_name)
    to_node = tree.nodes.get(to_node_name)
    if from_node is None:
        return {"error": f"node '{from_node_name}' not found"}
    if to_node is None:
        return {"error": f"node '{to_node_name}' not found"}

    out_sock = _find_output_socket(from_node, from_socket_name, allow_geometry_fallback=False)
    if out_sock is None and _is_geometry_like_socket_name(from_socket_name):
        out_sock = _find_output_socket(from_node, from_socket_name, allow_geometry_fallback=True)

    in_sock = _find_input_socket(to_node, to_socket_name, allow_geometry_fallback=False)
    if in_sock is None and _is_geometry_like_socket_name(to_socket_name):
        in_sock = _find_input_socket(to_node, to_socket_name, allow_geometry_fallback=True)
    in_sock = _prefer_unlinked_duplicate_input_socket(tree, to_node, to_socket_name, in_sock)

    if out_sock is None:
        return {
            "error": f"output socket '{from_socket_name}' not found on '{from_node_name}'",
            "details": {
                "from_node": from_node_name,
                "requested_from_socket": from_socket_name,
                "available_from_outputs": _serialize_socket_specs(
                    from_node.outputs, include_has_default=False
                ),
                "to_node": to_node_name,
                "requested_to_socket": to_socket_name,
                "available_to_inputs": _serialize_socket_specs(
                    to_node.inputs, include_has_default=False
                ),
                "hint": _socket_missing_hint(from_node_name, from_socket_name, "OUTPUT"),
            },
        }
    if in_sock is None:
        return {
            "error": f"input socket '{to_socket_name}' not found on '{to_node_name}'",
            "details": {
                "from_node": from_node_name,
                "requested_from_socket": from_socket_name,
                "available_from_outputs": _serialize_socket_specs(
                    from_node.outputs, include_has_default=False
                ),
                "to_node": to_node_name,
                "requested_to_socket": to_socket_name,
                "available_to_inputs": _serialize_socket_specs(
                    to_node.inputs, include_has_default=False
                ),
                "hint": _socket_missing_hint(to_node_name, to_socket_name, "INPUT"),
            },
        }

    out_type = getattr(out_sock, "type", "")
    in_type = getattr(in_sock, "type", "")
    compatible = _types_compatible(out_type, in_type)
    if not compatible:
        return {
            "error": "socket types are incompatible",
            "details": {
                "from_socket": out_sock.name,
                "from_type": out_type,
                "to_socket": in_sock.name,
                "to_type": in_type,
            },
        }

    if validate_only:
        return {
            "validated": True,
            "connected": False,
            "from_socket": out_sock.name,
            "to_socket": in_sock.name,
            "from_type": out_type,
            "to_type": in_type,
        }

    try:
        tree.links.new(out_sock, in_sock)
    except Exception as exc:
        return {
            "error": f"failed to connect: {exc}",
            "details": {
                "from_socket": out_sock.name,
                "to_socket": in_sock.name,
            },
        }

    return {
        "connected": True,
        "validated": True,
        "from_socket": out_sock.name,
        "to_socket": in_sock.name,
        "from_type": out_type,
        "to_type": in_type,
    }


def _cmd_disconnect_sockets(params: dict) -> dict:
    bpy = _get_bpy()
    tree_name = params.get("tree_name", "")
    from_node_name = params.get("from_node", "")
    from_socket_name = params.get("from_socket", "")
    to_node_name = params.get("to_node", "")
    to_socket_name = params.get("to_socket", "")

    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        return {"error": f"node tree '{tree_name}' not found"}

    from_node = tree.nodes.get(from_node_name)
    to_node = tree.nodes.get(to_node_name)
    if from_node is None:
        return {"error": f"node '{from_node_name}' not found"}
    if to_node is None:
        return {"error": f"node '{to_node_name}' not found"}

    out_sock = _find_output_socket(from_node, from_socket_name)
    in_sock = _find_input_socket(to_node, to_socket_name)
    if out_sock is None:
        return {"error": f"output socket '{from_socket_name}' not found"}
    if in_sock is None:
        return {"error": f"input socket '{to_socket_name}' not found"}

    removed = 0
    for link in list(tree.links):
        if link.from_socket == out_sock and link.to_socket == in_sock:
            tree.links.remove(link)
            removed += 1

    return {"removed": removed}


def _cmd_set_input_default(params: dict) -> dict:
    bpy = _get_bpy()
    tree_name = params.get("tree_name", "")
    node_name = params.get("node_name", "")
    socket_name = params.get("socket_name", "")
    value = params.get("value")

    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        return {"error": f"node tree '{tree_name}' not found"}

    node = tree.nodes.get(node_name)
    if node is None:
        return {"error": f"node '{node_name}' not found"}

    sock = _find_input_socket(node, socket_name, allow_geometry_fallback=False)
    if sock is None:
        # Some nodes, such as ShaderNodeValue, expose the editable number on an
        # output socket's default_value rather than on an input socket.
        sock = _find_output_socket(node, socket_name, allow_geometry_fallback=False)
    elif not hasattr(sock, "default_value"):
        # Some nodes reuse identifiers on both sides. If the input side is not
        # editable, allow writing a same-key output default (e.g. Menu Switch).
        out_sock = _find_output_socket(node, socket_name, allow_geometry_fallback=False)
        if out_sock is not None and hasattr(out_sock, "default_value"):
            sock = out_sock
    if sock is None:
        return {
            "error": f"input socket '{socket_name}' not found on '{node_name}'",
            "details": {
                "requested_socket": socket_name,
                "available_inputs": _serialize_socket_specs(
                    node.inputs, include_has_default=True
                ),
                "available_outputs": _serialize_socket_specs(
                    node.outputs, include_has_default=True
                ),
                "hint": "use an exact socket name/identifier from the returned lists; duplicate labels require the identifier.",
            },
        }
    if not hasattr(sock, "default_value"):
        return {
            "error": f"socket '{socket_name}' on '{node_name}' has no default value",
            "details": {
                "requested_socket": socket_name,
                "available_inputs": _serialize_socket_specs(
                    node.inputs, include_has_default=True
                ),
                "available_outputs": _serialize_socket_specs(
                    node.outputs, include_has_default=True
                ),
                "hint": "some nodes expose the editable value on an output socket (e.g. Value). Try the other side.",
            },
        }

    coerced_value = _coerce_socket_default_value(bpy, sock, value)
    if hasattr(sock, "bl_idname") and "NodeSocketMenu" in str(getattr(sock, "bl_idname", "")) and isinstance(value, str):
        # NodeSocketMenu does not expose enum_items in RNA; if user casing/spacing
        # does not match exactly, parse Blender's enum error once and retry.
        try:
            sock.default_value = coerced_value
            return {"set": True, "socket": sock.name}
        except Exception as exc:
            options = _extract_enum_options_from_error(str(exc))
            matched = _match_enum_item(options, value) if options else None
            if matched is None:
                return {"error": f"failed to set default value: {exc}"}
            try:
                sock.default_value = matched
            except Exception as retry_exc:
                return {"error": f"failed to set default value: {retry_exc}"}
            return {"set": True, "socket": sock.name}

    try:
        sock.default_value = coerced_value
    except Exception as exc:
        return {"error": f"failed to set default value: {exc}"}

    return {"set": True, "socket": sock.name}


def _cmd_delete_node(params: dict) -> dict:
    bpy = _get_bpy()
    tree_name = params.get("tree_name", "")
    node_name = params.get("node_name", "")

    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        return {"error": f"node tree '{tree_name}' not found"}

    node = tree.nodes.get(node_name)
    if node is None:
        return {"error": f"node '{node_name}' not found"}

    tree.nodes.remove(node)
    return {"deleted": node_name}


def _resolve_tree(params: dict):
    """Resolve a node tree by name, or fall back to the active object's GN modifier."""
    bpy = _get_bpy()
    tree_name = params.get("tree_name", "").strip()

    if tree_name:
        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            return None, {"error": f"node tree '{tree_name}' not found"}
        return tree, None

    # No tree_name — find from active object's GN modifier
    obj = bpy.context.active_object
    if obj is None:
        return None, {"error": "no tree_name provided and no active object"}

    for mod in getattr(obj, "modifiers", []):
        if getattr(mod, "type", "") == "NODES" and getattr(mod, "node_group", None):
            return mod.node_group, None

    return None, {"error": "no tree_name provided and no geometry nodes modifier on active object"}


def _cmd_add_frame(params: dict) -> dict:
    """Create or update a NodeFrame, set its label, and parent nodes to it.

    Used to teach users by visually grouping logically related nodes
    (e.g. "Driver: Random Scale", "Trunk: Distribute Points").
    """
    bpy = _get_bpy()
    tree_name = params.get("tree_name", "")
    frame_name = str(params.get("frame_name", "")).strip()
    label = str(params.get("label", "")).strip()
    node_names = params.get("node_names") or []
    label_size = params.get("label_size")  # optional int (font size)
    color = params.get("color")  # optional [r, g, b]

    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        return {"error": f"node tree '{tree_name}' not found"}
    if not label:
        return {"error": "missing label"}
    if not isinstance(node_names, list) or not node_names:
        return {"error": "node_names must be a non-empty list"}

    # Validate all node names exist before creating the frame
    missing = [n for n in node_names if tree.nodes.get(n) is None]
    if missing:
        return {"error": f"nodes not found: {missing}"}

    frame = None
    reused_by = ""
    if frame_name:
        candidate = tree.nodes.get(frame_name)
        if candidate is not None and getattr(candidate, "bl_idname", "") != "NodeFrame":
            return {"error": f"node '{frame_name}' is not a frame"}
        if candidate is not None:
            frame = candidate
            reused_by = "frame_name"

    if frame is None:
        for node in tree.nodes:
            if getattr(node, "bl_idname", "") == "NodeFrame" and getattr(node, "label", "") == label:
                frame = node
                reused_by = "label"
                break

    if frame is None:
        existing_parents = []
        for name in node_names:
            node = tree.nodes.get(name)
            parent = getattr(node, "parent", None)
            if parent is not None and getattr(parent, "bl_idname", "") == "NodeFrame":
                existing_parents.append(parent)
        unique_parents = list(dict.fromkeys(existing_parents))
        if len(unique_parents) == 1:
            frame = unique_parents[0]
            reused_by = "existing_parent"

    created = False
    if frame is None:
        try:
            frame = tree.nodes.new("NodeFrame")
        except Exception as exc:
            return {"error": f"failed to create frame: {exc}"}
        if frame_name:
            frame.name = frame_name
        created = True

    frame.label = label
    if isinstance(label_size, (int, float)) and label_size > 0:
        try:
            frame.label_size = int(label_size)
        except Exception:
            pass
    if isinstance(color, (list, tuple)) and len(color) == 3:
        try:
            frame.use_custom_color = True
            frame.color = (float(color[0]), float(color[1]), float(color[2]))
        except Exception:
            pass

    parented = []
    failed = []
    for name in node_names:
        node = tree.nodes.get(name)
        if node is None:
            failed.append(name)
            continue
        try:
            node.parent = frame
            parented.append(name)
        except Exception as exc:
            failed.append(f"{name}: {exc}")

    return {
        "frame_name": frame.name,
        "label": frame.label,
        "created": created,
        "reused_by": reused_by,
        "parented": parented,
        "failed": failed,
    }


def _cmd_get_tree_info(params: dict) -> dict:
    tree, err = _resolve_tree(params)
    if err:
        return err

    summary = bool(params.get("summary", False))

    if summary:
        nodes_summary = []
        for node in tree.nodes:
            bl = getattr(node, "bl_idname", "")
            entry: dict = {"name": node.name, "bl_idname": bl}
            if bl == "NodeGroupInput":
                entry["outputs"] = [s.name for s in node.outputs if s.name]
            elif bl == "NodeGroupOutput":
                entry["inputs"] = [s.name for s in node.inputs if s.name]
            nodes_summary.append(entry)
        links_summary = [
            {"from": link.from_node.name, "from_socket": link.from_socket.name,
             "to": link.to_node.name, "to_socket": link.to_socket.name}
            for link in tree.links
        ]
        return {
            "tree_name": tree.name,
            "node_count": len(nodes_summary),
            "link_count": len(links_summary),
            "nodes": nodes_summary,
            "links": links_summary,
        }

    nodes_info = []
    for node in tree.nodes:
        ref_tree_name = None
        parent_frame = None
        if getattr(node, "bl_idname", "") == "GeometryNodeGroup":
            try:
                nt = node.node_tree
                if nt is not None:
                    ref_tree_name = nt.name
            except Exception as exc:
                log.warning("Failed to read node_tree for %s: %s", node.name, exc)
                ref_tree_name = None
        parent = getattr(node, "parent", None)
        if parent is not None and getattr(parent, "bl_idname", "") == "NodeFrame":
            parent_frame = parent.name
        nodes_info.append(
            {
                "name": node.name,
                "label": getattr(node, "label", "") or "",
                "bl_idname": node.bl_idname,
                "node_tree_name": ref_tree_name,
                "location": [node.location.x, node.location.y],
                "is_selected": bool(getattr(node, "select", False)),
                "parent_frame": parent_frame,
                "enum_properties": _collect_enum_properties(node),
                "inputs": [
                    {
                        "name": s.name,
                        "identifier": getattr(s, "identifier", s.name),
                        "type": s.type,
                        "default_value": _serialize_value(
                            getattr(s, "default_value", None)
                        ),
                        "is_linked": s.is_linked,
                    }
                    for s in node.inputs
                ],
                "outputs": [
                    {
                        "name": s.name,
                        "identifier": getattr(s, "identifier", s.name),
                        "type": s.type,
                        "default_value": _serialize_value(getattr(s, "default_value", None)),
                        "is_linked": s.is_linked,
                    }
                    for s in node.outputs
                ],
            }
        )

    links_info = []
    for link in tree.links:
        links_info.append(
            {
                "from_node": link.from_node.name,
                "from_socket": link.from_socket.name,
                "to_node": link.to_node.name,
                "to_socket": link.to_socket.name,
            }
        )

    frames_info = []
    for node in tree.nodes:
        if getattr(node, "bl_idname", "") != "NodeFrame":
            continue
        child_names = [
            n.name
            for n in tree.nodes
            if getattr(n, "parent", None) == node
        ]
        frames_info.append(
            {
                "name": node.name,
                "label": getattr(node, "label", "") or node.name,
                "color": list(node.color) if getattr(node, "use_custom_color", False) else None,
                "child_nodes": child_names,
            }
        )

    active = getattr(tree.nodes, "active", None)
    active_node = active.name if active else None

    interface_info = []
    if hasattr(tree, "interface"):
        for item in tree.interface.items_tree:
            if not hasattr(item, "socket_type"):
                continue
            interface_info.append(
                {
                    "name": getattr(item, "name", ""),
                    "identifier": getattr(item, "identifier", getattr(item, "name", "")),
                    "in_out": getattr(item, "in_out", ""),
                    "socket_type": getattr(item, "socket_type", ""),
                    "default_value": _serialize_value(getattr(item, "default_value", None)),
                }
            )

    return {
        "tree_name": tree.name,
        "active_node": active_node,
        "nodes": nodes_info,
        "links": links_info,
        "frames": frames_info,
        "interface": interface_info,
    }


def _cmd_list_node_groups(_params: dict) -> dict:
    bpy = _get_bpy()
    groups = []
    for tree in bpy.data.node_groups:
        if tree.type != "GEOMETRY":
            continue
        groups.append({
            "name": tree.name,
            "node_count": len(tree.nodes),
            "is_asset": getattr(tree.asset_data, "description", None) is not None
                        if tree.asset_data else False,
            "asset_tags": [t.name for t in tree.asset_data.tags]
                          if tree.asset_data else [],
        })
    return {"node_groups": groups}


def _cmd_list_scene_objects(_params: dict) -> dict:
    bpy = _get_bpy()
    objects = []
    for obj in bpy.context.scene.objects:
        modifiers = [
            {"name": m.name, "type": m.type}
            for m in obj.modifiers
        ]
        objects.append({
            "name": obj.name,
            "type": obj.type,
            "is_active": obj == bpy.context.active_object,
            "modifiers": modifiers,
        })
    return {"objects": objects}


def _cmd_set_active_object(params: dict) -> dict:
    bpy = _get_bpy()
    name = params.get("name", "")
    obj = bpy.context.scene.objects.get(name)
    if obj is None:
        return {"error": f"object '{name}' not found in scene"}
    bpy.context.view_layer.objects.active = obj
    return {"active_object": obj.name}


def _cmd_add_modifier(params: dict) -> dict:
    bpy = _get_bpy()
    object_name = params.get("object_name", "")
    modifier_name = params.get("modifier_name", "GeometryNodes")
    modifier_type = params.get("modifier_type", "NODES")

    obj = bpy.context.scene.objects.get(object_name)
    if obj is None:
        return {"error": f"object '{object_name}' not found in scene"}

    mod = obj.modifiers.new(name=modifier_name, type=modifier_type)
    result = {"modifier_name": mod.name, "modifier_type": mod.type, "object_name": obj.name}

    # If it's a GN modifier and a node_group was specified, assign it.
    node_group = params.get("node_group", "")
    if node_group and mod.type == "NODES":
        tree = bpy.data.node_groups.get(node_group)
        if tree:
            mod.node_group = tree
            result["node_group"] = tree.name

    return result


def _cmd_remove_modifier(params: dict) -> dict:
    bpy = _get_bpy()
    object_name = params.get("object_name", "")
    modifier_name = params.get("modifier_name", "")

    obj = bpy.context.scene.objects.get(object_name)
    if obj is None:
        return {"error": f"object '{object_name}' not found in scene"}

    mod = obj.modifiers.get(modifier_name)
    if mod is None:
        return {"error": f"modifier '{modifier_name}' not found on '{object_name}'"}

    obj.modifiers.remove(mod)
    return {"removed": modifier_name, "object_name": obj.name}


def _cmd_read_active_tree(_params: dict) -> dict:
    """Read active object's GN tree. Delegates to get_tree_info with empty tree_name."""
    result = _cmd_get_tree_info({})
    if "error" in result:
        return {"ok": False, "error": result["error"]}
    return {"ok": True, "data": result}


def _cmd_set_node_property(params: dict) -> dict:
    bpy = _get_bpy()
    tree_name = params.get("tree_name", "")
    node_name = params.get("node_name", "")
    requested_property_name = params.get("property_name", "")
    value = params.get("value")

    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        return {"error": f"node tree '{tree_name}' not found"}

    node = tree.nodes.get(node_name)
    if node is None:
        return {"error": f"node '{node_name}' not found"}

    property_name, meta = _resolve_node_property(node, requested_property_name)
    if not hasattr(node, property_name):
        property_specs = _settable_property_specs(bpy, node)
        property_ids = [spec["identifier"] for spec in property_specs]
        suggestions = difflib.get_close_matches(
            requested_property_name, property_ids, n=5, cutoff=0.4
        )
        return {
            "error": f"node '{node_name}' has no property '{requested_property_name}'",
            "details": {
                "requested": requested_property_name,
                "available_properties": property_specs,
                "suggestions": suggestions,
                "hint": "check bl_rna.properties or the skill rules for the correct property identifier.",
            },
        }

    try:
        if node.is_property_readonly(property_name):
            return {"error": f"property '{property_name}' is read-only"}
    except Exception:
        pass
    if meta is not None and getattr(meta, "is_hidden", False):
        return {"error": f"property '{property_name}' is hidden and cannot be set"}
    if meta is not None and getattr(meta, "is_readonly", False):
        return {"error": f"property '{property_name}' is read-only"}

    try:
        value = _coerce_property_value(bpy, node, meta, value) if meta is not None else value
    except ValueError as exc:
        details = None
        if meta is not None and getattr(meta, "type", "") == "ENUM":
            details = {"valid_values": [it.identifier for it in getattr(meta, "enum_items", [])]}
        out = {"error": str(exc)}
        if details is not None:
            out["details"] = details
        return out

    try:
        setattr(node, property_name, value)
    except Exception as exc:
        return {"error": f"failed to set property '{property_name}': {exc}"}

    return {
        "set": True,
        "node": node_name,
        "property": property_name,
        "requested_property": requested_property_name,
        "value": _serialize_value(getattr(node, property_name)),
    }


def _cmd_set_node_enum(params: dict) -> dict:
    params = dict(params)
    # Delegate to generic property setter with enum validation path.
    return _cmd_set_node_property(params)


def _resolve_float_curve_target(params: dict):
    bpy = _get_bpy()
    tree_name = params.get("tree_name", "")
    node_name = params.get("node_name", "")
    raw_curve_index = params.get("curve_index", 0)

    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        return None, None, None, {"error": f"node tree '{tree_name}' not found"}

    node = tree.nodes.get(node_name)
    if node is None:
        return None, None, None, {"error": f"node '{node_name}' not found"}

    mapping = getattr(node, "mapping", None)
    if mapping is None:
        return None, None, None, {"error": f"node '{node_name}' has no curve mapping"}

    curves = getattr(mapping, "curves", None)
    if curves is None:
        return None, None, None, {"error": f"node '{node_name}' mapping has no curves"}

    try:
        curve_index = int(raw_curve_index)
    except Exception:
        return None, None, None, {"error": f"invalid curve_index '{raw_curve_index}'"}
    if curve_index < 0 or curve_index >= len(curves):
        return None, None, None, {"error": f"curve_index {curve_index} out of range"}

    curve = curves[curve_index]
    points = getattr(curve, "points", None)
    if points is None:
        return None, None, None, {"error": f"curve {curve_index} has no points collection"}
    return mapping, curve, points, None


def _serialize_curve_point(point, index: int) -> dict[str, Any]:
    raw_loc = getattr(point, "location", (0.0, 0.0))
    try:
        loc = list(raw_loc)
    except Exception:
        loc = [0.0, 0.0]
    x = float(loc[0]) if len(loc) > 0 else 0.0
    y = float(loc[1]) if len(loc) > 1 else 0.0
    return {
        "index": index,
        "x": x,
        "y": y,
        "handle_type": getattr(point, "handle_type", None),
        "select": bool(getattr(point, "select", False)),
    }


def _cmd_get_float_curve_points(params: dict) -> dict:
    mapping, _curve, points, err = _resolve_float_curve_target(params)
    if err is not None:
        return err
    curve_index = int(params.get("curve_index", 0))
    return {
        "curve_index": curve_index,
        "point_count": len(points),
        "points": [_serialize_curve_point(p, i) for i, p in enumerate(points)],
        "updated": bool(getattr(mapping, "_updated", False)),
    }


def _cmd_add_float_curve_point(params: dict) -> dict:
    mapping, _curve, points, err = _resolve_float_curve_target(params)
    if err is not None:
        return err

    try:
        x = float(params.get("x"))
        y = float(params.get("y"))
    except Exception:
        return {"error": "x and y must be numeric"}

    try:
        point = points.new(x, y)
    except Exception as exc:
        return {"error": f"failed to add curve point: {exc}"}

    handle_type = str(params.get("handle_type", "")).strip()
    if handle_type:
        try:
            point.handle_type = handle_type
        except Exception as exc:
            return {"error": f"failed to set handle_type '{handle_type}': {exc}"}

    try:
        mapping.update()
    except Exception as exc:
        return {"error": f"failed to update curve mapping: {exc}"}

    index = -1
    for i, p in enumerate(points):
        if p is point:
            index = i
            break
    return {"added": True, "point": _serialize_curve_point(point, index)}


def _cmd_set_float_curve_point(params: dict) -> dict:
    mapping, _curve, points, err = _resolve_float_curve_target(params)
    if err is not None:
        return err

    raw_index = params.get("index")
    try:
        index = int(raw_index)
    except Exception:
        return {"error": f"invalid index '{raw_index}'"}
    if index < 0 or index >= len(points):
        return {"error": f"index {index} out of range"}

    try:
        x = float(params.get("x"))
        y = float(params.get("y"))
    except Exception:
        return {"error": "x and y must be numeric"}

    point = points[index]
    try:
        point.location = (x, y)
    except Exception as exc:
        return {"error": f"failed to set point location: {exc}"}

    handle_type = str(params.get("handle_type", "")).strip()
    if handle_type:
        try:
            point.handle_type = handle_type
        except Exception as exc:
            return {"error": f"failed to set handle_type '{handle_type}': {exc}"}

    try:
        mapping.update()
    except Exception as exc:
        return {"error": f"failed to update curve mapping: {exc}"}

    return {"set": True, "point": _serialize_curve_point(point, index)}


def _cmd_open_blend_file(params: dict) -> dict:
    bpy = _get_bpy()
    path = params.get("path", "")
    if not path:
        return {"error": "missing path"}
    p = Path(path)
    if not p.exists():
        return {"error": f"blend file not found: {path}"}

    try:
        bpy.ops.wm.open_mainfile(filepath=str(p))
    except Exception as exc:
        return {"error": f"failed to open blend file: {exc}"}

    groups = [g.name for g in bpy.data.node_groups if g.type == "GEOMETRY"]
    objects = [o.name for o in bpy.context.scene.objects]
    active = bpy.context.active_object.name if bpy.context.active_object else None
    return {
        "opened": str(p),
        "active_object": active,
        "objects": objects,
        "geometry_node_groups": groups,
    }


def _cmd_add_group_interface_socket(params: dict) -> dict:
    bpy = _get_bpy()
    tree_name = params.get("tree_name", "")
    socket_name = params.get("name", "")
    raw_in_out = str(params.get("in_out", "INPUT")).upper()
    raw_socket_type = str(params.get("socket_type", "NodeSocketFloat"))
    default_value = params.get("default_value")

    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        return {"error": f"node tree '{tree_name}' not found"}
    if not socket_name:
        return {"error": "missing socket name"}
    if not hasattr(tree, "interface"):
        return {"error": f"node tree '{tree_name}' has no editable interface"}

    in_out = "OUTPUT" if raw_in_out == "OUTPUT" else "INPUT"
    socket_type = _normalize_interface_socket_type(raw_socket_type)

    # Dedup: reject if a socket with the same name and direction already exists
    for item in tree.interface.items_tree:
        if getattr(item, "in_out", "") == in_out and item.name == socket_name:
            return {"added": False, "name": socket_name, "in_out": in_out, "reason": "already exists"}

    try:
        iface_socket = tree.interface.new_socket(name=socket_name, in_out=in_out, socket_type=socket_type)
    except Exception as exc:
        return {
            "error": f"failed to create interface socket '{socket_name}': {exc}",
            "details": {"in_out": in_out, "socket_type": socket_type},
        }

    if default_value is not None and hasattr(iface_socket, "default_value"):
        try:
            iface_socket.default_value = default_value
        except Exception as exc:
            return {
                "error": f"created interface socket but failed to set default value: {exc}",
                "details": {"name": socket_name, "in_out": in_out, "socket_type": socket_type},
            }

    return {"added": True, "name": socket_name, "in_out": in_out, "socket_type": socket_type}


def _cmd_remove_group_interface_socket(params: dict) -> dict:
    bpy = _get_bpy()
    tree_name = params.get("tree_name", "")
    socket_name = params.get("name", "")
    raw_in_out = str(params.get("in_out", "INPUT")).upper()

    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        return {"error": f"node tree '{tree_name}' not found"}
    if not socket_name:
        return {"error": "missing socket name"}
    if not hasattr(tree, "interface"):
        return {"error": f"node tree '{tree_name}' has no editable interface"}

    in_out = "OUTPUT" if raw_in_out == "OUTPUT" else "INPUT"

    for item in tree.interface.items_tree:
        if getattr(item, "in_out", "") == in_out and item.name == socket_name:
            tree.interface.remove(item)
            return {"removed": True, "name": socket_name, "in_out": in_out}

    available = [
        item.name for item in tree.interface.items_tree
        if getattr(item, "in_out", "") == in_out
    ]
    return {
        "error": f"interface socket '{socket_name}' ({in_out}) not found",
        "available": available,
    }


def _cmd_get_node_sockets(params: dict) -> dict:
    bpy = _get_bpy()
    tree_name = params.get("tree_name", "")
    node_name = params.get("node_name", "")
    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        return {"error": f"node tree '{tree_name}' not found"}
    node = tree.nodes.get(node_name)
    if node is None:
        return {"error": f"node '{node_name}' not found"}

    return {
        "tree_name": tree.name,
        "node_name": node.name,
        "bl_idname": node.bl_idname,
        "inputs": [
            {
                "name": s.name,
                "identifier": getattr(s, "identifier", s.name),
                "type": s.type,
                "default_value": _serialize_value(getattr(s, "default_value", None)),
                "is_linked": s.is_linked,
            }
            for s in node.inputs
        ],
        "outputs": [
            {
                "name": s.name,
                "identifier": getattr(s, "identifier", s.name),
                "type": s.type,
                "default_value": _serialize_value(getattr(s, "default_value", None)),
                "is_linked": s.is_linked,
            }
            for s in node.outputs
        ],
    }


def _cmd_undo(params: dict) -> dict:
    bpy = _get_bpy()
    raw_steps = params.get("steps", 1)
    try:
        steps = max(1, int(raw_steps))
    except Exception:
        steps = 1
    done = 0
    for _ in range(steps):
        try:
            bpy.ops.ed.undo()
            done += 1
        except Exception as exc:
            return {"error": f"undo failed after {done} step(s): {exc}"}
    return {"undone": done}


def _serialize_value(val: Any) -> Any:
    """Convert Blender values to JSON-safe types."""
    if val is None:
        return None
    if isinstance(val, (str, int, float, bool)):
        return val
    try:
        # Vector / Color / Euler etc.
        return list(val)
    except TypeError:
        pass
    try:
        return float(val)
    except (TypeError, ValueError):
        pass
    return str(val)


# ---------------------------------------------------------------------------
# Asset library commands
# ---------------------------------------------------------------------------


def _get_asset_permissions() -> tuple[bool, bool]:
    """Read asset access permissions from addon preferences."""
    bpy = _get_bpy()
    try:
        prefs = bpy.context.preferences.addons["nodecue"].preferences
        return prefs.asset_access_essentials, prefs.asset_access_user
    except (KeyError, AttributeError):
        return True, False  # defaults: essentials=on, user=off


def _cmd_list_asset_node_groups(params: dict) -> dict:
    """Scan asset libraries for node group assets."""
    bpy = _get_bpy()
    import os

    allow_essentials, allow_user = _get_asset_permissions()
    result: list[dict] = []
    errors: list[str] = []
    source = params.get("source", "all")  # "all", "essentials", "user"

    # Essentials (bundled with Blender)
    if source in ("all", "essentials") and not allow_essentials:
        errors.append("Access to Blender built-in assets is disabled in addon preferences")
    elif source in ("all", "essentials"):
        local_res = bpy.utils.resource_path("LOCAL")
        essentials_dir = os.path.join(local_res, "datafiles", "assets", "nodes")
        if os.path.isdir(essentials_dir):
            for fname in os.listdir(essentials_dir):
                if not fname.endswith(".blend"):
                    continue
                filepath = os.path.join(essentials_dir, fname)
                try:
                    with bpy.data.libraries.load(filepath, assets_only=True) as (src, _dst):
                        for ng_name in src.node_groups:
                            result.append({
                                "name": ng_name,
                                "source_file": filepath,
                                "library": "_essentials",
                            })
                except Exception as e:
                    errors.append(f"Error reading {filepath}: {e}")

    # User-configured libraries
    if source in ("all", "user") and not allow_user:
        if source == "user":
            errors.append("Access to user asset libraries is disabled in addon preferences")
    elif source in ("all", "user"):
        for lib in bpy.context.preferences.filepaths.asset_libraries:
            lib_path = lib.path
            if not os.path.isdir(lib_path):
                continue
            for root, _dirs, files in os.walk(lib_path):
                for fname in files:
                    if not fname.endswith(".blend"):
                        continue
                    filepath = os.path.join(root, fname)
                    try:
                        with bpy.data.libraries.load(filepath, assets_only=True) as (src, _dst):
                            for ng_name in src.node_groups:
                                result.append({
                                    "name": ng_name,
                                    "source_file": filepath,
                                    "library": lib.name,
                                })
                    except Exception as e:
                        errors.append(f"Error reading {filepath}: {e}")

    out: dict = {"node_groups": result, "count": len(result)}
    if errors:
        out["errors"] = errors
    return out


def _cmd_append_asset_node_group(params: dict) -> dict:
    """Append a node group asset from a .blend file and optionally add it as a Group node."""
    bpy = _get_bpy()

    source_file = params.get("source_file", "")
    group_name = params.get("group_name", "")
    tree_name = params.get("tree_name", "")

    if not source_file or not group_name:
        return {"error": "source_file and group_name are required"}

    # Check permissions based on source file location
    import os
    allow_essentials, allow_user = _get_asset_permissions()
    local_res = bpy.utils.resource_path("LOCAL")
    is_essentials = source_file.startswith(os.path.join(local_res, "datafiles"))
    if is_essentials and not allow_essentials:
        return {"error": "Access to Blender built-in assets is disabled in addon preferences"}
    if not is_essentials and not allow_user:
        return {"error": "Access to user asset libraries is disabled in addon preferences"}

    # Check if already appended
    existing = bpy.data.node_groups.get(group_name)
    if existing is not None:
        appended_name = existing.name
    else:
        # Append from file
        try:
            with bpy.data.libraries.load(source_file, link=False, assets_only=True) as (src, dst):
                if group_name not in src.node_groups:
                    return {"error": f"Node group '{group_name}' not found in {source_file}"}
                dst.node_groups = [group_name]
        except Exception as e:
            return {"error": f"Failed to load {source_file}: {e}"}

        appended = bpy.data.node_groups.get(group_name)
        if appended is None:
            return {"error": f"Node group '{group_name}' was not appended successfully"}
        appended_name = appended.name

    result: dict = {"appended": appended_name}

    # Optionally insert as Group node into a tree
    if tree_name:
        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            return {"error": f"Tree '{tree_name}' not found"}

        group_node = tree.nodes.new("GeometryNodeGroup")
        group_node.node_tree = bpy.data.node_groups[appended_name]
        result["node_name"] = group_node.name
        result["tree_name"] = tree_name

        # Report the group's interface sockets (skip panels)
        ng = bpy.data.node_groups[appended_name]
        inputs = []
        outputs = []
        if hasattr(ng, "interface"):
            for item in ng.interface.items_tree:
                if not hasattr(item, "socket_type"):
                    continue
                entry = {"name": item.name, "socket_type": item.socket_type}
                if getattr(item, "in_out", None) == "INPUT":
                    inputs.append(entry)
                elif getattr(item, "in_out", None) == "OUTPUT":
                    outputs.append(entry)
        result["group_inputs"] = inputs
        result["group_outputs"] = outputs

    return result


# ---------------------------------------------------------------------------
# arrange_nodes — topological layout
# ---------------------------------------------------------------------------


def _cmd_arrange_nodes(params: dict) -> dict:
    """Auto-arrange nodes in a tree using topological (layered) layout.

    BFS backward from Group Output assigns each node a depth layer.
    Nodes are placed left-to-right (Group Input → Group Output) with
    even vertical spacing within each layer.
    """
    tree, err = _resolve_tree(params)
    if err:
        return err

    margin_x = float(params.get("margin_x", 280))
    margin_y = float(params.get("margin_y", 100))
    selected_only = bool(params.get("selected_only", False))

    all_nodes = list(tree.nodes)
    if not all_nodes:
        return {"ok": True, "arranged": 0}

    # Build name→node map and full adjacency (need full graph for layer assignment)
    by_name: dict[str, Any] = {}
    # predecessors[node_name] = set of node names that feed into it
    predecessors: dict[str, set[str]] = {}
    # successors[node_name] = set of node names it feeds into
    successors: dict[str, set[str]] = {}

    for node in all_nodes:
        by_name[node.name] = node
        predecessors[node.name] = set()
        successors[node.name] = set()

    for link in tree.links:
        fn = link.from_node.name
        tn = link.to_node.name
        if fn in by_name and tn in by_name:
            predecessors[tn].add(fn)
            successors[fn].add(tn)

    # Determine which nodes to reposition
    if selected_only:
        target_names = {n.name for n in all_nodes if getattr(n, "select", False)}
        if not target_names:
            return {"ok": True, "arranged": 0, "warning": "no nodes selected"}
        layout_nodes = [n for n in all_nodes if n.name in target_names]
    else:
        layout_nodes = [n for n in all_nodes if getattr(n, "bl_idname", "") != "NodeFrame"]

    # Unparent nodes from Frames so locations are absolute, not Frame-relative.
    # Record original parents to restore after positioning if needed.
    original_parents: dict[str, Any] = {}
    for node in layout_nodes:
        parent = getattr(node, "parent", None)
        if parent is not None:
            original_parents[node.name] = parent
            node.parent = None

    # Assign layers via BFS from sinks (nodes with no successors) backward
    # Use full graph for correct layer depth, then only reposition target nodes
    # Layer 0 = rightmost (Group Output), higher layers = further left
    layer_of: dict[str, int] = {}

    all_layout = [n for n in all_nodes if getattr(n, "bl_idname", "") != "NodeFrame"]
    # Find sinks — prefer Group Output, fall back to any node with no successors
    sinks = [n.name for n in all_layout if not successors[n.name]]
    if not sinks:
        # Cycle — just pick Group Output or first node
        sinks = [n.name for n in all_layout if getattr(n, "bl_idname", "") == "NodeGroupOutput"]
        if not sinks:
            sinks = [all_layout[0].name]

    from collections import deque

    queue: deque[str] = deque()
    for s in sinks:
        layer_of[s] = 0
        queue.append(s)

    while queue:
        name = queue.popleft()
        next_layer = layer_of[name] + 1
        for pred in predecessors[name]:
            if pred not in layer_of or layer_of[pred] < next_layer:
                layer_of[pred] = next_layer
                queue.append(pred)

    # Nodes not reached (isolated) get their own layer
    max_layer = max(layer_of.values()) if layer_of else 0
    for n in all_layout:
        if n.name not in layer_of:
            max_layer += 1
            layer_of[n.name] = max_layer

    # Group only the target nodes by layer
    layers: dict[int, list[str]] = {}
    for n in layout_nodes:
        layer = layer_of.get(n.name, 0)
        layers.setdefault(layer, []).append(n.name)

    # Estimate node height for vertical spacing
    def _node_height(node: Any) -> float:
        n_sockets = max(len(list(node.inputs)), len(list(node.outputs)), 1)
        return 40 + n_sockets * 22  # rough estimate

    # --- Crossing minimization via coordinate-based barycenter ---
    # Track actual y-coordinate for each node (not slot index).
    y_of: dict[str, float] = {}

    # Step 1: Initial placement — assign y within each layer by stacking.
    # Start from layer 0 (rightmost / sinks) and work left.
    target_names = {n.name for n in layout_nodes}
    for li in sorted(layers.keys()):
        names = layers[li]
        y = 0.0
        for name in names:
            y_of[name] = y
            y -= _node_height(by_name[name]) + margin_y

    # Step 2: Iterative sweeps using actual y-coordinates of neighbors.
    def _avg_y_of_neighbors(name: str, neighbor_set: set[str]) -> float | None:
        ys = [y_of[nb] for nb in neighbor_set if nb in y_of and nb in target_names]
        return sum(ys) / len(ys) if ys else None

    sorted_layer_indices = sorted(layers.keys())  # low (right) to high (left)

    for _sweep in range(6):
        # Right to left (layer 0 → max layer): sort by successor y
        for li in sorted_layer_indices:
            names = layers[li]
            keyed = []
            for name in names:
                avg = _avg_y_of_neighbors(name, successors.get(name, set()))
                keyed.append((avg if avg is not None else y_of.get(name, 0.0), name))
            keyed.sort(key=lambda t: -t[0])  # higher y = higher position
            layers[li] = [t[1] for t in keyed]
            # Reassign y positions based on new order
            y = 0.0
            for _, name in keyed:
                y_of[name] = y
                y -= _node_height(by_name[name]) + margin_y

        # Left to right (max layer → layer 0): sort by predecessor y
        for li in reversed(sorted_layer_indices):
            names = layers[li]
            keyed = []
            for name in names:
                avg = _avg_y_of_neighbors(name, predecessors.get(name, set()))
                keyed.append((avg if avg is not None else y_of.get(name, 0.0), name))
            keyed.sort(key=lambda t: -t[0])
            layers[li] = [t[1] for t in keyed]
            y = 0.0
            for _, name in keyed:
                y_of[name] = y
                y -= _node_height(by_name[name]) + margin_y

    # Position: use computed y_of values from barycenter optimization.
    if selected_only and layout_nodes:
        cx = sum(n.location.x for n in layout_nodes) / len(layout_nodes)
        present_layers = sorted(layers.keys())
        mid = (present_layers[0] + present_layers[-1]) / 2.0
    else:
        cx = 0.0
        mid = 0.0

    total_layers = max(layers.keys()) + 1 if layers else 1
    arranged = 0
    for layer_idx, layer_names in layers.items():
        if selected_only:
            x = cx - (layer_idx - mid) * margin_x
        else:
            x = -layer_idx * margin_x
        for name in layer_names:
            node = by_name[name]
            node.location.x = x
            node.location.y = y_of.get(name, 0.0)
            arranged += 1

    # Re-parent nodes back to their original Frames.
    # Blender auto-converts absolute → Frame-relative coordinates on reparent.
    for name, parent in original_parents.items():
        node = by_name.get(name)
        if node is not None:
            node.parent = parent

    return {"ok": True, "arranged": arranged, "layers": total_layers}


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------


def _cmd_execute_action_batch(params: dict) -> dict:
    from nodecue.bpy_recipes import execute_action_batch

    return execute_action_batch(
        params.get("actions", []),
        readback_after=bool(params.get("readback_after", True)),
        stop_on_error=bool(params.get("stop_on_error", True)),
    )


# Live activity counters so the UI can show real progress during agent runs.
_ACTIVITY: dict[str, Any] = {"ops": 0, "last": ""}


def get_activity() -> dict[str, Any]:
    return dict(_ACTIVITY)


def reset_activity() -> None:
    _ACTIVITY["ops"] = 0
    _ACTIVITY["last"] = ""


_COMMANDS: dict[str, Any] = {
    "ping": _cmd_ping,
    "list_node_groups": _cmd_list_node_groups,
    "list_scene_objects": _cmd_list_scene_objects,
    "set_active_object": _cmd_set_active_object,
    "add_modifier": _cmd_add_modifier,
    "remove_modifier": _cmd_remove_modifier,
    "create_node_tree": _cmd_create_node_tree,
    "open_blend_file": _cmd_open_blend_file,
    "add_group_interface_socket": _cmd_add_group_interface_socket,
    "remove_group_interface_socket": _cmd_remove_group_interface_socket,
    "undo": _cmd_undo,
    "create_node": _cmd_create_node,
    "connect": _cmd_connect,
    "disconnect_sockets": _cmd_disconnect_sockets,
    "set_input_default": _cmd_set_input_default,
    "set_node_property": _cmd_set_node_property,
    "set_node_enum": _cmd_set_node_enum,
    "get_float_curve_points": _cmd_get_float_curve_points,
    "add_float_curve_point": _cmd_add_float_curve_point,
    "set_float_curve_point": _cmd_set_float_curve_point,
    "get_node_sockets": _cmd_get_node_sockets,
    "delete_node": _cmd_delete_node,
    "add_frame": _cmd_add_frame,
    "get_tree_info": _cmd_get_tree_info,
    "read_active_tree": _cmd_read_active_tree,
    "list_asset_node_groups": _cmd_list_asset_node_groups,
    "append_asset_node_group": _cmd_append_asset_node_group,
    "arrange_nodes": _cmd_arrange_nodes,
    "execute_action_batch": _cmd_execute_action_batch,
}


# ---------------------------------------------------------------------------
# Server class
# ---------------------------------------------------------------------------


class GNMCPSocketServer:
    """TCP socket server bridging MCP to Blender's main thread."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9877):
        self.host = host
        self.port = port
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        # Queue for commands to execute on the main thread.
        self._pending: list[tuple[dict, socket.socket]] = []
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.settimeout(1.0)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen(4)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        # Register timer to process commands on the main thread.
        bpy = _get_bpy()
        bpy.app.timers.register(self._process_pending, first_interval=0.1, persistent=True)
        log.info("GN MCP socket listening on %s:%d", self.host, self.port)
        print(f"GN MCP socket listening on {self.host}:{self.port}")

    def stop(self) -> None:
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        try:
            bpy = _get_bpy()
            if bpy.app.timers.is_registered(self._process_pending):
                bpy.app.timers.unregister(self._process_pending)
        except Exception:
            pass
        print("GN MCP socket server stopped")

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, addr = self._server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._handle_connection, args=(conn,), daemon=True
            ).start()

    def _handle_connection(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(120.0)  # Prevent handler from blocking forever on partial messages
            while self._running:
                msg = _recv_msg(conn)
                if msg is None:
                    break
                # Queue command for main-thread execution and wait.
                event = threading.Event()
                result_holder: list[dict] = []

                def _callback(m=msg, rh=result_holder, ev=event):
                    try:
                        cmd_type = m.get("type", "")
                        params = m.get("params", {})
                        _ACTIVITY["ops"] += 1
                        _ACTIVITY["last"] = cmd_type
                        handler = _COMMANDS.get(cmd_type)
                        if handler is None:
                            rh.append(
                                {"status": "error", "result": {"error": f"unknown command: {cmd_type}"}}
                            )
                        else:
                            r = handler(params)
                            if "error" in r:
                                rh.append({"status": "error", "result": r})
                            else:
                                rh.append({"status": "success", "result": r})
                    except Exception as exc:
                        rh.append(
                            {
                                "status": "error",
                                "result": {"error": str(exc), "traceback": traceback.format_exc()},
                            }
                        )
                    finally:
                        ev.set()

                with self._lock:
                    self._pending.append((_callback, conn))

                event.wait(timeout=60.0)
                if result_holder:
                    _send_msg(conn, result_holder[0])
                else:
                    _send_msg(conn, {"status": "error", "result": {"error": "timeout"}})
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _process_pending(self) -> float | None:
        """Timer callback — runs on Blender's main thread."""
        if not self._running:
            return None  # Unregister timer.
        with self._lock:
            batch = list(self._pending)
            self._pending.clear()
        for callback, _conn in batch:
            try:
                callback()
            except Exception:
                pass
        return 0.1  # Re-run every 100ms.


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_server_instance: GNMCPSocketServer | None = None


def get_server() -> GNMCPSocketServer | None:
    return _server_instance


def start_server(port: int = 9877) -> GNMCPSocketServer:
    global _server_instance
    if _server_instance is not None and _server_instance.is_running:
        return _server_instance
    _server_instance = GNMCPSocketServer(port=port)
    _server_instance.start()
    return _server_instance


def stop_server() -> None:
    global _server_instance
    if _server_instance is not None:
        _server_instance.stop()
        _server_instance = None
