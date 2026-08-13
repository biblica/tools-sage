# Local-first semantic evidence

SAGE applies a local-first execution rule: deterministic parsing, hashing, occurrence lookup, lemma/SEMDOM retrieval, correspondence lookup, lexical-burden arithmetic, OL routing, risk-state derivation, validation, and report formatting belong to the controller whenever they can be computed reliably without semantic inference.

Any routed `semantic-*.json` packet is local retrieval evidence. Use it before generating new lexical alternatives, but do not treat absence of a local match as permission to invent evidence.

Semantic authority remains separated:

- SIL SEMDOM classifies and retrieves related meaning areas; it does not authorize a translation choice.
- A project sense identifies the contextual lexical sense.
- The project decision/memory layer carries translation authority according to its own status and provenance.
- RWC seed, FLEx import, Combine import, frequency, and cross-project occurrence evidence never become `APPROVED` merely by being present or repeated.

Lemma indexes are morphology-neutral where a reliable lemma is available. Surface forms remain occurrence evidence. `SURFACE_FORM_ONLY` records, including inflected Greek reference forms, are not lemma authority.
