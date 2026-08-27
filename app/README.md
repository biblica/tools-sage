# SAGE v0.01beta

> **v0.01beta — pre-release Beta. Fresh exact-source qualification is required before the first release candidate; public-production readiness is not claimed.** This Beta includes BLOCK/interruption semantics, Windows Unicode/Codex execution hardening, UTF-8 controller I/O, canonical Scripture-aware report naming, evidence-preserving Job-layout maintenance, BIC commit preflight, governed regional Language Profiles, and compact Operator UI/reporting refinements. The classic menu and scriptable CLI remain supported while TUI parity is incomplete. Interfaces and persisted pre-release state may change incompatibly.

**SAGE** means **Scripture Analysis and Generation Engine**. It is a menu-first controller for two independent Scripture workflows:

- **BIC — Bible Index & Context** — `SOURCE + DONOR -> TARGET`.
- **SAW — Scripture Analysis Workbench** — `WIP + REFERENCE -> findings`, with bounded OL clarification only for qualifying source-text discrepancies.

## Run SAGE

- **Windows:** `.\sage.cmd`
- **macOS/Linux:** `./sage`
- **TUI — EXPERIMENTAL / UNSTABLE:** `./sage tui` on macOS/Linux or `.\sage.cmd tui` on Windows; the supplemental TUI dependency profile is bootstrapped automatically
- **Classic fallback:** `sage menu`

The portable bundle has two ownership roots: `<bundle>/app/` contains the replaceable application and `<bundle>/localdata/` contains persistent Operator-owned and machine-local data. Within localdata, `inputs/` holds Operator-supplied material, `work/` holds active Projects and Jobs, and top-level `reports/` remains the clear finalized-output surface. Use `sage data-home show`, `sage data-home set PATH`, or `SAGE_DATA_HOME` to select another data location. See `docs/advanced/architecture/STORAGE-AND-CORE-BOUNDARY.md`.

Open a terminal in the SAGE bundle root and run the matching launcher. The root files are thin forwarding entry points; application launchers and bootstrap logic remain under `app/system/bin/`. Do **not** start Codex first. SAGE remains the parent process, resolves or creates `localdata`, selects an approved existing Python.org/Homebrew runtime when available or installs the exact SHA-256-pinned SAGE runtime, creates/validates `localdata/.system/runtime/venv`, checks pinned dependencies, resumes incomplete setup when needed, remembers the last active Job/Run, and invokes Codex only for sign-in or bounded AI work. First use does not require a separate setup command, system Python, or Homebrew.

`0.01beta` includes an **EXPERIMENTAL / UNSTABLE** Textual migration surface. It may change incompatibly, contains incomplete and read-only workflows, and is not the authoritative Operator interface. The TUI targets `100 x 30`, uses persistent System / Active AI / Project / Active Job dashboard blocks, keeps numeric `1`-`6` navigation plus global `A`-`F` controls, and reports sequential Run progress with a compact 10-cell bar derived from governed ACT work. `F Status` is a live overlay that preserves the current view. Use the classic menu/CLI for authoritative workflow operations; see `docs/TUI.md`.

Startup classifies the host as **BASIC** when available RAM is below 4 GiB, logical CPU threads are below 8, or hardware detection fails; otherwise it selects **STANDARD**. BASIC defaults hardening to 2 workers and STANDARD to 4, while `SAGE_HARDENING_WORKERS` remains explicitly bounded. The machine-local receipt is `localdata/.system/state/host-capability.json`; it is outside Git-controlled Core.

Release qualification uses deterministic hardening shards plus a formal combine gate. Every discovered test module must be scheduled exactly once, every shard must bind to the same governed source SHA-256, and schema/package/deep-audit gates must remain green with no source mutation.

`0.01beta` keeps the compact provider handoff and makes Reference Text Comparison (RTC) planning discourse-first. RTC governs the original WIP slice toward about 6,000 estimated tokens, prefers clean discourse boundaries in the 5,000–7,000 range, and never intentionally plans a WIP packet at 8,000 tokens or above. The configured Reference Project follows the exact same Scripture range. Complete RTC handoff is targeted below 28,000 estimated tokens and hard-stopped at 32,000. OL is not carried in the normal RTC package; a qualifying major WIP–Reference source-text discrepancy creates a separate bounded OL clarification package for only the affected coordinate(s). Prose prefers sections/pericopes and paragraphs; poetry preserves Psalm/song units and operational stanzas, with consecutive `\q`/`\qN` lines remaining together until a governed poetry break. See `docs/advanced/models-and-ai/MODEL-HANDOFF-OPTIMIZATION.md`.

The source ZIP contains the launchers, `app/`, and an empty `localdata/` seed represented by its README. It does **not** contain a Python runtime, Python virtual environment, Jobs, reports, imported Projects, local resources, caches, or machine state. First launch reuses a validated approved host CPython 3.12 when available; otherwise it installs the architecture-specific runtime at `localdata/.system/runtime/python` from `system/config/python-runtime.json`. It then creates the environment at `localdata/.system/runtime/venv`. Startup prints the exact application root, localdata root, managed-environment path, Python version, runtime provider, and pre-release state-policy status before application setup begins.

For a Git-based deployment, normal use is `git clone` followed by `./sage` or `.\sage.cmd`; the launcher bootstraps localdata automatically. The optional [clone helper](system/tools/CLONE-AND-INSTALL.md) automates the same flow and can bind an existing Paratext Projects root on a new host. It never deletes an existing recognized localdata directory.

Pre-release version changes do **not** delete Operator, Project, Job, Run, report, resource, or settings data. `app/` is the replaceable application boundary; `localdata/` is persistent local state. A clean first installation begins with zero SAGE Projects, while a Git update or re-clone can reuse an existing recognized localdata root. The canonical portable layout is `SAGE/app` plus `SAGE/localdata`.

SAGE connects to OpenAI through the **local Codex CLI using ChatGPT sign-in**. The Codex desktop app is not required. OpenAI API keys, service accounts, direct API calls, and API fallback are prohibited.

Optional **Local AI** uses the existing Ollama admin-assistant switch and remains `ASSISTIVE_ONLY`; CODEX is still the only governed automated BIC/SAW provider. Local AI can phrase bounded status/diagnostic/action facts and produce a separate non-authoritative executive-summary artifact from compact canonical report metadata. It cannot receive raw Scripture/original-language payloads, cannot mutate canonical Job/Run/Project Scripture state, and never falls back to CODEX when local assistance fails. Local AI enablement does not scan or block Jobs. Basic primary-language work remains available; only a specific Job's secondary rendering is rejected when that operation requires Hosted AI. See `docs/advanced/models-and-ai/LOCAL-AI-ASSISTIVE-MODE.md`.

Paratext/PTLite integration is root-based: configure one machine-local **Paratext/PTLite Projects root** once. Initial setup and **Quick rescan** now perform a tree-only discovery pass: SAGE enumerates immediate child directories and checks only for the `settings.xml` marker without opening Project files. New Projects enter the catalog as **PENDING** until selected/used or explicitly validated. **Full rescan** opens Project metadata and Scripture inventory for every discovered Project and rebuilds detailed readiness/warning state. The same tree-only mechanism detects added/removed configured resources without reading their contents.

Grammar profiles are maintained from **SAGE Maintenance > Configure languages > Maintain grammar profiles** or **Scripture Projects > Maintain grammar profiles**. Operators can choose/register a compatible profile already present in SAGE's profile library or add a validated grammar-profile YAML file. Interactive setup that encounters `LANGUAGE_PROFILE_NOT_CONFIGURED` opens the same maintenance flow pre-filtered to the required language and Job role, and retries only after a compatible profile exists. Project addition also opens language-focused maintenance when the new Project's language namespace is absent; backing out does not remove the Project.

A vanilla installation may report its empty SAGE Project Inventory as `READY_EMPTY`, but workstation setup remains `INCOMPLETE` until the Paratext/PTLite Projects root is configured and available. The complete system check reports this separately and cannot promote `READY_EMPTY` to overall readiness by itself.

The workstation interface language is a Setup-owned setting independent from reporting and Scripture language. The 0.01 Beta line retains a human-editable formatted UTF-8 JSON menu source for `en-US`, `en-GB`, `id`, `fr`, `ru`, and `pt-BR`; choose it in guided Setup or with `D. Language` from any menu. Functional operations remain numeric. The global footer is two rows: `A Back / B Main Menu / C Exit SAGE`, then `D Language / E Help / F Status`. Help and Status are non-destructive overlays that return to the invoking menu. Startup performs a non-generative workflow-AI readiness check and reports the provider, selected model, and effective reasoning level; AI Setup renders the same canonical state. Only its explicit **Check LLM connection** action sends a test prompt. The existing global Operator reporting language remains the runtime primary, with one optional Job secondary. Projects do not own report-language settings.

## Operator fallback docs

Use documentation only when normal guided operation is insufficient:

- Windows: `docs/windows/CHEAT-SHEET.md`, `RECOVERY.md`, `ERRORS.md`
- macOS/Linux: `docs/macos-linux/CHEAT-SHEET.md`, `RECOVERY.md`, `ERRORS.md`

Project setup/maintenance: `docs/PROJECT-OPERATOR-CHEAT-SHEET.md`. The compact menu map is
`docs/OPERATOR-GUIDE.md`. Short Operator instructions remain at the `docs/` root; technical material
is grouped under `docs/advanced/`. Developer maintenance is under
`docs/advanced/maintenance/PYTHON-MAINTENANCE.md`.

## Hard boundaries

- **Local Evidence Boundary:** Job content evidence is SAGE-local, governed, explicitly authorized, and sealed into the task. Model recall/pretraining, external Scripture/translations/lexicons/commentary, web/search, and unstated facts are never evidence.
- **General Linguistic Competence:** the model may use orthographic, morphological, grammatical, and syntactic competence only to understand or express locally supported content. Linguistic competence may determine how locally supported content is expressed; it may not determine what the content is.
- BIC content authority is SOURCE; DONOR is lexical-only; routed OL is bounded evidence. SAW normally compares the WIP with the configured Reference Project. For an explicitly OL-routed bounded source-text question, configured GRK/HEB is the primary textual authority for that question; the Reference Project remains comparative evidence. Governed project indexes are index evidence only and derived packs inherit their source authority/restrictions.
- BIC and SAW have separate Jobs and Runs; SAGE Projects may be reused across roles where policy allows, but there is no automatic BIC/SAW handoff.
- BIC has one bound SOURCE, one bound DONOR, and one bound TARGET.
- Only an explicitly mapped BIC TARGET may write external `.SFM`; SAW is read-only.
- External Scripture reads are limited to `.SFM` and `.VRS`; `.VRS` is never written.
- BIC remains `INSPECT -> REWRITE -> SELF-CHECK`; protected rewrite/verb-selection contracts remain hash-pinned.
- SAGE owns state, validation, commits, recovery, and task write allowlists. The model receives only sealed governed tasks.
