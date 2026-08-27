# Grammar profiles and regional language identity

SAGE operational grammar namespaces use canonical regional BCP 47 language tags such as `en-US`, `uk-UA`, `fa-IR`, and `de-DE`. Region is required for newly imported Projects and newly built operational profiles. For Operator readability, SAGE prefers an alphabetic country/territory subtag whenever the Project is actually associated with a known country (for example `fr-SN`, `es-MX`, or `ar-SA`). Numeric UN M49 region subtags such as `419` or `011` are reserved for genuinely multi-country regional profiles and are not used merely as a substitute for a known country. Where script materially distinguishes the language, the tag may also include an ISO 15924 script subtag.

Paratext Project codes and legacy language shorthand are import evidence only. They are never the SAGE language-profile key. SAGE resolves the full language identity from the available language name, ISO metadata, script, region and previously confirmed aliases, then asks the Operator to choose or confirm the regional profile. This prevents ambiguous shorthand such as a Paratext `pa` value used with Persian/Farsi metadata from being confused with ISO Punjabi `pa`.

Each YAML file is one executable language-and-role contract. The layout is:

```text
system/config/profiles/grammar/<regional-language-tag>/<role-or-project-variant>.yml
```

## Bundled regional WIP starters

| Profile | Language / region | Script | Relationship |
|---|---|---|---|
| `en-US` | English — United States | Latn | starter |
| `en-GB` | English — United Kingdom | Latn | regional derivation from `en-US` |
| `id-ID` | Indonesian — Indonesia | Latn | starter |
| `fa-IR` | Persian/Farsi — Iran | Arab | starter |
| `hi-IN` | Hindi — India | Deva | starter |
| `fr-FR` | French — France | Latn | starter |
| `fr-011` | French — Western Africa | Latn | regional derivation from `fr-FR` |
| `am-ET` | Amharic — Ethiopia | Ethi | starter |
| `ti-ER` | Tigrinya — Eritrea | Ethi | starter |
| `ti-ET` | Tigrinya — Ethiopia | Ethi | regional derivation from `ti-ER` |
| `ha-NG` | Hausa — Nigeria | Latn | starter |
| `ha-NE` | Hausa — Niger | Latn | regional derivation from `ha-NG` |
| `es-419` | Spanish — Latin America/Caribbean | Latn | starter |
| `es-BR` | Spanish — Brazil | Latn | regional derivation from `es-419` |
| `pt-BR` | Portuguese — Brazil | Latn | starter |
| `pt-419` | Portuguese — Latin America/Caribbean operational profile | Latn | regional derivation from `pt-BR` |
| `de-DE` | German — Germany | Latn | starter |
| `ar-SA` | Arabic — Saudi Arabia | Arab | starter |
| `ar-145` | Arabic — Western Asia / Middle-East operational profile | Arab | regional derivation from `ar-SA` |
| `uk-UA` | Ukrainian — Ukraine | Cyrl | starter |

All bundled starters are `PROJECT_REVIEW_REQUIRED`: they are governed provisional review contracts, not approved Project grammar.

## Import resolution

When a Paratext Project is imported, SAGE:

1. reads the raw Paratext language metadata and preserves it as provenance;
2. resolves the preferred language identity independently of the Project shorthand;
3. recommends configured regional profiles for that language;
4. requires a regional BCP 47 selection before the Project is stored;
5. if no bundled profile exists, opens grammar-profile maintenance so the Operator can choose an existing profile, derive one, build a guided starter, or add a reviewed YAML profile.

Regional siblings may be derived from an existing profile, but derivation is always explicit and review-required. SAGE never assumes that two regions have identical grammar, orthography or lexical conventions.

## Operator maintenance

Grammar-profile configuration is maintained from **SAGE Maintenance > Configure languages > Maintain grammar profiles** or **Scripture Projects > Maintain grammar profiles**. The same surface is opened when Job setup detects a missing required language/role profile.

Available routes are:

- **Choose from existing profile list** — register a compatible bundled or local profile.
- **Build guided regional profile** — create a `PROJECT_REVIEW_REQUIRED` local profile under `localdata/inputs/resources/grammar-profiles/<tag>/`; the Operator may start from the generic governed template or explicitly derive from an existing profile.
- **Add grammar profile from YAML file** — validate and register an externally prepared profile; external files are copied into the local governed profile library.
- **Show/validate configured profiles** — inspect the active registry.

## Status governance

- `ACTIVE`: accepted for governed use.
- `PROJECT_REVIEW_REQUIRED`: usable provisionally with review attention; not linguistic approval.
- `AI_DRAFTED`: accepted operational starting state with explicit AI provenance; not Team/project approval.
- `INACTIVE`: unavailable for normal analytical use.

AI output cannot promote a profile to human approval or invent an approval receipt.


## Model competency linkage

Grammar profiles and model competency are separate. Project profiles remain canonical regional BCP-47 identities and Project-reviewed linguistic configuration. Importing or opening a Project performs Language Profile resolution without triggering or displaying a model-competency lookup. Competency evidence is available only through its explicit language action, and a competency tier never substitutes for a grammar profile.

## Language relationship boundary

Grammar Profiles are dependants of a specific working Language Profile. They do not define language parent/member/regional relationships. Current Operator setup does not create `profile_alias`; legacy aliases are migration-only compatibility data.
