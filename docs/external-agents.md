# External Agents

NodeCue is not required for external agents to control Blender.

Recommended external workflow:

1. Install the standalone `nodecue-blender-node-skills` package.
2. Connect the agent to Blender through the community blender-mcp project. Blender has no official MCP today; if the Blender Foundation ships one, it becomes the preferred path.
3. Let the agent read the skill and execute Blender Python through MCP.

Install the skill by copying it into your agent's skills directory:

```bash
git clone https://github.com/monswag/nodecue-blender-node-skills.git
cp -r nodecue-blender-node-skills/skills/geometry-nodes ~/.claude/skills/   # Claude Code
# or ~/.codex/skills/ for Codex, or wherever your agent loads skills from
```

The shared skill describes Geometry Nodes reasoning, node relationships, socket safety, readback repair, and teachable frame organization. It does not require NodeCue's internal action schema.

NodeCue may later expose optional read-only helper data, such as asset indexes or node group descriptions. Those helpers should remain optional and should not replace the standard MCP path for external agents.
