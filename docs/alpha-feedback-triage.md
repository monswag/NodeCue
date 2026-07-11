# Alpha Feedback Triage

Use this after public alpha issues start coming in.

## First Pass

For every new alpha issue:

- Confirm the report does not include API keys, private asset-library paths, or unreleasable `.blend` files.
- Ask for missing basics if needed: Blender version, OS, mode, provider/model, prompt, report JSON, and screenshots or shareable `.blend`.
- Keep the original prompt intact. Do not rewrite the user's prompt when filing follow-up work.
- Add one primary area label and any useful secondary labels.

## Labels

- `setup`: install, Check Setup, Python path, `.env`, provider key, or sidecar startup.
- `model-provider`: OpenRouter, OpenAI-compatible endpoint, local model endpoint, model timeout, or model output format.
- `graph-quality`: generated or modified Geometry Nodes graph is structurally wrong, disconnected, or hard to use.
- `explanation-quality`: explanation is inaccurate, too shallow, missing readback details, or frames are unhelpful.
- `external-agent`: Codex, Claude, a Blender MCP server (official or community), or standalone skill workflow.
- `asset-library`: asset-library permission, node-group reuse, indexing, or private library behavior.
- `support-business`: setup help, consulting, sponsorship, or paid support discussion.
- `release-blocker`: anything that should stop a public release or announcement.

## Triage Outcomes

- Reproducible setup break: label `setup`, keep public, fix docs or Check Setup behavior first.
- Real model graph failure: label `graph-quality` and `model-provider`; ask for report JSON and saved `.blend` if missing.
- Explain mode changed the file: label `release-blocker`; Explain should be read-only.
- External agent result is poor after using the skill: label `external-agent`; move skill-specific fixes to the standalone skill repo when appropriate.
- Private asset-library problem: label `asset-library`; keep sensitive details out of public comments.
- Paid help request: label `support-business`; keep core bug fixes and alpha access free.

## Follow-Up Rules

- Prefer small fixes that improve installability, graph correctness, readback repair, or feedback quality.
- Do not use a benchmark pass rate as the only success measure. Keep a human note about what looked wrong in Blender.
- If a fix changes the vendored Geometry Nodes skill, check whether the standalone skill repo needs the same change.
- If a fix affects release readiness, update the public alpha launch checklist issue.
