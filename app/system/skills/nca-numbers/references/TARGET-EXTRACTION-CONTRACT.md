# Target numeric inventory extraction, version 2.0

Interpret only the supplied target language, parsing conventions, and independent target streams. The routed SFM is bounded source context; each work-unit text is the sole offset authority for its expressions. Other streams cannot supply evidence for an item.

Return one JSON object with schema_version `2.0`, phase `EXTRACTION`, the supplied batch_id, and work_units. Each work-unit item contains only input_id, status, limitations, and expressions. Echo the supplied input_id exactly. Input order is immaterial. Never invent an input or repeat one.

Identify every numeric expression, preserving multiplicity, its exact stream_id, quoted surface, half-open character span, reduced rational strings, kind, unit, qualifier, and exact referent role evidence when available. Each expression contains expression_id, stream_id, surface, span, values, kind, unit, qualifier, role, role_spans, and representations. Expression IDs are local to their input. Primary expressions cannot overlap. All representations of one words-plus-digits expression require separate exact spans and equal values.

Use COMPLETE only for complete interpretation of that input, including an explicitly interpreted stream with no numbers. Use PARTIAL or UNSUPPORTED with limitations when interpretation is incomplete. Missing input is unresolved coverage. Do not fill an omitted input with an empty COMPLETE result. Do not use confidence as an admission criterion or infer numbers from recall or external sources.

SAGE owns input identities, item hashes, coverage reconciliation, validation, and receipts. Return no controller hashes or policy decisions. Do not modify text or route identity.
