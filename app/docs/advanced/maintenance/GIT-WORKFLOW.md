# Git Workflow — SAGE 0.02alpha1

## Repository contract

`SAGE/` is the portable Git repository. `app/` contains reproducible application material and
`localdata/` contains persistent local operator/system data. Git tracks only `localdata/README.md`;
all other localdata content is ignored.

Core resources are accepted only after review, tests, qualification, and release approval. Local or
candidate resources remain in `localdata/inputs/resources/` or `localdata/plugins/`. See
`docs/advanced/future/RESOURCE-HUB.md` for the planned contribution model.

## Branch model

Use a light trunk/integration model:

```text
feature/* --\
fix/* ------> dev ----> release/vX.Y-rcN ----> main ----> annotated tag
refactor/* -/
```

- `main`: last known-good releasable Core; no routine direct pushes.
- `dev`: integration branch for the next build.
- `feature/*`, `fix/*`, `refactor/*`: short-lived branches, preferably one worker/worktree each.
- `release/*`: frozen stabilization branch; fixes and release/documentation corrections only.
- `hotfix/*`: exceptional release repair.

Feature/fix branches should normally squash into `dev`; release/hotfix merges should preserve an
explicit merge commit. A tag identifies the immutable source used to produce a distribution.

## Local worktrees

Multiple workers should use Git worktrees rather than copied source directories. Each concurrent
worktree should use a separate `SAGE_DATA_HOME` unless shared test data is deliberately required.
This prevents controllers, locks, Jobs, and generated state from contaminating one another.

## Safe update

Stop active SAGE processes, then from `SAGE/`:

```text
git status --short
git pull --ff-only
./sage
```

Windows uses `sage.cmd`. Git updates the application; localdata is not replaced. Re-cloning or
replacing `app/` can reuse the recognized `SAGE/localdata` directory.

Do not run `git clean -fdx` in a live bundle: ignored localdata is physically inside the repository
directory and a destructive clean can delete it. Back up `localdata/` before maintenance.

## Required gates

Before merging/tagging a qualified Core:

```text
python app/system/tools/validate_schemas.py
python app/system/tools/validate_package.py
python app/system/tools/deep_audit.py app --mode source
python app/system/tools/hardening.py
```

GitHub Actions also qualifies the source on Windows, macOS, and Linux across the supported Python
matrix. Release packaging must be created by `app/system/tools/build_release.py`, not by zipping a live
installation. Release validation includes only `localdata/README.md` and rejects runtime contents,
platform metadata, and other mutable local state from the distribution.

## Release provenance

A distributed package must be attributable to an exact commit/tag. Source changes and handover
material should be committed together when they describe the same release state. Generated release
ZIPs and hardening receipts are published as release/CI artifacts rather than accumulated in normal
source history.
