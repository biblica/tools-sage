# SAGE v0.01beta - Implementation Report

**Development status:** Beta; pre-release group-testing baseline. Qualification is bound to the exact source hash used by the release builder.

## Implemented

1. **Role-neutral SAGE Project Inventory.** Paratext discovery and **Add Project to SAGE** are system tasks; SOURCE / DONOR / TARGET / WIP / REFERENCE exist only as Job bindings.
2. **Canonical operator grammar.** Current menus, prompts, errors, help, schemas, and documentation follow `Scan → Discover → Add to SAGE → Assign role → Job → Run → Task`; Project-facing Register/Registered/Unregister language is no longer emitted.
3. **Persistent Paratext Project Catalog.** Selecting the Projects root scans immediate child folders with valid `settings.xml`, caches metadata, supports FB/NT/Portions + Language filtering, and supplies a rotating scan status line with counts.
4. **Project metadata and ISO handling.** Catalog rows preparse `settings.xml`, `canons.xml`, top-level `.SFM`, `custom.vrs`, and Project short-code metadata. A bundled offline ISO-639 registry validates language identity and suggests candidates when metadata is missing/invalid; ambiguous candidates are not silently substituted.
5. **Language-profile deferral.** A Project with valid ISO metadata can be added to SAGE before a SAGE language grammar/profile exists. Language-specific grammar is required only when a Job operation needs it.
6. **Base VRS default behavior.** The Paratext Projects root is the default Base VRS root; an explicit Base VRS override remains sticky across later root changes until the operator clears it.
7. **BIC/SAW runtime isolation.** Job runtime validation requires only the active tool profile. An empty inactive BIC template no longer blocks SAW, and an empty inactive SAW template no longer blocks BIC.
8. **Job-scoped authority derivation.** Runtime Project role, lifecycle, grammar, and write capability are derived from Job bindings without mutating the underlying SAGE Project record. Only BIC TARGET can receive governed external Scripture writes; SAW remains read-only.
9. **Job lifecycle controls.** BIC/SAW support selecting, adding, archiving, validating, and removing Jobs. Removing a Job removes Job-owned state only and does not remove or modify SAGE/Paratext Projects.
10. **Safe Project removal.** **Remove Project from SAGE** deletes only the inventory record, never Paratext files, and is blocked while active or archived Jobs still bind that Project.
11. **Auto-persisted setup.** Configuration changes are saved as they are made; BIC/SAW access from Main no longer depends on a separate SAVE action.
12. **Guided Scripture scope and pre-Run review.** Operators can choose a Book/range or enter a complete scope directly, then review deterministic work/token sections before Run creation and choose Run / Change scope / Back.
13. **Project-focused maintenance.** The Project detail screen uses `# Details`, `# Project Settings`, `# Maintenance`, and `# Advanced`, with VRS, Scripture books, location, validation, Job usage, and removal separated clearly. Reporting languages are configured globally and per Job, not on the Project.
14. **Governed OL separation.** `@GRK` / `@HEB` remain governed resources outside the ordinary SAGE Project Inventory, with bundled/recognized-Paratext/local configuration and runtime provenance.
15. **Clean Core and persistent-data policy.** The source distribution ships with no operator Project/Job/Run state or managed runtime. `SAGE/` is replaceable Core; `SAGEdata/` is persistent local/operator state. Release gates reject local/runtime roots, caches, nested archives, symlinks, and preconfigured Project state. Core/version updates preserve recognized SAGEdata; no legacy-layout migration function is required for this first published Beta baseline.
16. **File naming and serialization convergence.** SAGE-owned registries, pins, manifests, and machine records use JSON; editable configuration/policy/profile material remains YAML. Canonical internal config filenames are lowercase kebab-case, Run manifests are `run.json`, and platform/vendor-governed filenames are preserved.

## External-resource rule

SAGE reads Paratext Project metadata for discovery and validation but does not modify `settings.xml`, `canons.xml`, or `custom.vrs`. Governed Scripture access remains `.SFM`/`.VRS` only. Machine-local state stores the Paratext Projects root, the Paratext Project Catalog, the SAGE Project Inventory, Job/Run state, Base VRS override state, and governed OL source selection separately from static policy.

## Workflow rule

BIC and SAW remain independent. BIC binds exactly one SOURCE, DONOR, and TARGET. SAW binds exactly one WIP and one authorized REFERENCE. SAGE Projects are role-neutral; effective workflow purpose and access authority are assigned only by Jobs. Governed `@GRK`/`@HEB` resources are read-only evidence resources, not ordinary translation Projects.

## Compatibility rule

A narrow set of internal Python function names and machine keys retain legacy names where changing them would add unnecessary migration risk. They are compatibility implementation details only. Current operator-visible Project grammar uses the canonical v0.01beta terms.
