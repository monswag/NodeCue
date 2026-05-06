import nodecue


def test_addon_has_bl_info():
    assert hasattr(nodecue, "bl_info")
    assert nodecue.bl_info["name"]


def test_register_unregister_are_import_safe_without_bpy():
    assert nodecue.register() is None
    assert nodecue.unregister() is None
