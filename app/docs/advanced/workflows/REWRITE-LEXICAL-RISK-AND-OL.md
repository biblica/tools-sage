# REWRITE lexical risk and bounded OL flow

## Purpose

This document describes the current protected BIC verb/lexical-choice flow. REWRITE completes automatically; linguistic risk changes evidence and reporting priority, not whether the Operator must choose a candidate.

## Decision order

1. Establish source meaning, participant roles, force, tone, tense, aspect, mood, modality, voice, discourse function, terminology, and genuine ambiguity.
2. Eliminate candidates that alter any required feature.
3. Compare remaining candidates for grammar, valency, collocation, register, terminology, and relevant local semantic evidence.
4. Among semantically viable candidates that are equal in meaning, force, register, and discourse function, prefer the more familiar wording.
5. The model records semantic risk and any material semantic trigger.
6. The controller opens one bounded OL check only when **risk >= 2 AND at least one material semantic trigger exists**.
7. If OL evidence supports a better candidate, the OL check returns a replacement for that one verse; SAGE merges it into the bounded candidate and revalidates it.
8. REWRITE completes with the recommended candidate at every linguistic risk level.
9. SELF-CHECK independently verifies the sealed completed candidate.

## Familiarity tie-break

Among candidates that preserve meaning, force, register, and discourse function equally, REWRITE prefers the more familiar wording (`familiarity_tie_break` in the protected verb-selection contract). The rule applies only after the semantic gate passes; familiarity never overrides meaning. No lexical-burden score or frequency band is recorded: the five-part score and the Longman mapping were removed in the 2026-10-22 re-pin because nothing used the total and no licensed Longman data was ever routed.

## Risk and OL policy

| Risk | Behavior |
|---:|---|
| 0-1 | Continue without OL |
| 2 | Run one bounded OL check only when a material semantic trigger exists; continue |
| 3 | Run the same trigger-governed OL check; complete REWRITE and elevate the review report |
| 4 | Run the same trigger-governed OL check; complete REWRITE with the recommended candidate and create a critical review item |

Material triggers include competing non-equivalent senses, possible force/agency change, participant-role change, aspect/modality uncertainty, source-reference tension, discourse dependency, and significant project concepts. **Lexical difficulty by itself is not a trigger.**

No Operator can request an extra OL call from inside REWRITE, choose a candidate, or override the recommended candidate. Review occurs through the completed risk-rated report and normal Team/LC/SC workflow.

## High-risk alternatives

Risk 3-4 records retain the material alternatives actually considered and rejected. The human report stays concise:

```text
RISK 3 — MAT 8:25
Chosen: X — preserves urgent rescue sense and participant relation.
Alternatives:
- Y — rejected: weaker force.
- Z — rejected: introduces habitual sense.
OL: source evidence supports immediate rescue.
```

The machine ledger may retain fuller evidence. The human report normally shows no more than three material alternatives for risk 3 and four for risk 4.

## Non-blocking rule

Linguistic uncertainty never marks a completed REWRITE `BLOCKED`. A rewrite may finish `STAGED_VALIDATED_WITH_CHALLENGES`. Reserve `BLOCKED` for technical impossibility, invalid/corrupt evidence, unsafe writes, immutable-control failure, or transaction failure.

## Outputs

REWRITE writes exactly:

- `output/rewrite.usfm`;
- `output/grammar-assessment.json`;
- `output/translation-challenges.json`.

The controller renders `validation/TRANSLATION-CHALLENGES.md`. No candidate-decision sidecar is created.
