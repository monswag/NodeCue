# External Agents

NodeCue is not required for external agents to control Blender.

Recommended external workflow:

1. Install the standalone `nodecue-blender-node-skills` package.
2. Connect the agent to Blender through the official Blender MCP.
3. Let the agent read the skill and execute Blender Python through MCP.

After the npm package is published:

```bash
npx @nodecue/blender-node-skills install
```

If npm publishing is still pending, install from a public checkout:

```bash
git clone https://github.com/monswag/nodecue-blender-node-skills.git
cd nodecue-blender-node-skills
node bin/install.js install
```

The shared skill describes Geometry Nodes reasoning, node relationships, socket safety, readback repair, and teachable frame organization. It does not require NodeCue's internal action schema.

NodeCue may later expose optional read-only helper data, such as asset indexes or node group descriptions. Those helpers should remain optional and should not replace the official MCP path for external agents.
