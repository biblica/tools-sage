# SAGE v0.01-rc7.04 — Implementation Report

## Implemented

1. **Role-neutral SAGE Project Inventory.** Paratext discovery and **Add Project to SAGE** are system tasks; SOURCE / DONOR / TARGET / WIP / REFERENCE exist only as Job bindings.
2. **Canonical operator grammar.** Current menus, prompts, errors, help, schemas, and documentation follow `Scan → Discover → Add to SAGE → Assign role → Job → Run → Task`; Project-facing Register/Registered/Unregister language is no longer emitted.
3. **Persistent Paratext Project Catalogue.** Selecting the Projects root scans immediate child folders with valid `settings.xml`, caches metadata, supports FB/NT/Portions + Language filtering, and supplies a rotating scan status line with counts.
4. **Project metadata and ISO handling.** Catalogue rows preparse `settings.xml`, `canons.xml`, top-level `.SFM`, `custom.vrs`, and Project short-code metadata. A bundled offline ISO-639 registry validates language identity and suggests candidates when metadata is missing/invalid; ambiguous candidates are not silently substituted.
5. **Language-profile deferral.** A Project with valid ISO metadata can be added to SAGE before a SAGE language grammar/profile exists. Language-specific grammar is required only when a Job operation needs it.
6. **Base VRS default behaviour.** The Paratext Projects root is the default Base VRS root; an explicit Base VRS override remains sticky across later root changes until the operator clears it.
7. **BIC/SAW runtime isolation.** Job runtime validation requires only the active tool profile. An empty inactive BIC template no longer blocks SAW, and an empty inactive SAW template no longer blocks BIC.
8. **Job-scoped authority derivation.** Runtime Project role, lifecycle, grammar, and write capability are derived from Job bindings without mutating the underlying SAGE Project record. Only BIC TARGET can receive governed external Scripture writes; SAW remains read-only.
9. **Job lifecycle controls.** BIC/SAW support selecting, adding, archiving, validating, and removing Jobs. Removing a Job removes Job-owned state only and does not remove or modify SAGE/Paratext Projects.
10. **Safe Project removal.** **Remove Project from SAGE** deletes only the inventory record, never Paratext files, and is blocked while active or archived Jobs still bind that Project.
11. **Auto-persisted setup.** Configuration changes are saved as they are made; BIC/SAW access from Main no longer depends on a separate SAVE action.
12. **Guided Scripture scope and pre-Run review.** Operators can choose a Book/range or enter a complete scope directly, then review deterministic work/token sections before Run creation and choose Run / Change scope / Cancel.
13. **Project-focused maintenance.** The Project detail screen uses `# Details`, `# Project Settings`, `# Maintenance`, and `# Advanced`, with reporting, VRS, Scripture books, location, validation, Job usage, and removal separated clearly.
14. **Governed OL separation.** `@GRK` / `@HEB` remain governed resources outside the ordinary SAGE Project Inventory, with bundled/recognised-Paratext/local configuration and runtime provenance.
15. **Clean RC and package policy.** The source distribution ships with no operator Project/Job/Run state, no local `.venv`, and release gates against stale RC artefacts, caches, nested archives, symlinks, and preconfigured Project state.

## External-resource rule

SAGE reads Paratext Project metadata for discovery and validation but does not modify `settings.xml`, `canons.xml`, or `custom.vrs`. Governed Scripture access remains `.SFM`/`.VRS` only. Machine-local state stores the Paratext Projects root, the Paratext Project Catalogue, the SAGE Project Inventory, Job/Run state, Base VRS override state, and governed OL source selection separately from static policy.

## Workflow rule

BIC and SAW remain independent. BIC binds exactly one SOURCE, DONOR, and TARGET. SAW binds exactly one WIP and one authorised REFERENCE. SAGE Projects are role-neutral; effective workflow purpose and access authority are assigned only by Jobs. Governed `@GRK`/`@HEB` resources are read-only evidence resources, not ordinary translation Projects.

## Compatibility rule

A narrow set of internal Python function names and machine keys retain legacy names where changing them would add unnecessary RC risk. They are compatibility implementation details only. Current operator-visible Project grammar uses the canonical RC7.04 terms.
