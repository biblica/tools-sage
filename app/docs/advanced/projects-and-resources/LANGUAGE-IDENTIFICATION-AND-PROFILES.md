# Language Identification and Language Profiles — beta

Project registration treats Paratext metadata as evidence, not unquestionable identity.

## Evidence

SAGE reads:

- `Settings.xml` language metadata and any available country fields;
- every project-root `*.ldml` identity block (`language`, optional `script`, optional `territory`);
- the initial lowercase project-name prefix as weak independent ISO evidence.

Multiple LDML files are classified as evidence. They do not create multiple Language Profiles and they do not win by simple majority. `.ldml` files participate in the project source signature, so a metadata change invalidates a stale catalog row.

## Operator confirmation

Before Project registration, SAGE shows **LANGUAGE IDENTIFICATION** with resolved ISO 639 identity, language name, Paratext country evidence, primary audience country, and the current regional BCP-47 candidate. The Operator may change ISO or primary country, review the evidence, and then accept.

If Paratext supplies multiple countries, SAGE requires an Operator choice. If Paratext supplies no country and SAGE has one deterministic regional suggestion, it is labeled as a suggestion rather than Paratext evidence.

Beta keeps these concepts distinct in catalog/provenance metadata:

- exact Paratext language code;
- canonical ISO 639-3 identity;
- preferred BCP-47 language subtag;
- primary audience country;
- regional Language Profile tag, e.g. `id-ID`.

## Profile hierarchy

`Scripture Project -> Language Profile -> role-specific Grammar Profile -> Job binding -> Run`

Project addition establishes/selects the regional Language Profile namespace. A new Language Profile may validly have zero Grammar Profile variants and therefore show `INCOMPLETE`. Grammar Profile setup is deferred until a BIC/SAW Job role actually requires one.
