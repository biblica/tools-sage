# Model Language Competency

SAGE maintains a **Registered LLM Language Competency Evidence** table for each concrete provider/model release used for workflow AI. The registry is an operator aid, not a certification, translation-quality guarantee, or Scripture evidence source.

## Identity and persistence

- Competency is keyed by `provider + model release`, not globally across all LLMs.
- SAGE records the provider model ID as `model_version`/release key when the provider exposes no finer model revision.
- The provider CLI/runtime version is stored separately because a Codex CLI release is not the same thing as a model release.
- Older model-release records are preserved; a new model release receives a new table.
- The governed release protocol and seed table live in `system/config/model-language-competency.yml`.
- Locally supplied measured-evaluation records may be stored in `SAGEdata/.system/config/model-language-competency.yml`; SAGE does not rewrite `SYSTEM` to maintain local history.
- Model self-assessment is not accepted as competency evidence.

## Tiers

The tier names are deliberately plain:

- `EXCELLENT`
- `GOOD`
- `FAIR`
- `UNASSESSED`

Release-seed tiers remain policy estimates; measured-evaluation tiers identify their evidence source. Missing evidence is always `UNASSESSED`.

## New model release

When SAGE observes a concrete model release that has no trusted competency record, it reports `EVIDENCE_REQUIRED`. It does not ask the model to rate itself and does not create a registry record. A future release seed or measured evaluation must provide the evidence; older model tables remain unchanged.

A provider catalog that exposes only a model ID cannot prove an invisible backend revision. SAGE therefore treats a newly observed provider model ID as the detectable release boundary and records the provider runtime version separately.

## New Paratext Project language

Project import first resolves the Paratext metadata to a canonical regional BCP-47 identity. Paratext shorthand is evidence only and is never the profile/competency key.

Project addition establishes the regional language identity and continues into normal Language
Profile resolution. It does not probe the provider, run a competency lookup, or display the global
competency table. Competency evidence is requested only through an explicit Operator action.

When the explicit competency action is chosen:

1. SAGE checks the active concrete model-release competency table.
2. If the model release itself is new, SAGE marks all requested languages `UNASSESSED` until versioned or measured evidence is registered.
3. If the model release is known but the exact regional language is new, SAGE uses a governed base-language registry row when available; otherwise it marks the language `UNASSESSED`.
4. The result remains separate from Language Profile resolution and Project registration.

Operational Project language identities require region. Script is included where it materially distinguishes the writing system. Examples: `en-US`, `fa-IR`, `uk-UA`, `pa-Guru-IN`, `pa-Arab-PK`.

## Operator view

The Model menu exposes a lower-detail **Registered language competency** view. It shows:

- provider;
- concrete model;
- model release/version key;
- provider runtime version;
- language/profile identity;
- tier.

Detailed basis, limitations, confidence and evidence source remain in the YAML registry rather than cluttering normal operator screens.

## Governance boundary

Competency metadata may inform warnings, profile depth and human-review recommendations. It may not:

- authorize content evidence;
- replace a grammar profile;
- replace original-language evidence;
- make translation decisions authoritative;
- bypass Project/Team review;
- block importing a Project solely because a language is `FAIR` or `UNASSESSED`.

The normal SAGE invariant remains: **Local Evidence, General Linguistic Competence.**
