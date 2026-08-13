# SAGE v0.01-rc7.04

SAGE is a menu-first controller for two independent Scripture workflows:

- **BIC** — `SOURCE + DONOR -> TARGET`.
- **SAW** — `WIP + REFERENCE (+ OL) -> findings`.

## Run SAGE

- **Windows:** `sage.cmd`
- **macOS/Linux:** `./sage`

Run the launcher directly from the normal terminal; do **not** start Codex first. SAGE remains the parent process, creates/validates its local `.venv` before loading application code, checks prerequisites, resumes incomplete setup when needed, remembers the last active Job/Run, and invokes Codex only for sign-in or bounded AI work. First use does not require a Start Here document.

The source ZIP intentionally does **not** contain `.venv` (and SAGE does not use a `.env` directory). `.venv` is machine/OS specific and is created beside the `sage` launcher on the first approved launch. On macOS/Linux it is hidden by default because its name begins with `.`. Startup prints the exact SAGE root, `.venv` path, Python version, and RC clean-start status before application setup begins.

During release-candidate testing, each **new RC version starts with clean operator/project/workflow state**. SAGE does not migrate RC state forward; the local `.venv` is preserved. The first guided setup validates packaged VRS files and the SAGE Project Inventory before BIC/SAW configuration. Zero SAGE Projects is the expected clean starting state.

SAGE connects to OpenAI through the **local Codex CLI using ChatGPT sign-in**. The Codex desktop app is not required. OpenAI API keys, service accounts, direct API calls, and API fallback are prohibited.

Paratext/PTLite integration is root-based: configure one machine-local **Paratext/PTLite Projects root** once. SAGE immediately builds a persistent discovery catalogue from immediate child folders that contain a valid `settings.xml`. It preparses Project name/language, included books, `.SFM` inventory, and descriptive `custom.vrs` metadata so normal Project menus and the **FB / NT / Portions + Language** filters do not repeatedly rescan the filesystem. Add only the Projects SAGE should use to SAGE; BIC/SAW Jobs then bind those role-neutral SAGE Projects. `<Other location>` remains available for exceptional paths.

The RC7 terminal UI remains English. Reports are bilingual, with a per-Project primary/secondary language override and global fallback. Governed original-language aliases `@GRK` and `@HEB` are maintained separately from ordinary SAGE Project inventory and may be explicitly reconfigured to authorised Paratext or local resources.

## Operator fallback docs

Use documentation only when normal guided operation is insufficient:

- Windows: `docs/windows/CHEAT-SHEET.md`, `RECOVERY.md`, `ERRORS.md`
- macOS/Linux: `docs/macos-linux/CHEAT-SHEET.md`, `RECOVERY.md`, `ERRORS.md`

Project setup/maintenance: `docs/PROJECT-OPERATOR-CHEAT-SHEET.md`. Shared workflow rules remain under `docs/`. Developer maintenance: `docs/PYTHON-MAINTENANCE.md`.

## Hard boundaries

- BIC and SAW have separate Jobs and Runs; SAGE Projects may be reused across roles where policy allows, but there is no automatic BIC/SAW handoff.
- BIC has one bound SOURCE, one bound DONOR, and one bound TARGET.
- Only an explicitly mapped BIC TARGET may write external `.SFM`; SAW is read-only.
- External Scripture reads are limited to `.SFM` and `.VRS`; `.VRS` is never written.
- BIC remains `INSPECT -> REWRITE -> SELF-CHECK`; protected rewrite/verb-selection contracts remain hash-pinned.
- SAGE owns state, validation, commits, recovery, and task write allowlists. The model receives only sealed governed tasks.
