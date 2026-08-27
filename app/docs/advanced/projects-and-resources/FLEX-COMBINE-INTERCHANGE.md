# FLEx and Combine Interchange

SAGE separates immutable lexical input, governed semantic state, generated indexes, and outbound exchange files.

## Data flow

```text
FLEx / Combine / RWC seed
        |
        v
immutable reference snapshots
        |
        v
review state + current local indexes
        |
        +--> BIC / SAW evidence packets
        |
        +--> explicit FLEx LIFT view
        |
        +--> explicit Combine LIFT view
```

Imported LIFT files are never edited in place.

## FLEx import

```sh
./system/bin/sage rwc import flex \
  --file lexicon.lift \
  --source-id KKH-FLEx-2026-08 \
  --language KKH
```

SAGE imports lexical-unit/citation forms, senses, glosses, definitions, part of speech where present, Semantic Domain traits, notes, and source IDs. **Every imported FLEx sense enters SAGE as `OBSERVED`.** A status embedded in or implied by the external file does not grant SAGE project approval.

## Combine import

```sh
./system/bin/sage rwc import combine \
  --file rwc.lift \
  --source-id KKH-Combine-2026-08 \
  --language KKH
```

Combine imports also enter as `OBSERVED`. RWC collection provenance and SAGE linguistic authority remain separate.

## Governed evidence review

A stronger SAGE state is applied separately:

```sh
./system/bin/sage rwc review set \
  --language KKH \
  --sense-id SENSE_ID \
  --status ESTABLISHED \
  --reviewer LC

./system/bin/sage rwc index build --language KKH
```

This separation prevents an import source from silently conferring translation authority. Multiple sense reviews may be batched while imports/authorities remain unchanged; BIC, SAW, and export remain blocked until the index is rebuilt.

## Explicit export views

Every export requires an evidence-state view. There is no implicit production export of all data.

| View | Included states | Typical use |
|---|---|---|
| `starter` | SEED, OBSERVED, TEAM_CONFIRMED, ESTABLISHED, APPROVED | RWC/bootstrap exchange |
| `reviewed` | TEAM_CONFIRMED, ESTABLISHED, APPROVED | reviewed lexical exchange |
| `established` | ESTABLISHED, APPROVED | mature project lexicon |
| `approved` | APPROVED only | strict approved-only exchange |

Examples:

```sh
./system/bin/sage rwc export combine --language KKH --view starter
./system/bin/sage rwc export flex --language KKH --view reviewed
./system/bin/sage rwc export flex --language KKH --view approved
```

Generated filenames include the view, e.g. `KKH-reviewed.lift`.

## Profile differences

**FLEx profile** may contain:

- lexical unit;
- senses and glosses;
- definitions;
- part of speech;
- Semantic Domain traits;
- SAGE evidence-status note.

**Combine profile** intentionally remains narrower:

- lexical unit;
- senses and glosses;
- Semantic Domain traits.

## Export safety gates

SAGE refuses export when semantic indexes are stale or invalid. Every successful export is newly generated, reparsed locally, and accompanied by a manifest containing:

- profile and explicit view;
- included evidence states;
- entry/sense counts;
- source and exported status counts;
- SHA-256;
- validation result;
- source index location.

The operator imports the generated file into FLEx or Combine deliberately; SAGE does not write directly into either application's live data store.
