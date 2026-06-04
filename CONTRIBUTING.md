# Contributing

NodeCue is in public alpha preparation. Contributions are most useful when they improve installability, Geometry Nodes reliability, issue diagnosis, or the first user feedback loop.

Before contributing, read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Good First Contributions

- Quickstart fixes for macOS, Windows, or Linux.
- Clearer setup errors in the Blender panel.
- Offline tests for existing `bpy_recipes` behavior.
- Small Geometry Nodes bug fixes that include readback evidence.
- Better report summaries that make failed agent runs easier to debug.

## Please Avoid For Now

- Broad rewrites of the agent architecture.
- Shader Nodes or Compositing Nodes implementation before the Geometry Nodes alpha is stable.
- OAuth/account-login provider flows.
- Changes that require committing generated `.blend` files, private `.env` files, or local cache directories.
- Old MCP/server architecture changes. External agents should use the official Blender MCP path.

## Useful Issue Reports

For alpha feedback, include:

- Blender version;
- OS;
- mode: Generate, Explain, Modify, or external agent workflow;
- provider/model;
- prompt;
- report JSON snippet;
- screenshot or generated `.blend` if shareable;
- what looked wrong in the node graph.

Do not include API keys or private asset-library paths.

Maintainers can use [docs/alpha-feedback-triage.md](docs/alpha-feedback-triage.md) to label and route alpha reports.

## Pull Request Checklist

- Keep changes scoped to the reported issue.
- Run offline tests:

```bash
conda run -n blender python -m pytest tests/ -q
```

- If the change affects a real model or Blender execution path, add the report path and saved `.blend` path in the PR description.
- If the change affects the vendored Geometry Nodes skill, note whether the standalone `nodecue-blender-node-skills` repo also needs the same update.
- Do not commit generated artifacts: `.env`, `.DS_Store`, `__pycache__`, `.pytest_cache`, `.blend`, `.blend1`, or `tests/integration/debug_blends/`.
