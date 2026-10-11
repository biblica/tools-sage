# Target numeric value extraction, version 3.0

Interpret only the supplied target language, parsing conventions, and independent target streams. Each work-unit text is the sole evidence for its own values. Other streams cannot supply evidence for an item.

Return one JSON object with schema_version `1.0`, phase `EXTRACTION`, the supplied batch_id, and work_units. Each work-unit item contains only input_id, status, limitations, and numbers. Echo the supplied input_id exactly. Input order is immaterial. Never invent an input or repeat one.

Follow the counting convention below exactly: it decides which words count as numbers and what value each gets. Identify every counted number in the work unit's text, preserving multiplicity, in reading order. For each number return one object in `numbers` with exactly these fields:

- `text`: the number exactly as written in the work unit, copied character for character (for example `сорок дві тисячі триста шістдесят`, `42 360`, `півтора`). It must be a substring of the work unit text.
- `value`: its value as a reduced canonical rational string (for example `3`, `1/2`, `3/2`).
- `kind`: its kind from the convention (`CARDINAL`, `ORDINAL`, `FRACTION`, `PERCENT`, `APPROX`).
- `counts`: the words naming what the number counts, copied from the work unit (for example `золотих чаш`); empty when the text does not say.
- `counts_en`: a short English gloss of `counts` (for example `gold bowls`); empty when `counts` is empty.

Do not report roles, units, or offsets.

Use COMPLETE only for complete interpretation of that input, including an explicitly interpreted stream with no numbers (empty numbers). Use PARTIAL or UNSUPPORTED with limitations when interpretation is incomplete; still return the values you are sure of. Missing input is unresolved coverage. Do not fill an omitted input with an empty COMPLETE result. Do not use confidence as an admission criterion or infer numbers from recall or external sources.

SAGE owns input identities, item hashes, coverage reconciliation, comparison, validation, and receipts. Return no controller hashes or policy decisions. Do not modify text or route identity.
