---
name: nca-numbers
description: Interpret bounded numeric expressions, correspondence, and target-note evidence for one governed NCA work unit.
---
# Number Consistency & Accuracy model phases

Execute only the named phase of the sealed SAGE governed task described by `task-manifest.json` and its bounded work unit. Return one JSON object matching the phase schema. NCA is read-only for every Scripture Project.

For `EXTRACTION`, use only the target main-text stream, target language, and parsing conventions. Identify every numeric expression with its exact stream, quoted half-open span, reduced rational values, kind, unit, qualifier, and exact referent evidence when available. Do not infer expected values from original-language Scripture, NIV, model recall, or external sources.

For version-2.0 `EXTRACTION`, use the target-only capsule in `references/TARGET-EXTRACTION-CONTRACT.md`. One bounded request may inventory multiple independent target input streams. Echo their input IDs and keep offsets local to each admitted stream. Missing or invalid members remain pending; valid PARTIAL/UNSUPPORTED interpretations remain terminal. A batch shares one parent receipt. Independent semantic adjudications and note assessments remain separate.

For `CORRESPONDENCE`, use only the validated target extraction and bounded authoritative OL row. Preserve the supplied OL value sequence exactly. Bind OL expressions and target expressions to exact text and referent spans. Registered reading context is bounded evidence; it does not authorize the model to choose textual authority or a final policy outcome.

New Runs use version-2.0 `CORRESPONDENCE` and `FOOTNOTE` responses with the same independent evidence boundaries. Echo the sealed schema version; do not substitute version-1.0 output. `GROUP_CORRESPONDENCE` is reserved by the version-2.0 phase manifest; unresolved groups remain explicitly unavailable until that phase is enabled by the controller.

For `FOOTNOTE`, assess only the selected target note against the registered guidance. Quote every supporting note span exactly. Do not borrow evidence from another note or decide whether a registered reading is authoritative.

Return `PARTIAL`, `UNSUPPORTED`, or insufficient evidence whenever language interpretation or span/referent coverage is incomplete. Confidence does not bypass structural or evidence validation. Do not modify Scripture, notes, reference data, work-unit identity, or routing identity.

SAGE owns route selection, immutable input identity, exact value and span validation, source policy, coverage, comparison, classification, and reports.
interface:
  display_name: "NCA Numbers"
  short_description: "Interpret bounded numeric meaning and exact note evidence."
