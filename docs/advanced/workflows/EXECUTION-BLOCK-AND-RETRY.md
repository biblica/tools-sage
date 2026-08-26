# Execution interruptions, blocks, retries, and reports

SAGE v0.01beta reserves `BLOCKED` for the narrow case where the exact requested operation cannot safely proceed. Recoverable provider/task conditions use narrower dispositions and are persisted as execution evidence.

## Dispositions

- `INPUT_REQUIRED` — operator/configuration input is needed before the affected operation can proceed.
- `READY_WITH_ACTIONS` — advisory/action exists but execution may continue.
- `TASK_PAUSED` — provider/network/timeout interruption; retry the same sealed Task.
- `TASK_OUTPUT_REJECTED` — provider output failed validation; archive the rejected attempt and retry the same sealed Task.
- `STALE` — governed input/fingerprint changed; rebuild only the affected stage/task.
- `BLOCKED` — exact scope/stage/commit cannot safely proceed after deterministic validation.
- `ERROR` — unexpected software/runtime defect requiring developer review.

## Persistent evidence

Run-local execution events are append-only in `runs/<run-id>/diagnostics/EXECUTION-EVENTS.jsonl`. A deterministic human projection is written to the same Run `diagnostics/BLOCK-REPORT.md`. Final SAW reports include execution interruptions/blocks/advisories alongside findings. Event details are bounded and credential-like keys are redacted.

## Retry policy

Provider execution failures pause the current Task rather than invalidate the Run. Invalid provider output is moved to `tasks/<task-id>/attempts/attempt-NNN-rejected-*/` with a hash-bearing receipt; the sealed Task inputs remain unchanged and the Task can be executed again. Aggregate coverage/finalization inconsistencies remain Run-level blocks.

## Optional OL

Normal SAW QA requires WIP + REFERENCE. BIC core execution requires SOURCE + DONOR + TARGET. Original-language resources are conditional: a non-ready GRK/HEB resource produces `READY_WITH_LIMITATIONS` for normal workflow readiness and blocks only an invoked OL-required stage for the applicable testament.

## BIC commit preflight

Before BIC REWRITE/SELF-CHECK provider work, SAGE preflights an existing TARGET against the bounded SOURCE verse shape. Missing TARGET chapters, crossing bridges, incompatible existing verse/bridge shapes, and unsupported new bridged insertions block at `TARGET_COMMIT` before provider cost is incurred. Missing ordinary verses inside an existing chapter remain insertable.
