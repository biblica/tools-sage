# Clone and Install

SAGE 0.01beta2 normally needs no separate setup command:

```text
git clone <repository> SAGE
cd SAGE
./sage
```

Windows uses `sage.cmd`. The launcher resolves/creates localdata, installs the pinned SAGE CPython
runtime when needed, and bootstraps the managed Python environment automatically. System Python is
not required.

## Canonical folders

The default zero-configuration result is:

```text
SAGE/
├── sage / sage.cmd   root launchers
├── app/              replaceable application files
└── localdata/        persistent operator/system data
    ├── inputs/       operator-supplied resources
    ├── work/         active Projects and Jobs
    ├── reports/      finalized human-facing reports
    ├── exports/
    ├── plugins/
    └── .system/      managed runtime/controller state
```

The approved base runtime is `localdata/.system/runtime/python`; the managed application environment
is `localdata/.system/runtime/venv`. Both are host-specific and are never committed or included in a
Core release.

## Clone helper

The helper is optional:

```text
./app/system/tools/clone_and_install.sh <repo> [target]          macOS/Linux
app\system\tools\clone_and_install.cmd <repo> [target]          Windows
```

It requires Git but not system Python. The wrapper uses SAGE-managed Python, clones Core, bootstraps
localdata, validates the managed runtime, and writes an installation receipt under
`localdata/.system/state/installation.json`.

The helper is non-destructive. If the effective localdata directory already exists and carries a
valid SAGE marker, it is reused. Existing Projects, Jobs, reports, resources, settings, and state are
not removed merely because Core was cloned again.

### Custom localdata

```text
./app/system/tools/clone_and_install.sh <repo> SAGE --data-home /absolute/path/to/localdata
```

A custom data home is persisted after successful bootstrap. The helper does not move or copy data.
An unrecognized non-empty target directory is rejected.

### New-host Paratext binding

```text
./app/system/tools/clone_and_install.sh <repo> SAGE \
  --mode new-host \
  --paratext-projects-root /absolute/path/to/Paratext-Projects
```

Windows accepts the corresponding absolute Windows path. SAGE matches portable Project identifiers
to direct Paratext/PTLite subfolders. Missing or ambiguous matches fail closed before governed
bindings are changed.

## Cross-platform launch

- Windows: `sage.cmd`
- macOS/Linux: `./sage`
- Managed Python shell on Windows: `app\sage-python.cmd`
- Managed Python shell on macOS/Linux: `./app/sage-python`

The launchers select the exact OS/CPU entry in `system/config/python-runtime.json`, reuse or download
that archive, verify its SHA-256, and execute bootstrap through the installed SAGE CPython. Application
code then runs inside the managed localdata environment. Paths are passed as argv values rather than
shell-evaluated command strings, so spaces and Unicode path components are supported.

`app/sage-python` opens an interactive Python shell in the managed environment. It also accepts normal
Python arguments, for example `./app/sage-python -m pip check` or `./app/sage-python -c "import sage"`.
