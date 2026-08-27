# Known Limitations — v0.01beta

- Commentary and operator/runtime diagnostics are not yet fully separated into distinct report artifacts; provider execution diagnostics may still appear in the human report during interrupted Runs.
- v0.01beta enables governed BIC/SAW execution through CODEX only. Ollama remains optional explicit administration tooling and cannot execute governed tasks; administrative explanations and executive summaries are deterministic. Grok/Gemini remain future provider-adapter possibilities.
- Local AI mode intentionally disables Job secondary reporting while enabled. Existing secondary-language Jobs must be cleared by the Operator before Local AI can be enabled; SAGE does not silently modify them.
- The local admin assistant is disabled on hosts with less than 16 GiB total RAM. Its community-converted Gemma 4 E2B Q5_K_M GGUF is fetched from an immutable pinned upstream revision and accepted only after the fixed SHA-256 check succeeds.
- OpenAI API keys, direct OpenAI API execution, service accounts, and API fallback are unavailable/prohibited for SAGE.
- External Paratext/PTLite access is deliberately limited to `.SFM` and `.VRS` reads; only an explicitly writable BIC TARGET may receive `.SFM` writes. `.VRS` is always read-only.
- Bounded BIC TARGET merge fails closed when a requested scope partially intersects a verse bridge or another USFM structure that cannot be replaced safely without broadening the governed scope.
- A new TARGET book can be created progressively from bounded commits; insertion into an existing book requires the relevant chapter structure to exist rather than inventing surrounding USFM structure.
- The operating contract assumes Paratext/PTLite editors are closed while SAGE executes. v0.01beta does not implement cross-application editor locking.
- SAGE/SAW does not create or modify Paratext Notes XML. SAW emits plain Operator note text for manual copy/paste.
- Normal SAW Reference Text Comparison (RTC) can require multiple isolated model stages; it is one Operator operation, not one guaranteed model call.
- WDA / Word Data Analysis is future work and is not implemented as part of SAW.
- Existing-target/BASE_TARGET revision is future work and is not part of BIC.
- BIC and SAW remain independent; SAGE provides no direct BIC TARGET→SAW WIP handoff.
- `AI_DRAFTED` grammar may use only general orthographic, morphological, grammatical, and syntactic competence. It is a starting process/language-form profile, not content evidence, lexical authority, Scripture knowledge, or Team/project-approved linguistic evidence.
- SAGE can enforce a sealed local context, explicit evidence classes, no web/tool access from governed model tasks, and provenance-bound conclusions. It cannot prove that a general-purpose model contains no latent pretrained Scripture knowledge; the enforceable rule is that model recall/pretraining is never an authorized evidence source and substantive Job conclusions must be supportable from routed local evidence.
- Optional `./system/bin/sage request` remains bounded controller-owned natural-language command routing; it is not unrestricted model-driven execution and cannot bypass registered commands, Project/Job/Run governance, validation, or authority rules.

- Normal SAW Reference Text Comparison (RTC) meaning review is intentionally partitioned to deterministic discourse units. Poetry units are operational structural chunks, not AI-inferred literary stanza analysis.
- BIC conditional OL micro-checks are intentionally single-verse. A genuinely cross-verse linguistic dependency must be surfaced as an unresolved challenge rather than silently broadening provider Scripture context.
