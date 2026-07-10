# NodeCue

NodeCue is a Blender add-on prototype for learning, building, modifying, and explaining Geometry Nodes with a focused local agent.

The current alpha is intentionally narrow:

- Blender 5.0+ add-on package (most tested on 5.1): `nodecue/`
- local sidecar agent package: `nodecue_agent/`
- built-in Geometry Nodes skill snapshot: `nodecue/skills/geometry-nodes/`
- OpenRouter / OpenAI-compatible model configuration

The Geometry Nodes skill is also maintained in the standalone `nodecue-blender-node-skills` package. This repository vendors a copy so the Blender add-on works out of the box.

## Quick Start

1. Download the NodeCue release zip, for example `nodecue-v0.1.0-alpha.14-blender-addon.zip`.
2. In Blender 5.0 or newer, open `Edit > Preferences > Add-ons > Install...`, select the zip, then enable `NodeCue`.
3. Create a Python environment for the sidecar dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r "/path/to/Blender/5.1/scripts/addons/nodecue/requirements-agent.txt"
```

4. Create a small provider env file anywhere on your machine and point NodeCue preferences to it:

```text
OPENROUTER_API_KEY=...
NODECUE_AGENT_PROVIDER=openrouter
NODECUE_AGENT_MODEL=moonshotai/kimi-k2.6
```

5. In NodeCue preferences, set `Sidecar Python` to your `.venv` Python and run Check Setup.
6. Use the NodeCue panel to run Generate, Explain, or Modify.

Detailed setup is in [docs/quickstart.md](docs/quickstart.md).

To build a local release bundle zip:

```bash
python3 scripts/build_release_bundle.py
```

The output zip is installable through Blender's normal add-on installer.

Pushing a `v*` tag creates a draft GitHub Release with the same Blender add-on zip attached.

Before making the repositories public, use [docs/release-checklist.md](docs/release-checklist.md).

## External Agents

Codex, Claude, and other agents can use the standalone Geometry Nodes skill with the community blender-mcp project. External agents do not need to route through the NodeCue bridge unless they specifically want NodeCue-maintained helper data.

See [docs/external-agents.md](docs/external-agents.md).

## Alpha Feedback

Useful reports include the prompt, Blender version, provider/model, report JSON, and what looked wrong in the node graph. Use the `Alpha feedback` issue template after trying Generate, Explain, Modify, or the external-agent workflow.

Do not paste API keys or private asset-library paths into public issues.

Suggested first tests are in [docs/alpha-test-guide.md](docs/alpha-test-guide.md).

## Support and Business Model

The public alpha is free. Optional paid help should focus on setup support, workflow consulting, private asset-library indexing, or sponsored improvements. See [docs/support-and-business.md](docs/support-and-business.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for useful alpha contributions, PR expectations, and what to avoid while the Geometry Nodes alpha is still stabilizing.

## Security

Do not share API keys, private asset-library paths, or proprietary `.blend` files in public issues. See [SECURITY.md](SECURITY.md).

## Status

This is an alpha release candidate for public Geometry Nodes testing. It is usable for experiments, but setup still requires a sidecar Python environment and a model provider key. Current limits are tracked in [docs/known-limitations.md](docs/known-limitations.md), and the release/business direction is in [docs/public-alpha.md](docs/public-alpha.md).

See [CHANGELOG.md](CHANGELOG.md) for the current alpha snapshot contents.

## Tests

Offline tests:

```bash
python -m pytest tests/ -q
```

Real model and Blender/MCP smoke tests are opt-in and are not run in CI by default.
