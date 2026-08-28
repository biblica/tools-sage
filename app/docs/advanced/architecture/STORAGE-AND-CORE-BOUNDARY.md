# Storage and Core Boundary

SAGE 0.02alpha1 uses a hard ownership boundary between the Git-controlled product and local data.

## Canonical layout

```text
SAGE/                            # portable bundle / Git repository
├── sage / sage.cmd             # root launchers
├── app/                        # replaceable application
└── localdata/                  # persistent local/operator data
    ├── inputs/
    │   ├── resources/
    │   ├── styleguides/
    │   └── semantic-domains/
    ├── work/
    │   ├── projects/
    │   └── jobs/
    ├── reports/
    ├── exports/
    ├── plugins/
    └── .system/
        ├── config/
        ├── state/
        ├── jobs/
        ├── workflows/
        ├── indexes/
        ├── cache/
        ├── locks/
        ├── transactions/
        ├── logs/
        ├── diagnostics/
        ├── temp/
        └── runtime/
            ├── python/
            ├── downloads/
            └── venv/
```

The zero-configuration default is `<bundle>/localdata`, beside `<bundle>/app`. The whole bundle can
therefore be moved as one directory. `localdata` may instead be placed elsewhere on a writable local
disk, external volume, or suitable network location.

## Ownership rules

`app/` is replaceable and reproducible. It contains code, schemas, defaults, approved
built-in templates, approved localization resources, documentation, tests, and only resources that
have passed SAGE Core review and qualification. Runtime code must not write operator or machine
state into this tree.

`localdata/` is persistent. Visible top-level folders are operator-facing data. `.system/` is SAGE-
managed local state and is hidden by convention on macOS/Linux. The leading dot is not a security
boundary.

- `inputs/` holds operator-supplied resources. `styleguides/` and `semantic-domains/` are explicit
  reserved inputs rather than being mixed into working or output folders.
- `work/projects/` holds SAGE-managed/imported Project content. Imported resources should retain an
  immutable `original/` representation and a derived `parsed/` representation where applicable.
- `work/jobs/` holds durable human-facing Job manifests, Runs, diagnostics, and intermediate data.
- `inputs/resources/` holds local/operator-created or candidate resources that are not SAGE Core.
- `plugins/` is reserved for locally installed, separately governed extensions.
- `reports/` remains a separate top-level collection for polished Operator-facing reports.
- `exports/` holds portable exports.
- `.system/` holds mutable configuration overlays, machine state, controller Job state, caches,
  locks, transactions, logs, diagnostics, temporary files, and the managed Python environment.

## localdata resolution

Resolution precedence is:

1. global `--data-home PATH` for the invocation;
2. `SAGE_DATA_HOME` environment variable;
3. the persisted per-installation custom pointer;
4. portable default `<bundle>/localdata`.

Commands:

```text
./sage data-home show
./sage data-home set /absolute/path/to/localdata
./sage data-home reset
```

Windows uses the same commands through `sage.cmd`.

`data-home set` does not move or copy existing data. `data-home reset` clears only the pointer and
returns future launches to the sibling default. If a persisted custom location is unavailable,
startup fails closed rather than silently creating a new empty data root elsewhere.

A very small locator is stored in the operating system's normal per-user configuration location so
a custom `localdata` path survives Git replacement of `SAGE/`. It contains only the data-home path;
all substantive SAGE state remains in `localdata`.

## Safety invariants

- `localdata` must never overlap or be nested inside `app/`.
- An unrecognized non-empty directory is never adopted automatically as `localdata`.
- A marker under `.system/data-root.json` identifies a localdata root.
- Version changes do not delete Projects, Jobs, reports, resources, settings, or other persistent
  data.
- Ordinary cleanup/reset clears only explicitly regenerable `.system` state.
- Out-of-box reset is a separately named, explicitly confirmed destructive action bounded to known
  localdata subtrees; it must not modify Core.
- Application release validation fails if local/runtime roots such as `.venv`, `workspace_data`,
  `jobs`, `reports`, or `localdata` appear inside `app/`. Only `localdata/README.md` is tracked at the
  bundle boundary; all runtime contents are ignored.
- Concurrent development worktrees must use separate `SAGE_DATA_HOME` values unless shared local
  state is explicitly intended.

## Managed Python bootstrap

The source distribution contains no Python interpreter or copied virtual environment. Before any
Python application code runs, the POSIX shell or Windows PowerShell bootstrap resolves localdata and
detects the OS/CPU pair. It first accepts an approved CPython 3.12 host runtime: a Python Software
Foundation-signed Python.org installation, or an existing Homebrew installation on macOS. If none
is available, it selects one exact artifact from `system/config/python-runtime.json`, reuses a cached
verified archive when possible, or downloads and verifies the governed SHA-256 before installing it
at `localdata/.system/runtime/python`. Every provider creates or repairs `runtime/venv` from the
selected interpreter, and the runtime receipt records the exact patch version, provider, and path.

The supported manifest targets are macOS ARM64/x86-64, Linux ARM64/x86-64, and Windows x86-64.
Host Python and package managers are optional; copied `.venv` folders are never bootstrap inputs.
A failure renders a BLOCKED runtime installation report. It offers the SAGE-managed runtime again,
an explicitly approved Homebrew or WinGet Python installation when available, or exit. SAGE never
installs a package manager. A non-interactive invocation prints the same report and exits safely.

## Git update contract

A supported update is:

```text
stop active SAGE processes
verify Git working tree
pull/checkout qualified Core
run ./sage (or .\sage.cmd)
```

The updated Core discovers the existing `localdata`, validates its marker and local configuration,
and starts without replacing operator data. Active SAGE processes should be stopped before changing
Core files.
