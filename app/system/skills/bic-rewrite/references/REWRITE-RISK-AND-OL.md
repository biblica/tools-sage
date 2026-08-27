# REWRITE lexical burden and bounded OL risk control

## Principle

Use the contemporary CONTENT_SOURCE, bounded context, approved memory, and project grammar as the normal basis for REWRITE. Original-language evidence is a targeted risk-control resource, not a routine competing layer.

Lexical burden never overrides meaning. A less familiar verb remains required when it preserves a meaning component, semantic force, agency, participant relation, discourse function, or project term that an easier alternative loses.

## Lexical-burden scale

Score every candidate from 0 to 4 on these dimensions:

- familiarity: 40 per cent;
- register markedness: 15 per cent;
- sense ambiguity: 15 per cent;
- construction burden: 15 per cent;
- specialist load: 15 per cent.

Record every component and its evidence. Do not supply the weighted result as workflow authority; SAGE calculates the governed total locally. Use Longman bands only when licensed evidence is routed. Never invent a frequency band. The noun `translation` is permitted in human-facing BIC explanation and tables; `REWRITE` remains the sole canonical target-text action.

Lexical burden is a tie-breaker only among candidates that preserve the same meaning, force, tone, participant relationships, register, and discourse function.

### Licensed Longman familiarity mapping

| Band | Familiarity |
|---|---:|
| `S1` or `W1` | 0 |
| `S2` or `W2` | 1 |
| `S3`, `W3`, or `L3000` | 2 |
| `L6000` | 3 |
| `L9000` or `UNLISTED` | 4 |

Use a spoken band when present; otherwise use the written or Longman 9000 fallback. Retain every routed band. Use `UNKNOWN` when no licensed band is available.

## Automatic bounded OL referral

Do not consult OL merely because a candidate is uncommon or formal. Run one bounded OL check only when semantic risk is level 2 or higher and a material trigger exists. Keep the referral limited to one explicit question, the exact coordinate or short range, relevant form, morphology, syntax, and contextually plausible senses.

## Result handling

- Risk 0-1: continue automatically; aggregate low-level attention.
- Risk 2: continue automatically with a concise review item.
- Risk 3: complete REWRITE, emit an elevated review item, and continue automatically to SELF-CHECK.
- Risk 4: complete REWRITE with the recommended candidate, emit a concise critical review item, and continue to SELF-CHECK. REWRITE has no Operator candidate-selection path.

For risk 3-4, retain the material alternatives actually considered and a concise decisive rejection reason for each. The human report is capped and concise; the machine ledger retains full structured evidence.

When OL evidence supports a better candidate, update and revalidate the bounded USFM candidate and record the before/after candidate and risk. Linguistic uncertainty never sets the operation to `BLOCKED` or `DECISION_REQUIRED`.

## Inter-task resolution

Write the normalized challenge evidence to the persistent challenge ledger. SELF-CHECK consumes the sealed REWRITE candidate and ledger, then independently resolves, reduces, or carries each challenge forward. Reports and logs are the primary resolution mechanism. Reserve `BLOCKED` for technical impossibility, invalid evidence, unsafe writes, immutable-control failure, or transaction failure.
