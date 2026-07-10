# Changelog

## Unreleased

- One-click `Install Agent Dependencies` in the panel and add-on preferences: sidecar packages install into a NodeCue-managed `nodecue-deps` folder using the sidecar Python (Blender's own Python by default). No manual virtualenv needed.
- Sidecar runtime requirements now ship inside the add-on package (`nodecue/requirements-agent.txt`) and no longer include test-only packages.
- Repo-root `requirements-agent.txt` renamed to `requirements-dev.txt` (CI/test dependencies).
- Removed hardcoded developer paths from addon defaults; `NODECUE_AGENT_PYTHON` overrides the sidecar Python.
- Minimum Blender version raised to 5.0; docs state the Blender 5.0+ baseline.
- Docs now say community blender-mcp instead of official Blender MCP.

## 0.1.0-alpha.14 - 2026-06-08

This snapshot is preparing NodeCue for a first public alpha. The goal is a usable Geometry Nodes-focused Blender add-on that early users can install, test, and report issues against.

### Included

- Blender add-on package: `nodecue/`.
- Local SDK sidecar package: `nodecue_agent/`.
- Vendored Geometry Nodes skill snapshot.
- OpenRouter and OpenAI-compatible model configuration.
- Generate, Explain, and Modify modes through the NodeCue panel.
- Local bridge for controlled Blender node operations.
- Local report JSON and optional saved `.blend` copy for manual review.
- Offline tests and public-repo CI.
- Alpha issue template, contribution guide, security policy, and support/business model notes.
- README status wording aligned with a public alpha release candidate.
- Public launch announcement drafts for GitHub, Blender/community forums, the standalone skill package, and optional paid help.
- Post-public smoke check added to the release checklist.
- Maintainer release runbook added for the final public switch and npm follow-up.
- Maintainer runbook public-switch commands verified against the local GitHub CLI.
- Maintainer runbook now uses release tag variables instead of hardcoded NodeCue candidate tags.
- Paid support intake template added for optional setup help, workflow reviews, asset-library reviews, and sponsored fixes.
- Setup troubleshooting guide added for Check Setup, Sidecar Python, `.env`, provider/model, and graph-quality report issues.
- Release zip now installs through Blender's normal Add-ons installer.

### Not Included Yet

- Shader Nodes or Compositing Nodes support.
- ChatGPT Plus or Claude Pro OAuth login.
- Hosted service or paid feature gate.
- Bundled sidecar Python dependencies.
- Stable asset-library indexing beyond early opt-in experiments.

### External Agent Path

External agents should use the standalone `nodecue-blender-node-skills` package with the official Blender MCP. They do not need to route through NodeCue unless they specifically want NodeCue-maintained helper data in a future release.
