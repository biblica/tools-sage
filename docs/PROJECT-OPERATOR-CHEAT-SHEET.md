# Scripture Project Operator Cheat Sheet — RC7.04

## Normal path

```text
Main Menu
  -> Scripture Projects
  -> Scan / Rescan Paratext Projects
  -> Add Projects to SAGE
  -> SAGE Projects
```

For a clean machine:

1. Configure the Paratext Projects root.
2. SAGE scans direct child folders with valid `settings.xml` and saves the Paratext Project Catalogue.
3. Open **Add Projects to SAGE**.
4. Optionally filter by **FB / NT / Portions** and/or **Language**.
5. Review the detected Project metadata and add the Project to SAGE.
6. Create BIC/SAW Jobs separately and assign Job roles there.

Project addition is a System task. SOURCE/DONOR/TARGET/WIP/REFERENCE assignment is a tool setup task.

## Project identity

SAGE reads `settings.xml`, `canons.xml`, top-level `*.SFM`, `custom.vrs`, and the Project folder name. It does not modify those files during discovery or addition to SAGE.

A valid ISO language identity may be added to SAGE even when no SAGE language-analysis profile exists. Folder-prefix evidence is advisory; ambiguous corrections require operator selection.

## Base VRS

The Base VRS root defaults to the Paratext Projects root. An explicit Base VRS override survives later Paratext-root changes. Clear the override to return to the default.

## Job setup

BIC:

```text
SOURCE     Scripture being analysed
DONOR      Supporting translation/reference wording
TARGET     Translation BIC may modify through governed writes
```

SAW:

```text
WIP        Translation being reviewed
REFERENCE  Comparison/reference translation
```

Role selectors show only SAGE Projects. **Add another Project to SAGE** temporarily opens Project administration and then returns to the selector.

## Scope and preview

Runs use **SELECT SCRIPTURE SCOPE**. Choose a Book plus a range, choose direct entry, or type the scope at the selection prompt. `GEN` selects the whole book; `GEN 1` selects the whole chapter; `GEN 1:1-10` selects the verse range. Before Run creation SAGE shows **REVIEW WORK BEFORE RUNNING** with bounded sections and estimated tokens. Choose **Run**, **Change scope**, or **Cancel**.

## Job report batching

A Run owns the bounded Tasks, provider receipts, validation records, and intermediate plan/stage artefacts needed for audit and recovery. When the Run finalises, SAGE validates complete coverage and batches the approved findings into the owning Job's main report catalogue:

```text
jobs/<tool>/<job-id>/reports/<BOOK>/
```

For SAW QA on `GEN 1`, final files use names such as:

```text
GEN/GEN-001_2026-08-13_001_ACTION-REPORT.md
GEN/GEN-001_2026-08-13_001_OPERATOR-NOTE.txt
```

The final report is Job-owned, not Run-owned and not Project-owned. The `<job-id>` path segment identifies the Job, not a Project. A Project reporting-language override selects rendering languages only; it does not own or redirect report files. A Job may batch results from several Runs into the same book folder; the date and serial prevent collisions. SAGE prints the exact final report paths at completion. It never writes reports into a Paratext Project folder.

## Safe removal

**Remove Project from SAGE** removes SAGE state only. It never deletes or changes the Paratext Project. SAGE blocks removal while any Job still binds the Project.

**Remove Job** deletes SAGE Job-local state, Runs, and reports for that Job; it does not delete or modify SAGE Projects or Paratext files.

## Original-language resources

`@GRK` and `@HEB` are governed resources separate from ordinary SAGE Projects. Configure them under **Original-language resources**; Project discovery never silently changes their authority.
