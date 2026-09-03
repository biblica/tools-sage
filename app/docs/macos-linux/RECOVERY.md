# SAGE macOS / Linux Recovery Cheat Sheet

## macOS quarantine / malware warning

A Chrome, Safari, AirDrop, or other downloaded ZIP can attach macOS quarantine provenance to the
entire extracted SAGE tree. Because PyYAML includes a native `_yaml` extension, Gatekeeper can then
show an "Apple could not verify ... is free of malware" warning when SAGE first imports it. This
warning means the portable source ZIP and its nested native dependency are not notarized; it is not
evidence that SAGE's dependency check found malware.

SAGE does not remove quarantine automatically. It stops before dependency installation/import when
quarantine is present. For a release ZIP, first keep the ZIP and its adjacent `.sha256` file together
and verify the exact artifact from their containing directory:

```sh
shasum -a 256 -c SAGE-v0.01beta2-Full-Distribution.zip.sha256
```

Only after that prints `OK`, and only when the checksum came from a trusted SAGE release channel,
authorize that exact extracted copy:

```sh
/usr/bin/xattr -dr com.apple.quarantine "/absolute/path/to/SAGE-v0.01beta2-Full-Distribution"
```

Then rerun `./sage`. Do not use `spctl --master-disable`, do not disable Gatekeeper globally, and do
not remove quarantine from an unverified download. A public macOS distribution should be Developer
ID-signed and notarized so this manual recovery is unnecessary.

A Git source checkout contains read-only loose objects under `.git/objects`. Do not change their
permissions and do not recursively run `xattr` across `.git`; those objects are data and are never
executed by SAGE. If authorizing a trusted Git checkout rather than a release ZIP, scope removal to
the runnable bundle boundaries:

```sh
sage_bundle="/absolute/path/to/SAGE"
for sage_target in "$sage_bundle" "$sage_bundle/sage" "$sage_bundle/localdata"; do
  /usr/bin/xattr -d com.apple.quarantine "$sage_target" 2>/dev/null || true
done
/usr/bin/xattr -dr com.apple.quarantine "$sage_bundle/app"
if [ -d "$sage_bundle/localdata/.system/runtime" ]; then
  /usr/bin/xattr -dr com.apple.quarantine "$sage_bundle/localdata/.system/runtime"
fi
```

`Permission denied` messages for `.git/objects/*` from an earlier broad command are harmless once
the SAGE root, `app`, `localdata`, and managed runtime no longer carry quarantine.

## Normal resume

Run `./sage` from the SAGE root. If the last Run is unfinished, menu option **1** resumes it through its recorded SAGE checkpoint; SAGE does not blindly replay the previous shell command.

## Interrupted setup

Run `./sage` from the SAGE root. Startup first resolves localdata and revalidates the pinned runtime at `localdata/.system/runtime/python` plus the managed `runtime/venv`; guided setup then reads `localdata/.system/state/setup-state.json` and continues from `next_step`.

## Recovery menus

Open **BIC > Recovery and diagnostics**, **RTC > Recovery and diagnostics**, or **STC > Recovery and diagnostics** for recovery that belongs to a Job. Open **SAGE Maintenance > System actions** for global state, configuration, and diagnostic actions. TUI recovery writes are deferred to `0.02beta`; use the classic governed action throughout `0.01beta2`.

The workflow recovery menus can recover/reset the active Job and its Run. System recovery can:

- rebuild derived runtime configurations and indexes;
- show Project, Job, Run, and state paths;
- export diagnostics;
- clear only global active-Job/last-Run pointers.

**Reset SAGE to out-of-box state** is the destructive installation-wide reset. It removes all local Projects, Jobs, Runs, reports, caches, custom profiles, Operator settings, and generated workspace data; preserves the managed localdata runtime and packaged SAGE Core resources; writes `localdata/.system/state/out-of-box-reset.json`; then exits so the next launch begins first-use Setup. It requires both a negative-default confirmation and the exact text `RESET SAGE`.

**SAGE Maintenance > System actions > Wipe all Job data** is narrower. It requires `WIPE JOB DATA` and removes all BIC/RTC/STC and legacy SAW Jobs, Runs, tasks, reports, exports, histories, pointers, locks, and transactions. It preserves the managed environment and dependencies, Project Inventory and Paratext mappings, resources, indexes, and configuration. Its receipt is `localdata/.system/state/job-data-wipe.json`.

Do not manually edit task manifests, ACT files, transaction journals, or `.sage` controller state.

## State locations

```text
localdata/.system/state/setup-state.json       resumable setup snapshot
localdata/.system/state/project-inventory.json  SAGE Projects
localdata/.system/state/last-run.json          last Run pointer
localdata/.system/state/active-jobs.json       active BIC/RTC/STC Job pointers
localdata/.system/state/operator-cues.jsonl    append-only high-level Operator cues
localdata/.system/jobs/<tool>/<job-id>/        Job/Run controller state
```

For an incomplete governed write, use SAGE transaction recovery. For a completed BIC translation rollback, use governed TARGET history/Revert Scope rather than reset/rebuild.
