# Governed Original-Language Resources — RC7.04

## Stable aliases

Original-language Scripture is a governed SAGE resource, not an ordinary translation Project in the SAGE Project Inventory.

- `@GRK` — Greek original-language resource; machine binding ID `GRK`.
- `@HEB` — Hebrew original-language resource; machine binding ID `HEB`.

Jobs bind the stable machine IDs only when the configured resource validates as READY. Runtime provenance records the selected source, absolute path, detected books, and any Paratext override code.

## Default source

The preferred source is the authorised corpus bundled in the governed resource slots:

```text
resources/scripture/original-language/grk/
resources/scripture/original-language/heb/
```

The public/source RC package contains the slots and governance metadata but no fabricated or silently downloaded Scripture corpus. A licensed distribution may populate these locations with authorised `.SFM` data.

If a bundled corpus is absent, setup reports OL capability as PARTIAL or UNAVAILABLE without blocking general SAGE setup.

## Explicit override

The operator may reconfigure either alias to:

1. its bundled governed resource;
2. a recognised Paratext Project candidate;
3. another explicit local resource folder.

Changing OL authority is always explicit. SAGE never replaces a bundled source simply because a newer-looking Paratext Project exists.

## Recognised Paratext candidates

The catalogue recognises convenient override candidates:

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

OL resources are always externally read-only. They never gain BIC TARGET write capability, and Project-code naming never assigns a workflow role. Conditional BIC/SAW OL routing remains governed by the workflow's existing evidence and material-risk rules.
