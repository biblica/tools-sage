# SAGE Windows Recovery Cheat Sheet

## Normal resume

Run `sage.cmd`. If the last Run is unfinished, menu option **1** resumes it through its recorded SAGE checkpoint; SAGE does not blindly replay the previous shell command.

## Interrupted setup

Run `sage.cmd`. Startup first revalidates Python and the managed `.venv`; guided setup then reads `state\setup-state.json` and continues from `next_step`.

## Recovery menu

Use **6 Recovery & diagnostics** to:

- recover/reset the active BIC or SAW Job;
- rebuild derived runtime configurations and indexes;
- show Project, Job, Run, and state paths;
- export diagnostics;
- clear only global active-Job/last-Run pointers.

Do not manually edit task manifests, ACT files, transaction journals, or `.sage` controller state.

## State locations

```text
state\setup-state.json       resumable setup snapshot
state\project-inventory.json  SAGE Projects
state\last-run.json          last Run pointer
state\active-jobs.json       active BIC/SAW Job pointers
state\operator-cues.jsonl    append-only high-level operator cues
jobs\...\.sage\state\       Job/Run controller state
```

For an incomplete governed write, use SAGE transaction recovery. For a completed BIC translation rollback, use governed TARGET history/Revert Scope rather than reset/rebuild.
