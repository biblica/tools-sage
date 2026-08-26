# Git Workflow — SAGE 0.01beta

## Repository contract

`SAGE/` is the Git repository and contains only reproducible Core. `SAGEdata/` is persistent local
operator/system data and is outside the repository by default. `.gitignore` is defense in depth; it
is not the persistence mechanism.

Core resources are accepted only after review, tests, qualification, and release approval. Local or
candidate resources remain in `SAGEdata/resources/` or `SAGEdata/plugins/`. See
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

Windows uses `sage.cmd`. Git updates Core; SAGEdata is not replaced. Re-cloning to the same
`SAGE/` path can reuse the recognized sibling `SAGEdata` directory.

Do not use `git clean -fdx` as a persistence strategy. SAGEdata is physically outside the repository
so ordinary Git cleanup cannot delete operator data.

## Required gates

Before merging/tagging a qualified Core:

```text
python system/tools/validate_schemas.py
python system/tools/validate_package.py
python system/tools/deep_audit.py . --mode source
python system/tools/hardening.py
```

GitHub Actions also qualifies the source on Windows, macOS, and Linux across the supported Python
matrix. Release packaging must be created by `system/tools/build_release.py`, not by zipping a live
installation. Release validation rejects virtual environments, Jobs, reports, SAGEdata, platform
metadata, and other mutable local state inside Core.

## Release provenance

A distributed package must be attributable to an exact commit/tag. Source changes and handover
material should be committed together when they describe the same release state. Generated release
ZIPs and hardening receipts are published as release/CI artifacts rather than accumulated in normal
source history.
