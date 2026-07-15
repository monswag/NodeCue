# External Agents

NodeCue is not required for external agents to control Blender.

Recommended external workflow:

1. Install the standalone `nodecue-blender-node-skills` package.
2. Connect the agent to Blender through an MCP server. Prefer Blender's official MCP server from Blender Lab (https://www.blender.org/lab/mcp-server/, bundled from Blender 5.2 LTS and available as an add-on); the community blender-mcp project also works.
3. Let the agent read the skill and execute Blender Python through MCP.

Install the skill. Claude Code users can install it as a plugin, no terminal needed:

```text
/plugin marketplace add monswag/nodecue-blender-node-skills
/plugin install blender-node-skills@nodecue
```

Codex and other agents copy the skill folder into the agent's skills directory:

```bash
git clone https://github.com/monswag/nodecue-blender-node-skills.git
cp -r nodecue-blender-node-skills/skills/geometry-nodes ~/.codex/skills/   # Codex
# or wherever your agent loads skills from
```

The shared skill describes Geometry Nodes reasoning, node relationships, socket safety, readback repair, and teachable frame organization. It does not require NodeCue's internal action schema.

NodeCue may later expose optional read-only helper data, such as asset indexes or node group descriptions. Those helpers should remain optional and should not replace the standard MCP path for external agents.
