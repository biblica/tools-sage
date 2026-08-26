# SAGE Project Tree

SAGE 0.01beta separates replaceable Git-controlled Core from persistent local data.

```text
<parent>/
├── SAGE/
│   ├── .github/workflows/       Windows/macOS/Linux CI qualification
│   ├── .gitattributes           cross-platform line-ending policy
│   ├── .gitignore               Core hygiene / defense-in-depth exclusions
│   ├── README.md
│   ├── VERSION
│   ├── ecosystem.yml            immutable shipped defaults/policy
│   ├── sage                     macOS/Linux entry point
│   ├── sage.cmd                 Windows entry point
│   ├── docs/                    Operator and advanced documentation
│   └── system/
│       ├── bin/                 workflow/application launchers
│       ├── src/sage/            application package
│       ├── config/
│       │   ├── profiles/grammar/ reviewed Core grammar profiles
│       │   ├── project-management/ governed internal PM records
│       │   ├── schemas/          governed configuration/data schemas
│       │   └── workflows/        Core workflow policy/profiles
│       ├── resources/           tested and approved Core resources only
│       ├── skills/              governed Core analytical/controller skills
│       ├── tools/               bootstrap, audit, release and maintenance tools
│       ├── tests/               portable regression/contract tests
│       ├── pyproject.toml
│       ├── requirements.txt
│       ├── requirements-tui.txt
│       └── requirements-dev.txt
│
└── SAGEdata/
    ├── projects/                Operator/SAGE Project data
    ├── jobs/                    durable Job/Run data
    │   ├── bic/
    │   └── saw/
    ├── resources/               local/candidate resources; not Core
    │   └── grammar-profiles/    validated local grammar-profile candidates
    ├── plugins/                 reserved local plugin installation surface
    ├── reports/                 polished Operator-facing deliverables
    ├── exports/                 portable exports
    └── .system/                 hidden SAGE-managed local internals
        ├── config/              mutable local settings/overrides
        ├── state/               setup, inventory, mounts, pointers, receipts
        ├── jobs/                controller-only Job runtime/config/state
        ├── workflows/           workflow runtime state/output
        ├── indexes/
        ├── cache/
        ├── locks/
        ├── transactions/
        ├── logs/
        ├── diagnostics/
        ├── temp/
        └── runtime/venv/        host-specific scripted Python environment
```

The default data root is the sibling `SAGEdata`, but it is configurable. See
`STORAGE-AND-CORE-BOUNDARY.md`.

## Ownership and update boundaries

`SAGE/` is the Git/update boundary. It contains only reproducible product material. Built-in
resources, localization files, profiles, schemas, templates, and Skills become Core only when they
have been reviewed, tested, approved, and qualified for release. Operator-created, imported,
modified, experimental, or candidate resources stay in `SAGEdata/`.

`system/` is an internal Core application directory, not the persistence boundary. No root `state/`
or root `cache/` exists in Core, and no normal runtime operation may create one. Mutable state is
written below `SAGEdata/.system/`; visible Operator content is written to the appropriate visible
`SAGEdata/` collection.

`ecosystem.yml` is a shipped Core baseline. Mutable workstation/operator settings are applied from
`SAGEdata/.system/config/` overlays; normal operation must not rewrite Core configuration.

Internal project-management records are governed under `system/config/project-management/` and are
not part of the Operator documentation index.

## Project resources

A SAGE-managed Project lives under `SAGEdata/projects/<project-id>/`. Imported resources keep source
provenance and derived representations separately, for example:

```text
SAGEdata/projects/<project-id>/
├── sources/
│   ├── original/
│   └── parsed/
└── styleguide/
    ├── original/
    └── parsed/
```

External Paratext/PTLite Projects remain at their Operator-configured external location and are
mounted by absolute machine-local state; they are not copied into Core.

## Jobs, runtime state, and reports

Human-facing Job manifests/Runs remain under `SAGEdata/jobs/<tool>/<job-id>/`. Controller-only state,
locks, transactions, indexes, cache, runtime profiles, and derived settings live under
`SAGEdata/.system/jobs/<tool>/<job-id>/`. Workflow-level generated state lives below
`SAGEdata/.system/workflows/`.

Polished Operator-facing deliverables are published under `SAGEdata/reports/<job-id>/...`; they are
never written into Core or external Scripture Projects.

## Release and handover hygiene

A clean Core source/release must not contain `.venv`, `workspace_data`, top-level `jobs`, top-level
`reports`, `SAGEdata`, generated caches, or machine-specific state. Those names are retained in
release audits only as forbidden legacy/local roots. Runtime Python dependencies are created
scriptedly at `SAGEdata/.system/runtime/venv`; environments are never copied into a release.

`SAGE/` may be replaced by a Git pull, checkout, or clean re-clone while `SAGEdata/` persists. Version
changes record release state but do not delete Project, Job, report, resource, or operator settings.

Git workflow: `docs/advanced/maintenance/GIT-WORKFLOW.md`.
Python maintenance contract: `docs/advanced/maintenance/PYTHON-MAINTENANCE.md`.
Future contribution governance: `docs/advanced/future/RESOURCE-HUB.md`.
