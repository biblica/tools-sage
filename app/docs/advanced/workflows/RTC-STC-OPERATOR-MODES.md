# RTC/STC Operator workflows

This document defines the two canonical read-only analysis workflows for the current Beta. RTC and STC have separate Jobs, bindings, Skills, menus, Runs, reports, and reason-code identities.

## Reference Text Comparison (RTC)

Use RTC for a systematic comparison of one immutable WIP Project with one immutable Reference Project.

- Required Job bindings: `WIP`, `REFERENCE`.
- Ordinary model stages: structural adjudication when needed, required reference-text comparison, and selective original-language adjudication only when the sealed policy admits it.
- Versification differences and structural differences are reported without blocking the comparison.
- Scripture Projects are always read-only.

## Source Text Correspondence (STC)

Use STC for systematic WIP correspondence with the testament-appropriate primary original-language authority.

- Required Job binding: `WIP`.
- NT Books route PRIMARY GRK; OT Books route PRIMARY HEB.
- STC never reads, requires, fingerprints, or reports against a Reference Project.
- Scripture Projects and original-language resources are always read-only.

## Job menus

The Main Menu exposes RTC and STC separately. Each workflow menu can choose, add, or manage Jobs and open reports, recovery, and storage maintenance. A selected Job exposes exactly its own Run action:

- RTC Job: **Run Reference Text Comparison (RTC)**.
- STC Job: **Run Source Text Correspondence (STC)**.

WIP and RTC Reference bindings are immutable for the lifetime of a Job. Refreshing a WIP snapshot rereads the same Project source. Use a new Job to select a different WIP or Reference Project.

## Scope and progress

One Run may select ordered non-overlapping portions from one Book. A semicolon separates portions; the Book is inherited after the first portion, so `1CH 5-6; 24` means chapters 5, 6, and 24.

The Run header prints stable parameters once. In a terminal, one live progress row is replaced in place and may show workflow, stage, portion, and local case. Captured output emits one milestone per stage. It must not stack a permanent line for every Review portion.

## Completion

A Run ends `COMPLETE` after governed findings, exact coordinate coverage, receipts, and deterministic report publication pass. Plans and work units are internally `FINALIZED`; a Run never is. Reportable structural or versification differences end the Run as `COMPLETE_WITH_STRUCTURE_PROBLEMS`; they never block RTC/STC solely because project versifications differ. A Run in which some work units could not be assessed ends as `COMPLETE_WITH_EXCEPTIONS`.

## Exceptions and NOT_ASSESSED work units

A work unit whose provider output keeps failing is retried up to three times and then reported `NOT_ASSESSED`; the Run continues with the next unit. Its coordinates appear under "Exceptions — not assessed" in the chapter report, in the Run's `diagnostics/EXCEPTIONS-NOT-ASSESSED.md`, and as `PARTIAL` or `NOT_ASSESSED` coverage. A defective item inside an otherwise usable result (for example a finding outside the scope, or a quotation SAGE cannot find in the routed text) is dropped, corrected, or flagged and recorded in `diagnostics/EXCEPTION-REPORTS.jsonl`; the rest of the result is kept.

Only integrity guards (changed sealed inputs, task or Run identity, path safety) and provider, configuration, or controller failures stop a Run. A non-content failure that has already cost two work units stops the Run the next time it occurs. A stopped Run resumes where it stopped with **Continue active Run**.

## Legacy compatibility

Sealed Jobs created under the retired umbrella identity remain readable and resumable through compatibility code. That identity is not a current menu, Skill, prompt, Job type, or writer target.
