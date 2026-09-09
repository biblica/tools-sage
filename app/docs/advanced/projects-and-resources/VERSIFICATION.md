# Versification

SAGE distinguishes the canonical mapping target from the default translation versification.

```yaml
versification:
  canonical_file: org.vrs
  default_file: eng.vrs
  base_files:
    - eng.vrs
    - org.vrs
    - lxx.vrs
    - vul.vrs
    - rsc.vrs
    - rso.vrs
  custom_file_default: custom.vrs
```

- `org.vrs` is the canonical mapping target used for cross-versification equivalence. It is **not** the default numbering for an ordinary translation Project.
- `eng.vrs` is the default English/KJV-style versification for a Project that does not explicitly state another configured base VRS.
- `lxx.vrs`, `vul.vrs`, `rsc.vrs`, and `rso.vrs` provide the standard Septuagint,
  Vulgate, Russian Protestant, and Russian Orthodox schemes used by SIL/Paratext.
- A Project-declared or operator-approved base VRS overrides the default.
- `auto` for `custom_file` is a resolution instruction, not a filename.

Base VRS files reside directly under the configured base-VRS root. A custom VRS may reside only inside its own project. SAGE composes the effective schema, hashes all source files, and routes VRS evidence into analytical tasks.

The six bundled schemas are governed by
`system/resources/scripture/standard-vrs-provenance.json`, which pins their
upstream source revision and both upstream and shipped SHA-256 values. The parser
accepts plain and Paratext 7.3+ `#!` exclusion and verse-segment directives,
supports custom `END` chapter truncation, and enforces the one-sided `&` mapping
rule. Verse-segment metadata describes structural correspondence only; SAGE never
uses it to split or synthesize phrase-level Scripture text.

## Internal versification API

`VersificationService` is the single workflow-facing entry point for the base VRS
catalog, effective Project schema loading, fingerprints, and Project-local versus
canonical reference projection. Its cache identity includes the current base and
custom file hashes, so editing a governed VRS invalidates the schema within the
same process. It returns independent schema values until the low-level model is
deeply immutable.

`vrs.py` remains the parser and schema model. New workflow code must use the
service instead of directly parsing or composing Project schemas. The API does not
select Scripture evidence or decide whether structural differences block; those
policies remain with BIC, RTC, STC, and the planned canonical verse index.

## Bundled Greek resource correction

The bundled `GRK` resource owns `system/resources/scripture/original-language/grk/custom.vrs`. This is authoritative resource metadata, not a runtime workaround: it removes the 16 coordinates that are absent from the bundled critical Greek SFM while retaining coordinates whose text is present in double brackets or in a shorter critical reading. In particular, `JHN 5:4` is excluded; `JHN 7:53-8:11`, `MRK 16:9-20`, and `1JN 5:7-8` remain valid coordinates because those verse markers are present in the resource.

## RTC/STC structural policy

Versification-coordinate differences are structural deficiencies for RTC/STC and do not block Project readiness, Run creation, RTC work planning, or structural-stage execution when the evidence remains safe to analyze. This includes `EXPECTED_COORDINATE_MISSING`, `EXPECTED_CHAPTER_MISSING`, `COORDINATE_OUTSIDE_VRS`, and `EXCLUDED_COORDINATE_PRESENT`. SAGE uses `eng.vrs` as the default when no Project VRS is stated, records `READY_WITH_STRUCTURE_PROBLEMS` and `VERSIFICATION_MISMATCH`, retains the advisory with the Run, and renders it in the Action Report. A VRS mapping range is structural metadata and never becomes an RTC work-unit boundary constraint; only an actual multi-coordinate source-text record is protected as an indivisible verse bridge.

At runtime, RTC and STC preserve exact WIP coverage even when an otherwise ready comparison authority has no text at one of those coordinates. SAGE records a report-only `STRUCTURE_PROBLEM`, classifies `ADDITION` or `OMISSION` relative to the named WIP Project when the available evidence supports it, continues without inventing wording, and completes as `COMPLETE_WITH_STRUCTURE_PROBLEMS`. This runtime structure issue is separate from the Project's authoritative custom VRS correction.

This policy does **not** suppress Scripture integrity defects. Malformed USFM/USJ structure, missing Scripture files, duplicate/overlapping verse ranges, invalid book identity, or other non-versification resource defects remain blocking.

A declared `LOCKED` state does not validate Scripture. Conflicting or unsupported content is still reported and governed by the relevant validation policy.
