# Storage and Core Boundary

SAGE 0.01beta uses a hard ownership boundary between the Git-controlled product and local data.

## Canonical layout

```text
<parent>/
├── SAGE/                       # Git-controlled Core
└── SAGEdata/                   # persistent local/operator data
    ├── projects/
    ├── jobs/
    ├── resources/
    ├── plugins/
    ├── reports/
    ├── exports/
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
        └── runtime/venv/
```

The zero-configuration default is a sibling `SAGEdata` directory in the same parent directory as
`SAGE`. `SAGEdata` may be placed elsewhere on a writable local disk, external volume, or suitable
network location.

## Ownership rules

`SAGE/` is replaceable and reproducible. It contains code, launchers, schemas, defaults, approved
built-in templates, approved localization resources, documentation, tests, and only resources that
have passed SAGE Core review and qualification. Runtime code must not write operator or machine
state into this tree.

`SAGEdata/` is persistent. Visible top-level folders are operator-facing data. `.system/` is SAGE-
managed local state and is hidden by convention on macOS/Linux. The leading dot is not a security
boundary.

- `projects/` holds SAGE-managed/imported Project content. Imported resources should retain an
  immutable `original/` representation and a derived `parsed/` representation where applicable.
- `jobs/` holds durable human-facing Job manifests, Runs, diagnostics, and exports.
- `resources/` holds local/operator-created or candidate resources that are not SAGE Core.
- `plugins/` is reserved for locally installed, separately governed extensions.
- `reports/` holds polished Operator-facing reports.
- `exports/` holds portable exports.
- `.system/` holds mutable configuration overlays, machine state, controller Job state, caches,
  locks, transactions, logs, diagnostics, temporary files, and the managed Python environment.

## SAGEdata resolution

Resolution precedence is:

1. global `--data-home PATH` for the invocation;
2. `SAGE_DATA_HOME` environment variable;
3. the persisted per-installation custom pointer;
4. sibling `<parent>/SAGEdata`.

Commands:

```text
./sage data-home show
./sage data-home set /absolute/path/to/SAGEdata
./sage data-home reset
```

Windows uses the same commands through `sage.cmd`.

`data-home set` does not move or copy existing data. `data-home reset` clears only the pointer and
returns future launches to the sibling default. If a persisted custom location is unavailable,
startup fails closed rather than silently creating a new empty data root elsewhere.

A very small locator is stored in the operating system's normal per-user configuration location so
a custom `SAGEdata` path survives Git replacement of `SAGE/`. It contains only the data-home path;
all substantive SAGE state remains in `SAGEdata`.

## Safety invariants

- `SAGEdata` must never be inside `SAGE/`.
- An unrecognized non-empty directory is never adopted automatically as `SAGEdata`.
- A marker under `.system/data-root.json` identifies a SAGEdata root.
- Version changes do not delete Projects, Jobs, reports, resources, settings, or other persistent
  data.
- Ordinary cleanup/reset clears only explicitly regenerable `.system` state.
- Out-of-box reset is a separately named, explicitly confirmed destructive action bounded to known
  SAGEdata subtrees; it must not modify Core.
- Core release validation fails if local/runtime roots such as `.venv`, `workspace_data`, `jobs`,
  `reports`, or `SAGEdata` appear in the Git-controlled source root.
- Concurrent development worktrees must use separate `SAGE_DATA_HOME` values unless shared local
  state is explicitly intended.

## Git update contract

A supported update is:

```text
stop active SAGE processes
verify Git working tree
pull/checkout qualified Core
run ./sage (or .\sage.cmd)
```

The updated Core discovers the existing `SAGEdata`, validates its marker and local configuration,
and starts without replacing operator data. Active SAGE processes should be stopped before changing
Core files.
