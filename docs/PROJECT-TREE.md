# SAGE Project Tree

```text
SAGE-v0.01-rc7.04/
|-- sage / sage.cmd               Normal operator entry points
|-- bic / bic.cmd                 BIC shortcut wrappers
|-- saw / saw.cmd                 SAW shortcut wrappers
|-- .venv/                        Managed Python environment (runtime-created; not shipped)
|-- core/sage_core/               Deterministic controllers and CLI
|   |-- menu.py                   Guided setup, Projects, Jobs, Runs, recovery
|   |-- project_inventory.py      Role-neutral SAGE Project Inventory
|   |-- project_codes.py          Paratext <=8-character code parsing
|   |-- jobs.py                   Job/Run state + operator cue journal
|   |-- paratext_catalog.py       Persistent settings.xml-gated discovery catalogue
|   |-- original_language_resources.py  Governed @GRK/@HEB resolution + overrides
|   |-- resource_validation.py    Scripture/VRS/OL first-run and registry validation
|   |-- executors/                Provider transports; CODEX active in RC7.04
|   `-- ...                       Workflow/runtime controllers
|-- jobs/
|   |-- bic/                      Persistent BIC Jobs (empty in source release)
|   `-- saw/                      Persistent SAW Jobs (empty in source release)
|-- state/                        Runtime-created; not shipped in source release
|   |-- release-state.json        RC clean-start/version-boundary receipt
|   |-- setup-state.json          Resumable guided-setup snapshot
|   |-- project-inventory.json     SAGE translation Scripture/Paratext Projects
|   |-- paratext-project-catalog.json  Derived Paratext discovery catalogue
|   |-- original-language-resources.json  Explicit @GRK/@HEB source overrides
|   |-- active-jobs.json          Current BIC/SAW Job pointers
|   |-- last-run.json             Last Run resume pointer
|   |-- operator-cues.jsonl       Append-only high-level operator cues
|   |-- llm-settings.json         Provider/model settings
|   |-- runtime-state.json        Python/platform/dependency preflight record
|   `-- resource-mounts.json      Projects root, optional mappings, base VRS root
|-- workspace-data/
|   `-- scripture-projects/       SAGE-internal mutable Scripture-project storage
|-- resources/scripture/          Packaged/static VRS and governed Scripture resources
|   `-- original-language/        Governed @GRK/@HEB slots (authorised corpus only)
|-- resources/rwc/                RWC authority/source documentation
|-- profiles/languages/           Governed language/grammar profiles
|-- workflows/                    Independent BIC / SAW workflow profiles
|-- skills/                       Provider-neutral analytical Skills
|-- cache/                        Runtime-created caches; distribution-clean
|-- docs/                         Operator and governance documentation
|-- meta/                         Schemas, registries, governance
|-- scripts/                      Cross-platform Python validation/audit/build helpers
|-- tests/                        Regression inventory
|-- README.md                     Launch boundary
|-- HELP.md                       Compact menu/fallback map
`-- ecosystem.yml                 Static SAGE policy/configuration
```

`.venv/` is the managed Python environment. SAGE does not use a `/.env` directory for Python. The source archive intentionally omits `.venv/` because its executables and packages are platform/architecture-specific; the launcher creates or repairs it locally before SAGE imports application code. On macOS/Linux, dot-prefixed directories are hidden by default (`ls -la` shows them).

The source release also intentionally omits operator state. On first launch SAGE creates `state/`, records the RC release boundary, validates packaged VRS/Scripture resources, and begins with zero SAGE Projects. A clean first-run Scripture inventory is reported as `READY_EMPTY` until the operator adds Projects to SAGE.

Paratext/PTLite project folders remain external unless a TARGET uses SAGE-internal storage. Selecting the Projects root scans immediate child folders with valid `settings.xml` and writes the derived catalogue under `state/`; ordinary menus then use that catalogue for fast filtering and validation. `<Other location>` is available for exceptional paths and refreshes directly from the mapped folder. Matching single/double quotes around pasted paths are normalised. External Scripture reads are limited to `.SFM` and `.VRS`; only an explicitly configured BIC TARGET Job binding may write `.SFM`, and SAW/OL resources remain externally read-only.

`@GRK` and `@HEB` are governed resources separate from SAGE translation Projects. The source package ships their governed resource slots and override logic; authorised corpus data may populate those slots in a licensed distribution.

The operator cue journal is navigation/history evidence only. Run manifests and workflow transaction journals are authoritative for checkpointed work, governed writes, and recovery.

Release handovers must not contain runtime state, copied external Scripture payloads, beta-stage migration material, or a second full workspace mirror. Beta-stage migration references are kept outside the RC source tree.

Python source-maintenance rules: `docs/PYTHON-MAINTENANCE.md`.
