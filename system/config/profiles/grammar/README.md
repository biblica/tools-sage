# Grammar profiles

Profiles are stored under canonical regional BCP 47 language tags and selected by each Project. New operational Project profiles require a region. The layout is `system/config/profiles/grammar/<language-tag>/<variant>.yml`. The filename remains the role/project-style selector; the parent directory is the canonical language identity.

Paratext project codes are import evidence and aliases only; they are never the SAGE language-profile key. Import resolution must confirm language, script, and region before binding a Project to an operational profile. Ambiguous legacy codes (for example a Paratext `pa` value associated with Persian/Farsi metadata) must be resolved from the full metadata and must not be treated automatically as ISO Punjabi.

Bundled starter profiles are `PROJECT_REVIEW_REQUIRED`. They are usable as provisional governed review contracts but are not human-approved Project grammar. Regional sibling profiles may declare `derivation.parent_language_profile`; derivation is a starting point only and requires review.

## Bundled regional WIP starters

- `en-US/wip.yml` — English (United States) [Latn]
- `en-GB/wip.yml` — English (United Kingdom) [Latn]
- `id-ID/wip.yml` — Indonesian (Indonesia) [Latn]
- `fa-IR/wip.yml` — Persian / Farsi (Iran) [Arab]
- `hi-IN/wip.yml` — Hindi (India) [Deva]
- `fr-FR/wip.yml` — French (France) [Latn]
- `fr-011/wip.yml` — French (Western Africa) [Latn]
- `am-ET/wip.yml` — Amharic (Ethiopia) [Ethi]
- `ti-ER/wip.yml` — Tigrinya (Eritrea) [Ethi]
- `ti-ET/wip.yml` — Tigrinya (Ethiopia) [Ethi]
- `ha-NG/wip.yml` — Hausa (Nigeria) [Latn]
- `ha-NE/wip.yml` — Hausa (Niger) [Latn]
- `es-BR/wip.yml` — Spanish (Brazil) [Latn]
- `es-419/wip.yml` — Spanish (Latin America and Caribbean) [Latn]
- `pt-BR/wip.yml` — Portuguese (Brazil) [Latn]
- `pt-419/wip.yml` — Portuguese (Latin America and Caribbean) [Latn]
- `de-DE/wip.yml` — German (Germany) [Latn]
- `ar-SA/wip.yml` — Arabic (Saudi Arabia) [Arab]
- `ar-145/wip.yml` — Arabic (Western Asia / Middle East operational variant) [Arab]
- `uk-UA/wip.yml` — Ukrainian (Ukraine) [Cyrl]

Legacy bare-language starter files may remain in an upgraded installation for compatibility, but new Project/profile creation must use regional canonical tags.

## Status semantics

- `ACTIVE`: approved for governed use.
- `PROJECT_REVIEW_REQUIRED`: usable provisionally with attention reporting; it is not linguistic approval.
- `AI_DRAFTED`: accepted operational state with explicit AI provenance; it is not human approval.
- `INACTIVE`: unavailable for normal analytical use.
