# NCA Number Usage Report and Optional Stylesheet Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement and review these independently testable tasks.

**Goal:** Run NCA without an imported Number Style Profile and report observed numeric presentation, retaining optional approved-rule checking.

**Architecture:** An absent stylesheet is sealed explicitly as absent in Job/Run/task provenance; it never creates a fabricated approved guide. Numeric extraction remains available without style conventions. The usage report derives from validated, separately identified body/heading/footnote extractions and retains coverage limitations. Existing configured guides and historical Runs retain their validation contracts.

**Tech Stack:** Existing Python 3.10-compatible SAGE modules, pytest, YAML/JSON and Markdown; no new dependencies or provider phases.

**Spec:** User-approved design in this session: descriptive usage report with examples and mixed usage, optional stylesheet for approved rules.

## Global constraints

- No invented normative style rules; mixed usage is an observation requiring context, not an automatic error.
- Preserve exact numeric values, surface spans, protected bridge identity and note identity.
- No additional report-generation model calls. Existing presentation extraction supplies note and heading data.
- Missing/partial extraction remains visible; report scope never expands the Run.
- Existing registered doubtful-reading and footnote policies remain unchanged by this task.

## Task 1: Optional stylesheet lifecycle

- [x] Add failing no-style Job/Run/task and menu tests; retain explicit-invalid and sealed-style mutation tests.
- [x] Update style resolution, Job bindings, policy snapshots, task manifests, menu and CLI to accept explicit absence. An omitted selector means no stylesheet; menu offers continue without one.
- [x] Permit extraction with no parsing conventions. No-style rule assessment remains unassessed; do not mark style rules as passed.
- [x] Verify configured and absent styles, resume, and task preparation.

## Task 2: Auditable usage report

- [x] Test grouped body/heading/footnote evidence, mixed forms, partial extraction, protected bridges and escaped report text.
- [x] Retain validated note extractions in optional grouped-result evidence, with exact note identity and span checks; preserve historical v2 loading.
- [x] Derive usage counts and examples from admitted expressions only, grouped by stream and WIP chapter. Surface words/digits, punctuation, kind and unit as observations.
- [x] Render a Number Usage Report section in the existing canonical report, without creating an unapproved stylesheet or additional model phase.
- [x] Validate nullable stylesheet provenance and update report labels and current operator documentation.

## Task 3: Integration and release verification

- [x] Run NCA regressions and affected shared Job/report/menu checks.
- [x] Update vanilla inventory; run package, documentation, schema and source audits in a clean full-tree stage.
- [x] Independent review, address findings, commit the verified change.

## Verification

- Final clean-source NCA suite: 899 passed.
- Package, release-builder, documentation and schema tests: 77 passed.
- Shared Job, menu, snapshot and localization tests: 45 passed.
- Schema validation: 52 schemas PASS; source audit PASS with no warnings.
- Independent review: historical replay and exact pipe escaping findings resolved; final focused review checks 55 passed.
- Python 3.10 grammar and whitespace checks passed. No live provider calls were made.

Ruling: retain the historical `presentation_consistency` machine switch while labeling it Number usage and presentation. This preserves CLI and sealed check-policy compatibility. The report is a section in the existing canonical NCA report, using accepted parent and note extractions without a second report-generation model phase.
