# Maintainer Release Runbook

Use this only after the release candidate has passed CI and you are ready to expose the repositories publicly.

Current prepared add-on candidate:

- NodeCue release: `v0.1.0-alpha.9`
- Bundle: `nodecue-v0.1.0-alpha.9-alpha-bundle.zip`
- Bundle SHA256: `e4d5e945d01e704396d896de9723913e7710ad0c091ea6bb9f45640fa3fdeb38`

Current prepared skill candidate:

- Skill release: `v0.1.0-alpha.1`
- npm package: `@nodecue/blender-node-skills@0.1.0-alpha.1`
- npm status: not published yet

## Minimum Public Alpha Switch

Run these in order:

```bash
gh repo edit monswag/nodecue-blender-node-skills --visibility public --accept-visibility-change-consequences
gh repo edit monswag/NodeCue --visibility public --accept-visibility-change-consequences
gh release edit v0.1.0-alpha.1 --repo monswag/nodecue-blender-node-skills --draft=false --prerelease
gh release edit v0.1.0-alpha.9 --repo monswag/NodeCue --draft=false --prerelease
```

Then run the post-public smoke check in `docs/release-checklist.md`.

Do not run these commands until you are comfortable making both repositories publicly visible.

## Publish Announcement

Use `docs/launch-announcement.md` after the public smoke check passes.

Recommended first order:

1. GitHub release page / repository README.
2. Blender community forum or relevant Discord.
3. External-agent/skill-focused post.

## npm Follow-Up

Do this after the GitHub checkout fallback has been verified publicly:

```bash
gh secret set NPM_TOKEN --repo monswag/nodecue-blender-node-skills
gh workflow run publish.yml --repo monswag/nodecue-blender-node-skills -f publish=false -f tag=alpha
```

After the dry-run workflow passes:

```bash
gh workflow run publish.yml --repo monswag/nodecue-blender-node-skills -f publish=true -f tag=alpha
npm view @nodecue/blender-node-skills version dist-tags --json
npx @nodecue/blender-node-skills install --force
```

If the `@nodecue` npm scope is unavailable, stop and rename the package, README commands, docs, and release notes together. Do not publish under an improvised name.

## Older Draft Releases

Older NodeCue draft releases can be kept during the first alpha if they remain unpublished. Delete them only after confirming the current public release is visible and downloadable.
