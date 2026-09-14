# SAGE STC Planning Handover

## Status

**Planning only — no implementation changes are authorized by this handover.**

This document consolidates the current agreed design for the complete STC flow and supersedes earlier planning assumptions that treated STC as dependent on RTC data, translation references, or other SAGE sources.

---

## 1. STC Purpose

STC is an independent, headless **WIP ↔ Original Language correspondence checker**.

```text
WIP  ⇄  EMBEDDED OL
          ├─ GRK for NT
          └─ HEB for OT
```

STC does not depend on RTC or COMBO for analysis or completion.

STC does not compare the WIP against a translation reference.

---

## 2. Hard Evidence Boundary

```text
STC EVIDENCE RULE

Use only the supplied WIP + OL slice as evidence.
Do not use ANY information outside that slice to form or support a finding.
```

Fail-closed rule:

```text
If a finding cannot be established from the supplied WIP + OL slice,
do not report it.
```

Keep this rule short and decisive. Do not enumerate other SAGE data sources to the provider.

---

## 3. Python Control Takes Precedence Over Prompt Control

> Anything Python can determine must not be delegated to the prompt.

Python owns:

- source selection;
- requested WIP scope;
- embedded OL selection;
- coordinate mapping;
- bridge normalization;
- discourse segmentation;
- protected correspondence spans;
- slice boundaries;
- bounded context;
- token sizing;
- WIP/PACK limits;
- primary/context coverage;
- immutable work-unit identity;
- validation;
- aggregation;
- finalization.

The LLM owns only:

```text
Compare the supplied WIP + OL slice.
Identify governed STC findings.
Return the required structured result.
```

The LLM must not select sources, scope, boundaries, extra context, coverage, or aggregation ownership.

---

## 4. Reuse the Existing SAW Slicing Framework

Do not build a separate general STC slicer.

```text
SAW PYTHON CONTROL / SLICING CORE
        │
        ├── RTC profile
        └── STC profile
```

Reuse the recent SAW/RTC deterministic controls for:

- discourse segmentation;
- paragraph/stanza awareness;
- bridge-safe boundaries;
- protected-span handling;
- WIP token sizing;
- hard WIP limit enforcement;
- PACK hard-limit enforcement;
- bounded context allocation;
- primary/context separation;
- immutable work-unit IDs;
- coverage reconciliation;
- deterministic diagnostics;
- finalization.

STC profile:

```text
evidence pair   = WIP + embedded OL
provider task   = WIP <> OL correspondence review
protected spans = WIP bridge + OL correspondence/equivalence spans
result schema   = STC findings
```

---

## 5. End-to-End STC Flow

```text
STC RUN
  │
  ▼
SAW PYTHON CONTROL PLANE
  │
  ├─ resolve requested WIP scope
  ├─ select corresponding embedded OL
  ├─ normalize coordinates / bridges
  ├─ establish WIP <> OL correspondence coverage
  ├─ apply SAW discourse segmentation
  ├─ calculate protected spans
  ├─ choose legal boundaries
  ├─ enforce WIP / PACK limits
  ├─ assign primary coverage
  ├─ assign bounded context
  ├─ create immutable work_unit_id
  └─ validate packet and coverage
  │
  ▼
BOUNDED STC WORK UNIT
  │
  ├─ WIP slice
  ├─ corresponding OL slice
  ├─ bounded WIP/OL context selected by Python
  ├─ STC task rules
  ├─ REPORT_LANGUAGE
  └─ structured output schema
  │
  ▼
LLM STC ACT
  │
  ▼
STRUCTURED STC RESULT
  │
  ▼
PYTHON RESULT VALIDATION
  │
  ▼
PYTHON AGGREGATION / FINALIZATION
  │
  ├─ STC_RUN_RESULT.json
  ├─ STC_FINDINGS.json
  └─ STC_REPORT
```

---

## 6. OL Source Selection

```text
OT → embedded HEB
NT → embedded GRK
```

Python selects and supplies the governed OL material. The provider does not retrieve or choose Scripture evidence.

---

## 7. Core STC Analytical Unit

STC must not be a naive word-to-word comparator.

```text
OL element / phrase / construction
              ⇄
WIP rendering
```

Correspondence may be:

- one OL token → one WIP token;
- one OL token → several WIP words;
- several OL tokens → one WIP expression;
- several OL tokens → several WIP words;
- OL morphology → WIP grammatical construction;
- OL material → implicit target-language expression where supported.

Plan around bounded **OL correspondence groups**, not assumed one-to-one lexical alignment.

---

## 8. Canonical Coverage vs Source Representation

Example:

```text
Source identity:
JHN 3:16-17

Canonical coverage:
JHN 3:16
JHN 3:17
```

A source bridge remains indivisible as source text but expands into canonical coverage atoms for accounting.

Raw bridge labels must not be aggregate coverage keys.

---

## 9. STC Bridge and Correspondence Boundary Rule

Protect:

```text
WIP source bridges
+
OL correspondence/equivalence spans required for the comparison
```

A work-unit boundary may not bisect a protected WIP↔OL analytical span.

Translation-reference bridge structures are not part of STC.

---

## 10. Legal Boundary Selection

Do not always extend forward.

If a proposed cut intersects a protected span, evaluate both legal boundaries:

```text
        protected span
        16 ────── 18
             │
        proposed cut
             │
       ┌─────┴─────┐
       ▼           ▼
  cut before   cut after
```

Recommended deterministic priority:

1. preserve WIP↔OL correspondence integrity;
2. preserve required discourse integrity;
3. remain below WIP hard limit;
4. remain below PACK hard limit;
5. remain near WIP target;
6. avoid pathologically small units.

If no legal boundary satisfies a hard limit, fail closed.

---

## 11. Connected Protected Spans

Overlapping WIP and OL protected spans should be collapsed into a connected protected component before boundary selection.

Example:

```text
WIP bridge:          16-17
OL correspondence:      17-18
WIP protected span:        18-19

Effective protected component: 16-19
```

---

## 12. Primary Coverage vs Context

Only primary coverage participates in run completion.

```json
{
  "work_unit_id": "STC-WU-006",
  "primary_coverage": [
    "JHN 6:55",
    "JHN 6:56",
    "JHN 6:57"
  ],
  "context_coverage": [
    "JHN 6:54",
    "JHN 6:58"
  ]
}
```

Invariant:

```text
Every canonical primary coverage atom has exactly one primary work-unit owner.
```

Context may overlap adjacent units.

---

## 13. Immutable Work-Unit Plan

The SAW Python controller creates the authoritative immutable plan.

Provider output cannot redefine:

- work_unit_id;
- primary coverage;
- context coverage;
- source spans;
- OL correspondence spans;
- slice boundaries.

Aggregation must recover authoritative coverage from this plan.

---

## 14. STC Finding Scope

Current high-level categories:

```text
OMISSION
ADDITION
VARIATION
CONSISTENCY
```

Planning definitions:

**OMISSION** — supplied OL evidence contains material for which WIP lacks sufficient correspondence.

**ADDITION** — WIP expresses material for which supplied OL evidence does not establish correspondence.

**VARIATION** — WIP corresponds to OL, but materially departs from what supplied OL evidence supports.

**CONSISTENCY** — the same governed OL identity/construction shows materially inconsistent WIP correspondence across STC scope.

Exact implementation criteria must be frozen before coding.

---

## 15. Candidate vs Finding

```text
DETECTED CANDIDATE
       ↓
VALIDATION
       ↓
STC FINDING
```

Surface variation alone is not a finding.

---

## 16. Global / Local Consistency Indexes

Indexes must be anchored to OL identity:

```text
OL identity
   │
   ├─ WIP correspondence A
   ├─ WIP correspondence A
   ├─ WIP correspondence B
   └─ WIP correspondence A
```

Indexes locate candidate anomalies; they do not independently prove linguistic error.

---

## 17. Verb Consistency Caution

The same OL lemma can legitimately receive different WIP renderings.

Therefore:

```text
same OL lemma
+
different WIP rendering
```

must not automatically produce a finding.

It may produce a bounded review candidate only.

---

## 18. Cross-Work-Unit Consistency

Do not widen provider context.

```text
bounded STC work units
      │
      ▼
deterministic OL↔WIP index
      │
      ▼
candidate anomaly coordinates
      │
      ▼
new bounded WIP+OL consistency work unit
      │
      ▼
LLM validation
```

The evidence rule remains unchanged.

---

## 19. Result Validation

Python validates:

- schema;
- work_unit_id;
- governed categories;
- required evidence fields;
- valid coordinates;
- findings inside permitted evidence;
- report-language contract where practical;
- no provider redefinition of coverage.

---

## 20. Aggregation and Finalization

For every planned work unit:

```text
exactly one accepted terminal result must exist
```

Coverage invariant:

```text
UNION(all accepted primary work-unit coverage)
==
PLANNED RUN COVERAGE
```

No canonical primary atom may have multiple primary owners.

`AGGREGATE_COVERAGE_MISMATCH` remains fail-closed.

---

## 21. Analytical Completion Proof

Separate:

```text
SCRIPTURE COVERAGE
```

from:

```text
STC ANALYTICAL COVERAGE
```

A zero-finding run must still prove that all planned STC analysis executed.

---

## 22. Language Governance

Startup bindings:

```text
INTERFACE_LANGUAGE = ENG
REPORT_LANGUAGE    = ENG
SECONDARY_LANGUAGE = <optional>
```

Canonical generated narrative uses `REPORT_LANGUAGE`.

WIP / GRK / HEB quotations remain verbatim.

Missing `REPORT_LANGUAGE` should block provider handoff rather than be inferred.

---

## 23. Keep Evidence and Language Rules Separate

```text
EVIDENCE
Use only the supplied WIP + OL slice as evidence.
Do not use ANY information outside that slice to form or support a finding.
```

Separately:

```text
OUTPUT
Generate required narrative in REPORT_LANGUAGE.
```

---

## 24. Canonical STC Artifacts

### STC_RUN_RESULT.json
Machine-level run truth: run identity, fingerprints, work-unit plan, coverage, phase completion, finalization, diagnostics.

### STC_FINDINGS.json
Canonical normalized findings interface with auditable WIP and OL evidence/provenance.

### STC_REPORT
Operator-facing rendering from canonical run/finding data.

Human-readable report text must not become machine truth.

---

## 25. COMBO Relationship

STC completes independently.

```text
RUN STC
   │
   ▼
STC_FINDINGS
   │
   └── COMPLETE
```

COMBO remains optional/operator-requested and may later consume canonical STC and RTC findings.

---

## 26. Diagnostic Requirements

Coverage/bridge diagnostics should distinguish:

- real gap;
- real overlap;
- collapsed bridge label vs expanded atoms;
- split protected span;
- context counted as primary;
- missing work-unit result;
- duplicate work-unit result;
- provider coverage drift;
- coordinate/OL correspondence mismatch.

Suggested subordinate codes:

```text
BRIDGE_COVERAGE_COLLAPSE
BRIDGE_COVERAGE_EXPANSION
BRIDGE_SPLIT_ACROSS_PRIMARY_UNITS
BRIDGE_CONTEXT_COUNTED_AS_PRIMARY
OL_CORRESPONDENCE_BOUNDARY_SPLIT
RESULT_COVERAGE_DRIFT
DUPLICATE_WORK_UNIT_RESULT
MISSING_WORK_UNIT_RESULT
```

---

## 27. Regression Planning Matrix

Before implementation is complete, cover at least:

1. ordinary unbridged WIP/OL coverage;
2. WIP bridge with atomic OL coverage;
3. atomic WIP with multi-coordinate OL correspondence;
4. three-verse bridge;
5. proposed cut inside WIP bridge;
6. proposed cut inside OL correspondence span;
7. legal cut before protected span;
8. legal cut after protected span;
9. connected WIP/OL protected component;
10. context overlap accepted;
11. primary overlap rejected;
12. missing terminal result rejected;
13. duplicate terminal result rejected;
14. provider scope differs from immutable plan;
15. whole-chapter bridges;
16. whole-book bridges;
17. retry/resume retains identical coverage;
18. discourse/protected-span conflict;
19. protected span exceeds soft target but not hard max;
20. no legal boundary under hard max → fail closed;
21. OT uses HEB only;
22. NT uses GRK only;
23. zero-finding run proves analytical completion;
24. `REPORT_LANGUAGE=ENG` with non-English WIP keeps source quotes unchanged and generated prose English.

---

## 28. Remaining Planning Decisions

### P0 — Formal WIP↔OL correspondence model
Freeze data structures for WIP span, OL span/elements, canonical coverage, correspondence group, protected span, ambiguity state.

### P0 — Exact STC finding criteria
Freeze sufficient evidence and permitted claims for OMISSION, ADDITION, VARIATION, CONSISTENCY.

### P0 — SAW STC profile contract
Define how existing SAW slicing is parameterized for STC. Do not create a second general slicer.

### P0 — Protected-span boundary optimizer
Freeze before/after selection and connected-component behavior.

### P1 — Cross-work-unit consistency workflow
Define OL identity indexing, candidate selection, bounded repackaging, ownership, deduplication.

### P1 — Analytical completion receipt
Define machine-readable proof that all required phases executed.

### P1 — Stable finding identity
Define deterministic finding keys independent of LLM-generated IDs.

### P1 — Resume/fingerprint policy
Define what input/configuration changes invalidate analysis, indexing, or only rendering.

---

## 29. Explicit Non-Goals

STC must not:

- consume RTC findings;
- depend on RTC completion;
- compare against a translation reference;
- let the provider expand scope;
- let the provider select evidence;
- let the provider determine slice boundaries;
- let the provider redefine coverage;
- use human reports as machine truth;
- weaken exact finalization;
- auto-create findings solely from statistical WIP variation.

---

## 30. Governing Rules

```text
RULE 1
STC is a WIP <> embedded-OL correspondence checker.

RULE 2
Python control takes precedence over prompt control.

RULE 3
STC reuses the SAW deterministic slicing/work-unit framework.

RULE 4
The provider receives only the bounded WIP + OL evidence required for the work unit.

RULE 5
Use only the supplied WIP + OL slice as evidence.
Do not use ANY information outside that slice to form or support a finding.

RULE 6
If a finding cannot be established from the supplied WIP + OL slice,
do not report it.

RULE 7
The provider does not choose source, scope, context, boundary, or coverage.

RULE 8
A work-unit boundary may not bisect a protected WIP bridge or OL correspondence span.

RULE 9
When a proposed boundary intersects a protected span, Python evaluates legal boundaries before and after the protected component.

RULE 10
Coverage uses canonical atoms; source bridges remain source-span metadata.

RULE 11
Every canonical primary atom has exactly one primary work-unit owner.

RULE 12
Context may overlap; primary coverage may not.

RULE 13
The immutable Python work-unit plan is authoritative for coverage.

RULE 14
Provider output cannot redefine work-unit coverage.

RULE 15
Surface inconsistency creates a candidate, not automatically a finding.

RULE 16
Consistency analysis must remain anchored to OL identity/correspondence.

RULE 17
Finalization remains exact and fail-closed.

RULE 18
Canonical generated narrative uses REPORT_LANGUAGE.

RULE 19
WIP and OL quotations remain verbatim.

RULE 20
STC completes independently of RTC and optional COMBO.
```

---

## 31. Target Architecture

```text
                  STC REQUEST
                       │
                       ▼
              SAW PYTHON CONTROL
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
            WIP            EMBEDDED OL
                              GRK / HEB
             │                   │
             └─────────┬─────────┘
                       ▼
             COORDINATE / BRIDGE
               NORMALIZATION
                       │
                       ▼
             WIP <> OL CORRESPONDENCE
                       │
                       ▼
             SAW DISCOURSE SEGMENTATION
                       │
                       ▼
             PROTECTED-SPAN RESOLUTION
                       │
                       ▼
             LEGAL BOUNDARY SELECTION
                       │
                       ▼
              IMMUTABLE WU PLAN
                       │
                       ▼
              PRE-HANDOFF VALIDATION
                       │
                       ▼
                BOUNDED STC ACT
                       │
              WIP + OL slice only
                       │
                       ▼
                     LLM
                       │
                       ▼
              STRUCTURED STC RESULT
                       │
                       ▼
               PYTHON VALIDATION
                       │
                       ▼
             CANDIDATE / FINDING FLOW
                       │
                       ▼
                EXACT AGGREGATION
                       │
                       ▼
              RUN FINALIZATION
                       │
             ┌─────────┼─────────┐
             ▼         ▼         ▼
         RUN_RESULT  FINDINGS   REPORT
```

---

## 32. Handover Conclusion

The STC plan is a **Python-governed SAW work-unit flow with a minimal LLM analytical role**.

The strongest safeguard is deterministic construction of the exact bounded evidence packet before provider handoff.

```text
PYTHON GOVERNANCE
      ↓
BOUNDED WIP + OL WORK UNIT
      ↓
MINIMAL STC PROMPT
      ↓
STRUCTURED RESULT
      ↓
PYTHON VALIDATION / FINALIZATION
```

No implementation should begin until the P0 planning contracts in Section 28 are frozen.
