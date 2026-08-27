# SAGE macOS / Linux Recovery Cheat Sheet

## Normal resume

Run `./sage` from the SAGE root. If the last Run is unfinished, menu option **1** resumes it through its recorded SAGE checkpoint; SAGE does not blindly replay the previous shell command.

## Interrupted setup

Run `./sage` from the SAGE root. Startup first resolves localdata and revalidates the pinned runtime at `localdata/.system/runtime/python` plus the managed `runtime/venv`; guided setup then reads `localdata/.system/state/setup-state.json` and continues from `next_step`.

## Recovery menus

Open **BIC > Recovery and diagnostics** or **SAW > Recovery and diagnostics** for recovery that belongs to a Job. Open **SAGE Maintenance > System recovery and diagnostics** for global state, configuration, and diagnostic actions. The experimental TUI remains read-only for workflow-changing recovery operations; use the classic governed action when a write is required.

The workflow recovery menus can recover/reset the active Job and its Run. System recovery can:

- rebuild derived runtime configurations and indexes;
- show Project, Job, Run, and state paths;
- export diagnostics;
- clear only global active-Job/last-Run pointers.

**Reset SAGE to out-of-box state** is the destructive installation-wide reset. It removes all local Projects, Jobs, Runs, reports, caches, custom profiles, Operator settings, and generated workspace data; preserves the managed localdata runtime and packaged SAGE Core resources; writes `localdata/.system/state/out-of-box-reset.json`; then exits so the next launch begins first-use Setup. It requires both a negative-default confirmation and the exact text `RESET SAGE`.

Do not manually edit task manifests, ACT files, transaction journals, or `.sage` controller state.

## State locations

```text
localdata/.system/state/setup-state.json       resumable setup snapshot
localdata/.system/state/project-inventory.json  SAGE Projects
localdata/.system/state/last-run.json          last Run pointer
localdata/.system/state/active-jobs.json       active BIC/SAW Job pointers
localdata/.system/state/operator-cues.jsonl    append-only high-level Operator cues
jobs/.../.sage/state/        Job/Run controller state
```

For an incomplete governed write, use SAGE transaction recovery. For a completed BIC translation rollback, use governed TARGET history/Revert Scope rather than reset/rebuild.
