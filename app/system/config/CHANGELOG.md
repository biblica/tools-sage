# Changelog

## 0.02a3 — development branch (unreleased)

`0.02a3` is a non-release development branch on top of `0.02b1`. Its NCA (Number Consistency & Accuracy) work spans `a50cb30` to `11f95e0`, plus the NCA menu presentation change. **BREAKING** marks changes that invalidate earlier NCA Jobs, Runs, packages or extraction evidence; test data is disposable and no migration is provided.

- **BREAKING:** No NIV Scripture text is shipped (NIV fair use allows at most 500 verses). The typed package `SAGE_NUMBERS_TYPED_2026-10-09` (`sage-numbers-typed-1.1`) replaces `SAGE_NUMBERS_TYPED_2026-10-08`: `verses.tsv` quotes the public-domain Berean Standard Bible (`BSB_TEXT`, `BSB_NOTES`) instead of `NIV_TEXT`/`NIV_NOTES`; values are unchanged (5,345 original-language, 5,021 NIV). NCA reports quote the BSB and cite the NIV by reference and numbers ("Also see — NIV"). `NIV-EVIDENCE.tsv` keeps only a SHA-256 of each NIV verse and its number-bearing footnote count. BSB readings join the LXX/Vulgate/KJV witnesses with "Also see: MT, NIV, LXX, Vulgate, KJV", and BSB footnotes that report a number in another text are apparatus evidence.
- **BREAKING:** The typed reference package `SAGE_NUMBERS_TYPED_2026-10-08` (`sage-numbers-typed-1.0`) replaces `SAGE_NUMBERS_REFERENCE_2026-09-09` as the Core pin. It is built in the repository from MACULA Hebrew (WLC) and MACULA Greek (SBLGNT), with an NIV layer as secondary evidence, and records what each number counts. It covers 3,814 verses with 5,345 original-language and 5,021 NIV values. All index review items are resolved by the NIV number rule (`RULE-2026-10-08`); no provisional rows remain. The 2026-09-09 package stays in Core for comparison only.
- **BREAKING:** Counting convention 2.0 is shared by the index and the model: only numbers that state a quantity or a date are counted.
- **BREAKING:** Extraction contract 3.0: the model returns each number's exact text, value, kind and counted item; SAGE verifies the text, reads digit numerals itself, and flags or adds numerals the model misread or missed.
- **BREAKING:** BLOCKING FAIL is reserved for mismatches against an original-language reading the index vouches for. Other mismatches are NEEDS_REVIEW. The unused presentation-consistency Run check is removed; the Run switches are number accuracy and footnote review.
- **BREAKING:** NCA reports use the RTC/STC action-report template: per-chapter `ACTION-REPORT.md` and `OPERATOR-NOTE.txt` under `localdata/reports/<job>/<BOOK>/<CCC>/`, and `JOB-SUMMARY.md`. Each FAIL/NEEDS_REVIEW finding carries a copy-paste translator note. The technical projection moves to Run diagnostics.
- Adds the association check (`WRONG_ASSOCIATION`) and the FAILs `MALFORMED_NUMERAL` and `NUMBER_NOT_IN_SOURCE`, plus the report sections "Text-critical decisions (operator)" and "Notes (no action needed)".
- Adds an apparatus-backed text-critical list. NET Bible tc notes (short excerpts quoted under fair use with attribution), the SBLGNT apparatus, OSHB ketiv/qere, Brenton's LXX, the Douay-Rheims Vulgate, the KJV, and synoptic parallels are cited as evidence. A mismatch at an attested variant is review (`APPARATUS_VARIANT`), never FAIL. Reports end with "Sources and attribution".
- Adds the number formatting consistency report `<run>_NUMBER-STYLE.md` and, when no style profile is given, a reconstructed, importable `<run>_NUMBER-STYLE-PROFILE-RECONSTRUCTED.yml`.
- NCA never stops a Run on Scripture content. Damaged verses report `NOT_ASSESSED` with issue codes, and only integrity guards stop a Run.
- Normalized index readings are no longer presented as the original-language text.
- Faster package load (4.8 s to 0.3 s) through versification indexing, and a leaner extraction handover.
- Menu: NCA Jobs use the standard RTC/STC Job menu shape with a two-step Job delete. The style options are "Use standard language profile data" and "Upload style data from template". The package diagnostics block prints once per package per session as readable lines. The preflight screen shows only what the operator confirms; counters, batching and group IDs go to `last-preflight.json`.
- Review fixes: a style profile with unit forms no longer fails every Run (convention re-selection kept unit forms); a scope with nothing to extract publishes its `NOT_ASSESSED` verses instead of failing; a number's text is anchored to a whole token (a "7" inside "17" no longer yields a false FAIL); malformed model kinds are retried instead of crashing; no-break spaces group like a configured space and "30 40" is two numerals; suffixed digit ordinals ("2nd") are edge cases, not stray cardinals; a gap under a different WIP versification is no longer excused as covered; `WRONG_ASSOCIATION` is BLOCKING only under original-language authority; malformed numerals are reported in unindexed and partly read verses; diagnostics translator notes use the per-kind wording; the reconstructed style profile keeps the translation's digit script and never sets one mark for grouping and decimal.
- Adds Claude as a second governed provider through the Claude Code CLI and the Operator's own Claude subscription (never API keys). One selected provider serves all governed LLM work. Claude is implemented but disabled in this build until it is qualified.
- **BREAKING (Claude only):** token sizing uses the selected provider's tokenizer. Claude spends a median 1.6x the Codex tokens on the same Scripture, so switching provider makes approved RTC plans stale. Codex plans and budgets are unchanged.
- Adds the S/M/L work-unit size (Configure AI, `sage model work-unit-size`), which scales every RTC, STC, and BIC budget by 0.5/1/2, and a learned token correction that shrinks planning targets when real usage runs above the estimate.
- A Codex workspace that is out of credits is reported as a usage limit, not a task failure.
- SQS qualifies a second provider family: an Anthropic model catalog, family-aware discovery, planning and ADMIN queueing (the planner previously queued every test as OpenAI), and pack cost estimates scaled to each tokenizer.

Release gate (2026-10-18): the typed package failed live qualification on FAIL precision (60%; the bar is 90%); see `docs/advanced/release/NCA-RELEASE-GATE.md`. SQS confidence checks have not been performed.

## 0.02b1 — 2026-09-09

`0.02b1` consolidates the complete `0.02a1` development branch into `main` as the first Beta of the 0.02 line. It remains a pre-release build with `public_release_ready=false`.

- Adds shared canonical versification projection and source attribution across BIC, RTC and STC, including BIC target-coordinate alignment and the standard VRS resource set.
- Honors the Paratext Settings.xml filename template during Project import, discovery and snapshot capture; validates filename/book identity and records excluded working copies.
- Accepts UTF-8 BOM book IDs and generates BIC target filenames from the same template, including Paratext New Testament numbering. Corrects bundled Hebrew Settings.xml metadata to match its shipped filenames.
- Preserves scoped validation and disabled-Project behavior. Real faTMNv4 snapshot verification processed 66 books without changing its source files.
- Includes finalized NCA reference audits, functional design, implementation plan and Number Style Profile questionnaire as planning documents. NCA runtime and SQS confidence checks are not implemented in this release.
- Retains the existing classic menu/CLI authority and experimental Textual preview. No new TUI workflow parity is claimed.

Automated qualification is recorded against the final staged source. Native-platform and live workflow acceptance remain separate from automated test success; no public-production readiness is claimed.

## 0.01beta2

`0.01beta2` was the preceding group-testing Beta. It incorporates the accepted work from the historical `alpha/0.02alpha1` non-release branch while retaining the 0.01 product line.

- Added Source Text Correspondence (STC) with WIP-to-PRIMARY OL correspondence and fail-closed exact coverage/finalization.
- Unified BIC/RTC/STC review sizing under routed-SFM-only deterministic slicing.
- Added universal governed linguistic-profile routing for bounded model-facing requests, including historical GRK/HEB authority profiles.
- Added setup-selected ADVANCED host capability at >=16 GiB available RAM and >=16 logical CPUs with a hardening ceiling of 6 workers; BASIC/STANDARD remain capped at 2/4.
- Promoted RTC and STC to independent primary workflows; Targeted Check and standalone Original-Language Review remain parked compatibility paths.
- Replaced normal global model/reasoning selection with provider-only Setup and exact per-Skill
  provider/model/native-reasoning routing.
- Added deterministic execution-owner policy, sealed 3-case × 3-repetition qualification suites for
  all seven Skills, audited global route override receipts, and fail-closed route reconciliation.
- Added exact execution-route provenance to task receipts, BIC/RTC/STC aggregation, Job/Run displays, and
  final reports while keeping deterministic report composition outside LLM token accounting.
- Enforced one provider request per original-language adjudication item and per secondary-language
  report item.
- Restored approved RTC portions spanning chapters by validating scope containment directly against
  the immutable plan's exact atoms; structural-stage atoms now retain canonical numeric Scripture
  order. Unpublished multi-child stage creation rolls back its newly created task/control records if
  a later child fails.
- Corrected RTC planning so VRS mapping ranges remain non-blocking structural evidence instead of
  being treated as indivisible source bridges. Structural candidates may cross approved review
  portions and are routed to each affected portion for Action Report adjudication; actual WIP and
  REFERENCE source-record bridges remain protected.
- Fixed semicolon-separated RTC finding citations for numbered books such as `1CH`: repeated full
  book references and inherited chapter-only continuations now normalize without duplicating the
  book code, so valid provider output can be retried without changing the sealed task.
- Added discontinuous same-book RTC/STC Run scopes. An entry such as `1CH 5-6; 24` now canonicalizes
  to `1CH 5-6; 1CH 24`; planning and task creation preserve the gap as separate immutable Review
  portions instead of widening it or treating `1CH 5-6;` as a book name.
- Made RTC/STC WIP and REFERENCE Project bindings immutable for each Job. Their **Manage Job** menu
  now offers **Delete Job**, which removes all Job work/controller state, separately asks whether
  published reports should also be removed (default preserve), and never changes Projects or
  Paratext files.
- Changed interactive busy/progress indicators to one viewport-bounded row that redraws in place
  and erases before the final result; redirected output retains one static message per operation.

## 0.01beta

`0.01beta` is the first group-testing baseline published from the current Git-managed architecture. Unpublished internal development labels are intentionally not part of the public changelog.

### Storage and configuration

- Split replaceable Git-controlled `app/` Core from persistent `localdata/` inside the portable SAGE bundle root.
- Defaulted `localdata` to a sibling of `app/`, with explicit CLI/environment/persisted custom-location resolution.
- Added fail-closed data-root validation and prohibited data homes inside Core.
- Added visible operator roots for Projects, Jobs, reports, exports, local resources, and plugins.
- Added hidden `.system` roots for configuration overlays, state, indexes, caches, locks, transactions, logs, diagnostics, temporary data, workflows, Job controller state, and managed runtime.
- Made Core `ecosystem.yml` immutable during normal operation; mutable interface/operator settings now use local overlays.
- Redirected Project imports and parsed Styleguide/source material into project-owned localdata paths.
- Added a direct **Remove Project from SAGE** action with negative-default confirmation. Bound active
  and archived Jobs are listed and require explicit cascade confirmation before SAGE removes those
  Jobs, their Job-local data, and the Project inventory/mapping. Paratext files and root-level
  published reports remain unchanged.
- Removed legacy in-Core `workspace_data`, top-level Job/report state, and bundled `.venv` from the distribution contract.

### Deterministic runtime/bootstrap

- Added automatic first-run creation of the sibling/local localdata structure.
- Added Python-free shell and PowerShell bootstraps that install exact CPython 3.12.14 artifacts for
  macOS ARM/Intel, Linux ARM/x86-64, and Windows x86-64 from governed URLs and SHA-256 pins.
- Moved the generated managed Python environment to `localdata/.system/runtime/venv`.
- Added exact pinned dependency manifests and deterministic bootstrap/repair with binary-only packages, `--no-deps`, `pip check`, and runtime fingerprints.
- Added a blocking runtime-installation report that records the reason and asks the Operator to
  retry the SAGE runtime, use an available approved package-manager recovery, or exit SAGE.
- Removed the system-Python and Homebrew prerequisites from normal launch and clone/install paths.
- Added approved CPython 3.12 host-runtime discovery: signed Python.org installations on macOS and
  Windows, plus an existing Homebrew Python on macOS.
- Added explicit recovery choices for Homebrew `python@3.12` and WinGet `Python.Python.3.12`;
  package managers are never installed or invoked without Operator approval.
- Removed manual/copied-environment and consent-driven venv setup paths.
- Preserved operator data across Beta/Core version updates; version changes no longer trigger destructive local-state resets.
- Kept the explicit out-of-box reset bounded to localdata and Core-immutable while preserving the managed runtime.

### Release and Git hardening

- Added deterministic source staging and ZIP metadata independent of build host.
- Added exact-source sharded hardening receipts, formal exactly-once combine, package validation, source deep audit, archive integrity validation, and SHA-256 sidecars.
- Added release validation that rejects local/runtime roots, caches, bytecode, nested archives, stale artifacts, symlinks, and machine-specific state.
- Added GitHub Actions qualification across Ubuntu, Windows, and macOS with supported Python versions and checkout-clean verification.
- Sanitized machine-specific paths and unpublished version-history labels from the group-testing distribution.

### Resource governance

- Established Core as the home only for tested/reviewed/approved product resources.
- Established `localdata/inputs/resources` and `localdata/plugins` for local/candidate resources and extensions.
- Added the future Resource Hub contribution model for provenance, validation, security/license checks, review, plugin packaging, and controlled Core promotion.

### Workflow/operator continuity

- Retained role-neutral SAGE Project inventory with Job-scoped BIC/RTC/STC authority.
- Added governed Source Text Correspondence (STC) as an independent WIP-to-PRIMARY-OL review (NT -> GRK, OT -> HEB), alongside retained RTC, Targeted Check, and Original-Language Review operations.
- Unified BIC/RTC/STC Scripture sizing under routed-SFM-only deterministic planning; controller JSON, prompts, schemas, linguistic profiles, and provider transport overhead no longer affect Scripture slicing or token limits.
- Added complete model-facing LANGUAGE_PROFILE / source-bound OL_AUTHORITY_PROFILE routing, including explicit Ancient/NT Greek and Biblical/Ancient Hebrew register protection.
- Corrected approved RTC-plan reconciliation so an unchanged verse bridge is compared by its exact
  atomic coordinates instead of being falsely reported as stale because its display label is ranged.
- Retained cross-platform Codex/Ollama administration boundaries and extended setup-selected host capability to BASIC (2 workers), STANDARD (4), and ADVANCED (6; requires at least 16 GiB available RAM and 16 logical CPUs).
- Retained the classic terminal menu and scriptable CLI as authoritative Beta interfaces; Textual remains experimental/unstable.
