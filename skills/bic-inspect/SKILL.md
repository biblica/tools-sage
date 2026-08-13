---
name: bic-inspect
description: Inspect one bounded source scope and submit governed BIC challenges and memory proposals.
---
# BIC inspect

Execute only the sealed SAGE governed task described by `task-manifest.json` and `ACT.md`. Use only the routed immutable inputs; do not depend on provider workspace browsing, external file tools, or unlisted context. Write only the outputs declared by the task.

Execute only the generated ACT task. Read every file in the listed Skill `references/` set before analysing the bounded evidence. Treat the declared SOURCE (`CONTENT_SOURCE`) as the complete and exclusive content authority. Treat the routed DONOR vocabulary packet as lexical evidence only; never reconstruct donor verse wording, sequence, syntax, propositions, or discourse from it. Use the routed source-language grammar contract to analyse the source; do not infer target-language rules during INSPECT, import wording from the DONOR, or use pre-existing TARGET Scripture as evidence.

Work in this order:

1. Confirm the task identity, exact scope, input hashes, and permitted output.
2. Read any routed `semantic-*.json` packet before generating lexical hypotheses. Treat exact local matches, SEMDOM classifications, seed forms, and indexed senses as retrieval evidence only, never as translation authority.
3. Identify bounded translation challenges without rewriting Scripture.
4. Propose human-reviewable memory records only when the evidence supports a reusable project decision.
5. Distinguish observed evidence, inference, and unresolved uncertainty.
6. Write only `output/inspect-submission.json` in the required BIC INSPECT grammar.

Set `operation_id`, `scope`, and `resource_fingerprints` exactly from `task-manifest.json`. Do not generate TARGET Scripture, approve memory, modify configuration, broaden scope, or read unlisted files. Missing, stale, contradictory, or invalid evidence is a hard stop. Submit with the exact command in `ACT.md`.
