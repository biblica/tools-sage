---
name: nca-numbers
description: Identify the ordered numeric values found in one governed NCA work unit.
---
# Number Consistency & Accuracy model phase

Execute only the named phase of the sealed SAGE governed task described by `task-manifest.json` and its bounded work unit. Return one JSON object matching the phase schema. NCA is read-only for every Scripture Project.

For `EXTRACTION`, use the target-only capsule in `references/TARGET-EXTRACTION-CONTRACT.md`. One bounded request may inventory multiple independent target input streams. Echo their input IDs exactly. Missing or invalid members remain pending; valid PARTIAL/UNSUPPORTED interpretations remain terminal. A batch shares one parent receipt.

Identify every numeric expression in one work unit's target text, in the order it appears, and return it as a reduced canonical rational string. Do not classify kind, role, or unit; do not report spans or representations. Use only the target text, target language, and parsing conventions. Do not infer expected values from original-language Scripture, NIV, model recall, or external sources -- SAGE performs the comparison locally after extraction.

Return `PARTIAL`, `UNSUPPORTED`, or insufficient evidence whenever language interpretation is incomplete. Confidence does not bypass structural or evidence validation. Do not modify Scripture, notes, reference data, work-unit identity, or routing identity.

SAGE owns route selection, immutable input identity, exact value validation, comparison, classification, and reports.
interface:
  display_name: "NCA Numbers"
  short_description: "Identify the ordered numeric values in bounded target text."
