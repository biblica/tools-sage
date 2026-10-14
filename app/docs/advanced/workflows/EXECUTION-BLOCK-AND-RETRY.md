# Execution interruptions, blocks, retries, and reports

SAGE v0.02b1 reserves `BLOCKED` for the narrow case where the exact requested operation cannot safely proceed. Recoverable provider/task conditions use narrower dispositions and are persisted as execution evidence.

## Dispositions

- `INPUT_REQUIRED` — operator/configuration input is needed before the affected operation can proceed.
- `READY_WITH_ACTIONS` — advisory/action exists but execution may continue.
- `TASK_PAUSED` — provider/network/timeout interruption; retry the same sealed task.
- `TASK_OUTPUT_REJECTED` — provider output failed validation; archive the rejected attempt and retry the same sealed task.
- `STALE` — governed input/fingerprint changed; rebuild only the affected stage/task.
- `BLOCKED` — exact scope/stage/commit cannot safely proceed after deterministic validation.
- `ERROR` — unexpected software/runtime defect requiring developer review.

## Persistent evidence

Run-local execution events are append-only in `runs/<run-id>/diagnostics/EXECUTION-EVENTS.jsonl`. A deterministic human projection is written to the same Run `diagnostics/BLOCK-REPORT.md`. Final RTC/STC reports include execution interruptions/blocks/advisories alongside findings. Event details are bounded and credential-like keys are redacted.

## Retry policy

Provider execution failures pause the current task rather than invalidate the Run. Invalid provider output is moved to `tasks/<task-id>/attempts/attempt-NNN-rejected-*/` with a hash-bearing receipt; the sealed task inputs remain unchanged and the task can be executed again. Aggregate coverage/finalization inconsistencies remain Run-level blocks.

## Exception reports: content never stops a Run

Content and recoverable problems become exception reports; only integrity guards stop a Run. The plan runner (partitioned RTC/STC plans and every BIC chain) applies one policy to each failed work-unit attempt:

- **Stop** for an integrity code (`INTEGRITY_CODES` in `exception_reports.py`: hashes and fingerprints, stale inputs, task/Job/Project binding, pinned contracts, path safety, corrupt governed or commit state) and for environment conditions that say nothing about content (`INPUT_REQUIRED`, `TASK_PAUSED`: login, provider outage). The Run stays open and resumable.
- **Retry** any other failure automatically, up to three failed attempts per task.
- **Not assessed** after the third failure: SAGE seals the unit with a terminal `NOT_ASSESSED` result (`validation/submission.json` plus `validation/not-assessed.json`) and the Run continues with the next unit.

Each failed attempt is one structured record (tool, Job, Run, task, work unit, stage, coordinates, code, message, severity, effect, attempts, evidence path) in `runs/<run-id>/diagnostics/EXCEPTION-REPORTS.jsonl`. A `NOT_ASSESSED` unit is terminal for plan continuation. Aggregation, STC finalization, composite RTC finalization, and chapter consolidation accept it, report the coordinates as `not_assessed_references`, and derive coverage through `coverage.assess_coverage` (`PARTIAL`, or `NOT_ASSESSED` when nothing was assessed) instead of claiming `COMPLETE`. Every RTC, STC, BIC, and NCA report carries one shared "Exceptions — not assessed" section; a BIC Run also writes `diagnostics/EXCEPTIONS-NOT-ASSESSED.md`. For BIC a unit that cannot be assessed is not rewritten and its TARGET text is left untouched.

## Optional OL

RTC requires WIP + REFERENCE; STC requires WIP plus the testament-appropriate primary OL authority. BIC core execution requires SOURCE + DONOR + TARGET. Original-language resources are conditional: a non-ready GRK/HEB resource produces `READY_WITH_LIMITATIONS` for ordinary RTC/BIC readiness and blocks only an invoked OL-required stage for the applicable testament.

## BIC commit preflight

Before BIC REWRITE/SELF-CHECK provider work, SAGE preflights an existing TARGET against the bounded SOURCE verse shape. Missing TARGET chapters, crossing bridges, incompatible existing verse/bridge shapes, and unsupported new bridged insertions block at `TARGET_COMMIT` before provider cost is incurred. Missing ordinary verses inside an existing chapter remain insertable.
