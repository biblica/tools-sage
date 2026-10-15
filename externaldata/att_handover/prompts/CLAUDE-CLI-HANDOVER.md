# Claude CLI Implementation Handover - SAGE ATT

You are implementing a new SAGE extension called ATT (Advanced Term Tool).

## First action
Inspect the repository before coding. Identify:
- Translation Brief/config system
- existing resource/index loading patterns
- current OL shipped-resource conventions
- `input/` folder conventions
- reporting/finding models
- test framework
- command/ACT/run dispatch conventions
- any existing terminology or consistency tooling

Reuse existing SAGE conventions wherever possible.

## Product definition
ATT is a recurring-term consistency checker.

It answers:

> When the same recurring SOURCE term or SOURCE phrase appears again, does TARGET handle it consistently according to the project pattern?

ATT is NOT RTC/STC and must not become a general semantic correctness engine.

## Authority model
ATT inherits source/reference authority entirely from the Translation Brief.

Supported Phase 1 modes:
- SINGLE
- DUAL_HIERARCHICAL
- DUAL_COAUTHORITATIVE

Do not use OL as a fallback authority unless OL is explicitly configured as SOURCE.

## Phase 1 resource model
- Static, prebuilt, versioned reference packages shipped with SAGE.
- No runtime SQS dependency.
- TARGET indexing is dynamic/local.
- Canonical reference packages are immutable.
- Project-local custom terms/phrases are supported under:

```text
input/att/terms.txt
input/att/phrases.txt
```

Rules:
- UTF-8
- one SOURCE-language entry per line
- `#` comments
- blank lines ignored
- duplicates de-duplicated
- resolve only against configured SOURCE
- unresolved/ambiguous entries reported, never guessed
- local records are project-only and never written into canonical indexes

## Analysis streams

### Lexical
- proper nouns / named entities
- key verbs
- key concepts / terminology
- monitored lexical families

### Phrase
- fixed recurring phrases
- creedal/confessional formulae
- jargon
- rhetorical/discourse formulae

Use separate analyzers with shared normalization/alignment and one unified finding model.

## Run behavior

SINGLE:
- SOURCE -> TARGET detection

DUAL_HIERARCHICAL:
- PRIMARY -> TARGET detection
- SECONDARY only adds correlation context
- SECONDARY never silently overrides PRIMARY

DUAL_COAUTHORITATIVE:
- analyze A and B independently
- reconcile findings
- report REFERENCE_PATTERN_DIVERGENCE where needed
- do not fabricate consensus

## Finding classifications
At minimum support:
- CONSISTENT
- MORPHOLOGICAL_VARIANT
- ORTHOGRAPHIC_VARIANT
- APPROVED_RENDERING_VARIANT
- CONTEXTUAL_VARIANT
- UNIQUE_RENDERING
- POSSIBLE_INCONSISTENCY
- REFERENCE_PATTERN_DIVERGENCE
- UNRESOLVED_LOCAL_INPUT
- AMBIGUOUS_LOCAL_INPUT

## Phase 1 phrase matching
For local phrase uploads, literal normalized phrase matching is sufficient.
Do not add model-based phrase discovery to the critical path.

## Reproducibility
Record run metadata:
- run_id
- source/reference IDs and versions
- resource/index schema versions
- target checksum/version
- ruleset version
- timestamp

## Phase 2 guardrail
Do not implement SQS now.
Design interfaces so Phase 1 local reference packages can later be supplied by SQS without changing ATT analysis logic.

Phase 2 will add:
- SQS Source Registry
- version/checksum management
- advanced operator ingestion
- validation/review/publish lifecycle
- licensing/entitlements
- package distribution/cache
- future OL resource migration

## Required implementation deliverables
1. architecture note referencing existing SAGE modules to reuse
2. config/schema changes
3. reference package loader/validator
4. local ATT input reader/resolver
5. lexical analyzer
6. phrase analyzer
7. dual-reference correlation/reconciliation
8. unified finding/report model
9. unit/integration tests
10. operator/developer docs

## Non-negotiable constraints
- no SQS runtime dependency in Phase 1
- no mutation of canonical reference indexes
- no OL override of trusted SOURCE
- no RTC/STC verdicts
- no invented source authority
- preserve existing SAGE conventions where possible
- if repository reality conflicts with this handover, document the conflict and make the smallest compatible change

Read the accompanying docs and schemas before implementation.
