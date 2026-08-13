# RWC reference-resource area

This clean source package contains only provenance/configuration guidance. Project lexical payloads are runtime data and are never bundled into the source release.

RWC means Rapid Word Correction. `KKH` is the semantic/language namespace; `idKKHv0` is the Paratext/PTLite project/resource identifier and must be bound explicitly when that project consumes KKH semantic evidence.

## Normal operator path

1. Import classification/traversal authority resources with `sage rwc authority ...` when available.
2. Import immutable RWC seed, Greek reference, FLEx, or Combine snapshots with `sage rwc import ...`.
3. Run `sage rwc initialise --project idKKHv0 --language KKH` (and add `--greek-project GRK --greek-language grc` when Greek reference evidence is in use).
4. Inspect local senses with `sage rwc lookup ...`; apply stronger evidence states only through `sage rwc review ...`. Multiple reviews may be batched while imports/authorities remain unchanged.
5. Rebuild after the review batch, or after any input/authority change. `sage rwc status` must report the index `CURRENT` before BIC, SAW, or export uses it.
6. Generate new FLEx/Combine LIFT packages with an explicit export view (`starter`, `reviewed`, `established`, or `approved`). Imported files are never rewritten in place.

FLEx/Combine imports always enter SAGE as `OBSERVED`; import provenance never grants linguistic approval. RWC seed material enters as `SEED`. Seed headwords remain lexical heads unless an explicit trusted lemma/lexeme authority establishes canonical lemma identity.

Snapshot activation/deactivation and authority switching are advanced source-management actions. Semantic indexes fingerprint the exact active imports and selected authority content; stale indexes fail closed for BIC, SAW, and export.
