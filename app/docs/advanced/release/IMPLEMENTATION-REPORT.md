# SAGE v0.02alpha1 - Implementation Report

**Development status:** Alpha; pre-release group-testing baseline. Qualification is bound to the exact source hash used by the release builder.

## Implemented

1. **Role-neutral SAGE Project Inventory.** Paratext discovery and **Add Project to SAGE** are system tasks; SOURCE / DONOR / TARGET / WIP / REFERENCE exist only as Job bindings.
2. **Canonical Operator grammar.** Current menus, prompts, errors, help, schemas, and documentation follow `Scan → Discover → Add to SAGE → Assign role → Job → Run → task`; Project-facing Register/Registered/Unregister language is no longer emitted.
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
15. **Clean application and persistent-data policy.** The source distribution ships with no operator Project/Job/Run state or managed runtime. `app/` is replaceable; `localdata/` is persistent local/operator state inside the portable bundle. Release gates reject runtime contents, caches, nested archives, symlinks, and preconfigured Project state. Application/version updates preserve recognized localdata.
16. **File naming and serialization convergence.** SAGE-owned registries, pins, manifests, and machine records use JSON; editable configuration/policy/profile material remains YAML. Canonical internal config filenames are lowercase kebab-case, Run manifests are `run.json`, and platform/vendor-governed filenames are preserved.
17. **Independent Source Text Correspondence (STC).** SAW exposes RTC -> STC -> Targeted Check -> Original-Language Review. STC compares bounded WIP directly with the testament-correct PRIMARY OL authority (NT -> GRK, OT -> HEB), never consumes REFERENCE evidence or RTC findings, and finalizes only after exact primary coverage and analytical-completion reconciliation.
18. **One routed-SFM sizing authority.** BIC, RTC, STC, Targeted Check, and OL Review use the general deterministic SFM slicer. Only Scripture SFM actually routed to a model review item contributes tokens/hard bytes; controller JSON, prompts, schemas, profiles, IDs, hashes, provenance, diagnostics, and transport overhead do not.
19. **Universal language specificity.** Every bounded model-facing natural-language stream carries its complete canonical profile. Project/reporting streams use `LANGUAGE_PROFILE`; GRK/HEB use source-bound `OL_AUTHORITY_PROFILE`. Missing or ambiguous specificity fails closed, including BIC microtransactions, retries, RTC/STC, Targeted Check, OL Review, and secondary report rendering.
20. **Extensible OL authority families.** GRK/HEB retain exactly one configured PRIMARY authority for current workflows and may register zero or more SECONDARY authorities. Secondary authorities remain analytically inert until an explicit future review item routes them.
21. **Provider-neutral exact Skill routing.** Normal Setup retains provider connection/enablement only. Every governed BIC/SAW attempt resolves an available route qualified for the exact registered `skill_id`; provider-native reasoning IDs are retained without a fictional universal scale.
22. **Deterministic execution ownership.** Planning, parsing, SFM slicing, coverage, token measurement, validation, aggregation, report composition/naming, and finalization are explicitly Python-owned and never enter LLM routing or LLM token accounting. Local AI remains non-authoritative `ASSISTIVE_ONLY` work.
23. **Sealed route qualification.** All seven Skills have three packaged synthetic cases—positive, zero-finding, and adversarial—repeated three times per candidate route. Production validators determine `QUALIFIED`, `FAILED`, or `UNRELIABLE`; models cannot qualify themselves. Model/capability/Skill/suite/policy drift becomes `UNASSESSED` or `STALE`.
24. **Audited advanced override.** One optional exact provider/model/capability/reasoning route may be pinned outside normal Setup. Set/change/clear actions create local receipts, and execution still fails closed when the route is not qualified for the current Skill.
25. **Truthful route provenance.** Schema 2.0 execution receipts bind exact route and qualification evidence. BIC/SAW submissions, aggregation, Job/Run status, and final report Execution sections preserve the actual attempt route rather than recomputing history.
26. **Per-item isolation.** Original-language adjudication and secondary-language report rendering execute one item per provider request with no conversation reuse. Secondary rendering inherits the originating route and degrades without changing canonical results.

## External-resource rule

SAGE reads Paratext Project metadata for discovery and validation but does not modify `settings.xml`, `canons.xml`, or `custom.vrs`. Governed Scripture access remains `.SFM`/`.VRS` only. Machine-local state stores the Paratext Projects root, the Paratext Project Catalog, the SAGE Project Inventory, Job/Run state, Base VRS override state, and governed OL source selection separately from static policy.

## Workflow rule

BIC and SAW remain independent. BIC binds exactly one SOURCE, DONOR, and TARGET. SAW Jobs bind exactly one WIP and one authorized REFERENCE for operations that require comparison evidence. STC is explicitly independent of REFERENCE and routes WIP only with the testament-correct PRIMARY OL authority. SAGE Projects are role-neutral; effective workflow purpose and access authority are assigned only by Jobs. Governed `@GRK`/`@HEB` resources are read-only evidence resources, not ordinary translation Projects.

## Compatibility rule

A narrow set of internal Python function names and machine keys retain legacy names where changing them would add unnecessary migration risk. They are compatibility implementation details only. Current operator-visible Project grammar uses the canonical v0.02alpha1 terms.
