# SAGE system grammar

This document governs current SAGE English documentation, generated prompts, Skill instructions,
help text, comments, reports, and Operator-facing prose. It is the SAGE system grammar; it does not
override a language-specific Scripture Project grammar.

## English spelling standard

Use U.S. English (`en-US`) as the canonical editorial language for SAGE documentation, generated
prompts, Skill instructions, help text, comments, reports, and Operator-facing prose. The canonical
English system-interface locale is also `en-US`. Interface locale, Job reporting language, and
Scripture-language identity are separate authorities and must not inherit from one another.

Preferred forms include:

- `analyze`, `authorize`, `authorized`, `authorization`;
- `behavior`, `capitalization`, `finalize`, `finalized`;
- `initialize`, `initialization`, `normalize`, `normalization`;
- `organization`, `recognize`, `recognized`, `standardize`;
- `judgment` in general prose;
- `license` as both noun and verb;
- `artifact` in prose;
- `catalog` for a collection or index, and `catalogue` only when it is part of an external or
  compatibility name.

Preserve exact command names, identifiers, schema fields, status values, filenames, external-standard terms, and quoted historical text even when their spelling differs. Examples include `workspace initialize`, `FINALIZED`, `normalization`, `--keep-test-artifacts`, and `self_check`.

## System and Job language authority

- The SAGE system/interface language governs workstation menus, system help, setup, and
  administration surfaces. Its canonical English editorial profile is `en-US`.
- Each Job must own a required primary reporting language and may own one distinct secondary
  reporting language. The Job setting governs every human output derived from that Job.
- Choose the Job primary reporting language for the target audience. The setting persists because
  one Operator may work across Jobs serving different audiences.
- The primary may be any approved language of wider communication (`LWC`) supported by a governed
  reporting profile. It replaces the default for that Job; it is not merely an extra rendering.
- Use explicit English reporting tags: `en-US` for U.S. English and `en-GB` for U.K. English. Do
  not use bare `en` as a Job reporting-language value.
- A Project's Scripture-language identity and role-specific grammar profile remain distinct from
  report language. Projects are accessed only through Job bindings; Projects do not own reporting
  settings.
- Preserve canonical machine records across reporting languages. Never localize commands, paths,
  identifiers, hashes, status codes, evidence IDs, or Scripture coordinates.

The current implementation still inherits the Job primary report language from the global Operator
language. [Purpose and function drift report](../maintenance/PURPOSE-FUNCTION-DRIFT-REPORT.md) records the required
schema, menu, runtime, catalog, and validation adjustment.

## Canonical terminology

- Governed-entity capitalization: capitalize `Project`, `Job`, and `Run` (including the plurals
  `Projects`, `Jobs`, and `Runs`) when they name SAGE-governed records. Capitalize `Operator` and
  `Operators` when they name the formal SAGE human role. Keep ordinary process and artifact nouns such as `task`,
  `work unit`, and `report` lowercase except at the start of a sentence or in title-style interface
  text. Lowercase the same words when they are generic rather than SAGE terms, and preserve the
  exact lowercase spelling of command names, schema fields, identifiers, and path components. For
  example: `SAGE creates and manages Projects, Jobs, Runs, tasks, and reports.`
- Product: `SAGE` — Scripture Analysis and Generation Engine.
- Release: use `SAGE v0.01beta` for the exact product version and `current Beta development` in general prose. State `pre-release; fresh exact-source qualification required before the first RC; public-production readiness not claimed` in current entry-point, release, status, packaging, and testing material. Historical documents may retain their original release label when clearly identified as historical.
- Version progression: promote the qualified Beta to `v0.01rc1`; use `v0.01rc2`, `v0.01rc3`, and so on for later qualified candidates. Reserve `v0.01` for the approved release. Do not describe Beta builds as release candidates.
- Feature maturity: use machine state `EXPERIMENTAL_UNSTABLE` and exact display label `EXPERIMENTAL / UNSTABLE` for incomplete, non-authoritative features that may change incompatibly. Feature maturity is independent of the product phase and does not advance automatically with Beta, RC, or release promotion. The v0.01beta Textual TUI has this classification; the classic menu and scriptable CLI remain authoritative.
- Workflow: `BIC` — Bible Index & Context.
- Workflow: `SAW` — Scripture Analysis Workbench.
- Execution mode: `SAGE_GOVERNED_TASK_V1`.
- Evidence boundary: use `LOCAL EVIDENCE BOUNDARY` for the closed Job/task evidence perimeter.
- Content authority term: use `AUTHORIZED CONTENT EVIDENCE` for SAGE-local evidence that may support content judgments within its exact Job role and scope.
- Model-capability term: use `GENERAL LINGUISTIC COMPETENCE` only for orthographic, morphological, grammatical, and syntactic competence. It is capability, not evidence.
- Canonical invariant: `Local Evidence, General Linguistic Competence.` In prose: `Linguistic competence may determine how locally supported content is expressed; it may not determine what the content is.`
- Read classification: every model-facing read must carry one canonical `evidence_class`: `AUTHORIZED_CONTENT_EVIDENCE`, `AUTHORIZED_LEXICAL_EVIDENCE`, `PROJECT_INDEX_EVIDENCE`, `DERIVED_EVIDENCE`, `STRUCTURAL_EVIDENCE`, `SUBJECT_TEXT`, `LINGUISTIC_COMPETENCE_RULES`, or `PROCESS_CONTROL`. Unclassified reads fail closed.
- `AUXILIARY_SCRIPTURE`: inventory/scope compatibility role only. It is never content authority and must not be routed into analytical model evidence unless a Job binds that resource to a canonical authority role.
- Human role: `Operator`.
- Formal role identifiers: backticked uppercase, for example `CONTENT_SOURCE`.
- BIC prose roles: uppercase `SOURCE`, `DONOR`, and `TARGET` when naming the three authority roles. `REFERENCE` is prohibited for the BIC donor.
- SAW machine/procedure roles: uppercase `WIP` and `REFERENCE` identify the translation under analysis and the configured LWC Reference Project comparison. In Operator-facing final reports, resolve these role identifiers to the configured Project display names. Do not call the Reference Project a benchmark.
- Original language: use `original-language` adjectivally; introduce `OL` only after the full term.
- Task controls: `ACT.md` and `task-manifest.json`.
- Project context: every governed analytical task belongs to one persistent Job and one bounded Run built from SAGE Projects. Direct commands and natural-language routing must not create Job-less or Run-less BIC/SAW tasks.
- Reporting-language settings: `ecosystem.yml` owns the global Operator language (default `en`) and its `approved`, `candidates`, and `pilot_only` policy lists. Normal menus expose only approved languages and candidates. An advanced Operator must manually add a `pilot_only` tag to `candidates` before controlled evaluation. Each Job may store one optional secondary reporting language in `job.yml`. A secondary rendering adds model usage and report compilation time and requires more human review than a single-language report. A SAGE Project never stores report-language settings.
- Job report ownership: use `Job report catalog` for the canonical machine record under
  `jobs/<tool>/<job-id>/report_data/`. Use `Operator reports catalog` for polished output under
  `localdata/reports/<job-id>/<BOOK>/`. The `<job-id>` identifies the owning Job, never a Project.
- Consolidation: use `consolidate` for provenance-preserving deterministic combination of compatible
  finalized result sets. Equivalent findings may be deduplicated. Shared coordinates/categories do
  not prove contradiction; only explicit conflict lineage triggers `HUMAN_REVIEW_REQUIRED`.
- Run report provenance: Run directories retain tasks, validation receipts, stage aggregates, and machine plans. They do not own the final Job report catalog.
- Report-ownership wording: for final BIC/SAW workflow outputs, do not say `Project report`,
  `Project reports folder`, `Project-owned report`, or `Run report folder`. Use `global Operator
  language`, `Job secondary reporting language`, `Job report data`, and `Operator reports catalog`.
- Model-facing task resource identity: use `resource_bindings` with canonical BIC `SOURCE`/`DONOR`/`TARGET` or SAW `WIP`/`REFERENCE` roles. Internal projection fields `output_project` and `contemporary_source` may appear in task packets, but `resource_bindings` and the owning Job define authority semantics.
- BIC operator wording: one bound `SOURCE` resource, one bound `DONOR` resource, and one bound `TARGET` resource per BIC Job. TARGET storage location is not a second TARGET.
- Machine cardinality vocabulary: use only `exactly_one`, `zero_or_one`, `one_or_more`, `zero_or_more`, and `exactly_one_of` for schema cardinality. Do not use `exact`, `single`, `required`, or prose `one` as machine cardinality substitutes.
- BIC machine cardinality: `SOURCE=exactly_one`, `DONOR=exactly_one`, `TARGET=exactly_one`; TARGET storage is `exactly_one_of(SAGE_INTERNAL, PARATEXT_PROJECT)`.
- Original-language bindings: Operator prose says `configured Greek resource` / `configured Hebrew resource`; machine cardinality is `zero_or_one` for each. When an OL task is routed, exactly one applicable bound OL resource is required for that task.
- Grammar-profile wording: Operator prose says `selected SOURCE grammar profile`, `selected TARGET grammar profile`, or `selected WIP grammar profile`; machine selection is `exactly_one_active`.
- Qualification-language wording: the current Scripture test languages are Indonesian (`id`), Ukrainian (`uk`), and Persian (`fa`). A test-language designation records qualification scope; it does not mean that a Project, grammar profile, or localization catalog is bundled, configured, approved, or active. The vanilla package contains a regional review-required WIP starter library keyed by canonical BCP 47 regional tags; imported Projects must confirm a regional identity before operational profile binding. Keep Scripture test-language scope separate from Operator/report-language policy; `id` participates in both for different reasons, while `uk` and `fa` are not thereby Operator-language candidates.
- Interface-language wording: use `interface localization source` for the Setup-owned terminal labels and prompts governed by `system/config/localization/menu-localization.json`. The current interface set is `en-US`, `en-GB`, `id`, `fr`, `ru`, and `pt-BR`; every governed entry contains all six renderings. `ecosystem.yml > interface.language` selects the workstation interface locale. Menu behavior is keyed by invariant semantic controls, never by localized labels. Do not call this source a Scripture grammar profile or a Job reporting profile.
- Versification wording: Operator prose says `resolved effective VRS`; machine cardinality is `exactly_one` effective VRS per governed resource/Run context after resolution.
- SAW Operator check vocabulary: use **Standard QA**, **Targeted Check**, and **Original-Language Review** as the three public check-mode names.
  - **Standard QA** is the broad systematic SAW QA operation. The current machine operation remains `qa`; historical records may retain `Normal QA`, but current Operator surfaces must not. Standard QA contains conditional `STRUCTURAL_ADJUDICATION`, required `TRANSLATION_AND_MEANING_QA`, and conditional `SELECTIVE_OL_ADJUDICATION` model stages around deterministic preflight/finalization. Ordinary Standard QA stages do not receive OL Scripture. Only when `source_text_drift_adjudication` is `ENABLED` may the meaning stage defer a material Working-Project-versus-Reference-Project rendering conflict whose source provenance cannot be established from routed non-OL evidence; SAGE then routes only that bounded source-text question to selective OL adjudication.
  - **Targeted Check** is one explicitly bounded WIP+REFERENCE question that does not receive OL Scripture. The current machine operation remains `focused` for compatibility; do not use `Focused Check` as the canonical beta Operator label. If the bounded question requires direct Greek/Hebrew adjudication, route it as Original-Language Review instead.
  - **Original-Language Review** is one tightly bounded question requiring direct configured Greek/Hebrew evidence, normally one verse or short verse range. It is not a general commentary or unrestricted OL study. The current machine operation remains `ol`.
  - Selection rule: broad/systematic review -> Standard QA; one bounded non-OL question -> Targeted Check; one bounded question requiring direct OL evidence -> Original-Language Review.
- SAW note output: use `Operator note text` or `plain-text issue blocks`; never describe SAGE as creating Paratext Notes XML.

- Classic interactive-screen grammar: enclose every major menu title with the complete double-line set `╔═╗ / ║ / ╚═╝`. Render minor section headings with a `> ` prefix followed by an unindented, full-width `─` underline. Enclose the global A-F footer with the complete single-line set `┌─┐ / │ / └─┘`. Leave one blank line before and after each block. Indent footer keys with two spaces (`  A.`, `  D.`), matching the numeric-choice field. Put primary/commit actions before configurable options. Use fixed-width label columns instead of literal tab characters. Optional free-text/path prompts that accept cancellation must say `[Enter to cancel]` and must treat empty input as Back/cancel, not as an error.
- Compact-list grammar: primary Operator lists show only differentiating fields. Repeated role/status/path metadata belongs in a selected-item detail view. Grammar-profile candidate lists should expose script compactly, for example `fa-IR [Arab]`.
- SAW execution-feedback grammar: print stable Job/Run parameters once, then one replaceable `Working on SAW work unit n/N: <scope>` spinner line. Provider, model-selection, receipt, ACT, task-ID, and aggregate-path details remain in governed records/diagnostics rather than the default progress stream.
- Bilingual SAW finding grammar: render `Issue` immediately followed by `Proposed action` for the primary Operator language, then render `Issue` immediately followed by `Proposed action` for the secondary assistive language. Do not separate Issue blocks from their same-language actions.
- Scripture format: `USFM`.
- Versification: define `VRS` at first use for a general audience.
- Natural-language interface: `natural-language request`, `interpretation`, `canonical command`, and `advisory-only`.

## Review versus flow

Use `review` for an examination, assessment, adjudication, or governed human decision about evidence, text, configuration, output, or readiness. A review has a reviewer, review evidence, findings, a decision, or an approval state.

Use `flow` for an ordered sequence of stages, commands, transitions, or information movement. A flow has an entry point, ordered steps, branches, state transitions, and an exit condition.

- Use `process flow`, `workflow`, `operation order`, or `execution flow` when describing how work proceeds.
- Use `human review`, `grammar review`, `original-language review`, `consistency review`, or `output review` when describing examination or judgment.
- Do not use `review` as a synonym for a process sequence.
- Do not use `flow` as a synonym for an assessment or approval gate.
- A document may contain both: the flow defines when review evidence may be recorded, and the review records attention or provenance. Human review records attention, evidence, or provenance and does not gate normal workflow progression. Only objective technical or integrity prerequisites may prevent execution.

## BIC target-text action vocabulary

Use `REWRITE` as the sole canonical BIC operation that produces a target-text candidate. Use `rewrite`, `prepare target text`, `produce a target candidate`, or `rendering` in explanatory prose as appropriate.

The prohibited target-text verb forms are enforced by the vocabulary audit and must not appear in current commands, prompts, generated ACT files, Skills, help, status messages, error messages, or Operator instructions. The noun `translation` is permitted in human-facing BIC tables and explanatory text, including established phrases such as `translation challenges` and `translation memory`. Immutable Scripture, historical evidence, quoted Operator input, and the private natural-language input lexicon are outside this emitted-vocabulary rule.


## REWRITE lexical-risk vocabulary

Use `lexical burden` for audience processing difficulty and `semantic risk` for possible change to meaning, force, agency, participant relations, grammar, or discourse. Do not use `complexity` alone when the intended dimension is unclear.

Use `bounded OL check` for the automatic, tightly scoped original-language risk-control step. Use `original-language review` only for a distinct analytical review operation. A bounded OL check belongs inside the REWRITE flow; it is not a routine human gate.

Use `translation challenge` as the human-facing noun for a recorded BIC issue. The noun `translation` is permitted in explanatory text and tables. Use `REWRITE` as the canonical target-text action in commands, prompts, ACT files, Skills, status messages, and generated operational reports.

Use urgency levels `0` through `4`. Linguistic uncertainty produces `COMPLETED_WITH_CHALLENGES` or `STAGED_VALIDATED_WITH_CHALLENGES`; it does not produce `DECISION_REQUIRED` or `BLOCKED`. Reserve `BLOCKED` for technical or integrity impossibility.


## Human-output language and materiality

Use these configuration terms for the two human-output channels, which share the global primary language and optional Job secondary language:

- `logs_and_reports`: operational logs, non-JSON command summaries, INIT and validation reports, status summaries, errors, and remediation messages;
- `translation_challenges`: concise linguistic challenge summaries, evidence, alternatives, and actions.

A bilingual rendering is one canonical record displayed in two languages; never double the challenge or event count. Preserve commands, codes, project IDs, Scripture coordinates, candidate forms, paths, and hashes exactly. List only material translation challenges individually, consolidate repeated causes, and aggregate minor or automatically resolved matters. Put diagnostic vectors and hashes in machine records, not normal human reports.

Every bilingual report must state that the primary Operator-language rendering governs interpretation but does not guarantee that every finding is correct. It must identify the secondary rendering as assistive, lower-confidence, unverified translation that may contain ambiguity and must be checked against the primary before action. Canonical machine records, reason codes, evidence IDs, and Scripture coordinates remain authoritative.

### Final Beta Language/Profile hierarchy

Use `Language identity` for the broad ISO language/macrolanguage identity, `member language` where ISO defines one, and `regional Language Profile` for the working SAGE namespace bound to Projects and Grammar Profiles. Examples: `English [en/eng] -> en-US/en-GB`; `Persian [fa/fas] -> Iranian Persian [pes] -> pes-IR`; `Persian [fa/fas] -> Dari [prs] -> prs-AF`. Do not model these relationships with `profile_alias`. Legacy aliases are migration-only compatibility data.

Projects must have a confirmed regional Language Profile before SAGE registration completes. Grammar Profiles are subordinate role-specific dependants and may remain unconfigured until Job setup requires them.

### Final Beta report/storage grammar

Processing and evidence granularity may be smaller than a chapter; Operator report granularity is one chapter. Use `<BOOK>_<CCC>_ACTION-REPORT.md` and `<BOOK>_<CCC>_OPERATOR-NOTE.txt`, with a three-digit chapter even for single-chapter books. The Markdown report is canonical; TXT is a deterministic non-AI rendering of that finalized Markdown. Root `reports/` contains Operator deliverables only. Technical execution data belongs to `diagnostics/`, machine aggregation to `report_data/`, and block evidence to `tasks/`.

Operator-facing report prose resolves internal `WIP` and `REFERENCE` roles to configured Project display names. Original-language drift adjudication likewise reports `<project-name> CLOSER TO SOURCE`, `BOTH DEFENSIBLE`, or `INCONCLUSIVE`; it must not expose bare role labels as the decision.

### Final Beta Standard-QA policy

Standard QA has four independently toggled checks: structure/completeness, translation/meaning, language/readability, and consistency. USFM context policies are `NORMAL`, `MATERIAL_ONLY`, and `STRUCTURE_ONLY`; selecting a context cycles directly through these values. `MATERIAL_ONLY` controls finding elevation and never downgrades severity. `STRUCTURE_ONLY` validates marker structure without treating enclosed content as translation prose. The current contexts are `\add`, `\nd`, `\f`, and `\x`; quotation `\qt` is not an Operator policy toggle. `Check source-text drift adjudication` toggles `PROHIBITED`/`ENABLED`. When enabled, it permits a bounded OL request only when the Working Project and Reference Project materially conflict in their rendering of the same source meaning and routed non-OL evidence cannot establish source provenance. The OL stage answers only that source-text question and records the source basis; grammar, readability, punctuation, spelling, USFM/structure, style, and ordinary consistency defects never trigger OL routing. OL becomes primary source-text authority only for that bounded adjudication.

## Syntax and sentence design

- Put the responsible actor before the action when responsibility matters.
- Use imperative sentences for procedures.
- Keep one command or one decision in each numbered step.
- State the prerequisite, exact scope, action, expected result, and failure condition.
- Avoid unclear pronouns, especially `it`, `this`, and `they` without an explicit antecedent.
- Use `must` for enforced requirements, `should` for recommendations, and `may` for permission.
- Do not use `complete`, `approved`, `validated`, or `ready` without naming the controller state or evidence.
- Use `blocked` only for a valid corrected request that cannot execute safely; use `INPUT_REQUIRED` for recoverable Operator input.

## Punctuation and formatting

- Use sentence case for headings.
- Use a colon before a displayed command or list when the preceding clause is complete.
- Use an en dash only for prose ranges; preserve the hyphen in canonical Scripture scope syntax and command values.
- Use backticks for commands, paths, filenames, identifiers, status values, and schema fields.
- Use fenced `bash` blocks for executable commands and fenced `text` blocks for non-executable output.
- End complete list items with punctuation when any item in the list is a complete sentence.
- Avoid decorative emphasis, repeated warnings, and unexplained abbreviations.

## Commands and placeholders

- Use the canonical pattern `sage [global options] <domain> <action> [options]`.
- Place `--settings`, `--json`, `--no-prompt`, and the mutually exclusive `--quiet`, `--verbose`, or `--debug` option before the domain.
- Use `self_check` only as the canonical `sage task create` operation value; use `self-check` for the BIC shortcut and prose headings.
- Use `--id` for transaction recovery and `--selector` for BIC-local generation verification. Automatic BIC-to-SAW generation handoff is not a current SAGE workflow concept.
- Use uppercase underscore placeholders consistently, for example `FILE.yml`, `TASK_ID`, `TRANSACTION_ID`, `REVIEW_ID`, and `GRAMMAR_REVIEW_ID`.
- Do not mix hyphenated and underscored placeholders for the same value.
- Show only commands supported by the current parser or clearly label a command as proposed or historical.

## Naming: hyphen versus underscore

Use the separator required by the interface layer; do not standardize every identifier to one separator.

- Use lowercase hyphenated names for CLI domains, actions, and options, for example `reset-state`, `self-check`, and `--grammar-override-id`.
- Use lowercase hyphenated directory names for SAGE Skills, for example `bic-self-check` and `sage-command-router`.
- Use uppercase hyphenated filenames for current Markdown documents, for example `PROJECT-TREE.md` and `BIC-CHEAT-SHEET.md`. Preserve conventional filenames such as `README.md` and `VERSION`.
- Use lowercase `snake_case` for Python modules, functions, variables, and internal operation values, for example `natural_language.py`, `reset_project_state.py`, and `self_check`.
- Use lowercase kebab-case for SAGE-owned configuration, policy, profile, registry, manifest, and schema filenames. Append the semantic suffix where applicable, for example `model-policy.yml`, `skills.json`, `run.json`, and `job.schema.yml`.
- Use JSON for governed facts, registries, pins, manifests, indexes, receipts, findings, and generated state; use YAML for editable configuration, policy, workflow, grammar/profile guidance, and current SAGE schema specifications.
- Use `snake_case` for SAGE-owned YAML and JSON fields unless an external standard requires another form.
- Use uppercase underscore placeholders, for example `TASK_ID`, `REVIEW_ID`, and `GRAMMAR_REVIEW_ID`.
- For SAGE-owned **composite human-visible identifiers**, use `_` between hierarchy levels and `-` inside one level. Do not repeat an already implied workflow prefix in child components. Example: `SAW_PAPCV-A3A03DAC_QA-PH-99846F75_0001`, not `SAW-SAW-PAPCV-A3A03DAC-SAW-QA-PH-99846F75-0001`.
- Preserve SAGE Project IDs, language tags, USFM book codes, status values, external filenames, and historical identifiers exactly. Examples include `idKKHv0`, `ukrNPUv0`, `3JN`, `FINALIZED`, and `normalized-findings.json`.
- Never change `_` to `-`, or `-` to `_`, inside a literal command value, schema field, path, project ID, status, or filename merely for visual consistency.

## Python maintenance standard

Every maintained `.py` file must remain safe for human review and editing.

- Begin every module with a concise purpose docstring.
- Give every class, function, method, nested function, and test procedure a concise docstring that explains intent, boundary, or invariant.
- Use comments for non-obvious decisions, security boundaries, compatibility constraints, and reasons for deliberately unusual code.
- Do not add comments that only repeat the next statement or restate Python syntax.
- Keep one Python statement per line; do not compress imports, branches, or entry points with semicolons.
- Use descriptive names and explicit intermediate values where they make validation, path safety, state transitions, or evidence routing easier to audit.
- Keep operator-facing strings compliant with this SAGE system grammar. Preserve exact commands, status values, schema fields, filenames, and accepted natural-language synonyms where compatibility requires them.
- Update a procedure docstring whenever its contract, side effects, accepted state, or failure behavior changes.
- Remove stale `TODO`, `FIXME`, debugging, generated bytecode, coverage, cache, and editor artifacts before validation or packaging.

See [File Naming and Serialization](FILE-NAMING-AND-SERIALIZATION.md) for file/format ownership and [Python maintenance](../maintenance/PYTHON-MAINTENANCE.md) for the edit checklist and audit commands.

## Status and remediation terminology

Use these exact terms:

- `INPUT_REQUIRED`: recoverable or missing Operator input;
- `ABANDONED`: the Operator cancelled;
- `READY_WITH_ACTIONS`: execution may continue while review attention is logged;
- `READY_WITH_LIMITATIONS`: execution is permitted with declared optional limitations;
- `BLOCKED`: the valid corrected scope cannot execute safely.

Do not call a typo, omitted optional value, or unconfirmed automatic setting a failure when SAGE can request a correction.

## Natural-language routing terminology

- `natural-language request`: the exact Operator wording;
- `interpretation`: a ranked mapping to registered SAGE commands;
- `most likely command`: the strongest safe proposal shown as option 2;
- `canonical command`: the exact command submitted to the authoritative parser;
- `advisory-only`: analysis with no project execution or state change;
- `unsupported operation`: no command can be recommended safely.

Do not offer `freestyle execution` as an operating mode. When no command is executable, option 2 may show related supported operations, but it must not imply execution.

## Historical material

Files named `ORIGINAL-*`, promotion reports, historical conversion inputs, and directories explicitly named `historical-*` are retained for traceability. Historical spelling, commands, paths, version labels, and test counts must not be copied into current operating instructions.

## Versification authority grammar

- **CANONICAL VRS**: `org.vrs`, the canonical coordinate mapping target.
- **DEFAULT PROJECT VRS**: `eng.vrs`, the English/KJV-style numbering assumed when a translation Project states no other configured base VRS.
- **DECLARED PROJECT VRS**: a configured base/custom VRS explicitly supplied by Project metadata or approved by the operator; it overrides the default.
- **SAW VRS ADVISORY**: a coordinate discrepancy that is invalid under the effective Project VRS but specifically valid/explained under the default Project VRS. It is reported and retained but does not block SAW execution.
- A genuine coordinate omission under the default Project VRS is not an advisory and may still block.
## Beta path normalization

- Generated path grammar: never emit identical adjacent directory segments. For polished SAW output, use `localdata/reports/<job-id>/<BOOK>/` for a whole-book scope; add a distinct scope directory only when it contributes additional coordinates. The same non-duplication rule applies to Job `report_data/`.
