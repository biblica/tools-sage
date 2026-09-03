---
name: rtc
description: Execute one governed internal stage of Reference Text Comparison (RTC).
---
# Reference Text Comparison (RTC)

Execute only the sealed SAGE governed task described by `task-manifest.json` and `ACT.md`. Use only routed immutable inputs and return only the declared structured response. RTC is read-only for every Scripture Project.

Enforce the `LOCAL EVIDENCE BOUNDARY` in the manifest. Content evidence is SAGE-local: do not use model recall, pretrained Scripture wording, external Scripture, translations, lexicons, commentary, web sources, or unstated facts. General orthographic, morphological, grammatical, and syntactic competence may only interpret or express routed evidence.

RTC is one Operator operation with deterministic preflight, conditional structural adjudication, required reference-text comparison, conditional selective original-language adjudication, and deterministic coverage/finalization. Obey `rtc_stage`; do not perform later stages early.

Stage rules:

1. `STRUCTURAL_ADJUDICATION`: review only routed structural candidates. Versification and coordinate differences are reportable structure, never blockers. Do not infer missing content from numbering alone. No original-language Scripture is permitted.
2. `REFERENCE_TEXT_COMPARISON`: compare the complete bounded WIP with the bound REFERENCE. Treat actual multi-coordinate source records as indivisible verse bridges and compare all corresponding content even when bridge shapes differ. A VRS range is metadata, not a source-text bridge. Use no original-language Scripture. Emit bounded `ol_review_requests` only when the Run policy enables source-text-drift adjudication and correctness materially depends on source text; grammar, readability, punctuation, spelling, structure, style, and ordinary consistency remain direct RTC findings.
3. `SELECTIVE_OL_ADJUDICATION`: resolve only inherited bounded WIP–REFERENCE variance requests against the testament-correct Job authority (HEB for OT, GRK for NT). Return one `ol_resolutions` object per request. Do not broaden the task into a full original-language review or a new RTC pass.

Review every assigned coordinate or structural candidate and provide a concise `review_summary`, including when there are no findings. SAGE constructs identity, coverage, receipts, fingerprints, and final ledgers mechanically. Grammar findings must cite routed rule IDs. Semantic packets are local retrieval evidence, never findings by themselves.

Return only the stage-specific semantic fields required by the response schema. SAGE validates, normalizes, merges, and publishes the final RTC action report and plain-text issue blocks; it does not create or modify Paratext Notes XML.
