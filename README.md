# NodeCue

NodeCue is a Blender add-on prototype for learning, building, modifying, and explaining Geometry Nodes with a focused local agent.

The current alpha is intentionally narrow:

- Blender 5.1 add-on package: `nodecue/`
- local sidecar agent package: `nodecue_agent/`
- built-in Geometry Nodes skill snapshot: `nodecue/skills/geometry-nodes/`
- OpenRouter / OpenAI-compatible model configuration

The Geometry Nodes skill is also maintained in the standalone `nodecue-blender-node-skills` package. This repository vendors a copy so the Blender add-on works out of the box.

## Quick Start

1. Copy this repository or the add-on package to Blender's add-ons directory.
2. Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`.
3. Enable the `nodecue` add-on in Blender.
4. Use the NodeCue panel to run Check Setup, then Generate / Explain / Modify.

Detailed setup is in [docs/quickstart.md](docs/quickstart.md).

## External Agents

Codex, Claude, and other agents can use the standalone Geometry Nodes skill with the official Blender MCP. External agents do not need to route through the NodeCue bridge unless they specifically want NodeCue-maintained helper data.

See [docs/external-agents.md](docs/external-agents.md).

## Status

This is a public alpha preparation snapshot. It is usable for Geometry Nodes experiments, but not yet a polished public release. Current limits are tracked in [docs/known-limitations.md](docs/known-limitations.md), and the release/business direction is in [docs/public-alpha.md](docs/public-alpha.md).

## Tests

Offline tests:

```bash
conda run -n blender python -m pytest tests/ -q
```

Real model and Blender/MCP smoke tests are opt-in and are not run in CI by default.
