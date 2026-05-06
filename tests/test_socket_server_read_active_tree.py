from nodecue import socket_server


class _Modifier:
    def __init__(self, mod_type='NODES', node_group=None):
        self.type = mod_type
        self.node_group = node_group


class _Object:
    def __init__(self, modifiers):
        self.modifiers = modifiers


class _Context:
    def __init__(self, obj):
        self.active_object = obj


class _NodeGroups:
    def __init__(self, groups=None):
        self._groups = groups or {}

    def get(self, name):
        return self._groups.get(name)


class _Data:
    def __init__(self, node_groups=None):
        self.node_groups = _NodeGroups(node_groups or {})


class _Bpy:
    def __init__(self, obj, node_groups=None):
        self.context = _Context(obj)
        self.data = _Data(node_groups or {})


def test_cmd_read_active_tree_no_active_object(monkeypatch):
    monkeypatch.setattr(socket_server, '_get_bpy', lambda: _Bpy(None))
    result = socket_server._cmd_read_active_tree({})
    assert result['ok'] is False
    assert 'no active object' in result['error']


def test_cmd_read_active_tree_reads_first_gn_modifier(monkeypatch):
    tree = type('Tree', (), {
        'name': 'GN',
        'nodes': [],
        'links': [],
    })()
    obj = _Object([_Modifier('NODES', tree)])
    monkeypatch.setattr(socket_server, '_get_bpy', lambda: _Bpy(obj, {'GN': tree}))
    result = socket_server._cmd_read_active_tree({})
    assert result['ok'] is True
    assert result['data']['tree_name'] == 'GN'
    assert 'frames' in result['data']
    assert 'nodes' in result['data']
    assert 'links' in result['data']
