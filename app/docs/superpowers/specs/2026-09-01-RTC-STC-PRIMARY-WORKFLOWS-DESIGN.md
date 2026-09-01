# RTC and STC Primary Workflows Design

## Purpose

SAGE will replace the operator-facing Scripture Analysis Workbench (SAW) flow with two independent primary workflows:

- Reference Text Comparison (RTC), which compares one WIP Project with one distinct REFERENCE Project.
- Source Text Correspondence (STC), which compares one WIP Project directly with the applicable bundled original-language authority, `GRK` or `HEB`.

The change makes each workflow's authority, Job identity, imported Project snapshot, Run identity, structural deficiencies, and reports explicit. Existing shared analytical modules remain reusable implementation internals; SAW is no longer an operator-facing workflow or Job contract.

## Governing principles

1. Paratext remains the real authority for an operator's Scripture Project. SAGE analyzes a static USJ import and never presents that import as a replacement for Paratext.
2. Every RTC or STC Job records which imported WIP Project snapshot was benchmarked.
3. A Run seals its selected USJ evidence so refreshing a Job cannot alter evidence already under analysis.
4. Structural deficiencies are reported facts, not failed analysis. They must not abort an otherwise executable Run.
5. RTC and STC reports identify every Project and textual authority explicitly. They do not use an unidentified generic `WIP` label.
6. SAGE never silently changes governed Project, Job, Run, or report data while reporting a deficiency.

## Primary workflow architecture

The Main Menu exposes BIC, RTC, and STC as separate primary flows. It does not expose SAW.

RTC and STC each own:

- their Job type and active-Job pointer;
- Job creation, opening, management, and readiness display;
- bounded Run creation and serial allocation;
- reports, exports, and recovery;
- workflow-specific bindings and validation.

Existing SAW orchestration, RTC/STC planners, slicers, model routing, structural inspection, consolidation, and report rendering may be adapted and reused behind these interfaces. Reuse must not leak a SAW identity into new Job manifests, active pointers, operator menus, report paths, report headings, or new canonical artifact identifiers.

Existing Targeted Check and standalone Original-Language Review code remains in the repository but is removed from operator menus and marked as parked work in the project's development backlog. No migration from legacy SAW Jobs, Runs, or reports is required.

## RTC contract

An RTC Job binds exactly:

- `WIP Project`: one onboarded Scripture Project with analyzable imported content;
- `REFERENCE Project`: a different onboarded Scripture Project whose governed content is locked for comparison.

Job creation rejects selecting the same Project for both roles and keeps the operator in the Job-management flow with a corrective message.

RTC normally uses no original-language text. Advanced RTC option `#10`, Original-Language Review, may route bounded `GRK` evidence for New Testament scope or `HEB` evidence for Old Testament scope during that RTC Run. This is an in-Run evidence option, not a third Job binding and not a separate primary workflow.

An RTC report header uses concrete identities:

```text
Analysis                     RTC
WIP Project                  ukrNPUv1
WIP snapshot date            2026-09-01
WIP fingerprint              <sha256>
REFERENCE Project            usNIVv2
Comparison authority         usNIVv2
REFERENCE fingerprint        <sha256>
Original-language authority  NOT USED
```

When option `#10` routes original-language evidence, the last line is `GRK` or `HEB`, and the header includes that authority's fingerprint.

## STC contract

An STC Job binds exactly one operator Project:

- `WIP Project`: one onboarded Scripture Project with analyzable imported content.

STC never requests, stores, validates, or uses a REFERENCE Project. It selects the bundled authority from the Run scope:

- New Testament scope uses `GRK`.
- Old Testament scope uses `HEB`.

A mixed-testament request is partitioned into bounded units with the appropriate authority recorded for each unit. The Job remains a single-Project STC Job.

An STC report header uses concrete identities:

```text
Analysis                     STC
WIP Project                  ukrNPUv1
WIP snapshot date            2026-09-01
WIP fingerprint              <sha256>
Original-language authority  GRK
Authority fingerprint        <sha256>
REFERENCE Project            NOT USED
```

Old Testament reports show `HEB`. For the current release, reports use the exact authority names `GRK` and `HEB`; labels such as `GRK:PRIMARY`, `HEB:PRIMARY`, or an unnamed `source` are not operator-facing authority identities.

All STC report prose names the Project. For example:

```text
Project ukrNPUv1 contains an OMISSION at JHN 5:4 relative to GRK.
```

## Imported snapshot and Job identity

Project Inventory remains the current register of onboarded Projects. When SAGE creates or refreshes an RTC or STC Job, it imports current Project content to USJ and records a WIP snapshot receipt containing at least:

- Project identifier;
- import date and time in an unambiguous ISO-8601 form;
- display date in the configured operator timezone;
- deterministic content fingerprint over the imported, normalized WIP payload;
- imported Book inventory and coordinate coverage;
- source-location provenance needed to guide the operator back to Paratext.

The canonical Job identifier uses workflow, WIP Project, and snapshot date:

```text
RTC-ukrNPUv1_20260901
STC-ukrNPUv1_20260901
```

The date is the WIP import snapshot date, not the execution date. A same-day refresh that changes the fingerprint updates the existing current Job snapshot rather than creating retained snapshot history. The Job retains only its current imported snapshot.

When a refresh changes the snapshot date, SAGE keeps the same logical Job record but rotates its operator-facing canonical Job identifier to the new date and updates the active pointer atomically. Completed Run and report artifacts retain the snapshot-dated identifiers with which they were sealed. They are Run evidence, not retained copies of the mutable imported Project; SAGE does not retain the superseded whole-Project USJ snapshot merely to reconstruct old imports.

Refreshing a Job replaces its current imported USJ and snapshot receipt only when no active Run depends on mutable Job data. Every created Run seals a copy or immutable receipt of its selected USJ scope, snapshot date, fingerprint, bindings, authorities, and resource fingerprints. Completed and in-progress Run evidence therefore remains stable after a later Job refresh.

## Run identity

Runs against the same Job snapshot receive a monotonically increasing, three-digit serial:

```text
RTC-ukrNPUv1_20260901-001
RTC-ukrNPUv1_20260901-002
STC-ukrNPUv1_20260901-001
```

The serial, rather than the execution timestamp, is the operator-facing Run identity. Internal audit metadata may retain created, started, completed, and published timestamps, but those timestamps do not define the benchmark identity or replace the snapshot date in names and headers.

A snapshot refresh that does not change the Job identifier continues serial allocation without reusing an existing Run identifier. Run creation is atomic so concurrent or retried creation cannot allocate the same serial.

## Report storage and naming

Job and report roots use the canonical Job identifier. Reports are organized by canonical USFM Book code and zero-padded, three-digit chapter:

```text
localdata/.system/work/jobs/rtc/
└── RTC-ukrNPUv1_20260901/
    └── runs/
        ├── RTC-ukrNPUv1_20260901-001/
        └── RTC-ukrNPUv1_20260901-002/

localdata/reports/
└── RTC-ukrNPUv1_20260901/
    ├── JOB-SUMMARY.md
    ├── JHN/
    │   └── 005/
    │       └── RTC-ukrNPUv1_20260901-001_JHN-005_ACTION-REPORT.md
    └── ROM/
        └── 001/
            └── RTC-ukrNPUv1_20260901-001_ROM-001_ACTION-REPORT.md
```

STC uses the same layout with the `STC-` prefix. A Run spanning multiple chapters publishes one chapter-scoped report per Book/chapter. Job-wide summaries and indexes live at the Job report root and link to those reports. Operator-note and export artifacts follow the same canonical stem and Book/chapter location.

## Structural deficiency model

SAGE distinguishes executable text deficiencies from runtime failures.

The pre-Run or Job status is `READY_WITH_STRUCTURE_PROBLEMS` when the resources can be analyzed but contain structural deficiencies. A versification difference also exposes the specific status flag `VERSIFICATION_MISMATCH`.

During a Run, deterministic structural inspection records every affected coordinate, evidence stream, Project or authority identity, classification, effect on comparison evidence, and operator action. These records are sealed into the Run and included in Job summaries and Book/chapter reports.

An otherwise completed Run with one or more structural deficiencies has final status:

```text
COMPLETE_WITH_STRUCTURE_PROBLEMS
```

It must not become `ERROR`, `FAILED`, or `BLOCKED` solely because of:

- a missing Job binding or Project-register mismatch that can be diagnosed and corrected before execution;
- a versification mismatch or unmapped coordinate;
- absent comparison-source text at a valid WIP coordinate;
- a source-text addition, omission, variation, or consistency concern.

Missing Project bindings are reported as `STRUCTURE_PROBLEM` with the exact missing role, Project identifier, and onboarding or Job-management action. If a required Project is unavailable, SAGE keeps the Job visible as `ACTION_NEEDED`; it does not start an evidence comparison for which no data exists and does not label the Job itself as a failed Run.

Finding classification is evidence-based:

- `OMISSION`: the comparison authority has text and the WIP Project lacks it.
- `ADDITION`: the WIP Project has text and the comparison authority lacks it.
- `VARIATION`: both contain text but wording differs.
- `CONSISTENCY`: repeated comparable occurrences are treated inconsistently.
- `STRUCTURE_PROBLEM`: versification, coordinate mapping, binding, or other structural metadata is deficient.

A coordinate may have both a structural fact and the resulting `ADDITION` or `OMISSION` when evidence supports both. A missing Project binding alone cannot establish addition or omission because there is no comparison evidence.

True failure remains reserved for conditions that make safe, trustworthy execution impossible, including software faults, malformed or corrupted governed evidence, unsafe paths, prohibited writes, immutable Run/plan/result drift, and incomplete or irreconcilable WIP analytical coverage.

## Resource Status Report

SAGE Maintenance provides a read-only `Resource Status Report`. It inventories all onboarded Scripture resources and highlights resources bound to the active RTC and STC Jobs.

For every resource it shows:

- Project identifier, display name, and configured source location;
- current RTC/STC role or `UNBOUND`;
- content state;
- available Books and coordinate coverage;
- versification base, custom versification data, and mismatch state;
- WIP snapshot date and fingerprint when bound to a current Job;
- `GRK` or `HEB` authority identity and fingerprint where applicable;
- structural problems, affected scope, and concrete operator action;
- aggregate status: `READY`, `READY_WITH_STRUCTURE_PROBLEMS`, or `ACTION_NEEDED`.

The report diagnoses state only. It never repairs resources, changes bindings, refreshes snapshots, or blocks RTC/STC merely because a reportable deficiency exists.

## Job management

Each RTC and STC flow includes `Manage Job`. It supports:

- opening or selecting an existing Job;
- creating a Job with workflow-valid Project selections;
- changing the WIP Project;
- changing the RTC REFERENCE Project;
- refreshing the imported WIP snapshot from the authoritative Project location;
- displaying snapshot date, fingerprint, bindings, resource state, and structural status;
- archiving or removing a Job through existing governed confirmation patterns.

STC Job management never displays a REFERENCE selector. RTC prevents the same Project from occupying both WIP and REFERENCE roles at creation and update time.

Before opening a Job and again before creating a Run, SAGE checks bindings against Project Inventory. It gathers all missing or invalid roles into one actionable report rather than stopping at the first exception. The affected Job stays visible under `ACTION_NEEDED`, the surrounding menu remains usable, and the operator can open guided Project onboarding or correct the Job binding.

## Maintenance and reset behavior

SAGE Maintenance adds `Wipe all Job data`. This action removes all operator-created workflow state while preserving the installed environment and reusable resource configuration.

It removes:

- BIC, RTC, STC, and legacy SAW Jobs;
- Runs, tasks, sealed Run snapshots, plans, and canonical results;
- reports, exports, histories, and generated target rollback history;
- active-Job pointers, controller state, locks, and incomplete transactions associated with Jobs.

It preserves:

- Paratext and other external Project source locations;
- Project Inventory, Project catalog, resource mappings, language and grammar configuration;
- bundled semantic and original-language resources and indexes;
- operator and AI configuration;
- the managed virtual environment, installed dependencies, and SAGE Core.

The action defaults to no, requires exact confirmation text `WIPE JOB DATA`, writes an audit receipt outside the deleted Job-data roots, and returns to a usable SAGE session with no active Jobs.

The existing Out-of-Box reset remains a separate, stronger action. It removes all local and operator state and returns SAGE to a genuine first-run state while preserving only SAGE Core and the managed environment/dependencies required to launch setup. It requires its existing exact `RESET SAGE` confirmation.

## Compatibility and cleanup

No legacy data migration is implemented. The release process uses the governed maintenance wipe or Out-of-Box reset before creating new RTC/STC Jobs.

Legacy SAW code may remain only where it is still required by shared internals or parked checks during the transition. New operator surfaces, persisted primary-flow data, documentation examples, and active pointers use RTC/STC terminology. Tests must prevent accidental reintroduction of SAW into the Main Menu or a REFERENCE binding into STC.

## Error and operator-message contract

Expected resource, binding, versification, or coverage deficiencies are collected and rendered together. Operator messages include:

- what SAGE observed;
- the reason or structural code;
- the exact Project, authority, role, and affected scope;
- whether the Run continued or remained `ACTION_NEEDED` before execution;
- what data was not changed;
- the concrete next action.

One defective Job or resource must not prevent discovery, inspection, or management of other Jobs and resources.

## Verification requirements

Implementation is complete only when automated tests demonstrate:

1. Main Menu exposes BIC, RTC, and STC but not SAW.
2. Targeted Check and standalone Original-Language Review are absent from menus while their parked implementation remains importable.
3. RTC Job creation requires distinct WIP and REFERENCE Projects.
4. STC Job creation and Run startup require no REFERENCE Project.
5. RTC option `#10` routes only the testament-appropriate `GRK` or `HEB` evidence and records that authority in reports.
6. Job identifiers use workflow, WIP Project, and WIP snapshot date.
7. repeated Runs allocate `-001`, `-002`, and later serials atomically without using Run dates in the canonical name.
8. Run evidence remains unchanged after refreshing the current Job snapshot.
9. report paths are separated by Job, canonical Book, and zero-padded chapter.
10. RTC and STC headers identify the WIP Project, snapshot, fingerprints, and exact comparison authority.
11. STC headers and prose use `GRK`/`HEB`, never unidentified WIP/source labels or `GRK:PRIMARY`/`HEB:PRIMARY`.
12. versification and comparison-source gaps complete as `COMPLETE_WITH_STRUCTURE_PROBLEMS` and appear in the applicable Run reports.
13. addition, omission, variation, consistency, and structure-problem classifications follow the evidence rules in this design.
14. missing Project bindings remain visible as `ACTION_NEEDED`, report every missing role, and do not abort menus or hide valid Jobs.
15. Resource Status Report inventories all onboarded resources without mutating them.
16. `Wipe all Job data` deletes only the specified workflow data, requires exact confirmation, retains environment/configuration/resources, and writes a receipt.
17. Out-of-Box reset removes all local/operator state while retaining the managed virtual environment and dependencies.
18. the complete test suite and documentation-contract checks pass without introducing new warnings.
