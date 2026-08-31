# Changelog

## 0.01beta2

`0.01beta2` is the current group-testing Beta. It incorporates the accepted work from the historical `alpha/0.02alpha1` non-release branch while retaining the 0.01 product line.

- Added Source Text Correspondence (STC) with WIP-to-PRIMARY OL correspondence and fail-closed exact coverage/finalization.
- Unified BIC/RTC/STC review sizing under routed-SFM-only deterministic slicing.
- Added universal governed linguistic-profile routing for bounded model-facing requests, including historical GRK/HEB authority profiles.
- Added setup-selected ADVANCED host capability at >=16 GiB available RAM and >=16 logical CPUs with a hardening ceiling of 6 workers; BASIC/STANDARD remain capped at 2/4.
- Updated SAW operator order to RTC -> STC -> Targeted Check -> Original-Language Review.
- Replaced normal global model/reasoning selection with provider-only Setup and exact per-Skill
  provider/model/native-reasoning routing.
- Added deterministic execution-owner policy, sealed 3-case × 3-repetition qualification suites for
  all seven Skills, audited global route override receipts, and fail-closed route reconciliation.
- Added exact execution-route provenance to task receipts, BIC/SAW aggregation, Job/Run displays, and
  final reports while keeping deterministic report composition outside LLM token accounting.
- Enforced one provider request per original-language adjudication item and per secondary-language
  report item.
- Restored approved RTC portions spanning chapters by validating scope containment directly against
  the immutable plan's exact atoms; structural-stage atoms now retain canonical numeric Scripture
  order. Unpublished multi-child stage creation rolls back its newly created task/control records if
  a later child fails.

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
- Added governed Source Text Correspondence (STC) as an independent WIP-to-PRIMARY-OL review (NT -> GRK, OT -> HEB), alongside retained RTC, Targeted Check, and Original-Language Review operations.
- Unified BIC/RTC/STC Scripture sizing under routed-SFM-only deterministic planning; controller JSON, prompts, schemas, linguistic profiles, and provider transport overhead no longer affect Scripture slicing or token limits.
- Added complete model-facing LANGUAGE_PROFILE / source-bound OL_AUTHORITY_PROFILE routing, including explicit Ancient/NT Greek and Biblical/Ancient Hebrew register protection.
- Corrected approved SAW-plan reconciliation so an unchanged verse bridge is compared by its exact
  atomic coordinates instead of being falsely reported as stale because its display label is ranged.
- Retained cross-platform Codex/Ollama administration boundaries and extended setup-selected host capability to BASIC (2 workers), STANDARD (4), and ADVANCED (6; requires at least 16 GiB available RAM and 16 logical CPUs).
- Retained the classic terminal menu and scriptable CLI as authoritative Beta interfaces; Textual remains experimental/unstable.
