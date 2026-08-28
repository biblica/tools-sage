# BIC workflow

BIC implements:

```text
SOURCE + DONOR -> TARGET
INSPECT → REWRITE → SELF-CHECK → transactional TARGET commit
```

SOURCE (`CONTENT_SOURCE`) is the sole content/translation authority. DONOR (`LEXICAL_DONOR`) is vocabulary evidence only. TARGET (`GENERATED_TARGET`) is a write destination; existing TARGET Scripture is not routed during INSPECT/REWRITE.


An optional human memory-review receipt may be recorded as provenance after INSPECT; no human receipt is required for REWRITE. Urgency 3 is logged and carried into SELF-CHECK automatically under the protected policy. `--grammar-override-id` remains optional provenance. Guided Input returns `INPUT_REQUIRED` for recoverable missing/ambiguous values rather than allowing the provider to guess.

## Canonical linguistic profiles

Every BIC model-facing stage receives the complete canonical `LANGUAGE_PROFILE` for each routed project-language stream. Any authorized bounded OL micro-review additionally receives the source-bound GRK/HEB `OL_AUTHORITY_PROFILE`. Profiles are immutable governed context, are not sliced, and do not contribute to Scripture SFM sizing. Missing or ambiguous required linguistic specificity blocks provider handoff rather than allowing model inference.

## Required controls

- SOURCE, DONOR, and TARGET must be distinct projects.
- INSPECT routes bounded SOURCE evidence plus a decontextualized DONOR vocabulary packet; no donor verse text and no pre-existing TARGET Scripture are routed.
- REWRITE requires a committed exact-scope INSPECT submission.
- Only memory marked `APPROVED_FOR_USE` may influence REWRITE.
- REWRITE and SELF-CHECK route the required source/target grammar contracts without changing content authority.
- A BIC Job may configure one Greek resource and/or one Hebrew resource. Material semantic risk level 2 or higher plus the protected trigger may open one bounded OL packet; if the applicable OL resource is not configured or usable, the OL-dependent REWRITE cannot complete.
- The protected rewrite-detail and verb-selection policies remain authoritative and unchanged.
- Linguistic uncertainty elevates reporting; it does not create Operator candidate selection or override.
- SELF-CHECK receives the sealed REWRITE candidate as the object under check, independently validates it, and performs the controlled TARGET commit.
- Publication is a separate optional operation.

Use `./system/bin/bic --help` for operator syntax. Use `--source`, `--donor`, and `--target` for BIC resource bindings.
