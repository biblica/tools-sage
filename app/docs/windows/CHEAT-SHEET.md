# SAGE Windows Cheat Sheet

## Start

Classic menu (current default):

```bat
.\sage.cmd
```

TUI development surface:

```bat
.\sage.cmd tui
```

The TUI uses the supplemental `system\requirements-tui.txt` profile. If that profile cannot be installed, the classic menu and scriptable CLI remain available.

Run SAGE from Command Prompt/PowerShell; do not start `codex` first. If the Codex CLI is missing, installation requires explicit Operator confirmation. SAGE resolves/validates `localdata`, creates or repairs `localdata\.system\runtime\venv`, then checks Codex and the persisted ChatGPT login.

`localdata\.system\runtime\venv` is **not shipped in Core** and SAGE does not use `.env`. The launcher creates it on first approved launch. Startup prints the running SAGE root, localdata root, and managed environment path before guided setup.

A pre-release version change records the new Core version but preserves existing recognized localdata. Projects, Jobs, Runs, reports, resources, settings, and Operator state are not deleted by a Git update or normal launch.

```text
shell -> SAGE -> Codex login / governed AI subprocess
```

## Main menu and TUI controls

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

The same `1`-`4` functional grammar and `A`-`F` global controls are used by the development TUI. Reports and Job recovery are under BIC/SAW; system recovery is under SAGE Maintenance. `F. Status` opens a non-destructive overlay and returns to the invoking view. The TUI targets a `100 x 30` terminal and shows System Status, Active AI, Project, and one sequential Active Job. Active Job progress is compact, for example `SAW_UK-ENG [████░░░░░░]  43%`.

The classic menu remains the default/fallback while TUI action parity is incomplete.

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

## Create BIC / SAW Job

Choose **Add BIC Job** or **Add SAW Job**. Role selectors list only SAGE Projects. **Add another Project to SAGE** temporarily opens Project administration and then returns to the selector. SAGE generates the canonical Job ID automatically; only the display name is optional to change.

## Final reports

SAGE validates and batches finalized Run findings into the owning Job's main report catalog. Final SAW reports do not remain in the Run `plans` folder:

```text
localdata\reports\<job-id>\GEN\GEN_001_ACTION-REPORT.md
localdata\reports\<job-id>\GEN\GEN_001_OPERATOR-NOTE.txt
```

The `<job-id>` segment is the owning Job ID, not a Project ID. The completion screen prints the exact paths. SAGE does not write reports into the mapped Paratext Project folder.

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
