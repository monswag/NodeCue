# Maintainer Release Runbook

Use this only after the release candidate has passed CI and you are ready to expose the repositories publicly.

Before publishing, choose the current prepared add-on candidate from the latest green draft release:

```bash
gh release list --repo monswag/NodeCue --limit 5
NODECUE_TAG=<current NodeCue draft release tag>
gh release view "$NODECUE_TAG" --repo monswag/NodeCue --json isDraft,isPrerelease,assets
```

Current prepared skill candidate variables:

```bash
SKILL_TAG=v0.1.0-alpha.1
SKILL_PACKAGE=@nodecue/blender-node-skills@0.1.0-alpha.1
```

npm status is not published yet.

## Minimum Public Alpha Switch

Run these in order:

```bash
gh repo edit monswag/nodecue-blender-node-skills --visibility public --accept-visibility-change-consequences
gh repo edit monswag/NodeCue --visibility public --accept-visibility-change-consequences
gh release edit "$SKILL_TAG" --repo monswag/nodecue-blender-node-skills --draft=false --prerelease
gh release edit "$NODECUE_TAG" --repo monswag/NodeCue --draft=false --prerelease
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
