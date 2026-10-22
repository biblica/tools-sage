# REWRITE familiarity and bounded OL risk control

## Principle

Use the contemporary CONTENT_SOURCE, bounded context, approved memory, and project grammar as the normal basis for REWRITE. Original-language evidence is a targeted risk-control resource, not a routine competing layer.

Familiarity never overrides meaning. A less familiar verb remains required when it preserves a meaning component, semantic force, agency, participant relation, discourse function, or project term that an easier alternative loses.

## Familiarity tie-break

Among candidates that preserve meaning, force, register, and discourse function equally, prefer the more familiar wording (`familiarity_tie_break` in the protected verb-selection contract). The rule applies only after the semantic gate passes. No lexical-burden score or frequency band is recorded. The noun `translation` is permitted in human-facing BIC explanation and tables; `REWRITE` remains the sole canonical target-text action.

## Automatic bounded OL referral

REWRITE records each challenge's semantic risk (`risk.before_ol`) and material trigger codes; it never requests or reads OL evidence itself. SAGE runs one bounded OL check per challenge only when semantic risk is level 2 or higher and a material trigger exists, as a separate single-verse question. An uncommon or formal candidate alone is not a trigger. The referral is limited to one explicit question, the exact coordinate, relevant form, morphology, syntax, and contextually plausible senses.

## Result handling

- Risk 0-1: continue automatically; aggregate low-level attention.
- Risk 2: continue automatically with a concise review item.
- Risk 3: complete REWRITE, emit an elevated review item, and continue automatically to SELF-CHECK.
- Risk 4: complete REWRITE with the recommended candidate, emit a concise critical review item, and continue to SELF-CHECK. REWRITE has no Operator candidate-selection path.

For risk 3-4, retain the material alternatives actually considered and a concise decisive rejection reason for each. The human report is capped and concise; the machine ledger retains full structured evidence.

When OL evidence supports a better candidate, the OL check returns a replacement for that one verse; SAGE merges it into the bounded USFM candidate, revalidates it, and records the before/after candidate and risk. Linguistic uncertainty never sets the operation to `BLOCKED` or `DECISION_REQUIRED`.

## Inter-task resolution

Write the normalized challenge evidence to the persistent challenge ledger. SELF-CHECK consumes the sealed REWRITE candidate and ledger, then independently resolves, reduces, or carries each challenge forward. Reports and logs are the primary resolution mechanism. Reserve `BLOCKED` for technical impossibility, invalid evidence, unsafe writes, immutable-control failure, or transaction failure.
