---
name: saw-stc
description: Execute one governed SAW Source Text Correspondence (STC) work unit against bounded WIP and primary original-language Scripture.
---
# SAW Source Text Correspondence (STC)

Execute only the sealed SAGE governed task described by `task-manifest.json` and `ACT.md`. Use only routed immutable inputs and return only the declared structured response. SAW remains read-only for all Scripture resources.

## Evidence boundary

Use only the supplied WIP + OL slice as content evidence. Do not use ANY information outside that slice to form or support a finding. If a finding cannot be established from the supplied WIP + OL slice, do not report it.

The routed linguistic profiles are interpretation rules, not Scripture evidence. Use them to preserve canonical language, dialect, and historical register. Do not use model recall, pretrained Scripture text, external translations, lexicons, commentary, web sources, or inferred textual editions as content evidence.

STC compares the bounded WIP rendering directly with the testament-correct primary OL authority: NT uses GRK; OT uses HEB. Do not compare against the configured Reference Project and do not consume RTC findings.

Review governed correspondence at phrase/construction level rather than assuming one-to-one lexical alignment. Findings are limited to `OMISSION`, `ADDITION`, `VARIATION`, and `CONSISTENCY`. Surface variation alone is not a finding. Report only candidates that the supplied WIP+OL evidence establishes.

For every assigned primary coordinate, complete the semantic review even when there are zero findings. Do not construct work-unit identity, coverage, source selection, context, fingerprints, or final ledgers; SAGE owns those mechanically.

Return only the semantic fields required by the supplied response schema. SAGE validates evidence coordinates, normalizes stable finding IDs, proves analytical completion, reconciles exact primary coverage, and creates the canonical STC run result, findings artifact, and report.
