# SAW workflow

> Legacy compatibility profile only. New work uses the independent `rtc` or `stc` workflow; this profile remains readable solely for sealed pre-migration Jobs.

SAW hosts four independent analysis operations over one bounded WIP. RTC/Targeted Check use the authorized REFERENCE; STC uses the testament-appropriate PRIMARY original-language authority and does not consume REFERENCE evidence; Original-Language Review uses the bounded evidence declared by its operation contract. The Job may bind one configured Greek resource and/or one configured Hebrew resource; machine governance treats those bindings as OL authority families.

```text
WIP + REFERENCE (+ configured applicable GRK/HEB only when routed) -> findings
```

Guided Input returns `INPUT_REQUIRED` for recoverable missing/ambiguous values. Every governed task belongs to one persisted SAW Job and Run. SAW never writes Scripture projects.

## Reference Text Comparison (RTC)

Reference Text Comparison (RTC) is one Operator operation orchestrated as:

```text
deterministic preflight/structural triage
  -> conditional STRUCTURAL_ADJUDICATION model task
  -> required REFERENCE_TEXT_COMPARISON model task
  -> conditional SELECTIVE_OL_ADJUDICATION model task
  -> deterministic merge / coverage / finalization
```

Every model stage supplies substantive task-bound review evidence as a semantic `review_summary`; SAGE constructs receipts and exact coordinate coverage from the sealed manifest and validated result. The Operator-approved preview manifest is authoritative for meaning-stage review portions and boundaries; the model may not replan it. The structural and meaning stages receive no OL Scripture.

When RTC WIP–Reference source adjudication is enabled, a request is admitted only if all seven rules pass: the core proposition changes; the meanings are incompatible; the request declares one approved conflict class; correctness requires original-language evidence; routed non-OL evidence cannot settle it; the request contains one issue at the smallest scope; and the normalized conflict is unique. The closed classes are `NEGATION_OR_POLARITY_CONFLICT`, `PARTICIPANT_IDENTITY_OR_ROLE_CONFLICT`, `CORE_EVENT_OR_STATE_CONFLICT`, and `CORE_PROPOSITION_OMISSION_OR_ADDITION`. Lexical nuance/intensity, equivalent paraphrase or active/passive roles, grammar, readability, spelling, punctuation, USFM structure, style, and ordinary consistency are never source referrals. Each admitted request becomes one isolated selective task. OT routes only to Job-bound Hebrew and NT only to Job-bound Greek.

Operator progress distinguishes the immutable `Review range`, each approved `Review portion`, and local `Structural check` or `Source check` counters. Machine work units and their `work_unit_id` values remain diagnostic identifiers and are not the default progress vocabulary.

## Separate operations

- Targeted Check: one bounded WIP+REFERENCE question; no OL Scripture.
- Original-Language Review: one separate bounded WIP+REFERENCE+applicable configured GRK/HEB question. If that testament-specific OL binding is absent, the OL operation fails closed.

Semantic/index signals are local-first triage evidence only. Final SAW outputs are findings, an action report, and simple plain-text Operator issue blocks for manual copy/paste into Paratext Notes. SAGE does not create or modify Paratext Notes XML.

Use `./system/bin/saw --help` for operator syntax. Preferred flags are `--wip` and `--reference`; older generic parser aliases do not change the Project/Job/Run authority model.
