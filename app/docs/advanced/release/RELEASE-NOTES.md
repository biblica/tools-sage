# Release Notes - SAGE v0.02alpha1


## 0.02alpha1

`0.02alpha1` is the first Alpha build of the 0.02 development line. It remains pre-release and is not public-production ready.

- Adds governed Source Text Correspondence (STC) as an independent WIP-to-PRIMARY-original-language SAW operation.
- Unifies BIC, RTC, and STC Scripture planning under routed-SFM-only deterministic sizing.
- Enforces complete LANGUAGE_PROFILE / OL_AUTHORITY_PROFILE context on bounded model-facing natural-language requests.
- Adds BASIC / STANDARD / ADVANCED setup-selected hardening ceilings of 2 / 4 / 6 workers; ADVANCED requires at least 16 GiB available RAM and 16 logical CPUs.
- Preserves PRIMARY plus inert future SECONDARY original-language authority registration without analytical effect unless explicitly routed.
- Keeps the classic menu/CLI authoritative; Textual remains `EXPERIMENTAL / UNSTABLE`.


0.01beta remains the mainline baseline. 0.02alpha1 is developed on the parallel Alpha branch; this Alpha release does not replace, rename, or promote the 0.01beta mainline.

## 0.01beta baseline

`0.01beta` is the first group-testing baseline published from the current Git-managed layout. Earlier internal development labels were never public and are intentionally omitted from this release history.

### Core and local-data boundary

- `SAGE/app/` is the replaceable, reproducible application boundary; `SAGE/localdata/` persists with the portable bundle.
- `localdata/` is the persistent local/operator boundary and defaults to a sibling of `SAGE/`.
- Operators may place `localdata` elsewhere through the governed data-home resolver.
- Core rejects a data home located inside the Git-controlled SAGE tree.
- Visible `localdata` roots contain operator-facing Projects, Jobs, reports, exports, local resources, and plugins.
- `localdata/.system/` contains SAGE-owned configuration overlays, state, indexes, caches, locks, transactions, logs, diagnostics, temporary data, workflows, Job-controller state, and the managed runtime.
- Project imports keep original and parsed material separated so imported source evidence remains inspectable and derived material remains regenerable.
- Core release validation rejects local/runtime roots such as `localdata`, `workspace_data`, top-level `jobs`, top-level `reports`, and `.venv`.

### Deterministic first-run runtime

- `./sage` and `sage.cmd` automatically resolve/bootstrap local state; a separate mandatory setup command is not required.
- No host Python or package manager is required. The launcher can reuse a validated CPython 3.12 from Python.org/Homebrew, or install exact CPython 3.12.14 artifacts pinned by URL and SHA-256 for macOS ARM/Intel, Linux ARM/x86-64, and Windows x86-64.
- The approved base runtime is installed at `localdata/.system/runtime/python`; the managed environment is created at `localdata/.system/runtime/venv`. Neither is copied into a release.
- Runtime, development, and optional TUI dependencies are explicitly pinned in governed manifests.
- Bootstrap uses deterministic list-argv execution, exact pins, `--no-deps`, binary-only packages, `pip check`, and a runtime fingerprint.
- Missing or stale managed environments are repaired/rebuilt automatically from Core manifests.
- A failed base-runtime or environment installation produces a BLOCKED installation report and offers **Install again**, approved Python through available Homebrew/WinGet, or **Exit SAGE**. Package-manager execution requires explicit Operator approval.
- Version changes do not delete Projects, Jobs, reports, settings, or other operator data.
- The explicit out-of-box reset clears bounded local operating data while preserving the managed runtime and never modifying Core.

### Git and release hardening

- Normal SAGE operation no longer writes mutable configuration or runtime state into `SAGE/`.
- `ecosystem.yml` is an immutable Core baseline; operator/workstation changes are stored as local overlays in `localdata/.system/config`.
- Release ZIPs are built only from clean governed source staging, not from a live runtime folder.
- The production builder requires schema validation, package validation, deep source audit, exact-source hardening receipts, archive integrity validation, deterministic metadata, and SHA-256 output.
- Hardening runs each scheduled test module in its own clean source copy, splits long modules into bounded groups of at most eight pytest nodes per process, never counts timeout output as a pass, and proves the governed source hash is unchanged.
- GitHub CI covers Ubuntu, Windows, and macOS across supported Python versions and verifies the checkout remains clean.

### Resource governance

- Only tested, reviewed, approved resources belong in SAGE Core.
- Operator-created, imported, modified, experimental, or unvalidated resources remain in `localdata/inputs/resources` or `localdata/plugins`.
- A future SAGE Resource Hub is reserved for submission, provenance, validation, review, plugin packaging, and controlled promotion of candidate resources into Core.

### SAW STC, routed-SFM sizing, and linguistic specificity

- Added **Source Text Correspondence (STC)** between RTC and Targeted Check in SAW. STC is an independent WIP-to-primary-original-language review: NT routes PRIMARY GRK, OT routes PRIMARY HEB, and REFERENCE/RTC evidence is excluded.
- STC canonical findings are `OMISSION`, `ADDITION`, `VARIATION`, and `CONSISTENCY`; exact primary coverage and zero-finding analytical completion are fail-closed finalization requirements.
- Consolidated BIC/RTC/STC planning under one deterministic general SFM slicer. Review-item sizing counts only the Scripture SFM streams actually routed to that review item.
- Added complete `LANGUAGE_PROFILE` routing for project/reporting streams and source-bound `OL_AUTHORITY_PROFILE` routing for GRK/HEB on every applicable bounded model request. Profiles are immutable context and contribute nothing to SFM sizing.
- GRK governance explicitly requires Ancient/New-Testament Greek and rejects Modern Greek assumptions; HEB governance requires Biblical/Ancient Hebrew and rejects Modern Israeli Hebrew assumptions.
- OL authority state can retain future SECONDARY authorities, but they have no analytical or sizing effect until explicitly routed by an operation contract.

### Cross-platform and operator behavior

- macOS/Linux launchers retain deterministic executable metadata and quoted path handling.
- Windows launchers use bounded `cmd.exe`/PowerShell subprocess contracts and support paths containing spaces.
- Storage/path tests cover custom data homes, Unicode paths, Windows path forms, path containment, and fail-closed invalid locations.
- Host capability detection selects a conservative BASIC/STANDARD/ADVANCED execution profile from available RAM and logical CPU threads. BASIC is selected below 4 GiB available RAM or 8 logical CPUs and caps release-hardening concurrency at 2 workers; STANDARD covers capable hosts below the ADVANCED threshold and caps at 4; ADVANCED requires both at least 16 GiB available RAM and 16 logical CPUs and caps at 6. Environment overrides may lower, but never exceed, the setup-selected ceiling.
- BIC and SAW retain Job-scoped authority, governed source/project bindings, bounded work units, and operator-visible reports outside Core.
- The classic terminal interface and scriptable CLI remain authoritative for Beta; the Textual TUI remains `EXPERIMENTAL / UNSTABLE`.

## Release qualification

Qualification evidence is recorded in `TEST-AND-VALIDATION-REPORT.md` and in the release-side hardening/checksum receipts generated beside the ZIP. Any governed source or test change invalidates prior receipts and requires qualification from a new frozen source hash.
