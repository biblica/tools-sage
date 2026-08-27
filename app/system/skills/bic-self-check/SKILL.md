---
name: bic-self-check
description: Independently review one staged BIC rewrite and submit the final bounded target candidate.
---
# BIC self-check

Execute only the sealed SAGE governed task described by `task-manifest.json` and `ACT.md`. Use only the routed immutable inputs; do not depend on provider workspace browsing, external file tools, or unlisted context. Write only the outputs declared by the task.

Enforce the `LOCAL EVIDENCE BOUNDARY` in `task-manifest.json`. Content evidence is SAGE-local only: use each routed file only according to its `evidence_class`. Do not use model recall, pretrained Scripture knowledge, external Scripture/translations/lexicons/commentary, web sources, or unstated facts as content evidence. General orthographic, morphological, grammatical, and syntactic competence may be used only to understand or express the routed evidence; it must not introduce unsupported content.

Start only from a generated SELF-CHECK task whose predecessor is a staged, validated BIC REWRITE task. Read every listed Skill reference. Use the staged REWRITE candidate, SOURCE (`CONTENT_SOURCE`), decontextualized DONOR vocabulary evidence, committed memory, project grammar, the material translation-challenge ledger, and any OL evidence actually used by REWRITE. Independently verify the staged candidate and resolve, revise, or carry forward each material challenge. No decision file is required. The task must not expose Pass 1 rationale.

Independently check additions, omissions, semantic shifts, wrong senses, referent errors, grammar that obscures meaning, information-order errors, altered or missing USFM content, and every selected elevated-risk verb choice. Reassess every governed grammar rule.

Write only:

- `output/self-check.usfm`
- `output/grammar-assessment.json`

Preserve exact bounded coordinate coverage and all protected semantic markers; normalize layout markers only when the task policy permits it. Bind the grammar assessment to the final output hash and cover every routed rule. The submit command performs deterministic validation and a journaled atomic TARGET commit. Do not edit the TARGET project directly.
