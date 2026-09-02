# SAGE Windows Cheat Sheet

## Start

Classic menu (current default):

```bat
.\sage.cmd
```

Frozen TUI preview (`0.01beta2`):

```bat
.\sage.cmd tui
```

The TUI uses the supplemental `system\requirements-tui.txt` profile. Its current navigation/status baseline remains available, but additional workflow functionality is deferred to `0.02beta`. If the supplemental profile cannot be installed, the classic menu and scriptable CLI remain available.

Run SAGE from Command Prompt/PowerShell; do not start `codex` first. If the Codex CLI is missing, installation requires explicit Operator confirmation. SAGE resolves/validates `localdata`, creates or repairs `localdata\.system\runtime\venv`, then checks Codex and the persisted ChatGPT login.

`localdata\.system\runtime\venv` is **not shipped in Core** and SAGE does not use `.env`. The launcher creates it on first approved launch. Startup prints the running SAGE root, localdata root, and managed environment path before guided setup.

A pre-release version change records the new Core version but preserves existing recognized localdata. Projects, Jobs, Runs, reports, resources, settings, and Operator state are not deleted by a Git update or normal launch.

```text
shell -> SAGE -> Codex login / governed AI subprocess
```

## Main menu and TUI controls

```text
  1. Manage SAGE Scripture Projects

  2. Bible Index & Context (BIC)
  3. Reference Text Comparison (RTC)
  4. Source Text Correspondence (STC)

  5. SAGE Maintenance

┌──────────────────────────────────────────────────────────────────────┐
│  A. Back   B. Main Menu   C. Exit SAGE                               │
│  D. Language   E. Help   F. Status                                   │
└──────────────────────────────────────────────────────────────────────┘
```

The same numeric functional grammar and `A`-`F` global controls are used by the development TUI. Reports and Job recovery are under BIC/RTC/STC; system recovery is under SAGE Maintenance. `F. Status` opens a non-destructive overlay and returns to the invoking view. The TUI targets a `100 x 30` terminal and shows System Status, Active AI, Project, and one sequential Active Job. Active Job progress is compact, for example `RTC-ukrNPUv1_20260901-001 [████░░░░░░]  43%`.

The classic menu remains authoritative for `0.01beta2`. Further TUI action parity is paused until `0.02beta`.

## Paratext / PTLite

Configure a reusable projects root once under **Scripture Projects -> Paratext Projects root**.

Examples:

```text
C:\Paratext Projects
D:\Paratext Projects
\\server\share\Paratext Projects
```

SAGE then discovers immediate project subfolders and stores mappings as **projects root + subfolder**. When maintaining a SAGE Project, you may paste either the direct project folder or the parent Projects root. If the parent contains a direct child matching the selected Project code, SAGE selects that child automatically. Paths containing spaces are accepted directly; matching surrounding quotes pasted from a shell are also normalized.

External reads remain limited to `.SFM` and `.VRS`. Only an explicitly authorized BIC TARGET may write `.SFM`.

## Create BIC / RTC / STC Job

RTC binds different WIP and REFERENCE Projects. STC binds only WIP and chooses `GRK` or `HEB` by Book; it never uses REFERENCE. Analysis Job IDs use the WIP import date (`RTC-ukrNPUv1_20260901`), while repeated Runs append `-001`, `-002`, and later serials.

## Final reports

SAGE validates and batches finalized Run findings into the owning Job's main report catalog:

```text
localdata\reports\<job-id>\GEN\001\<run-id>_GEN-001_ACTION-REPORT.md
localdata\reports\<job-id>\GEN\001\<run-id>_GEN-001_OPERATOR-NOTE.txt
```

The `<job-id>` segment is the owning Job ID, not a Project ID. The completion screen prints the exact paths. SAGE does not write reports into the mapped Paratext Project folder.

Reportable versification or source-coordinate gaps finish as `COMPLETE_WITH_STRUCTURE_PROBLEMS`; they do not abort safe RTC/STC analysis. Use **SAGE Maintenance > Resource Status Report** to inspect resources. **Wipe all Job data** requires `WIPE JOB DATA` and preserves the managed environment, Projects, resources, indexes, and configuration.

## Models

Provider status separates **Codex CLI + ChatGPT execution readiness** from the live model catalog. A catalog-query error is diagnostic and does not erase a verified ChatGPT login.

The optional local admin assistant is under **SAGE Maintenance > Configure AI >
Configure Local AI**. SAGE detects an existing per-user
Ollama installation before offering `OllamaSetup.exe`. The menu can start or
stop a SAGE-owned service, import the hash-verified Gemma 4 E2B Q5_K_M model,
enforce the 16-GiB RAM gate, and run a structured local test. An external Ollama
tray application or service is reported but is never terminated by SAGE.

## Direct diagnostics

```bat
.\sage.cmd status
.\sage.cmd status --live
.\sage.cmd model status
.\sage.cmd resource list
.\sage.cmd workspace doctor
.\sage.cmd workspace validate
.\sage.cmd --help
```

## Runtime identity

The main menu shows both the running SAGE version and its root directory. During pre-release testing, verify these if a menu or prompt looks older than the current build.
