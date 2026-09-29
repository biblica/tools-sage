# Target numeric value extraction, version 1.0

Interpret only the supplied target language, parsing conventions, and independent target streams. Each work-unit text is the sole evidence for its own values. Other streams cannot supply evidence for an item.

Return one JSON object with schema_version `1.0`, phase `EXTRACTION`, the supplied batch_id, and work_units. Each work-unit item contains only input_id, status, limitations, and values. Echo the supplied input_id exactly. Input order is immaterial. Never invent an input or repeat one.

Identify every numeric expression in the work unit's text, preserving multiplicity, in the exact order it appears in reading order. Return each as a reduced canonical rational string (for example `3`, `-1/2`). Do not classify kind, role, or unit; do not report spans, surfaces, or representations.

Use COMPLETE only for complete interpretation of that input, including an explicitly interpreted stream with no numbers. Use PARTIAL or UNSUPPORTED with limitations when interpretation is incomplete. Missing input is unresolved coverage. Do not fill an omitted input with an empty COMPLETE result. Do not use confidence as an admission criterion or infer numbers from recall or external sources.

SAGE owns input identities, item hashes, coverage reconciliation, comparison, validation, and receipts. Return no controller hashes or policy decisions. Do not modify text or route identity.
