# Alpha Test Guide

Use this guide to test NodeCue without needing private project context.

The alpha is not scored by one perfect node graph. Good feedback should show whether NodeCue can build a usable, teachable Geometry Nodes graph and explain what it did.

## Before Testing

- Use Blender 5.0 or newer (most tested on 5.1).
- Run Check Setup in the NodeCue panel.
- Confirm your provider/model is configured.
- Start from a simple scene unless the test says otherwise.
- Keep the generated report JSON and saved `.blend` artifact if NodeCue creates one.

Do not share API keys, private asset-library paths, or unreleasable `.blend` files in public issues.

## Test 1: Generate Terrain Displacement

Mode: `Generate`

Prompt:

```text
Create a teachable Geometry Nodes setup that displaces a grid terrain with layered noise. Expose height, scale, and seed controls. Add frames that explain the terrain source, noise field, displacement, and output.
```

What to inspect:

- The graph should have a clear geometry path into `Group Output`.
- Noise should affect position through a real displacement path, not only a disconnected texture node.
- Height or scale should be adjustable through exposed group sockets or clearly labeled value controls.
- Explanatory notes should appear as frames, not by renaming every node.

## Test 2: Explain an Existing Node Group

Mode: `Explain`

Setup:

- Open any file that has a Geometry Nodes node group.
- Select the object using that modifier.

Prompt:

```text
Explain what this Geometry Nodes graph does for a beginner. Focus on the main geometry flow, important fields, exposed parameters, and any disconnected or suspicious parts.
```

What to inspect:

- NodeCue should read the graph instead of rebuilding it.
- The explanation should describe the graph's actual structure.
- It should call out disconnected nodes or missing output links if they exist.
- It should not modify the graph in Explain mode.

## Test 3: Modify With Exposed Controls

Mode: `Modify`

Setup:

- Use the terrain graph from Test 1 or another simple Geometry Nodes group.

Prompt:

```text
Modify this graph so the terrain height can be controlled from the group input. Keep the existing organization, avoid duplicate frames, and add a short frame note explaining the new control.
```

What to inspect:

- The existing graph should remain recognizable.
- NodeCue should avoid creating duplicate frames with the same purpose.
- The height control should be reachable from Group Input or an obvious value control.
- The final geometry path should still reach `Group Output`.

## Optional External Agent Comparison

Install the standalone skill package, then ask Codex, Claude, or another external agent to solve Test 1 through a Blender MCP server (official Blender Lab MCP or community blender-mcp).

```bash
git clone https://github.com/monswag/nodecue-blender-node-skills.git
cp -r nodecue-blender-node-skills/skills/geometry-nodes ~/.claude/skills/   # Claude Code
# or ~/.codex/skills/ for Codex, or wherever your agent loads skills from
```

Compare:

- Did the external agent read the Geometry Nodes skill?
- Did it produce fewer execution errors?
- Did it create orphan nodes?
- Was the explanation more useful?
- Did it preserve frame-based teaching notes?

External agents do not need to route through the NodeCue bridge for normal Blender MCP usage.

## Useful Feedback

Open an Alpha feedback issue with:

- test number and mode;
- exact prompt;
- Blender version;
- provider/model;
- report JSON snippets;
- screenshots or shareable `.blend` artifact;
- what looked wrong or confusing;
- whether the graph helped you learn the node logic.
