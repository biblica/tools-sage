# SAGE Windows Recovery Cheat Sheet

## Normal resume

Run `.\sage.cmd` from the SAGE root. If the last Run is unfinished, menu option **1** resumes it through its recorded SAGE checkpoint; SAGE does not blindly replay the previous shell command.

## Interrupted setup

Run `.\sage.cmd` from the SAGE root. Startup first resolves localdata and revalidates Python and the managed `localdata\.system\runtime\venv`; guided setup then reads `localdata\.system\state\setup-state.json` and continues from `next_step`.

## Codex CLI installation on Windows

SAGE installs Codex CLI through the official OpenAI standalone PowerShell installer. The installer is run non-interactively and SAGE remains the parent process. The Windows installer depends on the normal Windows identity environment (`OS=Windows_NT`, `USERPROFILE`, and `LOCALAPPDATA`); SAGE must preserve those variables even though provider subprocesses otherwise use a minimized environment.

If Python environment repair succeeds but Codex installation fails, rerun `\.\sage.cmd` after applying the current Windows bootstrap patch. No Node/npm installation is required for the standalone Codex installer.

## Recovery menus

Open **BIC > Recovery and diagnostics**, **RTC > Recovery and diagnostics**, or **STC > Recovery and diagnostics** for recovery that belongs to a Job. Open **SAGE Maintenance > System actions** for global state, configuration, and diagnostic actions. TUI recovery writes are deferred to `0.02beta`; use the classic governed action throughout `0.01beta2`.

The workflow recovery menus can recover/reset the active Job and its Run. System recovery can:

- rebuild derived runtime configurations and indexes;
- show Project, Job, Run, and state paths;
- export diagnostics;
- clear only global active-Job/last-Run pointers.

**Reset SAGE to out-of-box state** is the destructive installation-wide reset. It removes all local Projects, Jobs, Runs, reports, caches, custom profiles, Operator settings, and generated workspace data; preserves the managed localdata runtime and packaged SAGE Core resources; writes `localdata/.system/state/out-of-box-reset.json`; then exits so the next launch begins first-use Setup. It requires both a negative-default confirmation and the exact text `RESET SAGE`.

**SAGE Maintenance > System actions > Wipe all Job data** is narrower. It requires `WIPE JOB DATA` and removes all BIC/RTC/STC and legacy SAW Jobs, Runs, tasks, reports, exports, histories, pointers, locks, and transactions. It preserves the managed environment and dependencies, Project Inventory and Paratext mappings, resources, indexes, and configuration. Its receipt is `localdata\.system\state\job-data-wipe.json`.

Do not manually edit task manifests, ACT files, transaction journals, or `.sage` controller state.

## State locations

```text
localdata\.system\state\setup-state.json       resumable setup snapshot
localdata\.system\state\project-inventory.json  SAGE Projects
localdata\.system\state\last-run.json          last Run pointer
localdata\.system\state\active-jobs.json       active BIC/RTC/STC Job pointers
localdata\.system\state\operator-cues.jsonl    append-only high-level Operator cues
localdata\.system\jobs\<tool>\<job-id>\   Job/Run controller state
```

For an incomplete governed write, use SAGE transaction recovery. For a completed BIC translation rollback, use governed TARGET history/Revert Scope rather than reset/rebuild.
