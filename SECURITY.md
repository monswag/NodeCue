# Security Policy

NodeCue is an alpha Blender add-on that can read local Blender state, run a local sidecar process, and use model provider API keys. Treat it as experimental software and avoid running it on sensitive production files without backups.

## Do Not Share Secrets

Never post these in public issues:

- API keys or `.env` files;
- private asset-library paths;
- proprietary `.blend` files;
- reports that include private prompts, file paths, or studio data.

Redact sensitive values before attaching report JSON or screenshots.

## Reporting Security Issues

If you find a security issue, open a GitHub issue with minimal public detail and say that you have a private security report available. Do not include exploit details, secrets, or private files in the public issue.

Useful safe details:

- affected NodeCue version or commit;
- operating system;
- Blender version;
- whether the issue involves provider configuration, local file access, asset-library scanning, or the sidecar process;
- a short non-sensitive summary.

## Current Alpha Boundaries

- NodeCue does not intentionally upload `.blend` files or asset-library contents.
- The built-in agent uses the configured model provider and sends prompts/context needed for the run.
- User asset-library scanning is intended to be opt-in.
- External agents using official Blender MCP are outside NodeCue's permission boundary.

If you are testing with private assets, keep generated reports and `.blend` artifacts local unless you explicitly choose to share them.
