# Development Status — SAGE v0.01beta2

**Status: BETA — PRE-RELEASE; FRESH EXACT-SOURCE QUALIFICATION IS REQUIRED BEFORE THE FIRST RC. PUBLIC-PRODUCTION READINESS IS NOT CLAIMED.** This Beta carries Windows UTF-8 execution hardening, UTF-8 CLI/controller output handling, canonical numbered-book report naming, governed interruption/retry behavior, regional Language Profiles, Source Text Correspondence (STC), routed-SFM-only Scripture sizing, universal model-facing linguistic-profile specificity, and current Operator UI/reporting convergence. The classic menu and scriptable CLI remain authoritative. Further TUI workflow functionality is paused for `0.01beta2` and deferred to `0.02beta`.

See `docs/advanced/workflows/EXECUTION-BLOCK-AND-RETRY.md`, `docs/advanced/workflows/JOB-STORAGE-MAINTENANCE.md`, and `docs/advanced/maintenance/WINDOWS-CODEX-EXECUTION-AUDIT.md`.

---

## Current operator surface

- `sage tui` opens the optional **EXPERIMENTAL / UNSTABLE** full-screen Textual shell with keyboard/mouse navigation. It is not an authoritative Operator surface; no-argument launch opens the classic menu.
- The TUI targets `100 x 30` and provides numeric `1`-`5` top-level navigation, persistent view history, Help/Status overlays, interface-language switching, live session/AI status, startup-readiness gating, and native Projects-root / Quick Scan / AI-retest remediation. Persistent System Status / Active AI / Project / Active Job blocks show one sequential Job at a time; the Active Job line uses the governed 10-cell progress bar. Job/Run/report mutation remains read-only in the TUI.
- The retained TUI baseline is frozen for the rest of `0.01beta2`. Workflow-changing operations other than the existing bounded startup-remediation actions remain in `sage menu` / CLI; their TUI migration resumes in `0.02beta`.
- One normal root launcher per host: `.\sage.cmd` on Windows or `./sage` on macOS/Linux; both forward to the implementation under `system/bin/`.
- Main is ownership-oriented: **Scripture Projects**, **BIC**, **RTC**, **STC**, and **SAGE Maintenance**. Reports and Job recovery are under their BIC/RTC/STC workflow; system recovery is under SAGE Maintenance. Contextual Help and Status are global footer services rather than numbered Main-menu operations.
- Configuration persists when changed; there is no manual SAVE prerequisite before BIC/RTC/STC appear or can be opened.
- Scripture Project administration and workflow role assignment are separate concerns.
- **Scripture Projects** manages the Paratext Project Catalog and SAGE Project Inventory. It scans, adds, validates, configures, and safely removes Projects.
- **BIC/RTC/STC Job setup** assigns only already-added SAGE Projects to workflow-valid roles. BIC uses SOURCE / DONOR / TARGET, RTC uses WIP / REFERENCE, and STC uses WIP only. A selector can temporarily route to **Add another Project to SAGE**, then returns to the selector.
- BIC, RTC, and STC have independent persistent Jobs and bounded Runs. Jobs can be added, selected, archived, validated, and removed. RTC/STC WIP and REFERENCE bindings are immutable for the Job lifetime; a different Project requires a new Job.
- Scripture scope supports guided Book/range entry and direct expert scope entry. RTC/STC accept ordered, non-overlapping semicolon-separated portions from one book (for example `1CH 5-6; 24`) and plan each portion independently in one Run. A deterministic work/token preview is shown before Run creation.
- Initial/Quick Paratext scans are tree-only marker discovery and do not open Project files; Full rescans perform detailed whole-root validation. Long full scans expose a rotating status line and progress count.
- The two-row global footer is `A Back / B Main Menu / C Exit`, then `D Language / E Help / F Status`; Help/Status return to the invoking menu.
- Status-surface parity is hardened: Textual F-Status, classic-menu F-Status, and top-level local `sage status` consume the same canonical sequential Run quantifier; interactive Status shows the 10-cell bar plus activity/run/task detail, and CLI JSON exposes the same `job_progress` object.
- Run planning, governed task preparation/execution/submission, continuation, and aggregation expose one viewport-bounded status row that redraws in place and erases before permanent output; composite RTC stages also show current/total work-unit progress. Redirected output retains one static message per operation.

## Project and language state

- The v0.01beta2 vanilla tree ships a regional library of `PROJECT_REVIEW_REQUIRED` WIP grammar starters keyed by canonical BCP 47 region tags. New Project imports resolve and confirm a regional profile identity; Paratext shorthand is retained only as provenance.
- The Setup-owned terminal interface ships complete editable menu-localization entries for `en-US`, `en-GB`, `id`, `fr`, `ru`, and `pt-BR` in `system/config/localization/menu-localization.json`. Interface locale is independent from Job reporting and Scripture-language identity.
- The persistent ordinary Project collection is `localdata/.system/state/project-inventory.json` and is described to operators as the **SAGE Project Inventory**.
- SAGE Projects are role-neutral. Adding one never grants BIC TARGET write authority or assigns a workflow role.
- Project addition resolves and confirms a regional Language Profile identity before registration; role-specific Grammar Profiles remain deferred until a Job requires them.
- A bundled offline ISO-639 lookup validates codes and provides non-destructive suggestions from metadata/prefix evidence when the declared code is missing or invalid.
- Project prefix evidence is corroborative only; ambiguity remains an Operator decision.
- Language evidence from `Settings.xml`, all project LDML identities, and the lowercase project-name prefix is ranked as corroborative evidence. The Operator confirms or changes ISO identity and primary audience country before the regional BCP-47 Language Profile is established.
- Role-specific Grammar Profile requirements are enforced when a Job operation needs language-specific analysis; the Language Profile namespace already exists at Project registration.

## Paratext and VRS state

- One primary Paratext/PTLite Projects root is configured; Projects outside it use **Add Project from another location**.
- Selecting the root performs tree-only discovery of direct child folders carrying the `settings.xml` marker. New candidates are PENDING until selected/used or validated.
- Full/lazy validation supplies `settings.xml`, `canons.xml`, top-level `.SFM`, descriptive `custom.vrs` comments, scope, language, and Project-code metadata.
- The Paratext Projects root is also the default Base VRS root. An explicit Base VRS override remains in force until cleared.
- External metadata files are read for discovery/validation only. Governed external Scripture file access remains `.SFM`/`.VRS`.

## Workflow and authority state

- Canonical invariant: **Local Evidence, General Linguistic Competence**. Job content evidence must be SAGE-local, governed, authorized, and routed; model pretraining/recall is never evidence.
- Every task read is classified as content, lexical, project-index, derived, structural, subject text, linguistic-competence rules, or process control. Missing/unrecognized classification fails closed.
- The model's only permitted external competence is orthography, morphology, grammar, and syntax; it may not introduce unsupported propositions, lexical meanings, Scripture content, translation equivalents, interpretations, or cultural/historical claims.
- BIC: exactly one SOURCE, DONOR, TARGET; TARGET is the only possible ordinary external Scripture writer and only through governed write boundaries.
- RTC: exactly one WIP and authorized REFERENCE; external Scripture remains read-only. STC: exactly one WIP plus canon-routed PRIMARY OL authority and no REFERENCE Project.
- Active Job runtime validation is isolated by tool. Inactive empty workflow templates do not invalidate the active BIC, RTC, or STC Job.
- RTC/STC **Delete Job** removes all Job-owned work/controller state and optionally its separately published reports after an independent default-preserve prompt; it never modifies SAGE Projects or Paratext files. Removing a Project from SAGE uses negative-default
  confirmation; if Jobs bind it, SAGE lists them and requires explicit cascade confirmation before
  removing those Jobs, their Job-local data, and the Project inventory/mapping. Paratext files and
  root-level published reports remain unchanged.
- Governed `@GRK` / `@HEB` aliases are separate from the ordinary SAGE Project Inventory and support explicit bundled, recognized Paratext, or local source selection.
- Reporting uses a required Job-owned primary language and an optional Job-owned secondary language. The global Operator language is snapshotted only as the default when a Job is created; Projects never own reporting settings. Every narrative-generating ACT binds the primary language explicitly. When secondary report rendering is requested, that separate bounded translation request carries complete governed primary and secondary LANGUAGE_PROFILE objects; interface-language state remains outside analytical requests.

## Runtime/provider state

- Startup requires no system Python. Shell/PowerShell selects exact CPython 3.12.14 from the governed OS/CPU manifest, downloads it when absent, verifies its SHA-256, then checks standard-library `venv`, the managed `localdata/.system/runtime/venv`, base requirements, and `pip check` before importing SAGE application code. An explicit `tui` launch additionally validates the supplemental `requirements-tui.txt` profile; failure of that profile does not invalidate the classic interface.
- Startup also records machine-local host capability in `localdata/.system/state/host-capability.json`: available RAM `< 4 GiB` or logical CPU threads `< 8` selects `BASIC`; detection failure also selects `BASIC`; hosts meeting at least 4 GiB and 8 logical CPUs select `STANDARD`; hosts meeting both `>= 16 GiB` available RAM and `>= 16` logical CPUs select `ADVANCED`. BASIC caps release hardening at 2 workers, STANDARD at 4, and ADVANCED at 6. `SAGE_HARDENING_WORKERS` may reduce concurrency but cannot raise it above the setup-selected host-profile ceiling. The receipt is runtime state and never ships in the vanilla distribution.
- `localdata/.system/runtime/python/` and `venv/` are created/repaired deterministically outside Core and are intentionally absent from the source ZIP; startup prints the exact SAGE root, localdata root, and managed runtime path.
- CODEX is the only enabled automated provider; SAGE reuses persistent ChatGPT-managed Codex CLI authentication.
- The post-baseline development extension retains Ollama administration behind the existing `admin_assistant_enabled` compatibility switch. Administrative explanations and executive summaries are now deterministic Python renderings; Ollama cannot execute governed BIC/RTC/STC tasks or trigger primary-provider fallback.
- Local AI enablement is independent of Job configuration. Existing and new secondary-language Jobs do not block basic Local AI or primary-language work; only a Job's Hosted-AI-dependent secondary rendering is rejected while Local AI is enabled, leaving the governing primary report available.
- Capability-specific administrative transforms accept typed facts only and render in Python. Raw Scripture/USFM/USJ, Greek/Hebrew Scripture, ACT/Skill bodies, filesystem paths, credentials, and unwhitelisted fields are rejected. Optional report summaries are written separately after canonical publication and carry source SHA plus a non-authoritative label.
- Normal startup and AI Setup perform a non-generative readiness check and report provider, selected model, and effective reasoning level. Only the explicit **Check LLM connection** action performs a minimal model-generation test. Failed AI readiness blocks normal Main Menu entry.
- No OpenAI API-key/direct-API/fallback path exists.
- RTC/STC pre-run resource preflight is work-unit scoped: bound resource defects are reported with exact section, code, reference, and message before a Run is persisted. Explicit defects in other books are out-of-scope; unlocated parser/file failures remain conservatively blocking.
- RTC treats VRS mappings and versification-coordinate differences as non-blocking structural evidence. They remain visible in structural adjudication and final Action Reports even when one mapping crosses approved review portions; only actual multi-coordinate WIP/REFERENCE source records constrain RTC boundaries.

## Pre-release data policy

`localdata` is persistent local/operator state during Beta testing. Product-version changes do not delete Projects, Jobs, Runs, reports, local resources/plugins, or operator settings. Explicitly regenerable `.system` state may be invalidated by its own schema/fingerprint contract, and the managed runtime at `localdata/.system/runtime/venv` is repaired/rebuilt when dependency fingerprints change. This Beta intentionally provides no migration path from the retired in-Core development layout; `0.01beta2` establishes the canonical external-data contract.

## Naming and serialization state

- Qualification evidence created under earlier development labels is historical. The v0.01beta2 source requires a new clean staged-source qualification before it may become an RC; `MS-BETA2-QUALIFY` tracks that gate and is currently blocked by `BI-20260826-001` until the refactored external-data Core completes exact-source qualification.
- Current SAGE-owned configuration/policy/profile filenames use lowercase kebab-case; Python remains snake_case and current Markdown documents remain uppercase kebab-case.
- `sage.yml` and `terminology.yml` are consolidated into `system/config/sage-standard.json`.
- Skill, qualification-baseline, authority-source, protected-pin, and Run-manifest records now use JSON.
- `system/resources/rwc/authority/sources.json` is runtime-consumed authority metadata rather than a documentation-only table.
- Externally governed/platform names such as `SKILL.md`, `openai.yaml`, Paratext `Settings.xml`/`BookNames.xml`, and bundled `.SFM` filenames are preserved.

## Schema and release-gate state

- `system/tools/validate_schemas.py` validates all 43 shipped schema contracts, unique IDs, duplicate keys, owner mappings, and applicable source instances, including `OL_AUTHORITY_PROFILE`.
- `validate_package.py` requires every shipped schema, including evaluation-set and resource-rights contracts.
- Focused Beta validation is required after the version change. Clean source-package and deep-audit claims are deferred to `MS-BETA2-QUALIFY`.
- U.S. English is canonical for current system/operator prose; localized `en-GB` remains governed only in the interface localization source.

## Source hygiene

Current operating material must not present earlier pre-release implementation labels as current, use obsolete Project registration grammar, ship operator Project/Job/Run state, retain runtime caches/build artifacts, or include fixture workflow bindings. Historical labels may remain in the changelog, byte-pinned protected-contract metadata, compatibility tests, and migration references.

- Windows UNC-root launcher hardening: `system/bin/sage.cmd` now enters the SAGE root with `pushd`/`popd` instead of `cd /d`, preserving local-drive behavior while allowing cmd.exe UNC-drive mapping.
