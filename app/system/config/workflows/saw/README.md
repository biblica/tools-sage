# SAW workflow

SAW analyzes one bounded LWC work-in-progress translation (WIP) against one authorized LWC REFERENCE. Its Job may bind one configured Greek resource and/or one configured Hebrew resource for operations or stages that require original-language evidence.

```text
WIP + REFERENCE (+ configured applicable GRK/HEB only when routed) -> findings
```

Guided Input returns `INPUT_REQUIRED` for recoverable missing/ambiguous values. Every governed task belongs to one persisted SAW Job and Run. SAW never writes Scripture projects.

## Standard QA

Standard QA is one Operator operation orchestrated as:

```text
deterministic preflight/structural triage
  -> conditional STRUCTURAL_ADJUDICATION model task
  -> required TRANSLATION_AND_MEANING_QA model task
  -> conditional SELECTIVE_OL_ADJUDICATION model task
  -> deterministic merge / coverage / finalization
```

Every model stage supplies substantive task-bound review evidence as a semantic `review_summary`; SAGE constructs receipts and exact coordinate coverage from the sealed manifest and validated result. The Operator-approved preview manifest is authoritative for meaning-stage work units and boundaries; the model may not replan it. The structural and meaning stages receive no OL Scripture. When Standard-QA WIP–Reference source adjudication is enabled, the meaning stage defers every material content-bearing variance whose correctness depends on the source. Grammar, readability, punctuation, spelling, USFM/structure, style, and ordinary consistency remain direct findings. The selective stage routes OT requests only to Job-bound Hebrew and NT requests only to Job-bound Greek, returning source-comparison resolutions rather than performing a detailed OL review.

## Separate operations

- Targeted Check: one bounded WIP+REFERENCE question; no OL Scripture.
- Original-Language Review: one separate bounded WIP+REFERENCE+applicable configured GRK/HEB question. If that testament-specific OL binding is absent, the OL operation fails closed.

Semantic/index signals are local-first triage evidence only. Final SAW outputs are findings, an action report, and simple plain-text Operator issue blocks for manual copy/paste into Paratext Notes. SAGE does not create or modify Paratext Notes XML.

Use `./system/bin/saw --help` for operator syntax. Preferred flags are `--wip` and `--reference`; older generic parser aliases do not change the Project/Job/Run authority model.
