# Changelog

## 0.01beta

`0.01beta` is the first group-testing baseline published from the current Git-managed architecture. Unpublished internal development labels are intentionally not part of the public changelog.

### Storage and configuration

- Split replaceable Git-controlled `SAGE/` Core from persistent `SAGEdata/`.
- Defaulted `SAGEdata` to a sibling of `SAGE`, with explicit CLI/environment/persisted custom-location resolution.
- Added fail-closed data-root validation and prohibited data homes inside Core.
- Added visible operator roots for Projects, Jobs, reports, exports, local resources, and plugins.
- Added hidden `.system` roots for configuration overlays, state, indexes, caches, locks, transactions, logs, diagnostics, temporary data, workflows, Job controller state, and managed runtime.
- Made Core `ecosystem.yml` immutable during normal operation; mutable interface/operator settings now use local overlays.
- Redirected Project imports and parsed Styleguide/source material into project-owned SAGEdata paths.
- Removed legacy in-Core `workspace_data`, top-level Job/report state, and bundled `.venv` from the distribution contract.

### Deterministic runtime/bootstrap

- Added automatic first-run creation of the sibling/local SAGEdata structure.
- Moved the generated managed Python environment to `SAGEdata/.system/runtime/venv`.
- Added exact pinned dependency manifests and deterministic bootstrap/repair with binary-only packages, `--no-deps`, `pip check`, and runtime fingerprints.
- Removed manual/copied-environment and consent-driven venv setup paths.
- Preserved operator data across Beta/Core version updates; version changes no longer trigger destructive local-state resets.
- Kept the explicit out-of-box reset bounded to SAGEdata and Core-immutable while preserving the managed runtime.

### Release and Git hardening

- Added deterministic source staging and ZIP metadata independent of build host.
- Added exact-source sharded hardening receipts, formal exactly-once combine, package validation, source deep audit, archive integrity validation, and SHA-256 sidecars.
- Added release validation that rejects local/runtime roots, caches, bytecode, nested archives, stale artifacts, symlinks, and machine-specific state.
- Added GitHub Actions qualification across Ubuntu, Windows, and macOS with supported Python versions and checkout-clean verification.
- Sanitized machine-specific paths and unpublished version-history labels from the group-testing distribution.

### Resource governance

- Established Core as the home only for tested/reviewed/approved product resources.
- Established `SAGEdata/resources` and `SAGEdata/plugins` for local/candidate resources and extensions.
- Added the future Resource Hub contribution model for provenance, validation, security/license checks, review, plugin packaging, and controlled Core promotion.

### Workflow/operator continuity

- Retained role-neutral SAGE Project inventory with Job-scoped BIC/SAW authority.
- Retained governed Standard QA, Targeted Check, Original-Language Review, bounded work-unit planning, source-provenance handling, and chapter/report behavior.
- Retained cross-platform Codex/Ollama administration boundaries and host-capability detection.
- Retained the classic terminal menu and scriptable CLI as authoritative Beta interfaces; Textual remains experimental/unstable.
