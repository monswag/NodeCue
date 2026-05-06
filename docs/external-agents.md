# External Agents

NodeCue is not required for external agents to control Blender.

Recommended external workflow:

1. Install the standalone `nodecue-geometry-nodes-skill`.
2. Connect the agent to Blender through the official Blender MCP.
3. Let the agent read the skill and execute Blender Python through MCP.

The shared skill describes Geometry Nodes reasoning, node relationships, socket safety, readback repair, and teachable frame organization. It does not require NodeCue's internal action schema.

NodeCue may later expose optional read-only helper data, such as asset indexes or node group descriptions. Those helpers should remain optional and should not replace the official MCP path for external agents.
