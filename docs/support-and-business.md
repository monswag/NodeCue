# Support and Business Model

NodeCue's public alpha should stay useful without payment. The first goal is to learn whether Blender users can install it, run real Geometry Nodes prompts, and get teachable node graphs.

## Free During Alpha

- Core NodeCue alpha access.
- The vendored Geometry Nodes skill.
- Bug reports, reproducible setup issues, and public discussion.
- Fixes for broken install steps, unsafe behavior, or incorrect documented behavior.

## Optional Paid Help

Paid work should be optional and focused on convenience or specialized help:

- setup sessions for users who cannot configure Python, Blender, or model providers;
- workflow consultation for artists or studios testing NodeCue in production-like scenes;
- custom node-group/library indexing and descriptions for private asset libraries;
- sponsored development of specific Geometry Nodes reliability improvements.

Do not put basic alpha usage, bug fixes, or the standalone skill behind a paywall.

## Starter Support Menu

Use this as the first simple paid offering while the alpha is still proving value:

- Alpha setup help: install NodeCue, configure the sidecar Python, connect an OpenAI-compatible provider, and run the first Generate test.
- Workflow review: test NodeCue on one user-provided Geometry Nodes workflow and summarize where the graph or explanation fails.
- Asset-library review: inspect a small authorized node-group library and suggest reuse/indexing improvements without publishing private assets.
- Sponsored fix: fund a scoped Geometry Nodes reliability improvement that remains available in the public alpha.

Do not promise production support, private model hosting, OAuth login, or custom Shader/Compositing Nodes work in the first alpha offer.

Suggested public wording:

```text
NodeCue is free during alpha. If you want help getting it running or testing it on your Geometry Nodes workflow, paid setup and workflow review sessions are available. Bug reports and basic alpha access stay free.
```

Keep payment details out of public issues. Use issues to identify the request, then move scheduling, files, and private asset-library details to a private channel.

## Future Pro Direction

A future Pro tier can make sense only after the free alpha proves value. The most plausible paid features are:

- richer asset-library search and node-group descriptions;
- project-specific skill packs;
- saved workflow presets;
- team/studio support around private node libraries;
- polished release builds with fewer setup steps.

OAuth/account-login model access should remain research until there is a stable, appropriate third-party app path.

## Contact Path

For now, use GitHub issues for public feedback and keep sensitive details private. Do not post API keys, private asset-library paths, or unreleasable `.blend` files in public issues.
