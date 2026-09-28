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
- `es-MX/wip.yml` — Spanish (Mexico) [Latn]
- `it-IT/wip.yml` — Italian (Italy) [Latn]
- `prs-AF/wip.yml` — Dari (Afghanistan) [Arab]
- `ml-IN/wip.yml` — Malayalam (India) [Mlym]
- `ar-EG/wip.yml` — Arabic (Egypt) [Arab]
- `ar-015/wip.yml` — Arabic (North Africa) [Arab]
- `yo-NG/wip.yml` — Yoruba (Nigeria) [Latn]
- `sw-KE/wip.yml` — Swahili (Kenya) [Latn]
- `sw-TZ/wip.yml` — Swahili (Tanzania) [Latn]
- `ru-RU/wip.yml` — Russian (Russia) [Cyrl]
- `zh-CN/wip.yml` — Chinese, Simplified (China) [Hans]
- `zh-TW/wip.yml` — Chinese, Traditional (Taiwan) [Hant]
- `ms-MY/wip.yml` — Malay (Malaysia) [Latn]
- `th-TH/wip.yml` — Thai (Thailand) [Thai]
- `vi-VN/wip.yml` — Vietnamese (Vietnam) [Latn]
- `fil-PH/wip.yml` — Filipino (Philippines) [Latn]
- `tl-PH/wip.yml` — Tagalog (Philippines) [Latn]
- `ceb-PH/wip.yml` — Cebuano (Philippines) [Latn]
- `ur-PK/wip.yml` — Urdu (Pakistan) [Arab]
- `bn-BD/wip.yml` — Bengali (Bangladesh) [Beng]
- `ne-NP/wip.yml` — Nepali (Nepal) [Deva]
- `tr-TR/wip.yml` — Turkish (Turkey) [Latn]
- `tpi-PG/wip.yml` — Tok Pisin (Papua New Guinea) [Latn]
- `ln-CD/wip.yml` — Lingala (DR Congo) [Latn]

Legacy bare-language starter files may remain in an upgraded installation for compatibility, but new Project/profile creation must use regional canonical tags.

## Status semantics

- `ACTIVE`: approved for governed use.
- `PROJECT_REVIEW_REQUIRED`: usable provisionally with attention reporting; it is not linguistic approval.
- `AI_DRAFTED`: accepted operational state with explicit AI provenance; it is not human approval.
- `INACTIVE`: unavailable for normal analytical use.
