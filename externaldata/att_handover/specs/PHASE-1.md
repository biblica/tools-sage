# ATT Phase 1 Specification

## Objective
Deliver a deterministic recurring-term consistency checker using static reference-resource packages shipped with SAGE, plus project-local dynamic term and phrase additions.

## In scope

### Reference packages
- Prebuilt and versioned.
- Distributed with SAGE.
- Exact edition/version identity required.
- Immutable once published.
- Each package includes manifest, occurrence index, lexical recurrence index, phrase recurrence index and optional named-entity index.

### Supported reference modes
- SINGLE
- DUAL_HIERARCHICAL
- DUAL_COAUTHORITATIVE

### Local dynamic input
Project path:

```text
input/
  att/
    terms.txt
    phrases.txt
```

Rules:
- UTF-8 plain text.
- One SOURCE-language entry per line.
- Blank lines ignored.
- Lines beginning `#` are comments.
- No TARGET entries allowed.
- Resolve only against configured SOURCE reference(s).
- Unresolved items must be reported.
- Ambiguous items must be reported, not guessed.
- Duplicate entries must be normalized/de-duplicated.
- Origin metadata must mark these as local/project-only.

### Local dynamic source behavior
For Phase 1, local input extends monitored recurrence items only. It does not create a new trusted SOURCE.

### Target processing
TARGET is always indexed dynamically per project/run.

Minimum target processing:
- tokenization
- orthographic normalization
- morphology or lightweight lemma grouping where available
- phrase span matching
- source-target occurrence mapping/alignment using existing SAGE mechanisms or a clearly isolated ATT adapter

## Local entry metadata
Suggested effective fields:

```text
origin = LOCAL_INPUT
canonical = false
project_only = true
source_ref_id = <configured source>
source_ref_version = <exact version>
input_file = terms.txt | phrases.txt
```

## Canonical resource behavior
Canonical shipped indexes are read-only.
Project decisions and approved exceptions must be stored outside canonical packages.

## Report goals
For every monitored recurring term/phrase:
- SOURCE recurrence count
- TARGET rendering distribution
- dominant TARGET rendering
- outlier TARGET renderings
- locations of variants
- classification of variation
- correlation status for secondary reference when configured

## Explicit exclusions
- No SQS runtime dependency.
- No SQS admin upload.
- No OL fallback authority unless OL is itself configured as SOURCE.
- No RTC/STC semantic correctness verdicts.
- No automatic model-generated canonical phrase discovery required for v1.
