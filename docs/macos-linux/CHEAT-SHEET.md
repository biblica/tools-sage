# SAGE macOS/Linux Cheat Sheet

## Start

```sh
./sage
```

Run SAGE from the normal shell; do not start `codex` first. If the Codex CLI is missing, installation requires explicit operator confirmation. SAGE validates/repairs its local `.venv`, then checks Codex and the persisted ChatGPT login.

`.venv` is **not shipped in the ZIP** and SAGE does not use `.env`. It is created in the extracted SAGE root on first approved launch. Because it begins with `.`, Finder and normal `ls` output may hide it; use `ls -la` to see it.
Startup prints the running SAGE root and managed `.venv` path before guided setup.

On the first launch of each new RC version, SAGE resets prior RC operator/project/workflow state and validates Scripture/VRS resources. The expected initial Scripture inventory is empty. `.venv` is preserved.

```text
shell -> SAGE -> Codex login / governed AI subprocess
```

## Main menu

```text
1  Resume unfinished work / start a new task
2  BIC
3  SAW
4  Reports
5  System / Configuration
6  Help / Operator Guide
7  Recovery / Diagnostics
0  Exit
```

## Paratext / PTLite

Configure a reusable projects root once under **System / Configuration -> Paths and storage**.

Examples:

```text
/Volumes/Win11Arm64/Paratext Projects
/Users/NAME/Paratext Projects
/mnt/paratext/Paratext Projects
```

SAGE then discovers immediate project subfolders and stores mappings as **projects root + subfolder**. When maintaining a SAGE Project, you may paste either the direct project folder or the parent Projects root. If the parent contains a direct child matching the selected Project code, SAGE selects that child automatically. Pasted paths may be unquoted, single/double quoted, or use `\ ` for spaces; SAGE normalises them before validation.

External reads remain limited to `.SFM` and `.VRS`. Only an explicitly authorised BIC TARGET may write `.SFM`.

## Create BIC / SAW Job

Choose **Add BIC Job** or **Add SAW Job**. Role selectors list only SAGE Projects. **Add another Project to SAGE** temporarily opens Project administration and then returns to the selector. SAGE generates the canonical Job ID automatically; only the display name is optional to change.

## Final reports

SAGE validates and batches finalised Run findings into the owning Job's main report catalogue. Final SAW reports do not remain in the Run `plans/` folder:

```text
jobs/saw/<job-id>/reports/GEN/GEN-001_2026-08-13_001_ACTION-REPORT.md
jobs/saw/<job-id>/reports/GEN/GEN-001_2026-08-13_001_OPERATOR-NOTE.txt
```

The `<job-id>` segment is the owning Job ID, not a Project ID. The completion screen prints the exact paths. SAGE does not write reports into the mapped Paratext Project folder.

## Models

Provider status separates **Codex CLI + ChatGPT execution readiness** from the live model catalogue. A catalogue-query error is diagnostic and does not erase a verified ChatGPT login.

## Direct diagnostics

```sh
./sage status
./sage status --live
./sage model status
./sage resource list
./sage workspace doctor
./sage workspace validate
./sage --help
```

## Runtime identity

The main menu shows both the running SAGE version and its root directory. During RC testing, verify these if a menu or prompt looks older than the current build.
