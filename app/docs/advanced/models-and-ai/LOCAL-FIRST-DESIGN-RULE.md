# Local-First Design Rule

**Status:** current SAGE architectural rule.

SAGE MUST perform work locally and deterministically whenever the required result can be obtained reliably without semantic or linguistic inference. An AI call is permitted only when material judgment requires model reasoning.

## Local controller responsibilities

Use local code for USFM parsing, scope extraction, hashing, exact lookup, lemma and Semantic Domain retrieval, correspondence retrieval, occurrence counts, lexical-burden arithmetic, OL-trigger calculation, evidence-packet assembly, schema validation, report rendering, audit logging, and state transitions.

## AI responsibilities

Use AI for contextual sense judgment, semantic equivalence, candidate generation, tone and force evaluation, legitimate ambiguity, bounded original-language interpretation, final translation judgment, and independent SELF-CHECK.

## Decision test

1. If the answer can be computed reliably, do it locally.
2. If it cannot, ask whether semantic or linguistic judgment is genuinely required.
3. Only then create a governed AI task.
4. If a non-semantic operation still requires AI, improve the local implementation rather than normalizing the AI dependency.

This rule is independent of provider selection and applies to BIC, RTC/STC, RWC indexing, and future tools that reuse the SAGE semantic-index engine.
