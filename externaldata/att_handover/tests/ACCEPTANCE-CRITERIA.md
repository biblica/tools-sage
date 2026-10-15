# ATT Phase 1 Acceptance Criteria

## Configuration
- SINGLE mode loads one trusted reference.
- DUAL_HIERARCHICAL loads primary + secondary and preserves role distinction.
- DUAL_COAUTHORITATIVE loads two equal reference roles.
- Invalid combinations fail clearly.

## Static resources
- Reference package schema/version is validated.
- Exact reference edition/version is recorded.
- Checksum mismatch fails safely.
- Canonical indexes remain read-only.

## Local input
- Missing `input/att/` is allowed.
- Blank/comment lines are ignored.
- Duplicate lines are de-duplicated.
- Terms resolve only against configured SOURCE.
- Phrases resolve only against configured SOURCE.
- Unresolved entries are reported.
- Ambiguous entries are reported, not guessed.
- Local entries are marked project-only/non-canonical.

## Lexical recurrence
- Repeated SOURCE term with uniform TARGET rendering is reported consistent or omitted from exception report according to reporting mode.
- One TARGET outlier among repeated SOURCE occurrences is surfaced.
- Normal morphological variants do not create false positives when normalization can resolve them.
- Orthographic variants are classified separately.

## Phrase recurrence
- Repeated canonical/source phrase occurrences are grouped.
- One unique TARGET treatment is surfaced.
- Local phrases participate without mutating canonical phrase indexes.

## Dual hierarchical
- Primary drives detection.
- Secondary adds correlation metadata.
- Secondary does not silently clear primary findings.

## Dual co-authoritative
- Both references are analyzed independently.
- Divergent recurrence patterns produce REFERENCE_PATTERN_DIVERGENCE rather than a fabricated consensus.

## Scope protection
- No OL lookup occurs unless OL is the configured SOURCE.
- No RTC/STC semantic verdict is emitted.
- No SQS call is required in Phase 1.

## Reproducibility
Every run records:
- reference IDs and versions
- reference package schema versions
- target checksum/version
- ruleset version
- run ID
