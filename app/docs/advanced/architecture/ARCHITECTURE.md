# SAGE architecture — v0.02alpha1

## 1. Controller boundary

```text
Operator
  -> SAGE CLI / Control Center
  -> SAGE Project Inventory
  -> BIC / SAW Job
  -> deterministic parsers + VRS + semantic indexes
  -> Run + immutable governed task + hashes
  -> provider registry + build policy
  -> enabled executor (v0.02alpha1: Codex only)
  -> structured response gate
  -> deterministic validation / transaction / reporting
```

A provider never becomes the workflow controller. SAGE remains the operating-system parent process during normal use:

```text
shell -> SAGE -> Codex login / governed Codex subprocess
```

Bare interactive `codex` is not a SAGE setup/runtime transition.

### Filesystem ownership

SAGE has two ownership domains. `SAGE/` is immutable-at-runtime Git-controlled Core. `localdata/` is
persistent local/operator state and defaults to a sibling of `SAGE/`. All path construction is
centralized through the storage contract in `system/src/sage/storage.py`.

- Core: launchers, application code, schemas, defaults, approved localization/profile/template/Skill
  resources, tests, tools, and documentation.
- Visible localdata: Projects, Jobs, local/candidate resources, plugins, reports, and exports.
- Hidden `localdata/.system`: mutable configuration overlays, machine state, controller Job state,
  workflow runtime data, indexes, caches, locks, transactions, logs, diagnostics, temp data, and the
  managed Python environment.

Normal runtime operation must not write into Core. `ecosystem.yml` is a shipped baseline; mutable
workstation/operator settings are overlaid from localdata. Only reviewed/tested/approved resources
are allowed into Core. See `STORAGE-AND-CORE-BOUNDARY.md`.

No launcher depends on the shell starting directory. Each resolves Core relative to its own location,
then resolves localdata by explicit `--data-home`, environment, persisted pointer, or sibling default.
The same contract applies on Windows, macOS, and Linux.

## 2. Project, Job, Run, Task

- **Project**: one Scripture/Paratext/PTLite Project identity available to SAGE. Adding a Project to SAGE is role-neutral.
- **Job**: one persistent BIC or SAW binding of SAGE Projects. Workflow roles are assigned here.
- **Run**: one bounded operation and Scripture scope under one Job.
- **Task**: one immutable governed AI work unit inside one Run.

Canonical Job names are binding-derived and are also safe directory names:

```text
BIC_<SOURCE>-<DONOR>-<TARGET>
SAW_<WIP>-<REFERENCE>
```

## 3. Independent workflows

```text
BIC: SOURCE + DONOR -> TARGET
SAW: WIP + REFERENCE (+ OL) -> findings
```

BIC and SAW have no direct interface, automatic handoff, role conversion, or shared Run lifecycle. They share controller infrastructure and may independently bind the same SAGE Project where policy permits.

## 4. Provider layer

Adapters live under `system/src/sage/executors/`. `system/src/sage/build_policy.py` determines which implemented adapters may execute in the current release.

v0.02alpha1 enables Codex only for governed BIC/SAW execution. Ollama is also a
host-local runtime for the optional capability-restricted admin assistant; that
path cannot acquire workflow execution authority. Future providers can be added
behind the same abstraction. No OpenAI API-key path exists.

## 5. Paratext discovery and external Scripture-project layer

The normal Paratext/PTLite binding begins with one configured **Paratext Projects root**. Selecting that root immediately builds a machine-local discovery catalog from direct child folders with valid `settings.xml`. The catalog preparses `settings.xml`, `canons.xml`, top-level `.SFM`, `custom.vrs`, and Project-code metadata; normal menus use the catalog rather than rescanning files. Operator filters are FB / NT / Portions and Language. `<Other location>` may bind one Project outside the root after the same validation.

Every SAGE Project records its storage location and maximum access capability. A Job binding determines effective access:

```text
READ_ONLY_SCRIPTURE
  read  .SFM / .VRS    (case-insensitive)
  write none

READ_WRITE_TARGET
  read  .SFM / .VRS
  write .SFM only
  effective only for an explicitly authorized BIC TARGET Job binding
```

`.VRS` is always read-only. SOURCE, DONOR, REFERENCE, WIP and original-language bindings are always externally read-only. Other Paratext/PTLite files are outside the SAGE external-file boundary.

Scripture files remain UTF-8 USFM/SFM at rest and their exact bytes remain the source-of-record provenance. Every bounded Scripture comparison input—BIC SOURCE, staged TARGET candidate, SAW REFERENCE, WIP, context, and routed GRK/HEB—is compiled deterministically to full governed USJ. At provider serialization, `SAGE_SCRIPTURE_SLICE_V1` projects that same bounded USJ to exact `content` plus scope/book/source-hash metadata and omits duplicated parser/verse-record internals. Generated BIC candidates and governed Paratext write-back remain USFM. No Scripture wording is summarized by the projection.

Base VRS resolution prefers the matching project-local `.VRS`, then the separately configured base VRS root. SAGE fails closed if required versification cannot be resolved. Descriptive `custom.vrs` comment metadata is reported only when actually present and is never promoted into executable authority.

### Governed OL aliases

`@GRK` and `@HEB` are separate governed resources with stable machine binding IDs `GRK` and `HEB`; they are not normal translation SAGE Project Inventory entries. Their bundled, read-only USFM sources live under `system/resources/scripture/original-language/` and remain part of the distribution. SAGE compiles bounded OL evidence deterministically to USJ for comparison while retaining the source file and hash as authority provenance. Explicit operator overrides may choose a recognized `grcSRCv#` / `hboSRCv#` Paratext candidate or another local resource. Runtime provenance records the chosen source/path/books. No discovered Paratext iteration automatically replaces the configured OL authority.

## 6. Project short-name grammar

Paratext project short names are limited to eight characters. SAGE parses the governed convention by case and position:

```text
<lowercase-language-code><UPPERCASE-project-abbreviation><lowercase-type><iteration-digit>
```

Common layouts are `xxxYYYz0` and `xxYYYYz0`; shorter conforming names such as `idKKHv0` and `usNIVv2` are valid. The leading language component is usually an ISO-639-3 code, while established two-character codes remain accepted. `v` means translation/version and `x` means backtranslation; unknown type codes require review rather than rejection.

Iteration `0` is the initial creation (“something from nothing”) lifecycle state. Iteration increases cumulatively and does not reset when Scripture scope expands. Scope is detected from Scripture books and is never inferred from iteration. Project-code type never determines a workflow role.

## 7. BIC evidence continuity

Each BIC Job has exactly one bound SOURCE resource, one bound DONOR resource, and one bound TARGET resource. Job identity is `SOURCE + DONOR + TARGET`; TARGET storage may be internal or externally mapped without changing cardinality. INSPECT, REWRITE, and SELF-CHECK use one immutable evidence cohort containing SOURCE/DONOR fingerprints, scope, VRS evidence, semantic-index evidence, and grammar-profile identity. If an external resource changes, dependent stages cannot silently continue.

Conditional OL remains governed by the protected REWRITE policy. If REWRITE uses it, SELF-CHECK inherits byte-identical OL evidence from the predecessor; otherwise SELF-CHECK receives none.

## 8. SAW read-only analysis

SAW WIP uses lifecycle `UNDER_REVIEW`, but lifecycle does not grant write permission. SAW compiles bounded WIP and REFERENCE evidence, local triage, findings, and reports without modifying external Scripture. Reference Text Comparison (RTC) is: deterministic preflight/structural triage -> conditional structural adjudication -> required Reference Text Comparison (RTC) -> conditional selective OL adjudication -> deterministic merge/coverage/finalization. OL is resolved from the configured SAW Job binding, never a global role scan. STC is an independent WIP-to-primary-OL correspondence operation with no REFERENCE dependency; Targeted Check and standalone Original-Language Review remain separate bounded operations. SAW emits plain Operator note text and never Paratext Notes XML.

## 9. Provider-neutral task boundary

`system/src/sage/llm_tasks.py` resolves a task manifest, re-hashes controller governance inputs and authorized model reads, assembles the smallest governed provider handoff for the operation, invokes an enabled executor, validates the response, and materialises only allowlisted task outputs. Active mode is `SAGE_GOVERNED_TASK_V1`. `PROCESS_CONTROL` governance inputs remain immutable/hash-verified locally but are not automatically serialized to the model; the provider receives the deterministic ACT Process Brief plus evidence it must actually inspect.

The task boundary also enforces the canonical **LOCAL EVIDENCE BOUNDARY**. Every allowed read carries exactly one evidence class: `AUTHORIZED_CONTENT_EVIDENCE`, `AUTHORIZED_LEXICAL_EVIDENCE`, `PROJECT_INDEX_EVIDENCE`, `DERIVED_EVIDENCE`, `STRUCTURAL_EVIDENCE`, `SUBJECT_TEXT`, `LINGUISTIC_COMPETENCE_RULES`, or `PROCESS_CONTROL`. Missing/unrecognized classes fail closed. Routing proves integrity only after authority/provenance has been established; allowlisting alone never creates content authority.

Model recall/pretraining, external Scripture/translations/lexicons/commentary, web/search, and unstated facts are prohibited as task evidence. The only external model capability admitted by the contract is **GENERAL LINGUISTIC COMPETENCE** in orthography, morphology, grammar, and syntax. It may parse, validate, transform, or express locally supported material but may not introduce propositions, lexical meanings, translation equivalents, Scripture content, interpretation, or cultural/historical claims.

Derived evidence is not a new authority class: it inherits the authority and restrictions of its provenance. SAW predecessor packets additionally bind to the same Job, Run, WIP, REFERENCE, and WIP/REFERENCE fingerprints. BIC memory routed into later tasks must originate from governed INSPECT evidence for the same Job; generic lexicon imports remain reviewable data but cannot be promoted into Job content evidence.

SAW response contracts are stage-specific and semantic-only at the provider boundary; SAGE locally injects deterministic identity, coordinate coverage, task fingerprints, work-unit receipts, and required checks before canonical findings validation. BIC conditional OL uses a separate one-challenge/one-verse micro-contract and locally merges any bounded verse delta into the existing rewrite, so conditional adjudication never regenerates the complete REWRITE output set. Exact prompt/schema size and raw-versus-projected evidence savings are recorded per phase in the execution receipt.

## 10. State and transaction ownership

SAGE owns SAGE Project Inventory state, Job configuration, active Job pointers, Runs, evidence receipts, semantic freshness, BIC memory/generations, findings, journals, and transactions. A writable external BIC TARGET is still written only through the governed SELF-CHECK commit boundary.

## 11. Scope-aware readiness

Readiness and evidence validation are evaluated for the exact workflow, operation, bound Projects, book, and verse range. A defect outside that exact scope cannot deny the task.

## 12. Local-first semantic architecture

Deterministic parsing, indexing, retrieval, arithmetic, routing, validation, and reporting remain local. AI calls are reserved for judgments supported by the sealed local evidence plus the narrow linguistic-competence exception above. RWC/FLEx/Combine/SEMDOM resources are governed project-index evidence layers only after explicit local import/merge and project binding; locality by itself does not grant authority. Project indexes are never independent Scripture or translation authority.
