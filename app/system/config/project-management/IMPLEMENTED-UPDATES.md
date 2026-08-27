# Implemented Updates

This is an append-only implementation ledger. New entries go first. Historical version detail from
before this ledger remains in `system/config/CHANGELOG.md` and `docs/advanced/release/RELEASE-NOTES.md`.

## 2026-08-27

### IMP-20260827-002 — RTC bridge-safe slicing and atomic finalization

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-REQUALIFY`
- **Implemented:** Made canonical verse atoms authoritative for work-unit ownership and aggregation
  while retaining WIP/REFERENCE bridge labels as source metadata. RTC planner V2 now closes every
  proposed internal boundary across WIP bridges, REFERENCE bridges, and active local VRS
  equivalence spans before complete-package measurement. New stage plans persist per-unit atoms;
  legacy partition plans expand raw ranged keys deterministically during retry. Exact aggregate
  reconciliation remains fail-closed and now reports missing, extra, duplicate, ownership, and
  result-drift details. Routine Run preflight silently retains non-blocking VRS advisories instead
  of rendering them in the interactive UI.
- **Verification:** Regressions cover REFERENCE bridge boundary extension, atomic source-span
  metadata, legacy raw-bridge finalization, duplicate primary ownership, and silent-but-persisted
  VRS advisories. The complete test suite passes with two platform-dependent skips.

### IMP-20260827-001 — Job-owned canonical report-language enforcement

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-REQUALIFY`
- **Implemented:** Made primary report language required and Job-owned, retained secondary report
  language as optional downstream localization, and limited the global Operator language to the
  default snapshotted for new Jobs. Narrative-generating ACTs and provider schemas now bind the
  concrete Job language explicitly, canonical SAW findings record that authority, and a
  conservative post-response check performs at most one correction retry for a clear mismatch.
  Interface and secondary-language values are not sent as canonical narrative authority.
- **Verification:** Regression coverage proves existing Jobs keep their primary language, legacy
  Jobs receive one deterministic compatibility upgrade, missing ACT language blocks handoff, and
  clear Spanish narrative is rejected and retried before English canonical findings are written.

## 2026-08-26

### IMP-20260826-022 — Approved SAW verse-bridge plan reconciliation fixed

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-REQUALIFY`
- **Implemented:** Reconciled both the approved work-unit inventory and the current WIP inventory as
  atomic Scripture coordinates. An unchanged indivisible verse bridge such as `JHN 1:1-2` no longer
  produces a false `SAW_APPROVED_PLAN_STALE` result when runtime validation expands it to verses 1
  and 2. Genuine missing, extra, duplicated, or reordered coordinates still fail closed. The later
  RTC task separately seals `VERSE_BRIDGE_MAPPING` as a structure/completeness check and
  `VERSE_BRIDGE_CONTENT` as a translation/meaning check.
- **Verification:** The existing exact approved-partition regression passes, and end-to-end cases
  create the composite SAW RTC stage for a bridged WIP only, a bridged REFERENCE only, and both
  resources bridged, without rebuilding the valid approved plan.

### IMP-20260826-021 — Direct safe Project-removal action

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Promoted **Remove Project from SAGE** to the primary Scripture Projects menu while
  retaining the Project-detail action. The direct selector removes only SAGE inventory and mapping
  state, preserves the Paratext/PTLite folder and Scripture files, and blocks removal while an active
  or archived Job still binds the Project.
- **Verification:** Menu regressions prove the action is directly visible, unbound removal preserves
  the Scripture file while clearing SAGE state, and a Job-bound Project and mapping remain intact.

### IMP-20260826-020 — Self-contained governed Python bootstrap

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-REQUALIFY`
- **Implemented:** Added Python-free POSIX and Windows first-stage launchers. They detect the
  supported OS/CPU target, install exact CPython 3.12.14 from governed immutable URLs and SHA-256
  pins into `localdata/.system/runtime/python/`, build or repair the pinned environment under
  `localdata/.system/runtime/venv/`, and launch SAGE without system Python, Homebrew, or a copied
  virtual environment. A bootstrap failure now renders a **SAGE Runtime Installation Report** with
  the blocking reason and asks the Operator to **Install the SAGE Python runtime again** or **Exit
  SAGE**. Non-interactive launches emit the same report and exit with status 2.
- **Verification:** The macOS ARM64 artifact was downloaded, hash-verified, installed, and used to
  run SAGE under CPython 3.12.14. Launcher regression tests make `python`, `python3`, and `py` fail
  while proving SAGE uses its managed runtime; a real non-interactive boundary test pins the BLOCKED
  report and both actions. Cross-platform manifest, CMD/PowerShell, package, schema, and source-audit
  contracts pass. Native Windows, macOS Intel, and Linux artifact acceptance remains a release gate.

### IMP-20260826-019 — Workflow-owned Job-configuration rebuild fixed

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Moved **Rebuild Job configuration** from system recovery into the workflow-owned
  BIC and SAW Job-storage menus. Each action now rebuilds only that workflow's Jobs and reports the
  `job_id`; the former action had crashed while reading a nonexistent `project_id` from a Job.
- **Verification:** Regressions rebuild fixture BIC and SAW Jobs from their respective storage menus,
  verify runtime files and displayed Job IDs, and reject the action from system recovery.

### IMP-20260826-018 — Boxed classic-menu hierarchy and aligned footer

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Added shared Unicode presentation for classic menus: `╔═╗ / ║ / ╚═╝` for major
  headings, a `> `-prefixed label plus an unindented full-width `─` underline for minor headings, and
  `┌─┐ / │ / └─┘` for A-F footers, with one blank line before and after each block. Footer rows
  begin with two spaces before `A.`/`D.` to match numeric-choice indentation.
  Reference Text Comparison (RTC) and Configure AI now use the same renderer instead of private separator layouts.
  System Information is nested below its recovery-menu heading, with a single-line **System
  Actions** divider before the numbered operations. SAGE data folders are displayed as information
  inside that block instead of consuming a numbered action. The redundant **LLM status** subheading
  is omitted because the status rows already sit directly beneath **Configure AI**. Provider,
  model, and reasoning values appear only in those status rows; the numbered list contains concise
  change actions and rerenders the status after each change. When no model is explicitly pinned,
  changing reasoning uses and persists the concrete model resolved by the entry connection check.
  Cycle and explicit connection-check actions do not print intermediate values because the refreshed
  status block is the single state display. The nested configuration surfaces are explicitly named
  **Configure Hosted AI** and **Configure Local AI**; global `F. Status` reports both states.
  Configure Local AI limits its own summary to the enabled switch and configured model/install
  state; host/runtime metadata remains available through Status and diagnostic actions. The menu
  places enablement first, cycles Ollama start/stop in one position, delegates model installation
  to an extensible model-management submenu, refreshes after actions, and presents model source and
  integrity as information instead of an action. Secondary-language Jobs no longer block Local AI
  globally; only their Hosted-AI-dependent secondary rendering is rejected at the Job/report boundary.
- **Verification:** Menu presentation tests pin major/minor line styles, 72-column boundaries,
  blank-line separation, two-space footer keys, localization, and ANSI-free scrollback output.

### IMP-20260826-017 — Guided maintenance and governed out-of-box reset

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Removed the duplicate interface-language action from SAGE Maintenance because
  footer `D. Language` is globally available; moved Job-storage maintenance to BIC and SAW; merged
  system information with the system recovery/diagnostics panel; and added **Reset SAGE to
  out-of-box state**. The reset requires a negative-default confirmation plus exact `RESET SAGE`
  text, removes all local operating data and configuration, preserves `localdata/.system/runtime/` and packaged
  Core resources, writes a reset receipt, and exits for first-use Setup on relaunch.
- **Verification:** Isolated reset tests verify Project/Job/Run/report/profile removal, vanilla
  configuration reconstruction, packaged-profile restoration, managed-runtime preservation, receipt
  creation, and the revised menu ownership/localization contract.

### IMP-20260826-016 — Main navigation grouped by functional ownership

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Reduced Main to **Manage SAGE Scripture Projects**, **BIC**, **SAW**, and
  **SAGE Maintenance**. Reports and Job recovery now live under their respective BIC/SAW menus;
  system recovery, diagnostics, settings, paths, AI, and storage maintenance live under SAGE
  Maintenance. An uninitialized active Job no longer replaces Main with Manage Jobs; validation is
  deferred to workflow entry. Rebuilt affected labels across all six interface locales and aligned
  the experimental TUI navigation.
- **Verification:** Menu contracts reject top-level Reports/Recovery, require workflow-owned report
  and recovery routes, and pin the four-entry classic/TUI navigation grammar.

### IMP-20260826-015 — Continuous, non-blocking classic-menu flow

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Removed ANSI full-screen clearing between classic-menu forms and made routine
  completion pauses non-blocking. The terminal retains one continuous scrollback, with strong
  `=` title boundaries identifying each new form and no `Press Enter to continue...` prompts.
- **Verification:** TTY and captured-output contracts reject ANSI clear sequences, and a dedicated
  pause contract proves no prompt is printed and no input is consumed.

### IMP-20260826-014 — Audience-language recommendation for secondary reports

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Added a guided secondary-reporting-language chooser. It recommends the SAW WIP
  language or BIC TARGET language when distinct from the primary Operator language, and exposes
  explicit other-language and no-secondary choices. Rebuilt the changed menu text for all six
  interface locales.
- **Verification:** Menu persistence and localization contracts cover the recommendation, manual
  alternative, primary/secondary conflict boundary, and complete localized menu catalog.

### IMP-20260826-013 — All Job resource-assignment roles highlighted

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Extended angle-bracket role emphasis to all centralized Job Project assignment
  headings: BIC `<SOURCE>`, `<DONOR>`, `<TARGET>` and SAW `<WIP>`, `<REFERENCE>`. Rebuilt all five
  localization entries across the six interface locales.
- **Verification:** An AST contract inventories every `choose_or_add_resource()` call and requires
  the complete highlighted-role heading set, including future changes to this assignment path.

### IMP-20260826-012 — SAW chooser roles visually highlighted

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Changed the SAW Project chooser headings to `CHOOSE SAW <WIP>` and
  `CHOOSE SAW <REFERENCE>`, using angle brackets as deliberate visual role emphasis, and rebuilt
  the associated entry across all six interface locales.
- **Verification:** Localization contracts require the exact highlighted headings and the UI
  presentation contract defines their role-specific angle-bracket meaning.

### IMP-20260826-011 — Project loading no longer emits competency tables

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Removed the automatic model-competency registry lookup from successful Project
  registration. Adding or opening a Project now completes without provider probing or displaying a
  global language table; competency remains an explicit language action.
- **Verification:** A regression makes `ModelService` construction fail during Project registration
  and confirms the Project still registers without competency output.

### IMP-20260826-010 — Main-menu Project label simplified

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Replaced the redundant `Scripture Projects >> Manage SAGE Scripture Projects`
  Main-menu entry with `Manage SAGE Scripture Projects` and rebuilt the corresponding localization
  entry for all six supported interface locales.
- **Verification:** Menu, documentation, and localization contracts reject the former duplicated
  parent-context prefix.

### IMP-20260826-009 — Localization rebuild added to release tasks

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-REQUALIFY`
- **Implemented:** Added a mandatory pre-freeze task to rebuild every changed canonical menu phrase
  in the governed localization source, complete all six supported locale values, and reject missing,
  duplicate, blank, or stale changed-menu entries.
- **Verification:** Release Cleanup, Release Gates, Versioning Policy, and Menu Localization guidance
  require the rebuild and the complete `test_menu_localization.py` contract suite.

### IMP-20260826-008 — TUI marked experimental and unstable

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-TUI`
- **Implemented:** Added governed feature-maturity state `EXPERIMENTAL_UNSTABLE`, with exact display
  label `EXPERIMENTAL / UNSTABLE`, to the machine release definition and versioning policy. Bound
  the Textual TUI to it across the CLI, visible TUI header, Operator documentation, development
  status, package description, and roadmap. The classic menu and scriptable CLI remain authoritative.
- **Verification:** Documentation and CLI contract tests pin the warning so incomplete TUI parity
  cannot be presented as supported or authoritative during the Beta.

### IMP-20260826-007 — Project versioning policy

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-PM`
- **Implemented:** Added internal governance for canonical version spelling, Beta-to-RC promotion,
  release-state mapping, qualification gates, synchronized version surfaces, tags, artifact names,
  state reset, contract-version independence, and historical records.
- **Verification:** The PM inventory, vanilla manifest, project tree, and documentation contract all
  include the policy and pin the `0.01beta` → `0.01rc1` progression.

### IMP-20260826-006 — Version baseline reset

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-PM`
- **Implemented:** Reset current runtime, package, schema, documentation, test, release, and PM
  identity to `v0.01beta`, with `BETA` as the machine release state. Unpublished pre-Beta development labels are intentionally omitted from the group-testing distribution.
- **Verification:** Canonical version surfaces agree; compact `0.01beta` activates the governed
  pre-release boundary; existing operator localdata is preserved across Core/version updates; current documentation claims only Beta group-testing qualification and keeps production promotion gated separately.

### IMP-20260826-005 — Documentation grouped by audience and topic

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-PM`
- **Implemented:** Kept eight short daily-use Operator documents at the `docs/` root and moved
  technical material under `docs/advanced/`, grouped into architecture, projects/resources,
  workflows, models/AI, maintenance, release, and future-work topics.
- **Verification:** Documentation links, source path contracts, package inventory, deep-audit paths,
  and regression tests use the grouped layout. A contract test pins the compact root inventory and
  advanced topic set.

### IMP-20260826-004 — Internal development-record ownership

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-PM`
- **Implemented:** Moved Development Status, Next Development Work, and the project-management
  ledgers out of the Operator-facing `docs/` catalog and beside the changelog under
  `system/config/`.
- **Verification:** The Operator documentation index no longer exposes the internal records; the
  project tree, vanilla manifest, and PM documentation contract point to their new authority paths.

### IMP-20260826-003 — Standard release-cleanup checklist

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-PM`
- **Implemented:** Added a repeatable release-cleanup and evidence checklist covering scope freeze,
  active-data preservation, clean staging, forbidden artifacts, exact-source gates, deterministic
  packaging, native acceptance, handover, and milestone closeout.
- **Verification:** The checklist is linked from the internal PM index and recorded in the
  vanilla-install inventory and PM documentation contract.

### IMP-20260826-002 — Project-management ledger

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-PM`
- **Implemented:** Added governed Build Issues, TODO, Implemented Updates, and Milestones ledgers
  under `system/config/project-management/`, with stable identifiers and explicit links to version,
  changelog, release, status, and roadmap authorities.
- **Verification:** Documentation links and the vanilla-install inventory include the new governed
  files.

### IMP-20260826-001 — Consistent menu action grammar

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Standardized operator-facing menu instructions on **Choose**, including BIC/SAW
  resource setup, Scripture scope, Runs, Language Profiles, AI settings, countries, localization,
  and operator documentation. State-reporting and internal API concepts remain technically named.
- **Verification:** 62 focused menu/localization/operator-UX tests pass. A regression test prevents
  standalone **Select** instructions from returning to menu literals.

## Entry format

Each future entry must include an ID, date, version, milestone, implemented outcome, and verification
evidence. Release-significant entries must also be summarized in the product changelog and release
notes.
