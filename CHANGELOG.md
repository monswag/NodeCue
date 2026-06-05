# Changelog

## 0.1.0-alpha.12 - 2026-06-05

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

### Not Included Yet

- Shader Nodes or Compositing Nodes support.
- ChatGPT Plus or Claude Pro OAuth login.
- Hosted service or paid feature gate.
- Polished one-click release packaging.
- Stable asset-library indexing beyond early opt-in experiments.

### External Agent Path

External agents should use the standalone `nodecue-blender-node-skills` package with the official Blender MCP. They do not need to route through NodeCue unless they specifically want NodeCue-maintained helper data in a future release.
