# Next Development Work

1. Keep **primary reporting wire reduction** as a separate higher-risk promotion gate. Do not change BIC semantic wire contracts, Scripture projection, evidence authority, or reasoning policy as part of administrative-rendering work.
2. Native Windows, macOS, and Linux acceptance is accepted work: see `TODO-20260826-002` through `TODO-20260826-004` in [the TODO log](project-management/TODO.md).
3. Exercise Reference Text Comparison (RTC) against representative real Project scopes to tune deterministic preflight thresholds and selective-OL request granularity without changing authority boundaries.
4. Exercise broad Book/section scopes on real translations to validate the current pre-Run work/token preview, structural splitting, and Change-scope recovery path under realistic text sizes.
5. Continue menu-first convergence for any remaining low-frequency CLI-only maintenance actions; keep direct CLI syntax documented as a shortcut rather than the primary operator story.
6. Decide during Beta development whether to retire the narrow internal compatibility aliases whose Python names still contain legacy Project-registration terminology. They are not operator-facing and should not be renamed during Beta development without a migration reason.
7. Define a future localdata schema-migration policy before any release introduces an incompatible persisted-data schema. The first published `0.02b1` baseline requires no migration from unpublished legacy layouts.
8. Evaluate later provider enablement only after the development interaction grammar stabilizes. Ollama remains explicit administration tooling only; Grok/Gemini remain future adapters.
9. Continue regression testing of protected BIC rewrite-detail and verb-selection rules. Keep WDA and existing-target revision parked as separate future work.
10. Accepted and in progress as SQS (`MS-SQS`, `TODO-20261013-017`); the original requirements follow. Build a hosted qualification-registry service so normal Operators can begin work within minutes without running local catalog benchmarks. Publish signed, immutable route records keyed by provider, exact model/capability fingerprint, provider-native reasoning ID, Skill/adapted-Skill hash, suite hash, policy version, verdict, evidence hash, and review/expiry state. SAGE must query through the replaceable local qualification-evidence repository API, verify signatures and exact identities locally, cache an approved last-known registry for offline use, fail closed on mismatch, and never accept provider/model self-qualification. Full benchmarking remains release/maintainer tooling; local evaluation is only a fallback for new, unavailable, or disputed routes.


## Future architecture

- [ ] **`TODO-20260914-001` — UPDATE PROJECT propagation to WIP analysis footprints.** Define how updating a WIP Project affects its RTC, STC, and NCA footprints: reviewed coverage, findings, cached analysis, and continuation checkpoints. Compare the previous and updated Project revisions, identify affected books/chapters and dependent Jobs/Runs, and mark affected footprints as stale or requiring review. Plan refreshed analysis for changed or newly available scope, including previously missing books. Preserve valid unaffected coverage and immutable historical reports with their original Project revision; distinguish those reports from results current for the updated WIP. Verify changed text, added/removed books, unchanged updates, and continuation after an update across all three workflows. This is future architecture work; implementation is not scheduled.

## To consider (conditional; not accepted work)

- [ ] **MACULA annotation for BIC original-language micro-adjudication.** Not needed while OL stays a failover
  and tester feedback is positive. Revisit only if real runs show consistently inferior OL-assessed output
  (wrong verbal sense, a lemma or tense in `ol_evidence_summary` that is not in the verse, or weak Hebrew
  stem/weqatal readings). Idea: attach a verse-bounded MACULA extract (form, lemma, morphology, gloss, role,
  frame) to the existing conditional OL read for the one micro-verse. Add deterministic checks of the
  model's cited lemma or tense and, later, a Louw-Nida multi-domain pre-flag for the
  `COMPETING_NON_EQUIVALENT_SENSES` trigger.
  - Cost measured 2026-10-14 on MACULA Greek (17 words per verse): the bare Greek verse is about 200 bytes;
    form+lemma+morph is about 500 bytes and the fuller annotation about 800 bytes. A micro-call already
    carries about 9 KB of fixed text, so the addition is roughly 3–7% of tokens; lookup time is negligible
    from a compact pinned extract.
  - Real cost is engineering: a pinned per-verse extract shipped with the CC BY 4.0 attribution, mapping
    the AGNT/SBLGNT/WLC edition and versification differences through the VRS machinery, and a license
    check before sending Greek Louw-Nida domains (`macula.py` deliberately never copies the UBS Hebrew
    SDBH fields).
  - Before building: run a small A/B on OL-triggering fixtures, with and without the annotation, to confirm a
    quality gain. The pinned tables are already cached for NCA (`index_build/macula.py`).
- [ ] **NCA: replace part of the extraction LLM phase with deterministic code (app side first).** Audited
  read-only 2026-10-26. The app's only LLM phase is `EXTRACTION` (`numbers/model_tasks.py`); comparison,
  association and review classes are already local. Digit numerals are already read by code
  (`numerals.py`) but save nothing in practice: across the five saved gate runs every extracted number had
  `origin: MODEL`, because Ukrainian and Spanish WIPs spell numbers as words.
  - Measured on the held-out 2 and 3 data (539 verses with numbers; the sample is stratified toward hard
    classes, so a real WIP should have more plain cardinals): 413 verses (77%) contain only plain cardinals;
    kinds 781 cardinal, 135 ordinal, 39 fraction, 14 approximate; surfaces 720 one-word, 148 two-word, 101
    longer.
  - Limit: the model also returns what each number counts (target-language gloss and English gloss), and the
    association check uses that gloss. A number-word reader gives value and span but no gloss, so skipping
    the model on easy verses needs a gloss-free association step first (for example pairing a number with
    its noun through the OL alignment). That is a design change, not a switch.
  - Suggested order: (1) deterministic per-language number-word verifier that runs on every verse and turns
    any disagreement with the model's values or spans into a review item (no extra calls; also guards
    recall); start with Ukrainian and Spanish, honouring `COUNTING-CONVENTION.md`; (2) replay the saved gate
    data and measure agreement on plain cardinals; (3) only if agreement is very high, design the gloss-free
    association and let code settle those verses; this is a new system under test and must be re-qualified.
  - Gate side (separate, later): a deterministic text-plant planter and fewer judge calls on agreed verses.
    Keep the gate's number reader a separate implementation from the app's so it stays independent, and
    keep a seeded random sample judged so recall is not biased toward the system under test. The gate
    changes as the app code is refined, so do the app side first.

## Future TUI work (`MS-FUTURE-TUI`, deferred)

The `0.02b1` Textual shell is frozen as **EXPERIMENTAL / UNSTABLE**; the classic terminal menu and
scriptable CLI remain authoritative and the default launch surface. Accepted work is
`TODO-20260826-005`. When TUI work resumes:

1. Finish extracting UI-independent Project, Job, Run, AI, report, recovery, and setup services. Shared AI/status/help/dashboard services exist; workflow-changing action services remain.
2. Retain the scriptable CLI permanently.
3. Complete native Windows/macOS/Linux acceptance of the full-screen shell, which already supports keyboard/mouse navigation.
4. Migrate action-capable AI setup; canonical runtime/AI state already drives the session header and Status/Configure panels.
5. Retain the classic menu as a transition/fallback surface until TUI parity and portability tests pass.
