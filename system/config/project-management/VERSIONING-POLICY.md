# SAGE Project Versioning Policy

This document governs SAGE product versions, release states, promotion, source-control tags, and
distribution names. It is an internal project policy; Operator data and Job/Run schema versions are
separate contracts and do not inherit the product version.

## Canonical identity

- The root `VERSION` file is the canonical machine product version and never includes a leading
  `v`.
- Human-facing product labels, source-control tags, and release headings add the leading `v`.
- Preserve the approved two-digit minor spelling. The current source identity is `0.01beta`; the
  human label is `v0.01beta`.
- Python packaging tools may normalize `0.01beta` to the PEP 440 equivalent `0.1b0` in installed
  distribution metadata. SAGE menus, reports, documentation, artifacts, and tags continue to use
  the canonical SAGE spelling.

## Promotion sequence

| Phase | Machine version | Human label | Release status | Public ready |
|---|---|---|---|---|
| Beta baseline | `0.01beta` | `v0.01beta` | `BETA` | `false` |
| First qualified candidate | `0.01rc1` | `v0.01rc1` | `RELEASE_CANDIDATE` | `false` |
| Later qualified candidates | `0.01rcN` | `v0.01rcN` | `RELEASE_CANDIDATE` | `false` |
| Approved release | `0.01` | `v0.01` | `RELEASE` | Set `true` only after final approval |

Increment `N` for every new candidate source hash. Never reuse an RC number, move an existing tag,
or describe a Beta build as an RC. A later development line starts only through an approved project
decision recorded in Milestones, the changelog, and release notes.

## Feature-maturity classifications

Feature maturity is separate from the product release phase. A Beta, RC, or approved release may
contain features at different maturity levels when the release definition explicitly allows it.

| Machine state | Required display label | Meaning |
|---|---|---|
| `SUPPORTED` | `SUPPORTED` | Included in the authoritative interface for the declared release scope. |
| `EXPERIMENTAL_UNSTABLE` | `EXPERIMENTAL / UNSTABLE` | Incomplete, non-authoritative, and permitted to change incompatibly. |
| `DEPRECATED` | `DEPRECATED` | Retained temporarily for migration and scheduled for removal. |

The exact current Beta binding is:

| Feature | Classification | Authority consequence |
|---|---|---|
| Textual TUI | `EXPERIMENTAL_UNSTABLE` (`EXPERIMENTAL / UNSTABLE`) | Classic menu and scriptable CLI remain authoritative. |

Advancing the product from Beta to an RC does not automatically promote a feature. Changing a
feature classification requires an Implemented Update, its own acceptance evidence, synchronized
machine and human release definitions, and approval through the applicable milestone.

## Promotion gates

1. Freeze one exact governed source tree and record its source hash.
2. Close or explicitly defer every release-critical Build Issue and TODO.
3. Complete the applicable Release Cleanup record.
4. Pass schema validation, package validation, source deep audit, deterministic hardening and formal
   combine against the same frozen source hash.
5. Complete the platform and Operator acceptance required by the target milestone.
6. Rebuild changed canonical menu text for every supported interface locale and pass the complete
   menu-localization contract tests.
7. Update every canonical version surface in one governed change.
8. Build and verify the distribution before creating the immutable source-control tag.

Any governed source or test change invalidates the current receipts. Requalify the changed source
and use the next RC number. Promotion to `v0.01` additionally requires explicit public-readiness
approval; passing deterministic tests alone is insufficient.

## Required synchronized surfaces

Every product-version change must update and verify:

- `VERSION`;
- `system/config/sage-standard.json` release version, status, and readiness;
- machine feature classifications and their exact human-facing labels;
- `system/pyproject.toml` package version and description;
- `system/src/sage/__init__.py` and `system/src/sage/build_policy.py`;
- current entry-point, status, handover, test, release-note, changelog, and project-tree text;
- PM milestone, TODO, Build Issue, Implemented Update, and Release Cleanup targets;
- version-pinned tests, manifests, help text, and artifact naming;
- the governed pre-release state-boundary recognizer.

Distribution folders and archives use `SAGE-v<version>-Full-Distribution`. A version promotion must
not rename or rewrite Operator-owned external Project paths merely because a development workspace
directory contains an earlier label.

## State and compatibility

- A product-version change must preserve recognized `SAGEdata` Operator, Project, Job, Run, report,
  resource, plugin, and local-settings data. Version changes may invalidate and regenerate explicitly
  derived `.system` state, but they must not delete persistent Operator data. The managed runtime at
  `SAGEdata/.system/runtime/venv` is fingerprinted and repaired/rebuilt when Core dependency contracts change.
- Job, Run, workflow, profile, schema, and receipt fields named `schema_version`, `profile_version`,
  or similar are independent contract versions. Change them only when that contract changes.
- Protected-rule provenance and compatibility fixtures may retain earlier version tokens when they
  test migration or exact historical behavior.

## Historical records

Do not rewrite earlier changelog/release-note facts as though they occurred under the new version.
Keep prior labels only in sections explicitly marked historical, protected provenance, and
compatibility tests. Current source, menus, PM targets, package metadata, and release claims must
always use the canonical active identity.
