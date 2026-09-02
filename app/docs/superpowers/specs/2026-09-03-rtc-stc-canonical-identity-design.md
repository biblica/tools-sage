# RTC/STC Canonical Identity Design

## Status

Approved in conversation on 2026-09-03.

## Purpose

SAGE exposes Reference Text Comparison (RTC) and Source Text Correspondence
(STC) as separate primary workflows, but both still inherit the retired
Scripture Analysis Workbench (`SAW`) identity from their shared runtime. That
identity currently leaks into dialogs, validation messages, CLI help, reports,
Skill instructions, generated ACT tasks, configuration prose, documentation,
and persisted artifacts.

This change makes RTC and STC canonical throughout new work while preserving a
read-only compatibility path for existing sealed artifacts that use the legacy
`saw` identity.

## Canonical terminology

Current SAGE surfaces use these names:

- `RTC` / `Reference Text Comparison`
- `STC` / `Source Text Correspondence`
- `Targeted Check`
- `Original-Language Review`
- `analysis` or `Scripture analysis` when a neutral umbrella term is required

`SAW` is not a current product, workflow, menu, report, or model-instruction
term. It may appear only in code and documentation whose sole purpose is to
recognize, explain, or migrate a legacy stored identifier.

## Identity boundary

New operator Jobs already use `tool: rtc` or `tool: stc`; new Runs, plans,
manifests, findings, reports, execution events, and generated task instructions
must retain that identity instead of serializing `workflow: saw`.

The shared analysis implementation may use neutral internal abstractions, but
must not use `saw` as the current identity. Shared helpers and state are named
`analysis`; operation-specific output uses `rtc` or `stc`.

New identifiers follow these rules:

- workflow values: `rtc` or `stc`
- plan type: `RTC_COMPOSITE` for composite RTC plans
- task, plan, finding, and report prefixes: `RTC` or `STC`
- schema/format descriptions: `ANALYSIS_FINDINGS_2.0` where shared, otherwise
  operation-specific
- resource labels: `RTC WIP`, `RTC REFERENCE`, `STC WIP`, `OL GRK`, or `OL HEB`
- reason codes: operation-specific `RTC_*` or `STC_*`; neutral shared failures
  use `ANALYSIS_*`

## Legacy compatibility

Existing governed data is immutable. SAGE therefore continues to read legacy
values and filenames, including:

- `workflow: saw`
- `tool: saw`
- `SAW_RTC_COMPOSITE`
- `SAW_*` reason codes already stored in diagnostics or execution events
- legacy `saw-*` Skill IDs and `system/config/workflows/saw` profile references
- legacy plan, task, schema, and findings filenames
- legacy Job storage below `localdata/work/jobs/saw`

Compatibility is one-way:

1. Readers recognize legacy values and normalize them to RTC or STC using the
   stored operation.
2. Existing sealed manifests, checksums, reports, and events are never rewritten.
3. New writers never emit a legacy `SAW` identity.
4. Legacy records are identified as `Legacy RTC/STC compatibility data` only on
   maintenance or diagnostic surfaces where that distinction is necessary.

The compatibility code is isolated and explicitly named `legacy_saw`; ordinary
execution must not branch on raw `saw` strings outside that boundary.

## Runtime and configuration

RTC and STC receive canonical workflow profiles. Shared policy is factored into
neutral analysis helpers rather than copied through string substitutions.
Configuration loading accepts the legacy profile only while opening an old
sealed Job or Run.

The CLI accepts canonical `rtc` and `stc` workflow values for new work. Legacy
`saw` commands remain available only through a hidden compatibility parser or
loader and must not appear in normal help, guidance, or menus.

Targeted Check and Original-Language Review keep their operation names. Their
Skill prose and generated prompts use neutral analysis terminology; any legacy
Skill ID required to validate an old hash remains resolvable through the
compatibility registry.

## Operator and model-facing surfaces

The following current surfaces must contain no standalone `SAW` term:

- Main, Job, maintenance, recovery, and resource menus
- errors, confirmations, progress text, and TUI modal content
- CLI headings, help, and remediation guidance
- current RTC/STC reports and report localization
- generated `ACT.md` and provider assignment text
- active Skill titles, descriptions, instructions, and agent metadata
- current configuration comments and documentation

Historical source prompts, frozen evaluation fixtures, release archaeology, and
already generated Job/Run data are not rewritten. If linked from current docs,
they must be labeled historical.

## Progress display

An RTC Run may apply more than one internal stage to the same review portions.
The current display makes those stages look like duplicate or concurrent work
because it appends each `Review portion` line and resets the portion counter
without showing the stage.

Interactive output uses one replaceable live row:

```text
Stage:             Reference Text Comparison
Current portion:   1/2 — 1CH 5:1-6:19   /
```

When the stage changes, the fixed `Stage` value and the same live progress row
are replaced. Previous work-unit rows do not remain below the Run header.

Non-interactive output does not render spinner frames or one line per portion.
It emits a stage milestone when the stage changes and a final completion
summary. Per-unit detail remains available in governed diagnostics and execution
events.

Nested structural or original-language cases are represented in the same live
row, for example:

```text
Stage:             Selective OL adjudication
Current source check: 2/5 — 1CH 5:34 (portion 1/2)
```

The polished report never contains transient progress lines.

## Errors and reports

Errors derive their public label and new reason-code prefix from the owning
canonical workflow. A shared exception may retain neutral implementation data,
but the displayed message must say RTC, STC, or analysis as applicable.

Current reports use the same operation identity as their Job. Versification
advisories say that coordinate differences did not block RTC or STC execution.
Aggregate headings and report titles never say `SAW Aggregate` or `SAW Action
Report`.

## Tests and acceptance criteria

The migration is accepted when all of the following are true:

1. A new RTC Job produces only `rtc` workflow identities and RTC terminology in
   its Run artifacts, report, generated ACT, errors, and progress display.
2. A new STC Job produces only `stc` workflow identities and STC terminology in
   the same surfaces.
3. An existing sealed legacy `saw` RTC or STC Run remains readable and resumable
   without changing any sealed input.
4. Interactive progress occupies one live row and identifies stage transitions.
5. Captured/non-interactive progress does not accumulate one line per work unit.
6. Current menus, CLI help, current docs, active Skills, prompts, ACT templates,
   and report templates pass a terminology audit that rejects standalone `SAW`.
7. Explicit compatibility files, historical source material, frozen fixtures,
   legacy data, and stored historical reason codes are allowlisted rather than
   silently rewritten.
8. Schema validation, package validation, compilation, and the complete automated
   test suite pass.

## Non-goals

- Rewriting or resigning existing sealed task manifests
- Renaming historical release documents or original source prompts
- Re-enabling paused TUI workflow actions before 0.02beta
- Changing RTC/STC evidence policy, versification behavior, bridge handling, or
  analytical conclusions
