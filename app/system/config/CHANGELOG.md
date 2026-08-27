# Changelog

## 0.01beta

`0.01beta` is the first group-testing baseline published from the current Git-managed architecture. Unpublished internal development labels are intentionally not part of the public changelog.

### Storage and configuration

- Split replaceable Git-controlled `app/` Core from persistent `localdata/` inside the portable SAGE bundle root.
- Defaulted `localdata` to a sibling of `app/`, with explicit CLI/environment/persisted custom-location resolution.
- Added fail-closed data-root validation and prohibited data homes inside Core.
- Added visible operator roots for Projects, Jobs, reports, exports, local resources, and plugins.
- Added hidden `.system` roots for configuration overlays, state, indexes, caches, locks, transactions, logs, diagnostics, temporary data, workflows, Job controller state, and managed runtime.
- Made Core `ecosystem.yml` immutable during normal operation; mutable interface/operator settings now use local overlays.
- Redirected Project imports and parsed Styleguide/source material into project-owned localdata paths.
- Added a direct **Remove Project from SAGE** action that clears only SAGE inventory/mapping state,
  preserves Paratext files, and blocks removal while an active or archived Job still binds the Project.
- Removed legacy in-Core `workspace_data`, top-level Job/report state, and bundled `.venv` from the distribution contract.

### Deterministic runtime/bootstrap

- Added automatic first-run creation of the sibling/local localdata structure.
- Added Python-free shell and PowerShell bootstraps that install exact CPython 3.12.14 artifacts for
  macOS ARM/Intel, Linux ARM/x86-64, and Windows x86-64 from governed URLs and SHA-256 pins.
- Moved the generated managed Python environment to `localdata/.system/runtime/venv`.
- Added exact pinned dependency manifests and deterministic bootstrap/repair with binary-only packages, `--no-deps`, `pip check`, and runtime fingerprints.
- Added a blocking runtime-installation report that records the reason and asks the Operator to
  retry the SAGE runtime, use an available approved package-manager recovery, or exit SAGE.
- Removed the system-Python and Homebrew prerequisites from normal launch and clone/install paths.
- Added approved CPython 3.12 host-runtime discovery: signed Python.org installations on macOS and
  Windows, plus an existing Homebrew Python on macOS.
- Added explicit recovery choices for Homebrew `python@3.12` and WinGet `Python.Python.3.12`;
  package managers are never installed or invoked without Operator approval.
- Removed manual/copied-environment and consent-driven venv setup paths.
- Preserved operator data across Beta/Core version updates; version changes no longer trigger destructive local-state resets.
- Kept the explicit out-of-box reset bounded to localdata and Core-immutable while preserving the managed runtime.

### Release and Git hardening

- Added deterministic source staging and ZIP metadata independent of build host.
- Added exact-source sharded hardening receipts, formal exactly-once combine, package validation, source deep audit, archive integrity validation, and SHA-256 sidecars.
- Added release validation that rejects local/runtime roots, caches, bytecode, nested archives, stale artifacts, symlinks, and machine-specific state.
- Added GitHub Actions qualification across Ubuntu, Windows, and macOS with supported Python versions and checkout-clean verification.
- Sanitized machine-specific paths and unpublished version-history labels from the group-testing distribution.

### Resource governance

- Established Core as the home only for tested/reviewed/approved product resources.
- Established `localdata/inputs/resources` and `localdata/plugins` for local/candidate resources and extensions.
- Added the future Resource Hub contribution model for provenance, validation, security/license checks, review, plugin packaging, and controlled Core promotion.

### Workflow/operator continuity

- Retained role-neutral SAGE Project inventory with Job-scoped BIC/SAW authority.
- Retained governed Reference Text Comparison (RTC), Targeted Check, Original-Language Review, bounded work-unit planning, source-provenance handling, and chapter/report behavior.
- Corrected approved SAW-plan reconciliation so an unchanged verse bridge is compared by its exact
  atomic coordinates instead of being falsely reported as stale because its display label is ranged.
- Retained cross-platform Codex/Ollama administration boundaries and host-capability detection.
- Retained the classic terminal menu and scriptable CLI as authoritative Beta interfaces; Textual remains experimental/unstable.
