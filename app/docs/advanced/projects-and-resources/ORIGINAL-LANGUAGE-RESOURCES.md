# Governed Original-Language Resources — v0.02b1

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

The v0.02b1 distribution includes the manually governed Greek NT (27 books) and Hebrew Bible (39 books) `.SFM` resources in these locations. They are the immutable distribution source of record; SAGE never silently downloads or substitutes another corpus.

If a bundled corpus is absent, setup reports OL capability as PARTIAL or UNAVAILABLE without blocking general SAGE setup.

## SFM evidence and controller representation

Bundled and overridden OL resources remain UTF-8 USFM/SFM at rest so that their source, book identity, and byte-level provenance remain auditable. Model-facing OL Scripture is the exact bounded SFM selected for the analytical review item. SAGE may deterministically compile USJ/structural records locally for validation, coordinate mapping, coverage, and provenance, but those controller projections are not additional model evidence and do not participate in SFM sizing.

Distribution validation requires the bundled Greek resource to contain exactly the NT 27 and the bundled Hebrew resource to contain exactly the OT 39. Every bundled book must decode as UTF-8 and compile to non-empty verse units without parser errors.

The current imported metadata does not state adequate redistribution provenance: both `Settings.xml` files have an empty `Copyright` element, the Greek settings name Nestle-Aland while the SFM `\id` describes AGNT, and the Hebrew settings filename suffix contains `hebRESa` while the files use `hebRES`. These do not corrupt text conversion, but the exact editions, source locations, and redistribution authority must be documented before a public release. Do not infer those facts from filenames.

## Embedded OL authority profiles

Each governed OL authority carries a source-bound `OL_AUTHORITY_PROFILE` and every model-facing request that receives that authority receives the complete profile. The profile is interpretation governance, not Scripture content evidence. It is not sliced and it contributes zero to SFM token/hard-byte sizing.

- The bundled GRK profile identifies Ancient/New Testament Greek (`grc`) and explicitly prohibits Modern Greek vocabulary, grammar, idiom, pronunciation, and semantic assumptions. Its exact textual-edition identity remains unresolved where imported metadata conflicts.
- The bundled HEB profile identifies Biblical/Ancient Hebrew (`hbo`) and explicitly prohibits Modern Israeli Hebrew assumptions. Its exact MT edition remains unresolved unless authoritative provenance establishes it.
- Profiles describe only representation facts actually present in the governed resource. They must not invent lemma, morphology, gloss, or apparatus layers absent from the SFM.

Provider language detection is never a substitute for a profile. Missing or invalid authority-profile specificity fails closed before an OL-aware model handoff.

## Authority families and future secondary authorities

`GRK` and `HEB` are global OL authority families, not Project language profiles. A configured family has one PRIMARY authority for current analytical use and is architecturally allowed zero or more SECONDARY authorities. Current workflows do not silently route secondary authorities; a future operation must explicitly declare their analytical role and include their SFM in that review item's route before they can affect findings or sizing. Each secondary authority carries its own source-bound profile.

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

OL resources are always externally read-only. They never gain BIC TARGET write capability, and Project-code naming never assigns a workflow role. Conditional BIC/RTC/STC OL routing remains governed by the workflow's existing evidence and material-risk rules. Only the two governed bundled directories are permitted to contain Scripture inside a clean SAGE distribution; Job, Project, and operator Scripture remains local workspace data.

## Original-language analysis (MACULA)

SAGE also ships a pinned word-level analysis of the Hebrew and Greek text: package
`SAGE_OL_ANALYSIS_2026-10-15` under `system/resources/ol-analysis/2026-10-15/`, pinned by
`system/config/ol-analysis-reference.json` and checked against its checksums whenever it is loaded. It holds
every MACULA Hebrew (WLC) and Greek (SBLGNT) word with its lemma, Strong's number, morphology fields, and an
English gloss, in MACULA's own numbering. It is the `OL_ANALYSIS` role of the
[authority policy](../future/AUTHORITY-POLICY.md): it may decide lemma and morphology, never the wording of
`@HEB`/`@GRK`.

When an STC finding, an RTC original-language adjudication, or a BIC original-language check rests on
particular source words, the model lists them in `ol_words` with the lemma and parse it relies on. SAGE checks
each entry against MACULA for the verse and its immediate neighbours:

| Result | Meaning | Effect |
|---|---|---|
| `VERIFIED` | MACULA has the word with the claimed lemma and every claimed parse field | The report shows MACULA's lemma, parse, and gloss |
| `MISMATCH` | MACULA has the word but contradicts the lemma or a parse field | The finding is kept, marked `ol_analysis_verified: false`, and an `OL_CLAIM_UNVERIFIED` exception names MACULA's value |
| `NOT_FOUND` | MACULA has no such word in those verses (edition or numbering difference) | Neutral; nothing is flagged |
| `NOT_CHECKED` | The package is missing or failed its integrity check | Neutral; the reason is recorded and the Run continues |

SAGE computes these checks itself when it validates the output; check results written by the model are
ignored. Rebuild the package with `system/tools/build_ol_analysis.py build --date YYYY-MM-DD` from the
MACULA tables fetched by `system/tools/build_numbers_index.py fetch`; `verify` rebuilds it and requires
byte-identical files. Licenses and attribution: [Third-Party Data Notices](THIRD-PARTY-NOTICES.md).

### Name check (STC)

MACULA marks every proper name. When SAGE builds an STC task, it learns how the WIP renders each name across
all its books with a small word aligner (IBM Model 1 restricted to names, with a NULL word). Each name gets
spelling stems that cover its inflected forms. Code learns names from the whole WIP and caches them per WIP
text and package in `system/cache/name-alignment/`. A verse whose original-language text has a name but
whose WIP text lacks that name's usual rendering becomes a `NAME` candidate (`CONFIRM`/`REJECT`/`UNSURE`):

| Kind | Meaning |
|---|---|
| `VARIANT` | The verse has a rare word spelled one or two letters away from the usual rendering |
| `SUBSTITUTION` | The verse has another well-established name that its original-language verse does not have |

Code also recognizes `ABSENT` (neither of the above), but STC does not receive it. In an audit of 84 sampled
candidates from six WIPs, judged by an LLM, 3 of 59 `ABSENT` candidates were worth a reviewer's time; most were
pronouns or restructured sentences. STC's own review already looks for omissions.

A name needs at least three WIP verses, with its stems covering at least half of them, before it is checked.
A misspelling after the stem looks like inflection and is not flagged. Endings are learned from the WIP
itself: an ending of up to four letters (vowel signs and viramas do not count) that alternates in the forms
of at least five names. In scripts written without spaces (Chinese, Thai), `VARIANT` is not detected. The model judges each candidate: a different spelling, another
name, or an omission that changes the meaning is a `CONSISTENCY` finding, and a pronoun or a restructured
sentence is not. A missing package or a WIP that does not compile records `name_check: NOT_CHECKED` and the
task continues. Measure the check on a real WIP with `system/tools/evaluate_name_alignment.py`. It plants
misspellings, swapped names, and removed names, then reports how many come back as candidates. A removed name
comes back as `ABSENT`, which STC does not receive.
