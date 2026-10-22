---
name: bic-rewrite
description: Rewrite one bounded target scope after committed INSPECT with non-blocking review attention.
---
# BIC rewrite

This Skill records what a sealed SAGE governed task (`task-manifest.json` and `ACT.md`) asks of the model in BIC REWRITE (Pass 1). The model receives only the task's Process brief from `ACT.md` (`act_render.py`), the pinned protected contracts (`references/PROTECTED-REWRITE-DETAIL-RULES.md` and `system/config/contracts/bic-verb-selection-policy.yml`), the read-class rules, the routed evidence, and the output schema. This Skill and its references are hashed governance inputs and are not sent to the model; keep them consistent with the Process brief.

SAGE creates a REWRITE task only after the exact-scope INSPECT submission is committed. The declared SOURCE (`CONTENT_SOURCE`) is the complete and exclusive content authority. DONOR (`LEXICAL_DONOR`) is vocabulary evidence only; the model never infers or copies donor wording, verse sequence, syntax, propositions, participant structure, or discourse. Pre-existing TARGET Scripture is not input evidence. The model uses only `APPROVED_FOR_USE` memory, the governed project grammar, the committed translation challenges, and the conditional OL evidence SAGE releases under the material-risk rule.

The model:

1. Produces one bounded USFM candidate that preserves every bounded source content unit, exact coordinate coverage, and all protected semantic markers; layout markers are normalized only when the task marker policy permits it.
2. Uses routed semantic/index evidence and approved memory before generating new lexical alternatives, compares only semantically viable verbs or constructions, and keeps semantic precision ahead of accessibility.
3. Applies the familiarity tie-break of the verb-selection contract: among candidates that preserve meaning, force, register, and discourse function equally, the more familiar wording wins. No burden score is recorded. SAGE derives OL authorization, candidate-change state, urgency, and reporting level.
4. Records `risk.before_ol` and the material trigger codes for each challenge, and does not request, read, or simulate OL evidence. At material semantic-risk level 2 or higher with a material trigger, SAGE runs one automatic bounded OL check per challenge as a separate single-verse conditional OL question and merges any better candidate itself. Uncommon or formal wording alone is not a trigger.
5. Completes risk 3 and 4 challenges with the recommended candidate and keeps the concise material alternatives considered, each with its rejection code and reason. REWRITE accepts no Operator candidate input.
6. Assesses every governed grammar rule against the candidate.

Outputs: `output/rewrite.usfm`, `output/grammar-assessment.json`, and `output/translation-challenges.json`. SAGE binds the grammar assessment to the candidate hash and sets every identity field.

`translation-challenges.json` lists only material urgency 2–4 challenges individually, consolidates repeated causes, and aggregates lower-level or automatically resolved matters. Linguistic uncertainty elevates the report; it does not block completion of the current REWRITE operation.

This is Pass 1 only. SELF-CHECK runs as a separate task that never sees first-pass rationale.
