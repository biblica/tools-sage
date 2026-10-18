# Known Limitations — v0.02b1

- Further TUI workflow functionality is deliberately paused for `0.02b1` and deferred to a later release. The retained experimental preview provides navigation/status/readiness and its existing bounded setup-remediation actions; use the classic menu or scriptable CLI for authoritative Project, Job, Run, report, and recovery work.
- Commentary and operator/runtime diagnostics are not yet fully separated into distinct report artifacts; provider execution diagnostics may still appear in the human report during interrupted Runs.
- v0.02b1 enables governed BIC/RTC/STC/NCA execution through CODEX only. Ollama remains optional explicit administration tooling and cannot execute governed tasks; administrative explanations and executive summaries are deterministic. Grok/Gemini remain future provider-adapter possibilities.
- Local AI mode intentionally disables Job secondary reporting while enabled. Existing secondary-language Jobs must be cleared by the Operator before Local AI can be enabled; SAGE does not silently modify them.
- The local admin assistant is disabled on hosts with less than 16 GiB total RAM. Its community-converted Gemma 4 E2B Q5_K_M GGUF is fetched from an immutable pinned upstream revision and accepted only after the fixed SHA-256 check succeeds.
- OpenAI API keys, direct OpenAI API execution, service accounts, and API fallback are unavailable/prohibited for SAGE.
- External Paratext/PTLite access is deliberately limited to `.SFM` and `.VRS` reads; only an explicitly writable BIC TARGET may receive `.SFM` writes. `.VRS` is always read-only.
- Bounded BIC TARGET merge fails closed when a requested scope partially intersects a verse bridge or another USFM structure that cannot be replaced safely without broadening the governed scope.
- A new TARGET book can be created progressively from bounded commits; insertion into an existing book requires the relevant chapter structure to exist rather than inventing surrounding USFM structure.
- The operating contract assumes Paratext/PTLite editors are closed while SAGE executes. v0.02b1 does not implement cross-application editor locking.
- SAGE/RTC/STC does not create or modify Paratext Notes XML. RTC/STC emits plain Operator note text for manual copy/paste.
- RTC can require multiple isolated model stages; it is one Operator operation, not one guaranteed model call.
- WDA / Word Data Analysis is future work and is not implemented as part of RTC/STC.
- Existing-target/BASE_TARGET revision is future work and is not part of BIC.
- BIC, RTC, and STC remain independent; SAGE provides no direct BIC TARGET→analysis WIP handoff.
- `AI_DRAFTED` grammar may use only general orthographic, morphological, grammatical, and syntactic competence. It is a starting process/language-form profile, not content evidence, lexical authority, Scripture knowledge, or Team/project-approved linguistic evidence.
- SAGE can enforce a sealed local context, explicit evidence classes, no web/tool access from governed model tasks, and provenance-bound conclusions. It cannot prove that a general-purpose model contains no latent pretrained Scripture knowledge; the enforceable rule is that model recall/pretraining is never an authorized evidence source and substantive Job conclusions must be supportable from routed local evidence.
- Optional `./system/bin/sage request` remains bounded controller-owned natural-language command routing; it is not unrestricted model-driven execution and cannot bypass registered commands, Project/Job/Run governance, validation, or authority rules.

- RTC meaning review is intentionally partitioned to deterministic discourse units. Poetry units are operational structural chunks, not AI-inferred literary stanza analysis.
- BIC conditional OL micro-checks are intentionally single-verse. A genuinely cross-verse linguistic dependency must be surfaced as an unresolved challenge rather than silently broadening provider Scripture context.

- NCA findings are limited by the selected LLM's language understanding and numeric-interpretation capabilities; SQS confidence checks have not been applied. Provider-free tests establish software behavior, not live-model accuracy in a target language.
- NCA checks only numbers that state a quantity or a date (counting convention 2.0). Implied numbers, frequency, pronoun "one", rank ordinals, "both", pairs, and indefinite plurals are out of scope by design and are never reported.
- The NIV layer of the NCA index is secondary evidence. A WIP that follows the NIV where it differs from the original language is NEEDS_REVIEW, never FAIL; only an original-language reading the index vouches for can support a FAIL.
- NCA text-critical evidence is limited to the cached sources it cites (NET Bible tc notes, SBLGNT apparatus, OSHB ketiv/qere, Brenton LXX, Douay-Rheims, KJV, synoptic parallels). Twelve NET-cited number variants rest on the NET note alone, and eight registered footnote-guidance entries (1CH 25:9, 1KI 4:26, 1KI 5:11, 1SA 13:5, 1SA 1:24, 2KI 25:3, EZK 26:1, NEH 7:68) have no apparatus evidence; they are kept for operator review. See the [apparatus summary](advanced/release/nca-index-rebuild/APPARATUS-SUMMARY.md).
- The typed NCA package `SAGE_NUMBERS_TYPED_2026-10-09` **failed** its [release gate](advanced/release/NCA-RELEASE-GATE.md) on 2026-10-18. Extraction recall and planted-error detection pass, but FAIL precision is 60%; the bar is 90%. Treat every NCA FAIL as a candidate for review, not a confirmed error.
- NCA cannot run on Acts yet: the package mapping lacks the `ACT 19:40-41` continuation (`TODO-20261018-002`).
