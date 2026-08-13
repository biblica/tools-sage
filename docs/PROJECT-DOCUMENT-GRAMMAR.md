# Project documentation grammar

This document governs current SAGE English documentation, generated prompts, Skill instructions, help text, comments, reports, and Operator-facing prose. It does not override a language-specific Scripture project grammar.

## English spelling standard

Use British English with the SAGE project convention `-ise` and `-isation`.

Preferred forms include:

- `analyse`, `authorise`, `authorised`, `authorisation`;
- `behaviour`, `capitalisation`, `finalise`, `finalised`;
- `initialise`, `initialisation`, `normalise`, `normalisation`;
- `organisation`, `recognise`, `recognised`, `standardise`;
- `judgement` in general prose;
- `licence` as a noun and `license` as a verb;
- `artefact` in prose.

Preserve exact command names, identifiers, schema fields, status values, filenames, external-standard terms, and quoted historical text even when their spelling differs. Examples include `workspace initialize`, `FINALIZED`, `normalization`, `--keep-test-artifacts`, and `self_check`.

## Canonical terminology

- Product: `SAGE`.
- Release: `RC7.04` or `v0.01-rc7.04` when the version matters; otherwise use `current release candidate`. Historical documents may retain their original release label.
- Workflows: `BIC` and `SAW`.
- Execution mode: `SAGE_GOVERNED_TASK_V1`.
- Human role: `Operator`.
- Formal role identifiers: backticked uppercase, for example `CONTENT_SOURCE`.
- BIC prose roles: uppercase `SOURCE`, `DONOR`, and `TARGET` when naming the three authority roles. `REFERENCE` is prohibited for the BIC donor.
- SAW prose roles: uppercase `WIP` and `REFERENCE` when naming the translation under analysis and its authorised LWC benchmark. The formal identifiers are `WIP` and `REFERENCE`; do not substitute unrelated role names in current material.
- Original language: use `original-language` adjectivally; introduce `OL` only after the full term.
- Task controls: `ACT.md` and `task-manifest.json`.
- Project context: every governed analytical task belongs to one persistent Job and one bounded Run built from SAGE Projects. Direct commands and natural-language routing must not create Job-less or Run-less BIC/SAW tasks.
- Project reporting-language settings: a SAGE Project may store a `reporting` override, but that setting controls human-output languages only. It does not make the Project an owner or storage location for final workflow reports.
- Job report ownership: use `Job report catalogue` for `jobs/<tool>/<job-id>/reports/<BOOK>/`. The `<job-id>` segment identifies the owning Job, not a Project. Final action reports and Operator note text are Job-owned outputs batched from finalised Runs.
- Run report provenance: Run directories retain Tasks, validation receipts, stage aggregates, and machine plans. They do not own the final Job report catalogue.
- Report-ownership wording: for final BIC/SAW workflow outputs, do not say `Project report`, `Project reports folder`, `Project-owned report`, or `Run report folder`. Use `Project reporting-language override` for language configuration and `Job report catalogue` for final storage.
- Model-facing task resource identity: use `resource_bindings` with canonical BIC `SOURCE`/`DONOR`/`TARGET` or SAW `WIP`/`REFERENCE` roles. Internal projection fields `output_project` and `contemporary_source` may appear in task packets, but `resource_bindings` and the owning Job define authority semantics.
- BIC operator wording: one bound `SOURCE` resource, one bound `DONOR` resource, and one bound `TARGET` resource per BIC Job. TARGET storage location is not a second TARGET.
- Machine cardinality vocabulary: use only `exactly_one`, `zero_or_one`, `one_or_more`, `zero_or_more`, and `exactly_one_of` for schema cardinality. Do not use `exact`, `single`, `required`, or prose `one` as machine cardinality substitutes.
- BIC machine cardinality: `SOURCE=exactly_one`, `DONOR=exactly_one`, `TARGET=exactly_one`; TARGET storage is `exactly_one_of(SAGE_INTERNAL, PARATEXT_PROJECT)`.
- Original-language bindings: Operator prose says `configured Greek resource` / `configured Hebrew resource`; machine cardinality is `zero_or_one` for each. When an OL task is routed, exactly one applicable bound OL resource is required for that task.
- Grammar-profile wording: Operator prose says `selected SOURCE grammar profile`, `selected TARGET grammar profile`, or `selected WIP grammar profile`; machine selection is `exactly_one_active`.
- Versification wording: Operator prose says `resolved effective VRS`; machine cardinality is `exactly_one` effective VRS per governed resource/Run context after resolution.
- SAW Normal QA: one public operation containing conditional `STRUCTURAL_ADJUDICATION`, required `TRANSLATION_AND_MEANING_QA`, and conditional `SELECTIVE_OL_ADJUDICATION` model stages around deterministic preflight/finalisation.
- SAW note output: use `Operator note text` or `plain-text issue blocks`; never describe SAGE as creating Paratext Notes XML.
- Scripture format: `USFM`.
- Versification: define `VRS` at first use for a general audience.
- Natural-language interface: `natural-language request`, `interpretation`, `canonical command`, and `advisory-only`.

## Review versus flow

Use `review` for an examination, assessment, adjudication, or governed human decision about evidence, text, configuration, output, or readiness. A review has a reviewer, review evidence, findings, a decision, or an approval state.

Use `flow` for an ordered sequence of stages, commands, transitions, or information movement. A flow has an entry point, ordered steps, branches, state transitions, and an exit condition.

- Use `process flow`, `workflow`, `operation order`, or `execution flow` when describing how work proceeds.
- Use `human review`, `grammar review`, `original-language review`, `consistency review`, or `output review` when describing examination or judgement.
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

Use separate configuration terms for the two human-output channels:

- `logs_and_reports`: operational logs, non-JSON command summaries, INIT and validation reports, status summaries, errors, and remediation messages;
- `translation_challenges`: concise linguistic challenge summaries, evidence, alternatives, and actions.

A bilingual rendering is one canonical record displayed in two languages; never double the challenge or event count. Preserve commands, codes, project IDs, Scripture coordinates, candidate forms, paths, and hashes exactly. List only material translation challenges individually, consolidate repeated causes, and aggregate minor or automatically resolved matters. Put diagnostic vectors and hashes in machine records, not normal human reports.

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

Use the separator required by the interface layer; do not standardise every identifier to one separator.

- Use lowercase hyphenated names for CLI domains, actions, and options, for example `reset-state`, `self-check`, and `--grammar-override-id`.
- Use lowercase hyphenated directory names for SAGE Skills, for example `bic-self-check` and `sage-command-router`.
- Use uppercase hyphenated filenames for current Markdown documents, for example `PROJECT-TREE.md` and `BIC-CHEAT-SHEET.md`. Preserve conventional root filenames such as `README.md` and `HELP.md`.
- Use lowercase `snake_case` for Python modules, functions, variables, and internal operation values, for example `natural_language.py`, `reset_project_state.py`, and `self_check`.
- Use `snake_case` for SAGE-owned YAML and JSON schema fields unless an external standard requires another form.
- Use uppercase underscore placeholders, for example `TASK_ID`, `REVIEW_ID`, and `GRAMMAR_REVIEW_ID`.
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
- Keep operator-facing strings compliant with this project grammar. Preserve exact commands, status values, schema fields, filenames, and accepted natural-language synonyms where compatibility requires them.
- Update a procedure docstring whenever its contract, side effects, accepted state, or failure behaviour changes.
- Remove stale `TODO`, `FIXME`, debugging, generated bytecode, coverage, cache, and editor artefacts before validation or packaging.

See [Python maintenance](PYTHON-MAINTENANCE.md) for the edit checklist and audit commands.

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
