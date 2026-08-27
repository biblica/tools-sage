---
name: saw-ol-review
description: Perform one bounded SAW original-language review with one explicit question.
---
# SAW original-language review

Execute only the sealed SAGE governed task described by `task-manifest.json` and `ACT.md`. Use only the routed immutable inputs; do not depend on provider workspace browsing, external file tools, or unlisted context. Return only the declared structured response.

Enforce the `LOCAL EVIDENCE BOUNDARY` in `task-manifest.json`. Content evidence is SAGE-local only: use each routed file only according to its `evidence_class`. Do not use model recall, pretrained Scripture knowledge, external Scripture/translations/lexicons/commentary, web sources, or unstated facts as content evidence. General orthographic, morphological, grammatical, and syntactic competence may be used only to understand or express the routed evidence; it must not introduce unsupported content.

Review one short scope and exactly one original-language question. Read every listed Skill reference and only the hashed task inputs. If `semantic-saw-signals.json` or `semantic-*.json` is routed, use it only for local-first interrogation/triage; no SEMDOM/index signal is a finding until the bounded translation evidence verifies it. Compare the WIP directly with the authoritative routed GRK or HEB packet; use the configured LWC Reference Project as comparative translation evidence. Do not broaden into commentary, a book study, or general QA.

Use the controller-supplied preflight restrictions and semantically adjudicate any assigned structural candidates. Do not repeat mechanical preflight, coverage, identity, or receipt construction. Apply project-grammar rules only where the OL evidence materially affects the WIP analysis.

Return only the stage-specific semantic fields required by the supplied response schema: a concise `review_summary`, the direct bounded answer, actionable findings, and structural adjudications where requested. Every actionable finding must cite explicit `original_language_evidence`, bounded evidence IDs, confidence, and a project-facing recommendation. SAGE injects identity, scope, coverage, checks, and receipts and materializes `output/findings.json`. SAW must not edit Scripture.
