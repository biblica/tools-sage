# Release Cleanup Checklist

This is the standard SAGE release-cleanup and closeout list. Copy the checklist section for each
release candidate or release attempt, retain the completed record, and link the resulting evidence
to the applicable milestone. Cleanup is performed in a clean staging tree; it must never destroy
Operator-owned data in an active installation merely to make a release gate pass.

## Current release record

Promotion sequence: `v0.01beta` → `v0.01rc1` → later numbered RCs as required → `v0.01` only after final approval.

| Field | Value |
|---|---|
| Record | `RCLEAN-0.01beta-001` |
| Version | `0.01beta` |
| Milestone | `MS-BETA-REQUALIFY` |
| State | BLOCKED |
| Blocking issue | `BI-20260826-001` |
| Source hash | NOT RECORDED |
| Hardening receipt | NOT RECORDED |
| Release artifact | NOT BUILT |
| Artifact SHA-256 | NOT RECORDED |

## 1. Freeze release scope

- [ ] Confirm the root `VERSION` and `system/config/sage-standard.json` release version match.
- [ ] Confirm the target milestone, release status, and public-readiness claim are accurate.
- [ ] Review all open Build Issues and block release for every unresolved release-critical issue.
- [ ] Review the TODO log; close completed items and explicitly carry deferred work forward.
- [ ] Record verified work in Implemented Updates.
- [ ] Synchronize release-significant changes into `system/config/CHANGELOG.md` and
  `docs/advanced/release/RELEASE-NOTES.md`.
- [ ] Confirm `system/config/DEVELOPMENT-STATUS.md`, `docs/advanced/release/HANDOVER.md`, and
  `docs/KNOWN-LIMITATIONS.md` describe the same release state.
- [ ] Rebuild changed canonical menu text in
  `system/config/localization/menu-localization.json`; preserve a stable semantic key only when its
  meaning is unchanged, and complete every supported locale before qualification.
- [ ] Run `python -m pytest system/tests/test_menu_localization.py` and confirm every current static
  and governed dynamic menu phrase appears exactly once with nonblank `en-US`, `en-GB`, `id`, `fr`,
  `ru`, and `pt-BR` renderings.
- [ ] Freeze the governed source. Any later governed edit invalidates receipts and restarts
  qualification.

## 2. Preserve installation data

- [ ] Build from the clean staging process; do not manually purge the active installation tree.
- [ ] Keep all `localdata/` content, top-level `jobs/`/`reports/`/`workspace_data/` legacy roots,
  `.venv/`, and every machine/operator-local artifact out of Core staging.
- [ ] Stage the governed immutable `ecosystem.yml`; mutable workstation/operator policy belongs only
  in `localdata/.system/config/` and must never be copied into Core.
- [ ] Preserve any Operator-owned Job, Run, Project, report, and grammar-profile data required after
  the build.
- [ ] Write release ZIPs, receipts, and handover artifacts outside the governed source tree.

## 3. Inspect the staged source

- [ ] Confirm the staged tree matches `docs/advanced/release/VANILLA-INSTALL-MANIFEST.md`.
- [ ] Confirm only governed `@GRK` and `@HEB` Scripture payloads are present.
- [ ] Confirm no top-level `jobs/`, `reports/`, `workspace_data/`, or `localdata/` directory exists in
  the staged Core tree.
- [ ] Confirm no host-specific managed runtime exists in Core; first launch must install
  `localdata/.system/runtime/python` from the pinned OS/CPU artifact and create `runtime/venv` from
  the governed dependency manifests.
- [ ] Remove or reject `.git`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`,
  `htmlcov`, `.coverage`, `.venv`, build output, bytecode, editor backups, and platform debris.
- [ ] Remove or reject `.DS_Store`, `Thumbs.db`, `desktop.ini`, `__MACOSX`, temporary files, and
  generated runtime logs.
- [ ] Reject nested ZIP/archive files, symlinks, unknown root entries, and unintended executable
  files.
- [ ] Confirm Windows path, case-collision, filename, path-length, and line-ending rules pass.
- [ ] Confirm POSIX executable permissions remain only on governed launchers/tools.

## 4. Run exact-source gates

- [ ] Run `python system/tools/validate_schemas.py`.
- [ ] Run `python system/tools/validate_package.py` against the clean staged source.
- [ ] Run `python system/tools/deep_audit.py . --mode source` against the clean staged source.
- [ ] Run every deterministic hardening shard from zero.
- [ ] Formally combine shard receipts and confirm every discovered test module was scheduled exactly
  once.
- [ ] Confirm the formal hardening receipt has no errors or warnings and matches the frozen staged
  source SHA-256.
- [ ] Rerun package validation and source deep audit after formal testing.
- [ ] Record all commands, results, receipts, test totals, and the frozen source hash below.

## 5. Build and verify the distribution

- [ ] Run `python system/tools/build_release.py` with the frozen root, exact hardening receipt, and
  an output path outside the source tree.
- [ ] Verify ZIP integrity and the emitted SHA-256 file.
- [ ] Build a second time from the same frozen source and confirm an identical SHA-256.
- [ ] Extract the ZIP into a fresh empty directory.
- [ ] Run package validation and source deep audit against the extracted distribution.
- [ ] Confirm no local runtime data, `localdata`, caches, `.venv`, receipts, or release artifacts entered the ZIP.
- [ ] Run clean-start/bootstrap smoke checks on the extracted distribution.
- [ ] Verify BASIC, STANDARD, and hardware-detection-fallback startup behavior where applicable.

## 6. Acceptance and handover

- [ ] Complete the release milestone's required Windows acceptance.
- [ ] Complete the release milestone's required macOS acceptance.
- [ ] Complete the release milestone's required Linux acceptance.
- [ ] Complete the required real Operator BIC/SAW acceptance scopes.
- [ ] Record unresolved linguistic approval, corpus authority, redistribution rights, and platform
  limits without reclassifying them as passed technical gates.
- [ ] Confirm the handover manifest covers every included file and preserves required POSIX modes.
- [ ] Confirm the release remains pre-release unless every public-production gate is explicitly
  closed.

## 7. Close the release record

- [ ] Fill in the result record below and attach/link exact evidence.
- [ ] Resolve or close the linked Build Issues and TODOs.
- [ ] Add the release/build outcome to Implemented Updates.
- [ ] Update the milestone state and exit evidence.
- [ ] Update Development Status, Handover, Release Notes, and the changelog.
- [ ] Create the approved source-control commit/tag only after all applicable gates pass.
- [ ] Preserve the final artifact, SHA-256, exact-source hardening receipt, and handover evidence
  outside the source tree.

## Result record

| Date | Operator | Frozen source SHA-256 | Tests | Package/audit | Artifact | Artifact SHA-256 | Result |
|---|---|---|---|---|---|---|---|
| NOT RUN | NOT RECORDED | NOT RECORDED | NOT RUN | NOT RUN | NOT BUILT | NOT RECORDED | BLOCKED |

## Checklist maintenance

If a release tool or gate changes, update this checklist in the same governed change. The normative
technical requirements remain `docs/advanced/release/RELEASE-GATES.md`; this file is the PM execution and evidence
record for those requirements.
