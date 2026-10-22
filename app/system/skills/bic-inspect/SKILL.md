---
name: bic-inspect
description: Inspect one bounded source scope and submit governed BIC challenges and memory proposals.
---
# BIC inspect

This Skill records what a sealed SAGE governed task (`task-manifest.json` and `ACT.md`) asks of the model in BIC INSPECT. The model receives only the task's Process brief from `ACT.md` (`act_render.py`), the read-class rules, the routed evidence, and the output schema; INSPECT receives no protected contract. This Skill and its references are hashed governance inputs and are not sent to the model; keep them consistent with the Process brief.

The declared SOURCE (`CONTENT_SOURCE`) is the complete and exclusive content authority. The routed DONOR vocabulary packet is lexical evidence only; the model never reconstructs donor verse wording, sequence, syntax, propositions, or discourse from it. The routed source-language grammar contract is used to analyze the source. INSPECT infers no target-language rules, imports no DONOR wording, and receives no pre-existing TARGET Scripture or original-language Scripture.

The model:

1. Reads any routed `semantic-*.json` packet before forming lexical hypotheses, treating exact local matches, SEMDOM classes, seed forms, and indexed senses as retrieval evidence only, never as translation authority.
2. Identifies bounded translation challenges without rewriting Scripture, keeping what the routed evidence shows apart from inference and from unresolved uncertainty.
3. Proposes a memory record only for a reusable project decision the routed evidence supports, citing that evidence. A proposal stays `PROPOSED`; only an Operator can mark a record `APPROVED_FOR_USE`.
4. Returns the proposals and challenges for `output/inspect-submission.json`. SAGE sets `schema_version`, `operation_id`, `scope`, and `resource_fingerprints` from the task.

INSPECT never generates TARGET Scripture, approves memory, changes configuration, or broadens scope.
