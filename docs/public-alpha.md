# Public Alpha Direction

NodeCue should be public only when a new user can install it, run one Geometry Nodes prompt, inspect the generated graph, and report a useful issue without private context from the development workspace.

## Public Alpha Scope

- Blender 5.0+ Geometry Nodes only (developed and tested on 5.1).
- Built-in agent through OpenRouter or another OpenAI-compatible endpoint.
- External agent workflow through the standalone `nodecue-blender-node-skills` package and the community blender-mcp project.
- Local reports and saved `.blend` artifacts for debugging.
- No Shader Nodes, Compositing Nodes, OAuth login, hosted service, or paid feature gate in the first public alpha.

## Release Gates

- The repository is public, licensed, and has no private `.env`, debug `.blend`, cache, archive, or old MCP implementation files.
- Quickstart can be followed from a clean checkout.
- Check Setup succeeds from the Blender panel with a configured model provider.
- Generate, Explain, and Modify each pass at least one real-model smoke scenario.
- The standalone skill package installs with `npx @nodecue/blender-node-skills install`, or from a public checkout while npm publishing is pending.
- Known limitations are explicit, especially model quality, API-key provider setup, and early asset reuse.

## First Feedback Loop

Ask early users for:

- their prompt;
- provider/model used;
- generated report JSON;
- generated `.blend` artifact if they can share it;
- what looked wrong in the node graph;
- whether the explanation helped them learn the graph.

Do not optimize for benchmark pass rate alone. The first release should reveal where users get stuck: setup, model quality, graph correctness, explanation quality, or Blender execution.

## Business Model Starting Point

Keep the public alpha free. Charge only for optional help or convenience while the core project is still proving value.

Good first paid surfaces:

- paid setup/support sessions for artists who cannot configure model providers;
- sponsor/backer tier for users who want the Geometry Nodes skill and NodeCue agent to keep improving;
- paid custom node-group/library indexing for studios or advanced users;
- later, a Pro build that improves asset-library search, reusable node-group descriptions, and workflow polish.

Avoid charging for the basic Geometry Nodes skill, public alpha access, or bug fixes. Those need to stay open enough to build trust and attract feedback.

## Public Messaging

Position NodeCue as a focused Blender node learning and building assistant, not as a general replacement for Claude, Codex, or other full agents. The useful distinction is:

- NodeCue: in-Blender, node-focused, controlled execution, teachable graph output.
- External agents: broader reasoning and task control, improved by the same standalone skill package.

The shared skill is the durable asset. The plugin should make that knowledge easy to use inside Blender.
