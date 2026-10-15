# ATT Run Logic

## Run stages

1. Load Translation Brief ATT config.
2. Resolve reference package(s).
3. Verify package checksum and schema version.
4. Load local `input/att/terms.txt` and `phrases.txt` if present.
5. Resolve local additions against configured SOURCE reference(s).
6. Build effective monitored recurrence set without mutating canonical indexes.
7. Index TARGET dynamically.
8. Align/map SOURCE occurrences to TARGET spans.
9. Run lexical recurrence analysis.
10. Run phrase recurrence analysis.
11. Reconcile overlapping findings.
12. For dual-source modes, perform the appropriate correlation/reconciliation pass.
13. Emit machine-readable findings and human-readable report.

## Single source
Primary baseline only.

## Dual hierarchical
- Detect against PRIMARY.
- Independently inspect SECONDARY recurrence at finding locations.
- Add correlation status.
- Never suppress PRIMARY finding solely because SECONDARY differs.

Suggested correlation labels:
- NO_SECONDARY_PARALLEL
- SOME_SECONDARY_PARALLEL
- STRONG_SECONDARY_PARALLEL
- SECONDARY_SAME_PATTERN
- SECONDARY_DIFFERENT_PATTERN

## Dual co-authoritative
Run independent ATT analysis for A and B.
Reconcile results.

Possible classifications:
- BOTH_AGREE_TARGET_CONSISTENT
- BOTH_AGREE_TARGET_VARIANT
- TARGET_FOLLOWS_A_PATTERN
- TARGET_FOLLOWS_B_PATTERN
- TARGET_THIRD_PATTERN
- REFERENCE_PATTERN_DIVERGENCE

## Dynamic translation handling
ATT remains a recurrence checker.
Dynamic translations may legitimately use a small recurring rendering family.
ATT should detect outliers from the established family; it should not become an STC/RTC semantic-equivalence engine.

## Morphology/syntax/orthography handling
Normalization should group normal language realizations where deterministic language tooling allows it.
Do not report inflectional or orthographic forms as lexical inconsistency unless project rules require exact form consistency.

## Phrase handling in Phase 1
Local phrase additions use literal normalized phrase matching.
Canonical phrase indexes may contain richer precomputed phrase families.
No model-based phrase discovery is required in the critical path.
