# SAGE Help

Run SAGE directly from the normal terminal: `sage.cmd` on Windows or `./sage` on macOS/Linux. Do **not** start Codex first. SAGE remains the parent process and invokes Codex only for sign-in or bounded AI work.

```text
1  Scripture Projects
2  BIC
3  SAW
4  Reports
5  System / Configuration
6  Help / Operator Guide
7  Recovery / Diagnostics
0  Exit
```

Guided setup, Job/Run, and operator-cue state are persistent within the same RC version. Governed workflow transaction journals remain authoritative for writes and recovery.

First-launch checks occur before the menu: Python 3.10+, `venv`, pip/dependencies, RC clean-state boundary, then Scripture/VRS resource validation. The managed Python directory is `.venv`, not `.env`; it is created locally and is not included in the ZIP. Startup prints its exact path.


Project administration is under **Scripture Projects**. Configure the Paratext Projects root once; SAGE scans direct child folders with valid `settings.xml`, persists the Project catalogue, and builds discovery menus from that catalogue. Discovery filters are **FB / NT / Portions** and **Language**. Use **Paratext Projects root / rescan** for quick/full rescans.

The UI remains English. Bilingual report language overrides are configured per SAGE Project under **Project settings -> Reporting languages**. Governed `@GRK` / `@HEB` sources are configured separately under **Scripture Projects -> Original-language resources**.

Finalised Run findings are validated and batched into the owning Job's main report catalogue at `jobs/<tool>/<job-id>/reports/<BOOK>/`. The `<job-id>` segment names the Job, not a Project; Project reporting-language overrides affect rendering only. For example, SAW QA on `GEN 1` produces `GEN/GEN-001_YYYY-MM-DD_001_ACTION-REPORT.md` and the matching `_OPERATOR-NOTE.txt`. The completion screen prints the exact paths. Reports are never written into the Paratext Project folder.

Fallback docs:

- Windows: `docs/windows/CHEAT-SHEET.md`, `RECOVERY.md`, `ERRORS.md`
- macOS/Linux: `docs/macos-linux/CHEAT-SHEET.md`, `RECOVERY.md`, `ERRORS.md`

Direct command lookup: `sage.cmd --help` or `./sage --help`.

Developer/source maintenance: `docs/PYTHON-MAINTENANCE.md`.

During RC testing, the main menu prints the running SAGE version and root path. If those do not match the folder you just extracted, an older copy is being launched.
