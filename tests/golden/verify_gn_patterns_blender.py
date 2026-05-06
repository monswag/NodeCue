"""Create minimal Blender Geometry Nodes graphs for evidence-backed patterns.

Run with:
    conda run -n blender blender -b --python tests/golden/verify_gn_patterns_blender.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import bpy


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "nodecue" / "skills" / "geometry-nodes" / "evals" / "gn_pattern_readbacks.json"


def _socket(sockets: Iterable, *names: str):
    wanted = {name.lower() for name in names}
    for sock in sockets:
        if sock.name.lower() in wanted or getattr(sock, "identifier", "").lower() in wanted:
            return sock
    available = [sock.name for sock in sockets]
    raise RuntimeError(f"socket not found {names}; available={available}")


def _new_tree(name: str):
    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    tree.interface.new_socket(
        name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
    )
    tree.interface.new_socket(
        name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )
    group_in = tree.nodes.new("NodeGroupInput")
    group_out = tree.nodes.new("NodeGroupOutput")
    group_in.location = (-900, 0)
    group_out.location = (900, 0)
    return tree, group_in, group_out


def _link(tree, from_node, from_socket: str, to_node, to_socket: str):
    tree.links.new(
        _socket(from_node.outputs, from_socket),
        _socket(to_node.inputs, to_socket),
    )


def _set_node_locations(nodes):
    for index, node in enumerate(nodes):
        node.location = ((index % 4) * 260 - 500, -180 * (index // 4))


def _surface_displacement():
    tree, group_in, group_out = _new_tree("NC_Evidence_Surface_Displacement")
    noise = tree.nodes.new("ShaderNodeTexNoise")
    normal = tree.nodes.new("GeometryNodeInputNormal")
    scale = tree.nodes.new("ShaderNodeVectorMath")
    scale.operation = "SCALE"
    set_pos = tree.nodes.new("GeometryNodeSetPosition")
    _set_node_locations([group_in, normal, noise, scale, set_pos, group_out])

    _link(tree, group_in, "Geometry", set_pos, "Geometry")
    _link(tree, normal, "Normal", scale, "Vector")
    _link(tree, noise, "Fac", scale, "Scale")
    _link(tree, scale, "Vector", set_pos, "Offset")
    _link(tree, set_pos, "Geometry", group_out, "Geometry")
    return tree


def _density_controlled_scatter():
    tree, _group_in, group_out = _new_tree("NC_Evidence_Density_Scatter")
    grid = tree.nodes.new("GeometryNodeMeshGrid")
    distribute = tree.nodes.new("GeometryNodeDistributePointsOnFaces")
    noise = tree.nodes.new("ShaderNodeTexNoise")
    map_range = tree.nodes.new("ShaderNodeMapRange")
    cube = tree.nodes.new("GeometryNodeMeshCube")
    instance = tree.nodes.new("GeometryNodeInstanceOnPoints")
    _set_node_locations([grid, distribute, noise, map_range, cube, instance, group_out])

    _link(tree, grid, "Mesh", distribute, "Mesh")
    _link(tree, noise, "Fac", map_range, "Value")
    _link(tree, map_range, "Result", distribute, "Density Factor")
    _link(tree, distribute, "Points", instance, "Points")
    _link(tree, cube, "Mesh", instance, "Instance")
    _link(tree, instance, "Instances", group_out, "Geometry")
    return tree


def _material_attribute_handoff():
    tree, group_in, group_out = _new_tree("NC_Evidence_Material_Attribute_Handoff")
    noise = tree.nodes.new("ShaderNodeTexNoise")
    compare = tree.nodes.new("FunctionNodeCompare")
    set_index = tree.nodes.new("GeometryNodeSetMaterialIndex")
    store = tree.nodes.new("GeometryNodeStoreNamedAttribute")
    _set_node_locations([group_in, noise, compare, set_index, store, group_out])

    _socket(set_index.inputs, "Material Index").default_value = 1
    _socket(store.inputs, "Name").default_value = "nodecue_mask"
    _link(tree, noise, "Fac", compare, "A")
    _link(tree, compare, "Result", set_index, "Selection")
    _link(tree, group_in, "Geometry", set_index, "Geometry")
    _link(tree, set_index, "Geometry", store, "Geometry")
    _link(tree, compare, "Result", store, "Selection")
    _link(tree, noise, "Fac", store, "Value")
    _link(tree, store, "Geometry", group_out, "Geometry")
    return tree


def _readback(tree):
    return {
        "tree_name": tree.name,
        "nodes": [
            {
                "name": node.name,
                "bl_idname": node.bl_idname,
                "inputs": [
                    {
                        "name": sock.name,
                        "identifier": getattr(sock, "identifier", sock.name),
                        "type": sock.type,
                    }
                    for sock in node.inputs
                ],
                "outputs": [
                    {
                        "name": sock.name,
                        "identifier": getattr(sock, "identifier", sock.name),
                        "type": sock.type,
                    }
                    for sock in node.outputs
                ],
            }
            for node in tree.nodes
        ],
        "links": [
            {
                "from_node": link.from_node.name,
                "from_socket": link.from_socket.name,
                "to_node": link.to_node.name,
                "to_socket": link.to_socket.name,
            }
            for link in tree.links
        ],
    }


def main():
    trees = {
        "surface-displacement": _surface_displacement(),
        "density-controlled-scatter": _density_controlled_scatter(),
        "material-attribute-handoff": _material_attribute_handoff(),
    }
    payload = {
        "blender_version": bpy.app.version_string,
        "patterns": {name: _readback(tree) for name, tree in trees.items()},
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
