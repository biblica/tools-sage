# Governed Original-Language Resources — v0.01beta

## Stable aliases

Original-language Scripture is a governed SAGE resource, not an ordinary translation Project in the SAGE Project Inventory.

- `@GRK` — Greek original-language resource; machine binding ID `GRK`.
- `@HEB` — Hebrew original-language resource; machine binding ID `HEB`.

Jobs bind the stable machine IDs only when the configured resource validates as READY. Runtime provenance records the selected source, absolute path, detected books, and any Paratext override code.

## Default source

The preferred source is the authorized corpus bundled in the governed resource slots:

```text
system/resources/scripture/original-language/grk/
system/resources/scripture/original-language/heb/
```

The v0.01beta distribution includes the manually governed Greek NT (27 books) and Hebrew Bible (39 books) `.SFM` resources in these locations. They are the immutable distribution source of record; SAGE never silently downloads or substitutes another corpus.

If a bundled corpus is absent, setup reports OL capability as PARTIAL or UNAVAILABLE without blocking general SAGE setup.

## USFM source and USJ comparison representation

Bundled and overridden OL resources remain UTF-8 USFM/SFM at rest so that their Paratext source, book identity, and byte-level provenance remain auditable. As with SOURCE, REFERENCE, WIP, context, and staged candidates, SAGE deterministically compiles bounded OL coordinates to USJ before model comparison. USJ is the runtime comparison representation; it is not a second editable authority and is never written back over the source corpus.

Distribution validation requires the bundled Greek resource to contain exactly the NT 27 and the bundled Hebrew resource to contain exactly the OT 39. Every bundled book must decode as UTF-8 and compile to non-empty USJ verse units without parser errors.

The current imported metadata does not state adequate redistribution provenance: both `Settings.xml` files have an empty `Copyright` element, the Greek settings name Nestle-Aland while the MAT `\id` describes AGNT, and the Hebrew settings filename suffix contains `hebRESa` while the files use `hebRES`. These do not corrupt text conversion, but the exact editions, source locations, and redistribution authority must be documented before a public release. Do not infer those facts from filenames.

## Explicit override

The operator may reconfigure either alias to:

1. its bundled governed resource;
2. a recognized Paratext Project candidate;
3. another explicit local resource folder.

Changing OL authority is always explicit. SAGE never replaces a bundled source simply because a newer-looking Paratext Project exists.

## Recognized Paratext candidates

The catalog recognizes convenient override candidates:

```text
grcSRCv#  -> Greek candidate
hboSRCv#  -> Hebrew candidate
```

`#` is the iteration digit. Candidate lists are ordered by iteration for convenience, but ordering is not an authority decision. Only a candidate with the corresponding `grc` or `hbo` language metadata is offered.

These candidates remain ordinary discovered Paratext folders; SAGE does not add them to the normal translation-Project inventory merely to use them as OL resources.

## Setup and menu

First-run Scripture validation reports both aliases and their capability status. Missing OL does not make a clean translation-project setup fail.

Permanent configuration is under:

```text
Scripture Projects
  -> Original-language resources
```

The operator can configure Greek or Hebrew separately, validate both, or restore bundled defaults.

## Authority boundary

OL resources are always externally read-only. They never gain BIC TARGET write capability, and Project-code naming never assigns a workflow role. Conditional BIC/SAW OL routing remains governed by the workflow's existing evidence and material-risk rules. Only the two governed bundled directories are permitted to contain Scripture inside a clean SAGE distribution; Job, Project, and operator Scripture remains local workspace data.
