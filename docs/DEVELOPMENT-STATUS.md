# Development Status — SAGE RC7.04

## Current operator surface

- One normal launcher: `sage.cmd` on Windows or `./sage` on macOS/Linux.
- Main is task-oriented: **Scripture Projects**, **BIC**, **SAW**, **Reports**, **System / Configuration**, **Help / Operator Guide**, and **Recovery / Diagnostics**.
- Configuration persists when changed; there is no manual SAVE prerequisite before BIC/SAW appear or can be opened.
- Scripture Project administration and workflow role assignment are separate concerns.
- **Scripture Projects** manages the Paratext Project Catalogue and SAGE Project Inventory. It scans, adds, validates, configures, and safely removes Projects.
- **BIC/SAW Job setup** assigns only already-added SAGE Projects to SOURCE / DONOR / TARGET / WIP / REFERENCE roles. A selector can temporarily route to **Add another Project to SAGE**, then returns to the selector.
- BIC and SAW have independent persistent Jobs and bounded Runs. Jobs can be added, selected, archived, validated, and removed.
- Scripture scope supports guided Book/range entry and direct expert scope entry. A deterministic work/token preview is shown before Run creation.
- Long Paratext scans expose a rotating status line and progress count.
- Run planning, governed task preparation/execution/submission, continuation, and aggregation expose rotating status lines; composite SAW stages also show current/total work-unit progress.

## Project and language state

- The persistent ordinary Project collection is `state/project-inventory.json` and is described to operators as the **SAGE Project Inventory**.
- SAGE Projects are role-neutral. Adding one never grants BIC TARGET write authority or assigns a workflow role.
- Project addition accepts valid ISO language identity without requiring a SAGE language grammar/profile first.
- A bundled offline ISO-639 lookup validates codes and provides non-destructive suggestions from metadata/prefix evidence when the declared code is missing or invalid.
- Project prefix evidence is corroborative only; ambiguity remains an operator decision.
- When ISO metadata such as `pes` and a Project prefix such as `fa` consistently identify Persian, Job setup can offer an Operator-approved `ecosystem.yml` profile alias to the existing role-compatible profile.
- Language grammar/profile requirements are enforced when a Job operation actually needs language-specific analysis.

## Paratext and VRS state

- One primary Paratext/PTLite Projects root is configured; Projects outside it use **Add Project from another location**.
- Selecting the root builds the persistent Paratext Project Catalogue from direct child folders with valid `settings.xml`.
- Catalogue metadata includes `settings.xml`, `canons.xml`, top-level `.SFM`, descriptive `custom.vrs` comments, scope, language, and Project-code metadata.
- The Paratext Projects root is also the default Base VRS root. An explicit Base VRS override remains in force until cleared.
- External metadata files are read for discovery/validation only. Governed external Scripture file access remains `.SFM`/`.VRS`.

## Workflow and authority state

- BIC: exactly one SOURCE, DONOR, TARGET; TARGET is the only possible ordinary external Scripture writer and only through governed write boundaries.
- SAW: exactly one WIP and authorised REFERENCE; external Scripture remains read-only.
- Active Job runtime validation is isolated by tool. Inactive empty workflow templates do not invalidate the active BIC/SAW Job.
- Removing a Job deletes only Job-owned state. Removing a Project from SAGE deletes only SAGE inventory state and is blocked while any Job still uses it.
- Governed `@GRK` / `@HEB` aliases are separate from the ordinary SAGE Project Inventory and support explicit bundled, recognised Paratext, or local source selection.
- Per-Project bilingual reporting overrides remain available; the terminal UI remains English for RC7.04. BIC uses TARGET reporting and SAW uses WIP reporting.

## Runtime/provider state

- Startup checks Python 3.10+, standard-library `venv`, the managed `.venv`, declared requirements, and `pip check` before importing SAGE application code.
- `.venv/` is created/repaired locally beside the launcher and is intentionally absent from the source ZIP; startup prints the exact SAGE root and managed `.venv` path.
- CODEX is the only enabled automated provider; SAGE reuses persistent ChatGPT-managed Codex CLI authentication.
- No OpenAI API-key/direct-API/fallback path exists.

## RC-stage data policy

Release-candidate builds are forward-only. A new RC version uses a clean RC-state boundary: stale operator Project/Job/Run state from an overlaid earlier RC is reset once when the version changes; the managed `.venv` is retained. Re-launching the same RC preserves state created by that RC.

## Source hygiene

Current operating material must not contain previous-RC implementation labels, obsolete Project registration grammar, shipped operator Project/Job/Run state, runtime caches, or fixture workflow bindings. Historical labels may remain in the changelog, byte-pinned protected-contract metadata, compatibility tests, and beta-stage migration references.
