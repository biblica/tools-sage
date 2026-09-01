# Job storage maintenance

SAGE v0.01beta2 removes unused legacy directory creation from new Jobs/Runs and provides evidence-preserving maintenance for existing trees.

## Current layout

New Jobs no longer create `archive/` or `.sage/workspace_data/`. New Runs no longer create `operator-note-text/`. `decisions/` and `findings/` remain preserved/reserved pending later contract consolidation. Run-local `diagnostics/` remains canonical for diagnostics such as VRS advisories and execution-event evidence.

## Maintenance flow

Use **BIC/RTC/STC > Maintain Job storage**, or use CLI commands:

- `sage maintenance jobs audit-layout`
- `sage maintenance jobs migrate-layout --from-audit <JOB-LAYOUT-AUDIT.json>` (dry run)
- add `--apply` only after reviewing the exact audit
- `sage maintenance jobs verify-layout`

The audit carries a stable structural SHA-256. Apply refuses a stale audit if the Job tree changed. Empty retired directories may be removed. Unknown/non-empty content is always preserved for review. This release does not migrate legacy SAW Jobs into RTC/STC; use the governed Job-data wipe before creating the new primary-flow Jobs.

## Beta ownership

- `localdata/reports/` is reserved for finalized Operator-facing deliverables outside Git-controlled Core.
- `jobs/.../diagnostics/` and `jobs/.../runs/.../diagnostics/` contain technical execution/validation diagnostics.
- `report_data/` contains machine-readable report aggregation and rendering receipts.
- `tasks/` contains block-level governed evidence.
- New Runs do not create empty `decisions/` or `findings/` directories.
- Legacy technical `reports/` migrate to `diagnostics/` with hash verification; obsolete polished Run-local reports are quarantined under `localdata/.system/diagnostics/legacy-reports/` and never republished automatically.

## Wipe all Job data

**SAGE Maintenance > Wipe all Job data** requires exact `WIPE JOB DATA`. It removes all
BIC/RTC/STC and legacy SAW Jobs, Runs, tasks, reports, exports, histories, pointers,
controller state, locks, and transactions. It preserves Project Inventory, external Paratext
locations, resource mappings and selections, language/grammar/AI configuration, indexes,
SAGE Core, and `localdata/.system/runtime/venv`. The receipt is
`localdata/.system/state/job-data-wipe.json`.
