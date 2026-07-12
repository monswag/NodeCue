# Alpha Launch Announcement

Use these drafts after the repository is public and the current draft release is published.

## GitHub Release / README Short Intro

```text
NodeCue is an early Blender 5.0+ add-on for learning, building, modifying, and explaining Geometry Nodes with a focused local agent.

The first alpha is intentionally narrow: Geometry Nodes only, OpenRouter/OpenAI-compatible model setup, Build and read-only Explain actions, local report JSON, and optional saved .blend artifacts for debugging.

The add-on installs through Blender's normal Add-ons installer, and its Python dependencies install with one click from the add-on itself. The goal is to learn where real Blender users get stuck: setup, model choice, graph quality, explanation quality, or node execution.
```

## Blender / Community Forum Post

```text
I am opening an alpha for NodeCue, a Blender add-on focused on Geometry Nodes learning and graph construction.

The idea is not to replace full agents like Claude or Codex. NodeCue is narrower: it runs inside Blender, uses a controlled set of node operations, and tries to create teachable node graphs with frames and explanations.

Current alpha scope:
- Blender 5.0+ Geometry Nodes only
- Build (create or modify, decided from the prompt) and read-only Explain
- OpenRouter or another OpenAI-compatible model endpoint
- local report JSON and optional saved .blend artifacts
- a standalone Geometry Nodes skill that external agents can also use with Blender's official MCP or the community blender-mcp

Useful feedback:
- whether you could install it from the quickstart
- prompt, provider/model, and mode used
- what the generated node graph got wrong
- whether the explanation helped you understand the graph
- screenshots, report JSON, or a shareable .blend if possible

Please do not post API keys, private asset-library paths, or unreleasable production files in public issues.
```

## Standalone Skill Package Post

```text
I also split out the Geometry Nodes skill as a standalone package for agents such as Codex, Claude, or other tools that can control Blender through an MCP server (Blender's official Lab MCP or the community blender-mcp).

The skill is not a fixed list of graph templates. It is a knowledge package about Geometry Nodes reasoning: node roles, sockets, field/data-flow relationships, verified patterns, readback repair, and teachable frame organization.

Install is a plain git checkout: clone the repository and copy the skill folder into your agent's skills directory. See the README for exact commands.
```

## Optional Paid Help Wording

```text
NodeCue is free during alpha. If you want help getting it running or testing it on a specific Geometry Nodes workflow, paid setup and workflow review sessions may be available. Bug reports, basic alpha access, and fixes for broken documented behavior stay free.
```

Keep payment details, private files, and API credentials out of public issue threads.
