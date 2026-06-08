# Public Release Checklist

Use this before making the private release repositories public.

## Repository Checks

- Confirm both repositories are private until the first Blender add-on zip and skill package are ready:
  - `monswag/NodeCue`
  - `monswag/nodecue-blender-node-skills`
- Confirm the repositories have:
  - `README.md`
  - `LICENSE`
  - `CONTRIBUTING.md` where applicable
  - `SECURITY.md`
  - `CHANGELOG.md`
  - issue templates
  - CI workflows
- Confirm no private local files are present:

```bash
find . -name '.env' -o -name '.DS_Store' -o -name '__pycache__' -o -name '*.pyc' -o -name '*.blend' -o -name '*.blend1' -o -name '*.tgz' -o -name '*.zip'
```

## NodeCue Add-on Release

- Run offline tests:

```bash
python -m pytest tests/ -q
```

- Build the Blender add-on zip:

```bash
python scripts/build_release_bundle.py
```

- Verify the zip contains `nodecue/__init__.py`, `nodecue/nodecue_agent/`, `nodecue/requirements-agent.txt`, `nodecue/nodecue.env.example`, and no private artifacts.
- Create an alpha tag such as `v0.1.0-alpha.1`.
- Let GitHub Actions create the draft release.
- Review the draft release notes before publishing.
- Keep the release notes clear that the add-on installs through Blender normally, but still needs sidecar Python dependencies and a model provider key.

## Skill Package Release

- Run the install smoke test:

```bash
npm test
```

- Verify package contents:

```bash
npm pack --dry-run
```

- Run the manual publish workflow with `publish=false` first.
- Configure `NPM_TOKEN` only when ready to publish.
- Publish with the `alpha` npm dist-tag until community feedback is stable.
- Verify install from npm:

```bash
npx @nodecue/blender-node-skills install --force
```

- If npm publishing is still pending, verify the checkout fallback:

```bash
git clone https://github.com/monswag/nodecue-blender-node-skills.git
cd nodecue-blender-node-skills
node bin/install.js install
```

## Public Launch Notes

- Make both repositories public only after CI is green.
- Pin the first public GitHub release.
- Open one tracking issue for alpha feedback themes:
  - setup failures
  - model/provider configuration
  - graph correctness
  - explanation quality
  - external agent + Blender MCP results
- Do not charge for alpha access, bug fixes, or the standalone skill.
- Offer optional paid help only for setup support, workflow consulting, private asset-library indexing, or sponsored improvements.

## Post-Public Smoke Check

Run this immediately after making the repositories public and publishing the draft release:

- Open both repositories from a signed-out or incognito browser:
  - `https://github.com/monswag/NodeCue`
  - `https://github.com/monswag/nodecue-blender-node-skills`
- Confirm the NodeCue release page is public and shows the current Blender add-on zip.
- Download the zip from the public release page.
- Install the zip through Blender's normal add-on installer.
- Confirm the installed add-on folder contains:
  - `nodecue/__init__.py`
  - `nodecue/nodecue_agent/__init__.py`
  - `nodecue/requirements-agent.txt`
  - `nodecue/nodecue.env.example`

- Confirm GitHub issues show the alpha feedback template.
- Confirm the standalone skill checkout fallback works from a fresh directory:

```bash
git clone https://github.com/monswag/nodecue-blender-node-skills.git
cd nodecue-blender-node-skills
node bin/install.js install
```

- If npm is not published yet, confirm public docs clearly say to use the checkout fallback.

## First Community Ask

Ask testers to try one of these:

- Generate a noise-displaced terrain graph.
- Explain an existing Geometry Nodes group.
- Modify an existing graph by adding exposed controls.
- Use the standalone skill with Codex, Claude, or another agent through Blender MCP.

Useful feedback includes the exact prompt, model/provider, report JSON, Blender version, screenshots, and what looked wrong in the graph.
