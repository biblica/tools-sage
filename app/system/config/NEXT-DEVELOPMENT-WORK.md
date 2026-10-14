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

## Future TUI work (`MS-FUTURE-TUI`, deferred)

The `0.02b1` Textual shell is frozen as **EXPERIMENTAL / UNSTABLE**; the classic terminal menu and
scriptable CLI remain authoritative and the default launch surface. Accepted work is
`TODO-20260826-005`. When TUI work resumes:

1. Finish extracting UI-independent Project, Job, Run, AI, report, recovery, and setup services. Shared AI/status/help/dashboard services exist; workflow-changing action services remain.
2. Retain the scriptable CLI permanently.
3. Complete native Windows/macOS/Linux acceptance of the full-screen shell, which already supports keyboard/mouse navigation.
4. Migrate action-capable AI setup; canonical runtime/AI state already drives the session header and Status/Configure panels.
5. Retain the classic menu as a transition/fallback surface until TUI parity and portability tests pass.
