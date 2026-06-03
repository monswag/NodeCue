# NodeCue

NodeCue is a Blender add-on prototype for learning, building, modifying, and explaining Geometry Nodes with a focused local agent.

The current alpha is intentionally narrow:

- Blender 5.1 add-on package: `nodecue/`
- local sidecar agent package: `nodecue_agent/`
- built-in Geometry Nodes skill snapshot: `nodecue/skills/geometry-nodes/`
- OpenRouter / OpenAI-compatible model configuration

The Geometry Nodes skill is also maintained in the standalone `nodecue-blender-node-skills` package. This repository vendors a copy so the Blender add-on works out of the box.

## Quick Start

1. Install the sidecar dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-agent.txt
```

2. Copy NodeCue into Blender's add-ons directory:

```bash
python3 scripts/install_addon.py --blender-version 5.1 --force
```

3. Copy the installed `nodecue.env.example` to `.env` in Blender's add-ons directory and set `OPENROUTER_API_KEY`.
4. Enable the `nodecue` add-on in Blender.
5. In NodeCue preferences, set `Sidecar Python` to your `.venv` Python and run Check Setup.
6. Use the NodeCue panel to run Generate, Explain, or Modify.

Detailed setup is in [docs/quickstart.md](docs/quickstart.md).

## External Agents

Codex, Claude, and other agents can use the standalone Geometry Nodes skill with the official Blender MCP. External agents do not need to route through the NodeCue bridge unless they specifically want NodeCue-maintained helper data.

See [docs/external-agents.md](docs/external-agents.md).

## Alpha Feedback

Useful reports include the prompt, Blender version, provider/model, report JSON, and what looked wrong in the node graph. Use the `Alpha feedback` issue template after trying Generate, Explain, Modify, or the external-agent workflow.

Do not paste API keys or private asset-library paths into public issues.

## Support and Business Model

The public alpha is free. Optional paid help should focus on setup support, workflow consulting, private asset-library indexing, or sponsored improvements. See [docs/support-and-business.md](docs/support-and-business.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for useful alpha contributions, PR expectations, and what to avoid while the Geometry Nodes alpha is still stabilizing.

## Status

This is a public alpha preparation snapshot. It is usable for Geometry Nodes experiments, but not yet a polished public release. Current limits are tracked in [docs/known-limitations.md](docs/known-limitations.md), and the release/business direction is in [docs/public-alpha.md](docs/public-alpha.md).

## Tests

Offline tests:

```bash
python -m pytest tests/ -q
```

Real model and Blender/MCP smoke tests are opt-in and are not run in CI by default.
