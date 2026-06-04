# Changelog

## 0.1.0-alpha.0 - 2026-06-04

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

### Not Included Yet

- Shader Nodes or Compositing Nodes support.
- ChatGPT Plus or Claude Pro OAuth login.
- Hosted service or paid feature gate.
- Polished one-click release packaging.
- Stable asset-library indexing beyond early opt-in experiments.

### External Agent Path

External agents should use the standalone `nodecue-blender-node-skills` package with the official Blender MCP. They do not need to route through NodeCue unless they specifically want NodeCue-maintained helper data in a future release.
