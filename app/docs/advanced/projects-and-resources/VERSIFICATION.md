# Versification

SAGE distinguishes the canonical mapping target from the default translation versification.

```yaml
versification:
  canonical_file: org.vrs
  default_file: eng.vrs
  base_files:
    - eng.vrs
    - org.vrs
  custom_file_default: custom.vrs
```

- `org.vrs` is the canonical mapping target used for cross-versification equivalence. It is **not** the default numbering for an ordinary translation Project.
- `eng.vrs` is the default English/KJV-style versification for a Project that does not explicitly state another configured base VRS.
- A Project-declared or operator-approved base VRS overrides the default.
- `auto` for `custom_file` is a resolution instruction, not a filename.

Base VRS files reside directly under the configured base-VRS root. A custom VRS may reside only inside its own project. SAGE composes the effective schema, hashes all source files, and routes VRS evidence into analytical tasks.

## Bundled Greek resource correction

The bundled `GRK` resource owns `system/resources/scripture/original-language/grk/custom.vrs`. This is authoritative resource metadata, not a runtime workaround: it removes the 16 coordinates that are absent from the bundled critical Greek SFM while retaining coordinates whose text is present in double brackets or in a shorter critical reading. In particular, `JHN 5:4` is excluded; `JHN 7:53-8:11`, `MRK 16:9-20`, and `1JN 5:7-8` remain valid coordinates because those verse markers are present in the resource.

## SAW preflight policy

Versification-coordinate differences are advisory for SAW and do not block Project readiness or Run creation. This includes `EXPECTED_COORDINATE_MISSING`, `EXPECTED_CHAPTER_MISSING`, `COORDINATE_OUTSIDE_VRS`, and `EXCLUDED_COORDINATE_PRESENT`. SAGE uses `eng.vrs` as the default when no Project VRS is stated, silently retains the advisory with the Run during routine preflight, and renders it in the SAW Action Report. Explicit Job validation may show an advisory count and details.

At runtime, RTC and STC preserve exact WIP coverage even when an otherwise ready comparison source has no text at one of those coordinates. SAGE records `SOURCE_PRIMARY_COVERAGE_MISMATCH` under `source_text_issues`, continues the run without inventing source wording, and renders the issue in the final Operator report. This runtime text issue is separate from the Project's authoritative custom VRS correction.

This policy does **not** suppress Scripture integrity defects. Malformed USFM/USJ structure, missing Scripture files, duplicate/overlapping verse ranges, invalid book identity, or other non-versification resource defects remain blocking.

A declared `LOCKED` state does not validate Scripture. Conflicting or unsupported content is still reported and governed by the relevant validation policy.
