---
name: saw-focused-check
description: Answer one bounded SAW focus question for one LWC work-in-progress translation.
---
# SAW Targeted Check

Execute only the sealed SAGE governed task described by `task-manifest.json` and `ACT.md`. Use only the routed immutable inputs; do not depend on provider workspace browsing, external file tools, or unlisted context. Return only the declared structured response.

Enforce the `LOCAL EVIDENCE BOUNDARY` in `task-manifest.json`. Content evidence is SAGE-local only: use each routed file only according to its `evidence_class`. Do not use model recall, pretrained Scripture knowledge, external Scripture/translations/lexicons/commentary, web sources, or unstated facts as content evidence. General orthographic, morphological, grammatical, and syntactic competence may be used only to understand or express the routed evidence; it must not introduce unsupported content.

Answer exactly the one bounded focus question and declared check type in `ACT.md` for one LWC WIP translation. Read every listed Skill reference and only the hashed task inputs. If `semantic-saw-signals.json` or `semantic-*.json` is routed, use it only for local-first interrogation/triage; no SEMDOM/index signal is a finding until the bounded translation evidence verifies it. Use the authorized REFERENCE and routed local evidence only. Targeted Check never receives OL Scripture. If the bounded question requires original-language adjudication, report that limitation and use the separate governed SAW OL Review operation rather than answering from memory. Do not broaden into general RTC, commentary, or rewriting.

Use the controller-supplied preflight restrictions and semantically adjudicate any assigned structural candidates. Do not repeat mechanical preflight, coverage, identity, or receipt construction. Apply routed project-grammar rules where relevant and cite their IDs.

Return only the stage-specific semantic fields required by the supplied response schema: a concise `review_summary`, the direct bounded `answer`, actionable findings, and structural adjudications where requested. SAGE injects identity, scope, coverage, checks, and receipts and materializes `output/findings.json`. SAW must not edit Scripture.
