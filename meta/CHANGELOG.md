# Changelog

## 0.01-rc7.04 — Project Inventory grammar, Job-role separation, and runtime isolation

- Replaced operator-facing Project registration grammar with **Paratext Project Catalogue → Add Project to SAGE → SAGE Project Inventory**.
- Made SAGE Projects role-neutral; BIC SOURCE/DONOR/TARGET and SAW WIP/REFERENCE are assigned only as Job bindings.
- Fixed SAW/BIC runtime validation so an inactive empty workflow template cannot invalidate the active Job.
- Fixed ACT continuation to consume the active Job's initialization receipt; Job-menu validation no longer falls through to a missing root-workspace receipt.
- Allowed Projects with valid ISO language metadata to enter SAGE before a language grammar/profile is configured; added offline ISO lookup and non-destructive language suggestions.
- Added guided ISO/profile reconciliation: a consistent Project prefix can identify an existing compatible profile, and the Operator can explicitly add a validated `profile_alias` to `ecosystem.yml` before Job creation retries.
- Classified standard USFM peripheral books separately from biblical scope, corrected CRLF-only book-ID detection, added guided base-VRS correction from `custom.vrs`, and made Job validation show bounded actionable failures instead of a generic controller error.
- Allowed configured external base/custom VRS sources to contribute hashed, bounded ACT evidence under logical provenance labels without exposing external filesystem paths as model-readable task inputs.
- Added Paratext scan heartbeat/progress and made the Paratext Projects root the default Base VRS root while preserving explicit overrides.
- Added explicit Add Job / Remove Job flows and safe Remove Project from SAGE semantics that never delete Paratext Projects.
- Removed the setup SAVE dependency by persisting configuration changes as they are made.
- Reconciled the cached Setup summary with active Job initialisation receipts at startup, so a current ready Job opens the Main Menu while genuinely missing, stale, or blocked receipts still resume Setup.
- Added guided Scripture scope selection and a pre-Run bounded-work/token preview with Run / Change scope / Cancel.
- Accepted direct scope text at the scope-selection prompt, preserved `BOOK` as whole-book and `BOOK CHAPTER` as whole-chapter syntax, and limited evidence-planning blockers to defects intersecting that exact scope.
- Fixed menu handling for partitioned `COMPOSITE` Normal-QA creation, preserving and resuming its plan instead of requiring a single-task `act_path`; unexpected continuation defects are now bounded at the Run menu with saved state preserved.
- Added rotating status lines for evidence planning, governed task preparation/execution/submission, continuation lookup, and aggregation, plus persistent `current/total` scope progress for composite SAW work units.
- Converged current menus, prompts, diagnostics, help, schemas, and documentation on the RC7.04 Project/Job vocabulary while retaining narrow internal compatibility aliases where required.
- Preserved CODEX-only execution, governed external-write boundaries, separate `@GRK`/`@HEB` authority, and protected BIC linguistic contracts.

## 0.01-rc7.03 — Paratext catalogue, Project maintenance, bilingual reporting, and governed OL resources

- Added a persistent `settings.xml`-gated Paratext Project catalogue, preparsing `settings.xml`, `canons.xml`, `.SFM`, `custom.vrs`, and short-code metadata for fast menu construction.
- Added operator discovery filters limited to FB/NT/Portions and Language, plus quick/full rescans and direct refresh for `<Other location>` Projects.
- Reworked Scripture Project maintenance around Project identity, books, versification, reporting, storage, validation, Job usage, and safe unregister.
- Added per-Project bilingual reporting overrides while keeping the RC7 UI English; BIC resolves reports from TARGET and SAW from WIP.
- Separated governed `@GRK` / `@HEB` resources from ordinary translation Project registration and added explicit bundled/Paratext/local override configuration with runtime provenance.
- Preserved clean-RC startup, Job/Run authority boundaries, external write restrictions, CODEX-only execution policy, and protected BIC linguistic contracts.

## 0.01-rc7.02 — clean RC start, first-run Scripture validation, and runtime-path hardening

- Enforced clean operator/project/workflow state on first launch of each new RC version; `.venv` is preserved and beta migration remains outside the RC core distribution.
- Added first-run Scripture/VRS validation with an intentionally valid empty project inventory.
- Removed shipped workflow fixture profiles and executable project-specific defaults from RWC/generation surfaces.
- Made original-language resources registerable from an empty install and constrained OL metadata to `grc` / `hbo`.
- Startup now prints the exact SAGE root and managed `.venv` path, making stale extracted copies visible immediately.
- Retained quoted macOS/Linux path normalisation and parent Paratext Projects-root resolution.

## 0.01-rc7.01 — operator path handling and runtime identity

- Accept quoted macOS/Linux project-path pastes consistently.
- When mapping a selected project, accept either the direct project folder or its parent Paratext/PTLite Projects root and resolve the matching child project.
- Show the running SAGE version and root on the main menu to expose stale extracted/runtime copies during RC testing.
- Apply shared operator path normalisation to RWC/SEMDOM import prompts.

## 0.01-rc7.00 — root-based resource setup and provider probe repair

- added reusable named Paratext/PTLite projects roots and root-relative resource mounts;
- normalised pasted macOS/Linux/Windows project paths, including matching shell quotes and Unix escaped spaces;
- allowed BIC/SAW project creation to register required resources from detected Paratext/PTLite subfolders without leaving the wizard;
- made Tool Project IDs deterministic/automatic on the normal guided path;
- sequenced the Codex App Server handshake before `account/read` and `model/list`, while separating execution readiness from catalogue health;
- removed obsolete RC-specific source artifacts, renamed regression files by capability, and added a package gate against previous-RC filenames;
- preserved SAGE-parent Codex execution, local `.venv` bootstrap, authority boundaries, external read/write restrictions, and protected BIC linguistic contracts.

## 0.01-rc7.00 — local Python bootstrap hardening

- Added a standard-library bootstrap that runs before any `sage_core` import.
- First launch creates the local `.venv` only with operator approval and installs declared `requirements.txt` dependencies as part of the same approved action.
- Existing `.venv` environments are checked for supported Python, pip, declared requirement versions, and `pip check` consistency; incomplete environments offer guided repair.
- Removed silent system-Python fallback for SAGE application execution; healthy startup always runs `sage_core` through the validated local `.venv`.
- Added `state/runtime-state.json` with the validated Python version and requirements fingerprint, and excluded `.venv` from release-source collection.
- Preserved RC7.00 SAGE-parent Codex installation/login behaviour and protected BIC contracts unchanged.

## 0.01-rc7.00 — SAGE-parent runtime and setup navigation

- SAGE remains the parent process during Codex installation, login, and AI execution.
- Windows and Unix standalone Codex installation set `CODEX_NON_INTERACTIVE=1`, suppressing the installer TUI launch and returning control to SAGE.
- Post-install verification resolves the standalone `~/.local/bin/codex` binary before shell PATH refresh and keeps it available to the current SAGE process.
- BIC and SAW setup states are independent; configuring one valid workflow is enough for SAGE readiness.
- Setup adds System / Configuration, Save and return, and Exit SAGE routes.


## 0.01-rc7.00 — Resumable guided operator UX

- Made `sage` / `sage.cmd` the single normal entry point with lightweight Codex/ChatGPT preflight.
- Added explicit operator-approved Codex CLI installation from guided setup when the CLI is missing.
- Made setup resumable through `state/setup-state.json` with a single recommended `next_step`.
- Added `state/operator-cues.jsonl` as a high-level append-only navigation/session cue journal; workflow transaction journals remain authoritative for governed writes.
- Reduced the main menu to Resume/New Task, BIC, SAW, Projects & Resources, Setup & OpenAI, and Recovery & Diagnostics.
- Removed duplicate recovery/configuration entries from task menus without removing underlying operations.
- Replaced documentation-driven onboarding with Windows and UNIX cheat-sheet/recovery/error fallback sets.
- Preserved BIC/SAW authority boundaries and byte-pinned protected BIC rewrite/verb-selection contracts.

## 0.01-rc7.00 — Guided setup and platform onboarding

- Reworked first-run setup into a menu-driven setup control panel with readiness and nested configuration paths.
- Added SAGE-managed OpenAI/ChatGPT connection through interactive Codex CLI login; Codex desktop app is not required.
- Preserved fail-closed ChatGPT-only authentication and the prohibition on OpenAI API keys/direct API/fallback.
- Split operator documentation into independently maintained `docs/windows/` and `docs/unix/` sets; root `START-HERE.md` is now a platform selector.
- Preserved RC7.00 bounded-storage, OL micro-scope, SAW segmentation, provider, and protected BIC linguistic contracts.

## 0.01-rc7.00 — Hardening and context refinement

- fixed bounded TARGET insertion at end-of-chapter and added exact post-merge/out-of-scope validation before write;
- added exact post-revert verification and nanosecond TARGET-history ordering;
- moved context enforcement to the exact provider prompt + output-schema boundary for every LLM phase;
- constrained conditional BIC OL adjudication to one material challenge and one single-verse raw SOURCE/OL micro-scope per phase, with VERB_CHOICE question-limited to verbal sense/function;
- added deterministic SAW discourse units and one-unit Normal meaning-QA partitioning for prose, lists, and operational poetry stanzas;
- made hardening auto-cover every discovered test module, terminate timed-out process trees, and record the governed source-tree hash;
- made production release packaging require a hardening PASS bound to the exact staged source hash;
- preserved RC5.05 cardinality/binding grammar, CODEX-only activation, authority boundaries, and byte-pinned protected BIC linguistic contracts.

## 0.01-rc5.05 — Cardinality and binding grammar convergence

- standardised machine cardinality on `exactly_one`, `zero_or_one`, `one_or_more`, `zero_or_more`, and `exactly_one_of`;
- declared BIC SOURCE/DONOR/TARGET as `exactly_one` and TARGET storage as `exactly_one_of` internal or mapped Paratext/PTLite storage;
- made Greek and Hebrew Tool Project bindings independently `zero_or_one`, with one applicable OL resource required only when OL is actually routed;
- documented selected SOURCE/TARGET/WIP grammar contracts as `exactly_one_active` and effective VRS as `exactly_one` after resolution;
- converged current human-facing docs, cheat sheets, workflow READMEs, help text, generated project README templates, and status prose on bound/configured/selected/resolved terminology;
- preserved RC5.04 bounded TARGET mutation, composite SAW QA, provider policy, and protected BIC linguistic contracts.

## 0.01-rc5.04 — Bounded storage and composite-QA grammar repair

- merged bounded BIC SELF-CHECK results into the existing single TARGET book instead of replacing full-book content;
- preserved existing mapped Paratext book filenames and out-of-scope Scripture;
- added bounded TARGET commit history and explicit Revert TARGET Scope;
- separated Restart Scope and system Recover/Reset/Break Lock/Rebuild operations from translation rollback;
- added transaction conflict checks immediately before replacement;
- scoped SAW structural and selective-OL stages to exact candidate/request coordinates;
- added structured OL request-resolution objects, required OL evidence, deferred-issue reconciliation, and preserved resolution provenance;
- validated Tool Project resource/profile bindings before persistence and kept direct BIC stages in one matching Session;
- repaired declarative role vocabulary, true ISO calendar-date validation, and USFM-vs-internal-USJ format semantics;
- expanded current-surface semantic contract lint and adversarial boundedness tests;
- preserved protected BIC rewrite-detail and verb-selection contracts unchanged.


## 0.01-rc5.03 — Project grammar and workflow convergence

- unified governed BIC/SAW work under persistent Tool Project -> Session -> Task identity;
- enforced strict language/workflow/Tool Project manifest schemas;
- enforced exactly one BIC SOURCE, DONOR, and TARGET, with one TARGET resource regardless of storage binding;
- resolved OL authority from exact project bindings;
- restored Normal SAW QA as deterministic preflight + conditional structural + required meaning + conditional OL + deterministic finalisation;
- replaced Paratext Notes output claims with plain Operator copy/paste note text;
- defined `AI_DRAFTED` provenance as LLM general target-language knowledge;
- converged live Skill references with current authority and stage routing;
- preserved protected BIC rewrite-detail and verb-selection contracts unchanged.

## 0.01-rc5.02 — Boundary and configuration hardening

- separated provider provisioning from RC5.02 execution permission; Codex is the only enabled automated provider;
- added role-specific Paratext/PTLite access with case-insensitive `.SFM`/`.VRS` reads and optional BIC TARGET `.SFM` writes;
- added configurable base VRS root and project-local VRS precedence;
- migrated SAW to exact WIP/REFERENCE roles with `UNDER_REVIEW` lifecycle and no external writes;
- removed BIC-to-SAW handoff/pin semantics;
- made BIC project identity SOURCE+DONOR+TARGET and added immutable evidence cohorts with exact OL inheritance;
- accepted `AI_DRAFTED` as an explicit operational grammar state.


## 0.01-rc5.01 — BIC/SAW authority-boundary cleanup

- Added explicit BIC `LEXICAL_DONOR`; BIC is now `SOURCE + DONOR -> TARGET`.
- SOURCE is the sole BIC content/translation authority; DONOR is decontextualised vocabulary evidence only.
- Existing BIC TARGET Scripture is no longer routed during INSPECT or REWRITE.
- SAW operator semantics are now WIP + authorised REFERENCE (+ routed GRK/HEB).
- Preferred CLI/UI vocabulary is `--source/--donor/--target` for BIC and `--wip/--reference` for SAW; generic aliases remain compatible.
- Parked WDA and existing-target revision as separate future work.
- Protected BIC rewrite-detail and verb-selection contracts remain byte-identical.

## 0.01-rc4.04 — Workflow integrity and semantic governance

- Added semantic index freshness fingerprints and fail-closed stale-index gates.
- Separated seed lexical heads from canonical lemma authority.
- FLEx/Combine imports now always enter as OBSERVED; reviewed states require explicit provenance.
- Added local RWC lookup, governed review states, explicit export views, and RWC initialisation.
- Added stable external LIFT sense-ID reconciliation without unsafe string-based merging.
- Fixed the documented `bic self-check` public shortcut.
- Reorganised the RWC Control Center and converged active documentation with runtime behaviour.
- No live semantic-data migration is required; RC4.04 is a forward-only contract.

## 0.01-rc4.03 — Local-first semantic indexes and BIC/SAW governance

- Elevated deterministic local-before-AI execution to an architectural rule.
- Added RWC/SEMDOM indexes, explicit idKKH→KKH binding, immutable FLEx/Combine LIFT exchange, and Greek reference import.
- Added external active-import selection, changed-byte rejection for reused source IDs, and source-scoped internal LIFT identifiers for safe multi-snapshot indexing.
- Removed all Operator candidate input from BIC REWRITE; retained concise risk-rated reporting and SELF-CHECK.
- Added a separately pinned BIC verb-selection policy while retaining the protected rewrite-detail contract unchanged.

## 0.01-rc4.02 — UX and provider-runtime hardening

- Added fast local `sage status` plus explicit `sage status --live` provider probing.
- Added direct four-section `sage setup` that returns to the shell and skips live provider probing.
- Made setup project initialisation idempotent when derived settings are unchanged.
- Added shared `ModelService` for CLI/menu provider discovery, selection, policy, recommendation, and tests.
- Parallelised independent read-only all-provider status probes.
- Removed provider-specific bridge/assets and legacy task execution-mode acceptance.
- Removed controller-only/provider-specific instructions from routed analytical Skills and added contamination guards.
- Added `docs/INDEX.md` and the RC4.02 UX/code review; historical analysis reports are no longer mandatory package documentation.
- Preserved the protected BIC rewrite contract byte-identically.

## 0.01-rc4

- Added the menu-driven SAGE Control Center as the default `./sage` experience.
- Added deterministic first-run setup and global recalibration under menu option 9.
- Added persistent BIC/SAW project and session manifests with independent active-project pointers.
- Added project/session-scoped task and plan paths.
- Added project-scoped BIC memory and generations and project-scoped SAW pins.
- Added controlled Cline CLI steering with explicit `--auto-approve false`.
- Moved shared Scripture resources to `resources/scripture/` and reserved `projects/` for tool projects.
- Added RC4 menu, isolation, runtime-root, session, and Cline-boundary regression tests.

## 0.01-rc3

- Added stale-safe individual BIC memory transitions and exact approved-memory materialisation.
- Added governed lexicon import, source provenance, import receipts, and explicit rollback.
- Added workflow-bound BIC and SAW stage reset receipts with downstream and governance protections.
- Added sequential SAW partition continuation and out-of-order finalisation detection.
- Added exact-hash grammar-profile review and effective-status routing.
- Added machine-readable resource provenance and rights validation without inventing external authority.
- Preserved the complete pinned BIC 4 protected REWRITE contract byte-identically.
- Added one canonical `START-HERE.md` setup flow with explicit Terminal/CLI, Cline Chat, and Cline Act boundaries.
- Added read-only `sage guide` and `sage help` commands, YAML setup notices, and local `.venv` launcher preference.
- The exact isolated clean RC3 build passes 233 tests with pre/post package validation and deep audit.

## 0.01-rc2b

- Reconciled commands, Skills, prompts, ACT templates, workflow profiles, tests, and documentation with non-blocking review attention.
- Added independent language configuration for logs/reports and translation challenges.
- Added concise material challenge reporting, readable operational logs, and conditionally authorised OL evidence.
- Preserved the complete pinned BIC 4 contract and deterministic release controls.
- The exact clean RC2b build passes 220 tests across the complete strengthening sequence.

## 0.01-rc2a

- Promoted the cumulative guided-remediation and hypercritical-review refinements to a distinct RC revision.
- Added governed natural-language request routing through `sage request`.
- Ranked registered commands, placed the strongest safe command at option 2, and required explicit confirmation before execution.
- Added edit, explain, related-operation, advisory-only, and cancellation paths without permitting freestyle project execution.
- Added a request-routing audit log, a dedicated command-router Skill, and natural-language contracts across all workflow Skills and operator documents.
- Added deterministic routing regression tests and integrated them into the clean-state hardening runner.
- Completed the RC2 prompt/command/Skill/project-grammar consistency and distribution-cleanup pass.
- Separated BIC stage references, completed all 17 Skill metadata bundles, and aligned the process tree and cheat sheets.
- Added explicit `_` versus `-` naming contracts and Python human-maintainability gates for every module and procedure.
- Removed generated runtime, cache, bytecode, log, and test artefacts from release inputs.
- Restored the complete explicit BIC 4 protected REWRITE contract, with only project-spelling, canonical-action, and approved layout-marker adaptations.
- Pinned the active REWRITE and SELF-CHECK contract mirrors by SHA-256 and added runtime, audit, and regression enforcement.
- Distinguished `review` from `flow` in project grammar and enforced canonical target-text action vocabulary while retaining the noun `translation` in human-facing BIC explanatory text and tables.
- Verified generated REWRITE and SELF-CHECK ACT files against the pinned contract and vocabulary rules.
- Added objective REWRITE lexical-burden scoring, licensed Longman-band validation, automatic bounded OL mitigation, non-blocking urgency reporting, and governed Operator verb selection.
- The exact clean RC2a build passes 207 tests across the equivalent 12-step hardening sequence.

## 0.01-rc1 guided-remediation revision

- Added interactive correction and structured `INPUT_REQUIRED` results across canonical commands, wrappers, INIT, runtime identifiers, grammar decisions, and workspace initialisation.
- Added governed effective-configuration sidecars with source-hash staleness protection and reset preservation.
- Limited task-triggered INIT review to the exact projects selected by the task.
- Propagated the state contract through all 16 Skills, ACT guidance, and current help documents.
- Hardened the one-command runner with file-backed output capture and explicit descendant termination.
- The exact clean build passes 170 tests with pre/post validation and deep audit.

## v0.01-rc1 hypercritical reviewed revision

- Completed full operational-document review and added a formal documentation grammar.
- Corrected command syntax, process order, grammar-override guidance, and recovery/generation flags.
- Reconciled all routed BIC and SAW references with current ACT behaviour.
- Added skill frontmatter and refreshed registered adapted-skill hashes.
- Expanded language grammar profiles for spelling, syntax, orthography, and clause attachment.
- Added quick start, BIC/SAW cheat sheets, project tree, good-practice guide, and help index.
- Added documentation compliance regression tests and preserved POSIX executable mode.

- Added ten documentation-contract regressions; the exact reviewed clean build passes 154 tests.

## 0.01-rc1

- Promoted the validated dev.8 baseline to release-candidate status for controlled small-group testing.
- Updated runtime, package, metadata, documentation, and test fixture version identities.
- Added an explicit promotion record tied to the supplied dev.8 reports.
- Preserved all resource restrictions, human acceptance requirements, and external authority gates.
- Added explicit RC version validation and a zero-warning release-builder gate.


## 0.01-dev.8

- Repaired ACT readiness, immutability, traversal, scope, output-grammar, and resubmission defects.
- Migrated and hashed BIC/SAW source instructions and strengthened six adapted analytical Skills.
- Implemented BIC staged memory/rewrite/self-check flow and SAW staged preflight/review/finalisation flow.
- Strengthened Farsi, Ukrainian, Indonesian, and English language profiles.
- Standardised the CLI as `sage <domain> <action>` and aligned all launchers/help.
- Rewrote human-facing documentation and expanded deep audit/release gates.

## Earlier development

Earlier builds established the shared registry, strict USFM/USJ compiler, VRS composition, language-code profile routing, project scope/canon/state/role declarations, immutable target generations, work-unit planning, and resource handover structure. Historical details are retained in prior handover packages.

## 0.01-rc4.01 — live model policy and XHigh reasoning ceiling

- Added live Codex App Server account/model capability discovery.
- Added Available / SAGE-qualified / Recommended task-aware model routing.
- Added deterministic per-task reasoning recommendations and per-phase execution-receipt provenance.
- Set XHigh as the hard maximum SAGE reasoning level.
- Provider-advertised levels outside SAGE's supported set are filtered from discovery and cannot be selected, persisted, executed, or enabled by policy override.
