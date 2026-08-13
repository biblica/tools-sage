# Known Limitations — RC7.04

- RC7.04 enables automated execution through CODEX only. Ollama and LM Studio may be provisioned but cannot execute governed tasks in this build. Grok/Gemini remain future provider-adapter possibilities.
- OpenAI API keys, direct OpenAI API execution, service accounts, and API fallback are unavailable/prohibited for SAGE.
- External Paratext/PTLite access is deliberately limited to `.SFM` and `.VRS` reads; only an explicitly writable BIC TARGET may receive `.SFM` writes. `.VRS` is always read-only.
- Bounded BIC TARGET merge fails closed when a requested scope partially intersects a verse bridge or another USFM structure that cannot be replaced safely without broadening the governed scope.
- A new TARGET book can be created progressively from bounded commits; insertion into an existing book requires the relevant chapter structure to exist rather than inventing surrounding USFM structure.
- The operating contract assumes Paratext/PTLite editors are closed while SAGE executes. RC7.04 does not implement cross-application editor locking.
- SAGE/SAW does not create or modify Paratext Notes XML. SAW emits plain Operator note text for manual copy/paste.
- Normal SAW QA can require multiple isolated model stages; it is one Operator operation, not one guaranteed model call.
- WDA / Word Data Analysis is future work and is not implemented as part of SAW.
- Existing-target/BASE_TARGET revision is future work and is not part of BIC.
- BIC and SAW remain independent; SAGE provides no direct BIC TARGET→SAW WIP handoff.
- `AI_DRAFTED` grammar is an accepted LLM-general-language-knowledge starting profile, not Team/project-approved linguistic evidence.
- Optional `./sage request` remains bounded controller-owned natural-language command routing; it is not unrestricted model-driven execution and cannot bypass registered commands, Project/Job/Run governance, validation, or authority rules.

- Normal SAW QA meaning review is intentionally partitioned to deterministic discourse units. Poetry units are operational structural chunks, not AI-inferred literary stanza analysis.
- BIC conditional OL micro-checks are intentionally single-verse. A genuinely cross-verse linguistic dependency must be surfaced as an unresolved challenge rather than silently broadening provider Scripture context.
