"""Installable Blender NodeCue addon package."""

bl_info = {
    "name": "NodeCue",
    "author": "NodeCue",
    "version": (0, 2, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > NodeCue",
    "description": "AI-assisted node learning, generation, and validation for Blender",
    "category": "Node",
}


def register():
    try:
        from nodecue.ui import register_ui

        register_ui()
    except Exception:
        # Keep register import-safe for non-Blender test runs.
        return None
    return None


def unregister():
    try:
        from nodecue.socket_server import stop_server

        stop_server()
    except Exception:
        pass
    try:
        from nodecue.ui import unregister_ui

        unregister_ui()
    except Exception:
        return None
    return None
