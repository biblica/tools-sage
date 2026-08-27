# SAGE Help

**Beta — pre-release; fresh exact-source qualification is required before an RC.** Use for controlled Operator testing and development only.

Open a terminal in the SAGE root. The classic menu remains the authoritative default: run `.\sage.cmd` on Windows or `./sage` on macOS/Linux. The **EXPERIMENTAL / UNSTABLE** TUI is explicit: run `.\sage.cmd tui` or `./sage tui`. Do **not** start Codex first. SAGE remains the parent process and invokes Codex only for sign-in or bounded AI work.

```text
  1. Manage SAGE Scripture Projects

  2. BIC
  3. SAW
  4. SAGE Maintenance

┌──────────────────────────────────────────────────────────────────────┐
│  A. Back   B. Main Menu   C. Exit SAGE                               │
│  D. Language   E. Help   F. Status                                   │
└──────────────────────────────────────────────────────────────────────┘
```

## Experimental / unstable TUI

The v0.01beta TUI is experimental, may change incompatibly, and does not yet provide authoritative workflow parity. It targets a `100 x 30` terminal and uses the same `1`-`4` functional controls and `A`-`F` global controls as the classic interface. Mouse buttons route through the same semantic actions. The main dashboard keeps four operational blocks visible: **System Status**, **Active AI**, **Project**, and one sequential **Active Job**. SAGE does not run multiple Jobs in parallel in this development line.

The Active Job block reports a compact governed progress quantifier without exposing token accounting:

```text
SAW_UK-ENG  [████░░░░░░]  43%
ACT 3 / OL REVIEW / RUNNING
```

The bar has 10 visual cells (10% each); the aligned numeric percentage remains integer-granular and is derived from finalized governed ACT work. A task advances the Job quantifier only after finalization, so retries do not falsely advance progress. Terminal results are `DONE`, `FAILED`, `BLOCKED`, or `CANCELLED`. A `BLOCKED` result includes a machine-readable reason and preserves progress for remediation/resume.

`F. Status` opens a modal status overlay instead of navigating away. It shows detailed System, AI, Project, session, and Active Job state; `F` or `Esc` closes it and `R` refreshes it. Closing Help or Status returns to the invoking TUI view without changing Back history.
The classic menu `F. Status` uses the same canonical Active Job quantifier and shows the Run progress bar, ACT/Skill activity, Run/stage, and finalized-task count. Top-level `sage status` exposes the same `job_progress` snapshot in JSON and prints the compact Run progress/activity lines in human output; its default path remains local-only and does not probe the provider.

The TUI currently provides native Projects-root setup, tree-only Quick Scan, and AI/readiness retest. Other workflow-changing Project, Job, Run, report, and recovery actions remain in the classic menu/scriptable CLI until their shared service boundaries and parity tests are complete. If Textual cannot be installed, launch SAGE without `tui`; the base classic interface remains valid.

Startup readiness, Job, Run, and Operator-cue state are persistent within the same pre-release
version. Guided startup uses **Manage Jobs** for initial BIC and SAW readiness; the Main Menu opens
the corresponding **BIC Jobs** and **SAW Jobs** surfaces. Reports, Job recovery, and Job-storage
maintenance belong to their respective BIC/SAW menus. **SAGE Maintenance** owns workstation paths,
resources, AI, system checks, and system recovery. Interface language is available from
`D. Language`, `E. Help`, and `F. Status` in the global two-row footer. Governed workflow transaction journals remain authoritative
for writes and recovery.

The Job-management list marks exactly one selected row as `[ACTIVE]`. **Choose active Job** changes that marker and returns to the same list; it does not start work. Use **Open active SAW Job** or **Open active BIC Job** to enter the selected Job’s operational menu. This separation prevents Job selection from silently starting or trapping an operation.

Guided input helps Operators complete missing command details without bypassing validation or Job authority.

## Evidence boundary

SAGE Jobs operate inside a closed **LOCAL EVIDENCE BOUNDARY**. Content-bearing evidence must be stored inside SAGE, governed, authorized for the owning Job/Project, and explicitly routed into the sealed task. A file does not become authorized merely because it is local, hashed, or allowlisted.

- **BIC:** SOURCE is content authority; DONOR is lexical evidence only; TARGET is subject/output only; OL is available only when explicitly routed by the governed operation.
- **SAW:** REFERENCE is the normal authorized LWC Reference Project comparison; WIP is the subject under analysis. When an explicitly bounded task is routed to original-language review, configured GRK/HEB is primary textual authority for the source-text question in that task only; REFERENCE remains comparative evidence and does not override contrary OL evidence.
- Governed RWC/SEMDOM and future explicitly imported/merged project indexes are **PROJECT_INDEX_EVIDENCE**, not Scripture or translation authority.
- Derived packets inherit the authority and restrictions of their authorized local provenance. Generic imported lexicon material cannot be promoted into Job content evidence merely by review status.
- The model may use **GENERAL LINGUISTIC COMPETENCE** only for orthography, morphology, grammar, and syntax. Model recall/pretraining, external Scripture/translations/lexicons/commentary, web/search, cultural/history recall, and unstated facts are not evidence.

**Linguistic competence may determine how locally supported content is expressed; it may not determine what the content is.**

Each sealed task labels every read with an evidence class. Missing or invalid classification fails closed rather than widening the model context.

First-launch checks occur before the menu: localdata resolution/validation, macOS launch/runtime quarantine detection, exact OS/CPU detection, approved CPython selection, `venv`, pinned dependencies, `pip check`, real import smoke tests for every declared runtime module, non-destructive pre-release version-state recording, then Scripture/VRS resource validation. SAGE accepts the qualified CPython 3.12 line from a signed Python.org installation, an existing Homebrew installation on macOS, or the exact SAGE-managed artifact. The fallback base runtime is `localdata/.system/runtime/python`; the application environment is always `localdata/.system/runtime/venv`. Neither is included in Core. Host Python and Homebrew are not prerequisites. If runtime installation fails, SAGE prints a BLOCKED runtime installation report and offers the SAGE-managed runtime again, approved Python through Homebrew or WinGet when that package manager is available, or exit. Package-manager installation requires an explicit Operator choice. Startup prints the SAGE root, localdata root, managed environment, and selected runtime provider. Version changes preserve persistent localdata. The optional `system/tools/CLONE-AND-INSTALL.md` helper automates cloning/bootstrap and can rebind an existing Paratext Projects root on a new host.


Project administration is under **Scripture Projects**. Configure the Paratext Projects root once; the initial scan and **Quick rescan** enumerate immediate child directories and check only for the `settings.xml` marker. Quick discovery never opens Project files. Newly discovered Projects are marked **PENDING** until selected/used or validated. **Full rescan** reads Project metadata and Scripture inventory for every discovered Project and rebuilds detailed readiness/warning state. The same tree-only discovery layer reports added/removed configured resources without opening their contents. **Remove Project from SAGE** is a direct menu action: it removes SAGE inventory/mapping state, never Paratext files, and is blocked while any active or archived Job still uses the Project.

Language Profiles are maintained under **Scripture Projects > Language Profiles**. Role-specific Grammar Profiles are maintained beneath the selected Language Profile and are required only when a Job role needs them. Use **Choose from existing profile list** to register a compatible profile already in SAGE, or **Add grammar profile from YAML file** to import and validate a profile. When Job setup reports `LANGUAGE_PROFILE_NOT_CONFIGURED`, SAGE opens this same menu already filtered to the required language and Job role; after a compatible profile is registered, Job creation retries. Project addition establishes or selects the regional Language Profile namespace before registration; it does not force Grammar Profile setup.

Startup also treats workflow AI as a prerequisite: it checks installation, authentication, configured provider, selected **Model**, and effective **Reasoning level** without generating model output. The **AI Setup and Status** menu loads that same canonical state once on entry; model/reasoning toggles do not recheck it. Only **Check LLM connection** performs an explicit end-to-end test prompt. A failed readiness check leaves setup `INCOMPLETE` and blocks normal Main Menu entry.

Startup displays an empty valid inventory as **No SAGE Projects added yet**. The corresponding machine-record state is `READY_EMPTY`; it does not mean workstation configuration is complete. Until the Paratext Projects root is configured and available, startup and the complete system check report `INCOMPLETE` with `PROJECTS_ROOT_NOT_CONFIGURED` or `PROJECTS_ROOT_NOT_FOUND`.

The workstation interface language is stored in the local `localdata/.system/config/local-settings.yml` overlay and is selectable in guided Setup or with `D. Language` from any menu. v0.01beta ships complete editable menu-localization entries for `en-US`, `en-GB`, `id`, `fr`, `ru`, and `pt-BR`. Functional menu choices remain numeric. The global footer is two rows: `A. Back   B. Main Menu   C. Exit SAGE`, then `D. Language   E. Help   F. Status`. Help and Status return to the same active menu. Localized labels never control navigation.

Reporting language is a separate authority. In this localization patch, the existing global Operator reporting language remains the current runtime primary and each Job may still add one optional secondary reporting language. The approved target architecture is Job-owned primary and optional secondary reporting; see **SAGE System Grammar** and **Purpose and Function Drift Report**. Projects do not own report-language settings. Governed `@GRK` and `@HEB` sources are configured separately under **Scripture Projects > Original-language resources**.

Finalized Run findings remain as governed Job data. SAGE consolidates compatible results for the
same chapter/scope and publishes polished output at `localdata/reports/<job-id>/<BOOK>/`. For example,
SAW Reference Text Comparison (RTC) on `GEN 1` publishes
`localdata/reports/<job-id>/GEN/GEN-001_YYYY-MM-DD_001_ACTION-REPORT.md` and its matching
`_OPERATOR-NOTE.txt`. The canonical consolidation record remains under the Job's `report_data/`
folder. Findings sharing a verse/category are not guessed to conflict. When an upstream validator
supplies explicit conflict lineage, competing conclusions are retained and marked
`HUMAN_REVIEW_REQUIRED`; SAGE never chooses one silently. Reports are never written into a
Paratext Project.

Fallback docs:

- Windows: `docs/windows/CHEAT-SHEET.md`, `RECOVERY.md`, `ERRORS.md`
- macOS/Linux: `docs/macos-linux/CHEAT-SHEET.md`, `RECOVERY.md`, `ERRORS.md`

Direct command lookup: `.\sage.cmd --help` or `./sage --help`.

Advanced technical documentation: `docs/advanced/README.md`.

During pre-release testing, the main menu prints the running SAGE version and development warning. If the version does not match the folder you just extracted, an older copy is being launched.


## Estimated language competency

`AI setup and status -> Registered language competency` shows versioned registry or measured-evaluation evidence for the selected Codex model release. A new model or language with no trusted evidence remains `UNASSESSED`; SAGE never asks a model to rate itself and does not fabricate or append a tier. Adding or opening a Project does not run or display this lookup; competency is an explicit language action.


## Guided Input

When SAGE returns `INPUT_REQUIRED`, use Guided Input to provide the requested bounded Operator value. SAGE must not invent missing project identity, primary audience country, Job binding, or scope.
## Beta interaction pattern

Interactive classic-menu navigation starts each new form on a fresh terminal viewport. A full-width `=` boundary appears above and below the screen title, so a new panel remains obvious when a short result message is intentionally retained. Redirected/scripted output contains the same panel boundary without ANSI control codes. `-` remains the section/footer boundary; primary actions and fixed-width label/value columns remain consistent. Optional file/path prompts show `[Enter to cancel]`; pressing Enter cancels rather than raising a required-input error. See `docs/advanced/maintenance/UI-PRESENTATION.md`.
## Beta path normalization

Path rule: SAGE never repeats the same adjacent Book/scope directory. Whole-book output is published under `localdata/reports/<job-id>/<BOOK>/`; a distinct scope directory is added only when it carries additional chapter/verse information.
