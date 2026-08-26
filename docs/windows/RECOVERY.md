# SAGE Windows Recovery Cheat Sheet

## Normal resume

Run `.\sage.cmd` from the SAGE root. If the last Run is unfinished, menu option **1** resumes it through its recorded SAGE checkpoint; SAGE does not blindly replay the previous shell command.

## Interrupted setup

Run `.\sage.cmd` from the SAGE root. Startup first resolves SAGEdata and revalidates Python and the managed `SAGEdata\.system\runtime\venv`; guided setup then reads `SAGEdata\.system\state\setup-state.json` and continues from `next_step`.

## Codex CLI installation on Windows

SAGE installs Codex CLI through the official OpenAI standalone PowerShell installer. The installer is run non-interactively and SAGE remains the parent process. The Windows installer depends on the normal Windows identity environment (`OS=Windows_NT`, `USERPROFILE`, and `LOCALAPPDATA`); SAGE must preserve those variables even though provider subprocesses otherwise use a minimized environment.

If Python environment repair succeeds but Codex installation fails, rerun `\.\sage.cmd` after applying the current Windows bootstrap patch. No Node/npm installation is required for the standalone Codex installer.

## Recovery menus

Open **BIC > Recovery and diagnostics** or **SAW > Recovery and diagnostics** for recovery that belongs to a Job. Open **SAGE Maintenance > System recovery and diagnostics** for global state, configuration, and diagnostic actions. The experimental TUI remains read-only for workflow-changing recovery operations; use the classic governed action when a write is required.

The workflow recovery menus can recover/reset the active Job and its Run. System recovery can:

- rebuild derived runtime configurations and indexes;
- show Project, Job, Run, and state paths;
- export diagnostics;
- clear only global active-Job/last-Run pointers.

**Reset SAGE to out-of-box state** is the destructive installation-wide reset. It removes all local Projects, Jobs, Runs, reports, caches, custom profiles, Operator settings, and generated workspace data; preserves the managed SAGEdata runtime and packaged SAGE Core resources; writes `SAGEdata/.system/state/out-of-box-reset.json`; then exits so the next launch begins first-use Setup. It requires both a negative-default confirmation and the exact text `RESET SAGE`.

Do not manually edit task manifests, ACT files, transaction journals, or `.sage` controller state.

## State locations

```text
SAGEdata\.system\state\setup-state.json       resumable setup snapshot
SAGEdata\.system\state\project-inventory.json  SAGE Projects
SAGEdata\.system\state\last-run.json          last Run pointer
SAGEdata\.system\state\active-jobs.json       active BIC/SAW Job pointers
SAGEdata\.system\state\operator-cues.jsonl    append-only high-level Operator cues
SAGEdata\.system\jobs\<tool>\<job-id>\   Job/Run controller state
```

For an incomplete governed write, use SAGE transaction recovery. For a completed BIC translation rollback, use governed TARGET history/Revert Scope rather than reset/rebuild.
