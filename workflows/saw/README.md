# SAW workflow

SAW analyses one bounded LWC work-in-progress translation (WIP) against one authorised LWC REFERENCE. Its Job may bind one configured Greek resource and/or one configured Hebrew resource for operations or stages that require original-language evidence.

```text
WIP + REFERENCE (+ configured applicable GRK/HEB only when routed) -> findings
```

Guided Input returns `INPUT_REQUIRED` for recoverable missing/ambiguous values. Every governed task belongs to one persisted SAW Job and Run. SAW never writes Scripture projects.

## Normal QA

Normal QA is one Operator operation orchestrated as:

```text
deterministic preflight/structural triage
  -> conditional STRUCTURAL_ADJUDICATION model task
  -> required TRANSLATION_AND_MEANING_QA model task
  -> conditional SELECTIVE_OL_ADJUDICATION model task
  -> deterministic merge / coverage / finalisation
```

Every model stage requires substantive task-bound review evidence and exact coordinate coverage. Partitioned work units remain separately governed and aggregate only after their required units finalise. The structural and meaning stages receive no OL Scripture. The meaning stage may emit exact bounded `ol_review_requests`; only the selective OL stage receives the configured project-bound GRK/HEB packet required to resolve those IDs. Large scopes may be partitioned into deterministic work units while preserving the same stage isolation.

## Separate operations

- Focused Check: one bounded WIP+REFERENCE question; no OL Scripture.
- OL Review: one separate bounded WIP+REFERENCE+applicable configured GRK/HEB question. If that testament-specific OL binding is absent, the OL operation fails closed.

Semantic/index signals are local-first triage evidence only. Final SAW outputs are findings, an action report, and simple plain-text Operator issue blocks for manual copy/paste into Paratext Notes. SAGE does not create or modify Paratext Notes XML.

Use `./saw --help` for operator syntax. Preferred flags are `--wip` and `--reference`; older generic parser aliases do not change the Project/Job/Run authority model.
