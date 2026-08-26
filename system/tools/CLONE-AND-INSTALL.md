# Clone and Install

SAGE 0.01beta normally needs no separate setup command:

```text
git clone <repository> SAGE
cd SAGE
./sage
```

Windows uses `sage.cmd`. The launcher resolves/creates SAGEdata and bootstraps the managed Python
environment automatically.

## Canonical folders

The default zero-configuration result is:

```text
<parent>/
├── SAGE/       Git-controlled Core
└── SAGEdata/   persistent operator/system data
```

The managed Python environment is `SAGEdata/.system/runtime/venv`. It is host-specific and is never
committed or included in a Core release.

## Clone helper

The helper is optional:

```text
python system/tools/clone_and_install.py <repo> [target]
```

It requires System Python 3.10+ and Git. It clones Core, bootstraps SAGEdata, validates the managed
runtime, and writes an installation receipt under `SAGEdata/.system/state/installation.json`.

The helper is non-destructive. If the effective SAGEdata directory already exists and carries a
valid SAGE marker, it is reused. Existing Projects, Jobs, reports, resources, settings, and state are
not removed merely because Core was cloned again.

### Custom SAGEdata

```text
python system/tools/clone_and_install.py <repo> SAGE --data-home /absolute/path/to/SAGEdata
```

A custom data home is persisted after successful bootstrap. The helper does not move or copy data.
An unrecognized non-empty target directory is rejected.

### New-host Paratext binding

```text
python system/tools/clone_and_install.py <repo> SAGE \
  --mode new-host \
  --paratext-projects-root /absolute/path/to/Paratext-Projects
```

Windows accepts the corresponding absolute Windows path. SAGE matches portable Project identifiers
to direct Paratext/PTLite subfolders. Missing or ambiguous matches fail closed before governed
bindings are changed.

## Cross-platform launch

- Windows: `sage.cmd`
- macOS/Linux: `./sage`

The launchers select a System Python 3.10+ interpreter only long enough to run bootstrap. Application
code then runs inside the managed SAGEdata environment. Paths are passed as argv values rather than
shell-evaluated command strings, so spaces and Unicode path components are supported.
