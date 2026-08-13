---
name: saw-qa
description: Execute one governed internal stage of the composite SAW Normal QA workflow.
---
# SAW Normal QA stage

Execute only the sealed SAGE governed task described by `task-manifest.json` and `ACT.md`. Use only routed immutable inputs; do not depend on provider workspace browsing, external file tools, or unlisted context. Write only the declared output. SAW is read-only for every external Scripture resource.

Normal QA is one Operator operation orchestrated by SAGE as deterministic preflight/structural triage, conditional structural adjudication, required translation/meaning QA, conditional selective OL adjudication, and deterministic merge/coverage/finalisation. This Skill receives exactly one model stage at a time. Obey the `qa_stage` in the governed task; do not perform later stages early.

Stage rules:

1. `STRUCTURAL_ADJUDICATION`: review only the routed ambiguous structural candidates against WIP, REFERENCE, VRS, and permitted grammar evidence. No OL Scripture is routed or permitted.
2. `TRANSLATION_AND_MEANING_QA`: review the complete bounded WIP against the authorised REFERENCE and routed WIP grammar/local semantic evidence. Do not use OL Scripture. If a specific unresolved question genuinely requires GRK/HEB, emit a bounded `ol_review_requests` entry with a unique `deferred_finding_id`; do not also emit that deferred issue as a final finding and do not answer it from memory.
3. `SELECTIVE_OL_ADJUDICATION`: resolve only the inherited bounded OL requests using the exact stage-reference inventory, routed GRK/HEB packet, and predecessor evidence. Return exactly one structured `ol_resolutions` object per request. A `FINDING` outcome must use the inherited `deferred_finding_id`; every resolution must cite actual OL evidence. Do not broaden into a new full QA pass.

For every stage, reconcile the exact stage-reference coordinates and provide task-bound review receipts with the task fingerprint, required checks, exact reviewed references, and a substantive evidence summary. If semantic packets are routed, treat them as local retrieval/triage evidence, never as findings by themselves. Grammar findings must cite routed rule IDs.

Write only `output/findings.json` in the current SAW findings grammar and submit with the exact command in `ACT.md`. SAGE validates each stage and deterministically finalises the composite QA result. The final Operator outputs are an action report plus simple plain-text, copy/paste-ready issue blocks; SAGE does not create or modify Paratext Notes XML.
