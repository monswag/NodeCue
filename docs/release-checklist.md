# Public Release Checklist

Use this before making the private release repositories public.

## Repository Checks

- Confirm both repositories are private until the first alpha bundle and skill package are ready:
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

- Build the alpha bundle:

```bash
python scripts/build_release_bundle.py
```

- Verify the bundle contains `nodecue/`, `nodecue_agent/`, `docs/`, `scripts/`, `.env.example`, and no private artifacts.
- Create an alpha tag such as `v0.1.0-alpha.1`.
- Let GitHub Actions create the draft release.
- Review the draft release notes before publishing.
- Keep the release notes clear that this is a Blender 5.1 Geometry Nodes alpha, not a polished one-click installer.

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

## First Community Ask

Ask testers to try one of these:

- Generate a noise-displaced terrain graph.
- Explain an existing Geometry Nodes group.
- Modify an existing graph by adding exposed controls.
- Use the standalone skill with Codex, Claude, or another agent through Blender MCP.

Useful feedback includes the exact prompt, model/provider, report JSON, Blender version, screenshots, and what looked wrong in the graph.
