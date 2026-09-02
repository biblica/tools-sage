# Scripture Project Operator Cheat Sheet — v0.01beta2

Every menu, including Manage Jobs, Scripture Projects, BIC, SAW, and SAGE
Maintenance, ends with the same navigation block:

```text
┌──────────────────────────────────────────────────────────────────────┐
│  A. Back   B. Main Menu   C. Exit SAGE                               │
│  D. Language   E. Help   F. Status                                   │
└──────────────────────────────────────────────────────────────────────┘
```

`A` returns to the immediate parent when Back is available, `B` returns directly to the Main Menu,
`C` exits SAGE, `D` opens Interface Language, `E` opens contextual Help, and `F` opens Status. Help and Status return to the invoking view. Footer keys do not change with localization.

## Normal path

```text
Main Menu
  -> Scripture Projects
  -> Paratext Projects root
  -> Scan Paratext Projects
  -> Add Projects to SAGE
  -> List / manage SAGE Scripture Projects
  -> Remove Project from SAGE
```

For a clean machine:

1. Configure the Paratext Projects root.
2. SAGE scans direct child folders with valid `settings.xml` and saves the Paratext Project Catalog.
3. Open **Add Projects to SAGE**.
4. Optionally filter by **FB**, **NT**, **Portions**, or **Language**.
5. Review the detected Project metadata and add the Project to SAGE.
6. Create BIC, RTC, and STC Jobs separately and assign Job roles there.

Project addition is a System task. SOURCE/DONOR/TARGET/WIP/REFERENCE assignment is a tool setup task.

## Project identity

SAGE reads `settings.xml`, `canons.xml`, top-level `*.SFM`, `custom.vrs`, and the Project folder name. It does not modify those files during discovery or addition to SAGE.

A Project is registered only after SAGE has confirmed a regional Language Profile namespace. Grammar Profiles remain separate and may be configured later when a Job role requires one. Settings.xml, all relevant LDML identities, Project-name prefix evidence, ISO relationships, and country evidence support the estimate; ambiguous identity or country choices require Operator confirmation.

Successful addition records the immutable full UTC import timestamp and displays its stable `YYYYMMDD` **Imported to SAGE** date. Project validation, rescanning, and remapping preserve it. Removing and later re-adding a Project creates a new import date.

## Base VRS

The Base VRS root defaults to the Paratext Projects root. An explicit Base VRS override survives later Paratext-root changes. Clear the override to return to the default.

## Job setup

BIC:

```text
SOURCE     Scripture being analyzed
DONOR      Decontextualized vocabulary evidence only
TARGET     Translation BIC may modify through governed writes
```

RTC:

```text
WIP        Translation being reviewed
REFERENCE  Comparison/reference translation
```

STC:

```text
WIP        Translation being reviewed against GRK/HEB authority
```

Role selectors show only SAGE Projects and report each Project's SAGE import date. The final Job review repeats every selected Project and date. RTC/STC Job IDs and WIP snapshot dates use the WIP Project import date; they do not use Job setup or Run execution time. **Add another Project to SAGE** temporarily opens Project administration and then returns to the selector.

## Scope and preview

Runs use **CHOOSE SCRIPTURE SCOPE**. Choose a Book plus a range, choose direct entry, or type the scope at the choice prompt. `GEN` means the whole book; `GEN 1` means the whole chapter; `GEN 1:1-10` means the verse range. Before Run creation SAGE shows **REVIEW WORK BEFORE RUNNING** with bounded sections and estimated tokens. Choose **Run**, **Change scope**, or **Back**.

## Job report batching

A Run owns the bounded tasks, provider receipts, validation records, and intermediate plan/stage
artifacts needed for audit and recovery. When the Run finalizes, SAGE validates complete coverage
and batches the approved findings into the owning Job's main report catalog:

```text
localdata/reports/<job-id>/<BOOK>/
```

For SAW Reference Text Comparison (RTC), Operator reports are chapter-scoped with an explicit three-digit chapter component:

```text
GEN/GEN_001_RTC_ACTION-REPORT.md
GEN/GEN_001_RTC_OPERATOR-NOTE.txt
```

Single-chapter books still use chapter `001`, for example `PHM_001_STC_ACTION-REPORT.md`. The current report ID is `RTC` or `STC`. Block-level evidence remains under the governed Run task tree.

The final report is Job-owned, not Run-owned and not Project-owned. The `<job-id>` path segment identifies the Job, not a Project. Each Job owns one required primary reporting language; the global Operator language is only the default captured for a new Job. Normal menus expose only `approved` languages and configured `candidates`; an advanced Operator must add a `pilot_only` tag to `human_output.operator_language_policy.candidates` by hand before evaluation. The Job may add an optional secondary reporting language; SAGE recommends the SAW WIP language or BIC TARGET language and also offers another language or none. In every bilingual report, the primary rendering governs interpretation and the secondary is an assistive, lower-confidence downstream translation that must be checked against the primary before action. A secondary rendering adds model usage and report compilation time and requires more human review than a single-language report. Canonical machine evidence remains authoritative. A finalized chapter report is the current canonical Operator projection for that Job/book/chapter. Governed Run/task evidence preserves historical execution identity; Operator filenames do not encode Run date/serial. SAGE prints the exact final report paths at completion. It never writes reports into a Paratext Project folder.

## Safe removal

**Scripture Projects > Remove Project from SAGE** is the direct removal path. The same action remains available from an individual Project's detail screen. It removes SAGE inventory and mapping state only; it never deletes or changes the Paratext Project. SAGE blocks removal while any active or archived Job still binds the Project.

**Remove Job** deletes the Job directory, including its Runs and Job-local report data. Published
files in the root Operator reports catalog are separate and remain available. Removal does not
delete or modify SAGE Projects or Paratext files.

## Original-language resources

`@GRK` and `@HEB` are governed resources separate from ordinary SAGE Projects. Configure them under **Original-language resources**; Project discovery never silently changes their authority.
