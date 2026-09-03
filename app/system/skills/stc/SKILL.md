---
name: stc
description: Execute one governed Source Text Correspondence (STC) work unit against bounded WIP and primary original-language Scripture.
---
# Source Text Correspondence (STC)

Execute only the sealed SAGE governed task described by `task-manifest.json` and `ACT.md`. Use only routed immutable inputs and return only the declared structured response. STC is read-only for every Scripture Project.

Use only the supplied WIP and original-language slice as content evidence. If a finding cannot be established from that slice, do not report it. Routed linguistic profiles are interpretation rules, not Scripture evidence. Do not use model recall, pretrained Scripture wording, external translations, lexicons, commentary, web sources, or inferred textual editions.

STC compares the bounded WIP directly with the testament-correct primary authority: GRK for the New Testament and HEB for the Old Testament. It has no Reference Project dependency and does not consume RTC findings.

Review correspondence at phrase and construction level; do not assume one-to-one lexical alignment. Findings are limited to `OMISSION`, `ADDITION`, `VARIATION`, and `CONSISTENCY`. Surface variation alone is not a finding. Report only what the routed WIP and original-language evidence establish.

Complete the semantic review for every assigned coordinate, including when there are no findings. SAGE owns work-unit identity, source selection, scope, context, fingerprints, coverage, and final ledgers.

Return only the semantic fields required by the response schema. SAGE validates coordinates, normalizes finding IDs, reconciles exact primary coverage, and creates the canonical STC Run result and reports.
