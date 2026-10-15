# SAGE ATT Developer Handover

Advanced Term Tool (ATT) for recurring-term consistency review.

## Purpose
ATT checks whether recurring terms and recurring phrases in a configured trusted SOURCE are handled consistently in the TARGET translation according to the translation brief and the project's established rendering pattern.

ATT is NOT RTC/STC and does NOT judge general semantic correctness or faithfulness.

Core question:

> When the same recurring SOURCE term or SOURCE phrase appears again, does TARGET handle it consistently according to the project pattern?

## Primary analysis streams
1. Lexical recurrence
   - proper nouns / named entities
   - key verbs
   - key concepts / technical terms
   - monitored lexical families
2. Phrase recurrence
   - fixed phrases
   - creedal / confessional formulae
   - jargon
   - rhetorical / discourse formulae

## Source authority
ATT inherits source/reference authority from the Translation Brief.

Supported Phase 1 reference modes:
- SINGLE
- DUAL_HIERARCHICAL
- DUAL_COAUTHORITATIVE

## Phase 1
- Static, prebuilt reference indexes shipped with SAGE.
- No runtime SQS dependency.
- No admin upload to SQS.
- TARGET indexing is dynamic/local.
- Local project-only term and phrase additions supported under `input/att/` using flat UTF-8 text lists.
- Local additions reference the configured SOURCE only and never modify canonical shipped indexes.

## Phase 2
- SQS Reference Data Service.
- Central source registry, versioning, checksums, index publishing, entitlement/licensing, advanced operator upload, validation, approval, deprecation, local caching.
- Same canonical reference package schema as Phase 1.
- Existing OL resources may migrate to the same SQS service later as a separate extensibility feature.

## Package contents
- `docs/` design and implementation handover
- `specs/` Phase 1 and Phase 2 requirements
- `schemas/` proposed JSON schemas and data contracts
- `samples/` example Translation Brief and local ATT inputs
- `prompts/` Claude CLI implementation prompt
- `tests/` acceptance criteria and test matrix

Start with `docs/01-ATT-Architecture.md` and `prompts/CLAUDE-CLI-HANDOVER.md`.
