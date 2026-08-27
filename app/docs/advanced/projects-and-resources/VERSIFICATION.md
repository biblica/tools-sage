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

## SAW preflight policy

Versification-coordinate differences are advisory for SAW and do not block Project readiness or Run creation. This includes `EXPECTED_COORDINATE_MISSING`, `EXPECTED_CHAPTER_MISSING`, `COORDINATE_OUTSIDE_VRS`, and `EXCLUDED_COORDINATE_PRESENT`. SAGE uses `eng.vrs` as the default when no Project VRS is stated, silently retains the advisory with the Run during routine preflight, and renders it in the SAW Action Report. Explicit Job validation may show an advisory count and details.

This policy does **not** suppress Scripture integrity defects. Malformed USFM/USJ structure, missing Scripture files, duplicate/overlapping verse ranges, invalid book identity, or other non-versification resource defects remain blocking.

A declared `LOCKED` state does not validate Scripture. Conflicting or unsupported content is still reported and governed by the relevant validation policy.
