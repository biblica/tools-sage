# SAGE architecture — RC7.04

## 1. Controller boundary

```text
Operator
  -> SAGE CLI / Control Center
  -> SAGE Project Inventory
  -> BIC / SAW Job
  -> deterministic parsers + VRS + semantic indexes
  -> Run + immutable governed task + hashes
  -> provider registry + build policy
  -> enabled executor (RC7.04: Codex only)
  -> structured response gate
  -> deterministic validation / transaction / reporting
```

A provider never becomes the workflow controller. SAGE remains the operating-system parent process during normal use:

```text
shell -> SAGE -> Codex login / governed Codex subprocess
```

Bare interactive `codex` is not a SAGE setup/runtime transition.

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

Adapters live under `core/sage_core/executors/`. `core/sage_core/build_policy.py` determines which implemented adapters may execute in the current release.

RC7.04 enables Codex only. Ollama/LM Studio remain provisionable but execution-disabled. Future providers can be added behind the same abstraction. No OpenAI API-key path exists.

## 5. Paratext discovery and external Scripture-project layer

The normal Paratext/PTLite binding begins with one configured **Paratext Projects root**. Selecting that root immediately builds a machine-local discovery catalogue from direct child folders with valid `settings.xml`. The catalogue preparses `settings.xml`, `canons.xml`, top-level `.SFM`, `custom.vrs`, and Project-code metadata; normal menus use the catalogue rather than rescanning files. Operator filters are FB / NT / Portions and Language. `<Other location>` may bind one Project outside the root after the same validation.

Every SAGE Project records its storage location and maximum access capability. A Job binding determines effective access:

```text
READ_ONLY_SCRIPTURE
  read  .SFM / .VRS    (case-insensitive)
  write none

READ_WRITE_TARGET
  read  .SFM / .VRS
  write .SFM only
  effective only for an explicitly authorised BIC TARGET Job binding
```

`.VRS` is always read-only. SOURCE, DONOR, REFERENCE, WIP and original-language bindings are always externally read-only. Other Paratext/PTLite files are outside the SAGE external-file boundary.

Base VRS resolution prefers the matching project-local `.VRS`, then the separately configured base VRS root. SAGE fails closed if required versification cannot be resolved. Descriptive `custom.vrs` comment metadata is reported only when actually present and is never promoted into executable authority.

### Governed OL aliases

`@GRK` and `@HEB` are separate governed resources with stable machine binding IDs `GRK` and `HEB`; they are not normal translation SAGE Project Inventory entries. Their default resource slots live under `resources/scripture/original-language/`. Explicit operator overrides may select a recognised `grcSRCv#` / `hboSRCv#` Paratext candidate or another local resource. Runtime provenance records the selected source/path/books. No discovered Paratext iteration automatically replaces the configured OL authority.

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

SAW WIP uses lifecycle `UNDER_REVIEW`, but lifecycle does not grant write permission. SAW compiles bounded WIP and REFERENCE evidence, local triage, findings, and reports without modifying external Scripture. Normal QA is: deterministic preflight/structural triage -> conditional structural adjudication -> required translation/meaning QA -> conditional selective OL adjudication -> deterministic merge/coverage/finalisation. OL is resolved from the configured SAW Job binding, never a global role scan. Focused Check and standalone OL Review remain separate bounded operations. SAW emits plain Operator note text and never Paratext Notes XML.

## 9. Provider-neutral task boundary

`core/sage_core/llm_tasks.py` resolves a task manifest, re-hashes authorised reads, assembles a sealed prompt, invokes an enabled executor, validates the response envelope, and materialises only allowlisted task outputs. Active mode is `SAGE_GOVERNED_TASK_V1`.

## 10. State and transaction ownership

SAGE owns SAGE Project Inventory state, Job configuration, active Job pointers, Runs, evidence receipts, semantic freshness, BIC memory/generations, findings, journals, and transactions. A writable external BIC TARGET is still written only through the governed SELF-CHECK commit boundary.

## 11. Scope-aware readiness

Readiness and evidence validation are evaluated for the exact workflow, operation, bound Projects, book, and verse range. A defect outside that exact scope cannot deny the task.

## 12. Local-first semantic architecture

Deterministic parsing, indexing, retrieval, arithmetic, routing, validation, and reporting remain local. AI calls are reserved for contextual linguistic or interpretive judgement. RWC/FLEx/Combine/SEMDOM resources are evidence layers; SEMDOM classification is not translation authority.
