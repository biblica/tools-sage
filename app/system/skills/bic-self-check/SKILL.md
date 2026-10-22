---
name: bic-self-check
description: Independently review one staged BIC rewrite and submit the final bounded target candidate.
---
# BIC self-check

This Skill records what a sealed SAGE governed task (`task-manifest.json` and `ACT.md`) asks of the model in BIC SELF-CHECK. The model receives only the task's Process brief from `ACT.md` (`act_render.py`), the pinned protected contracts (`references/PROTECTED-REWRITE-DETAIL-RULES.md` and `system/config/contracts/bic-verb-selection-policy.yml`), the read-class rules, the routed evidence, and the output schema. This Skill and its references are hashed governance inputs and are not sent to the model; keep them consistent with the Process brief.

SAGE creates a SELF-CHECK task only from a staged, validated BIC REWRITE task. The task routes the staged REWRITE candidate, SOURCE (`CONTENT_SOURCE`), decontextualized DONOR vocabulary evidence, approved memory, project grammar, the material translation-challenge ledger, and any OL evidence REWRITE actually used. It never routes Pass 1 rationale, and no decision file is required.

The model:

1. Compares the candidate directly with SOURCE, verse by verse, for additions, omissions, semantic shifts, wrong senses, referent errors, grammar that obscures meaning, information-order errors, and altered or missing USFM content.
2. Re-checks every verb or construction choice behind a material challenge in the ledger, and resolves, revises, or carries it forward.
3. Corrects only supported fidelity, USFM, project-grammar, or governed candidate-decision issues, preserving exact bounded coordinate coverage and all protected semantic markers; layout markers are normalized only when the task marker policy permits it.
4. Reassesses every governed grammar rule for the final candidate.

Outputs: `output/self-check.usfm` and `output/grammar-assessment.json`. SAGE binds the grammar assessment to the final output hash, validates the candidate, commits each passing verse to the TARGET in one journaled transaction, and reports any verse left out. The model never edits the TARGET project directly.
