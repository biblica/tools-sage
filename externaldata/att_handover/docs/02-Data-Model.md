# ATT Data Model

## Canonical reference package
Suggested logical files:

```text
reference-package/
  manifest.json
  occurrences.jsonl
  lexical.jsonl
  phrases.jsonl
  entities.jsonl        # optional
```

## Lexical record
Suggested fields:
- term_id
- source_ref_id
- surface_forms[]
- normalized_form
- lemma if available
- morphology_family if available
- lexical_class: ENTITY | KEY_CONCEPT | KEY_VERB | MONITORED_TERM
- occurrence_ids[]
- recurrence_count
- origin: CANONICAL | LOCAL_INPUT

## Phrase record
Suggested fields:
- phrase_id
- source_ref_id
- canonical_phrase
- normalized_phrase
- phrase_variants[]
- phrase_class: FIXED | CREED | JARGON | RHETORICAL
- occurrence_ids[]
- recurrence_count
- origin: CANONICAL | LOCAL_INPUT

## Occurrence record
Suggested fields:
- occurrence_id
- source_ref_id
- book
- chapter
- verse
- span_start
- span_end
- surface_text
- normalized_text
- term_ids[]
- phrase_ids[]

## Project overlay
Suggested logical files:

```text
project-data/
  att/
    local-resolved.jsonl
    exceptions.jsonl
    approvals.jsonl
```

Canonical reference data must never be modified by these files.

## Stable IDs
Stable IDs should be deterministic within an immutable reference package.
Avoid IDs that depend on array position only.

Recommended construction:
- reference identity + item class + normalized key + disambiguator
- hash-based suffix where necessary

Example:
`ATT:REF_PRIMARY_EXAMPLE_V1:LEX:covenant:<hash>`
