# Release Notes - SAGE v0.02b1


## 0.02a3 — development branch (unreleased)

`0.02a3` is a non-release development branch on top of `0.02b1`. Its NCA (Number Consistency & Accuracy) work spans `a50cb30` to `11f95e0`, plus the NCA menu presentation change. **BREAKING** marks changes that invalidate earlier NCA Jobs, Runs, packages or extraction evidence; test data is disposable and no migration is provided.

- **BREAKING:** No NIV Scripture text is shipped (NIV fair use allows at most 500 verses). The typed package `SAGE_NUMBERS_TYPED_2026-10-09` (`sage-numbers-typed-1.1`) replaces `SAGE_NUMBERS_TYPED_2026-10-08`: `verses.tsv` quotes the public-domain Berean Standard Bible (`BSB_TEXT`, `BSB_NOTES`) instead of `NIV_TEXT`/`NIV_NOTES`; values are unchanged (5,345 original-language, 5,021 NIV). NCA reports quote the BSB and cite the NIV by reference and numbers ("Also see — NIV"). `NIV-EVIDENCE.tsv` keeps only a SHA-256 of each NIV verse and its number-bearing footnote count. BSB readings join the LXX/Vulgate/KJV witnesses with "Also see: MT, NIV, LXX, Vulgate, KJV", and BSB footnotes that report a number in another text are apparatus evidence.
- **BREAKING:** The typed reference package `SAGE_NUMBERS_TYPED_2026-10-08` (`sage-numbers-typed-1.0`) replaces `SAGE_NUMBERS_REFERENCE_2026-09-09` as the Core pin. It is built in the repository from MACULA Hebrew (WLC) and MACULA Greek (SBLGNT), with an NIV layer as secondary evidence, and records what each number counts. It covers 3,814 verses with 5,345 original-language and 5,021 NIV values. All index review items are resolved by the NIV number rule (`RULE-2026-10-08`); no provisional rows remain. The 2026-09-09 package stays in Core for comparison only.
- **BREAKING:** Counting convention 2.0 is shared by the index and the model: only numbers that state a quantity or a date are counted.
- **BREAKING:** Extraction contract 3.0: the model returns each number's exact text, value, kind and counted item; SAGE verifies the text, reads digit numerals itself, and flags or adds numerals the model misread or missed.
- **BREAKING:** BLOCKING FAIL is reserved for mismatches against an original-language reading the index vouches for. Other mismatches are NEEDS_REVIEW. The unused presentation-consistency Run check is removed; the Run switches are number accuracy and footnote review.
- **BREAKING:** NCA reports use the RTC/STC action-report template: per-chapter `ACTION-REPORT.md` and `OPERATOR-NOTE.txt` under `localdata/reports/<job>/<BOOK>/<CCC>/`, and `JOB-SUMMARY.md`. Each FAIL/NEEDS_REVIEW finding carries a copy-paste translator note. The technical projection moves to Run diagnostics.
- Adds the association check (`WRONG_ASSOCIATION`) and the FAILs `MALFORMED_NUMERAL` and `NUMBER_NOT_IN_SOURCE`, plus the report sections "Text-critical decisions (operator)" and "Notes (no action needed)".
- Adds an apparatus-backed text-critical list. NET Bible tc notes (short excerpts quoted under fair use with attribution), the SBLGNT apparatus, OSHB ketiv/qere, Brenton's LXX, the Douay-Rheims Vulgate, the KJV, Berean Standard Bible footnotes (public domain), and synoptic parallels are cited as evidence. BSB readings are cited as a rendering reference with "Also see: MT, NIV, LXX, Vulgate, KJV". A mismatch at an attested variant is review (`APPARATUS_VARIANT`), never FAIL. Reports end with "Sources and attribution".
- Adds the number formatting consistency report `<run>_NUMBER-STYLE.md` and, when no style profile is given, a reconstructed, importable `<run>_NUMBER-STYLE-PROFILE-RECONSTRUCTED.yml`.
- NCA never stops a Run on Scripture content. Damaged verses report `NOT_ASSESSED` with issue codes, and only integrity guards stop a Run.
- Normalized index readings are no longer presented as the original-language text.
- Faster package load (4.8 s to 0.3 s) through versification indexing, and a leaner extraction handover.
- Menu: NCA Jobs use the standard RTC/STC Job menu shape with a two-step Job delete. The style options are "Use standard language profile data" and "Upload style data from template". The package diagnostics block prints once per package per session as readable lines. The preflight screen shows only what the operator confirms; counters, batching and group IDs go to `last-preflight.json`.
- Review fixes: a style profile with unit forms no longer fails every Run (convention re-selection kept unit forms); a scope with nothing to extract publishes its `NOT_ASSESSED` verses instead of failing; a number's text is anchored to a whole token (a "7" inside "17" no longer yields a false FAIL); malformed model kinds are retried instead of crashing; no-break spaces group like a configured space and "30 40" is two numerals; suffixed digit ordinals ("2nd") are edge cases, not stray cardinals; a gap under a different WIP versification is no longer excused as covered; `WRONG_ASSOCIATION` is BLOCKING only under original-language authority; malformed numerals are reported in unindexed and partly read verses; diagnostics translator notes use the per-kind wording; the reconstructed style profile keeps the translation's digit script and never sets one mark for grouping and decimal.

Open: no release-gate receipt exists yet for the typed package; live-model qualification and SQS confidence checks have not been performed.

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

`0.01beta2` is the second group-testing Beta of the 0.01 line. It integrates the work validated on the historical `alpha/0.02alpha1` branch and remains pre-release and not public-production ready.

- Adds governed Source Text Correspondence (STC) as an independent WIP-to-PRIMARY-original-language workflow.
- Unifies BIC, RTC, and STC Scripture planning under routed-SFM-only deterministic sizing.
- Enforces complete LANGUAGE_PROFILE / OL_AUTHORITY_PROFILE context on bounded model-facing natural-language requests.
- Adds BASIC / STANDARD / ADVANCED setup-selected hardening ceilings of 2 / 4 / 6 workers; ADVANCED requires at least 16 GiB available RAM and 16 logical CPUs.
- Preserves PRIMARY plus inert future SECONDARY original-language authority registration without analytical effect unless explicitly routed.
- Replaces normal global model/reasoning selection with provider-only Setup and deterministic exact
  per-Skill route resolution using provider-native reasoning labels.
- Adds sealed three-repetition route qualification for all seven analytical Skills, with explicit per-Skill case inventories and five RTC referral-boundary cases, an
  audited exact-route override, fail-closed stale/unavailable handling, and route evidence in task
  receipts, Job/Run status, and final reports.
- Establishes the universal automatic/no-data fallback: Codex native Medium is executable in every release state only in a true absence
  of qualification evidence and is labelled `PROVISIONAL_UNQUALIFIED`; current data selects the
  qualified route, while the existing audited exact override remains the sole manual state.
- Resolves RTC/STC routing before visible work and preserves the same sealed task for `CONTINUE RUN`.
- Records an immutable UTC timestamp and stable `YYYYMMDD` date when each Project is added to SAGE; Project screens, Job setup, classic/CLI Run Status, and status JSON report it, while RTC/STC identity and WIP snapshot dates use the stored Project import date rather than Job creation time.
- Makes deterministic Python ownership explicit for planning, slicing, validation, aggregation,
  report composition/naming, and finalization; these operations have no LLM tokenization.
- Enforces one request per source-text adjudication item and one request per secondary-language report
  item, without provider conversation reuse.
- Seals `RTC_OL_REFERRAL_ADMISSION_V1` on new RTC Runs: four closed fundamental-conflict classes, fail-closed structured assertions, controller-derived conflict keys, duplicate/overlap rejection, and legacy readability for pre-contract tasks.
- Separates Operator `Review range`, immutable `Review portion`, and local `Structural check` / `Source check` progress so internal task expansion never appears as a changed review-plan denominator.
- Accepts approved RTC review portions that cross chapter boundaries by comparing Scripture-scope
  bounds directly, while retaining strict rejection of ambiguous cross-chapter coverage shorthand.
  Structural-stage references are deduplicated and sorted as Scripture coordinates rather than text.
  If any child task prevents an approved stage from being published, SAGE removes the unpublished
  child task/control records created by that attempt before returning the original error.
- Keeps the classic menu/CLI authoritative; Textual remains `EXPERIMENTAL / UNSTABLE`.
- Freezes the existing Textual navigation/status/readiness preview for the remainder of `0.01beta2`; further Project, Job, Run, report, and recovery functionality is deferred to `0.02beta`.


### Historical Alpha branch provenance

The `0.02alpha1` identity was used only on the parallel `alpha/0.02alpha1` non-release development branch. Its approved work was merged into the 0.01 line as `0.01beta2`; no `0.02alpha1` public release was created.

## 0.01beta baseline

`0.01beta` is the first group-testing baseline published from the current Git-managed layout. Earlier internal development labels were never public and are intentionally omitted from this release history.

### Core and local-data boundary

- `SAGE/app/` is the replaceable, reproducible application boundary; `SAGE/localdata/` persists with the portable bundle.
- `localdata/` is the persistent local/operator boundary and defaults to a sibling of `SAGE/`.
- Operators may place `localdata` elsewhere through the governed data-home resolver.
- Core rejects a data home located inside the Git-controlled SAGE tree.
- Visible `localdata` roots contain operator-facing Projects, Jobs, reports, exports, local resources, and plugins.
- `localdata/.system/` contains SAGE-owned configuration overlays, state, indexes, caches, locks, transactions, logs, diagnostics, temporary data, workflows, Job-controller state, and the managed runtime.
- Project imports keep original and parsed material separated so imported source evidence remains inspectable and derived material remains regenerable.
- Core release validation rejects local/runtime roots such as `localdata`, `workspace_data`, top-level `jobs`, top-level `reports`, and `.venv`.

### Deterministic first-run runtime

- `./sage` and `sage.cmd` automatically resolve/bootstrap local state; a separate mandatory setup command is not required.
- No host Python or package manager is required. The launcher can reuse a validated CPython 3.12 from Python.org/Homebrew, or install exact CPython 3.12.14 artifacts pinned by URL and SHA-256 for macOS ARM/Intel, Linux ARM/x86-64, and Windows x86-64.
- The approved base runtime is installed at `localdata/.system/runtime/python`; the managed environment is created at `localdata/.system/runtime/venv`. Neither is copied into a release.
- Runtime, development, and optional TUI dependencies are explicitly pinned in governed manifests.
- Bootstrap uses deterministic list-argv execution, exact pins, `--no-deps`, binary-only packages, `pip check`, and a runtime fingerprint.
- Missing or stale managed environments are repaired/rebuilt automatically from Core manifests.
- A failed base-runtime or environment installation produces a BLOCKED installation report and offers **Install again**, approved Python through available Homebrew/WinGet, or **Exit SAGE**. Package-manager execution requires explicit Operator approval.
- Version changes do not delete Projects, Jobs, reports, settings, or other operator data.
- The explicit out-of-box reset clears bounded local operating data while preserving the managed runtime and never modifying Core.

### Git and release hardening

- Normal SAGE operation no longer writes mutable configuration or runtime state into `SAGE/`.
- `ecosystem.yml` is an immutable Core baseline; operator/workstation changes are stored as local overlays in `localdata/.system/config`.
- Release ZIPs are built only from clean governed source staging, not from a live runtime folder.
- The production builder requires schema validation, package validation, deep source audit, exact-source hardening receipts, archive integrity validation, deterministic metadata, and SHA-256 output.
- Hardening runs each scheduled test module in its own clean source copy, splits long modules into bounded groups of at most eight pytest nodes per process, never counts timeout output as a pass, and proves the governed source hash is unchanged.
- GitHub CI covers Ubuntu, Windows, and macOS across supported Python versions and verifies the checkout remains clean.

### Resource governance

- Only tested, reviewed, approved resources belong in SAGE Core.
- Operator-created, imported, modified, experimental, or unvalidated resources remain in `localdata/inputs/resources` or `localdata/plugins`.
- A future SAGE Resource Hub is reserved for submission, provenance, validation, review, plugin packaging, and controlled promotion of candidate resources into Core.

### RTC/STC routed-SFM sizing and linguistic specificity

- Added **Source Text Correspondence (STC)** as an independent WIP-to-primary-original-language workflow: NT routes PRIMARY GRK, OT routes PRIMARY HEB, and REFERENCE/RTC evidence is excluded.
- STC canonical findings are `OMISSION`, `ADDITION`, `VARIATION`, and `CONSISTENCY`; exact primary coverage and zero-finding analytical completion are fail-closed finalization requirements.
- Consolidated BIC/RTC/STC planning under one deterministic general SFM slicer. Review-item sizing counts only the Scripture SFM streams actually routed to that review item.
- Added complete `LANGUAGE_PROFILE` routing for project/reporting streams and source-bound `OL_AUTHORITY_PROFILE` routing for GRK/HEB on every applicable bounded model request. Profiles are immutable context and contribute nothing to SFM sizing.
- GRK governance explicitly requires Ancient/New-Testament Greek and rejects Modern Greek assumptions; HEB governance requires Biblical/Ancient Hebrew and rejects Modern Israeli Hebrew assumptions.
- OL authority state can retain future SECONDARY authorities, but they have no analytical or sizing effect until explicitly routed by an operation contract.

### Cross-platform and operator behavior

- macOS/Linux launchers retain deterministic executable metadata and quoted path handling.
- Windows launchers use bounded `cmd.exe`/PowerShell subprocess contracts and support paths containing spaces.
- Storage/path tests cover custom data homes, Unicode paths, Windows path forms, path containment, and fail-closed invalid locations.
- Host capability detection selects a conservative BASIC/STANDARD/ADVANCED execution profile from available RAM and logical CPU threads. BASIC is selected below 4 GiB available RAM or 8 logical CPUs and caps release-hardening concurrency at 2 workers; STANDARD covers capable hosts below the ADVANCED threshold and caps at 4; ADVANCED requires both at least 16 GiB available RAM and 16 logical CPUs and caps at 6. Environment overrides may lower, but never exceed, the setup-selected ceiling.
- BIC, RTC, and STC retain Job-scoped authority, governed Project bindings, bounded work units, and operator-visible reports outside Core.
- The classic terminal interface and scriptable CLI remain authoritative for Beta; the Textual TUI remains `EXPERIMENTAL / UNSTABLE`, and further workflow functionality is deferred to `0.02beta`.

## Release qualification

Qualification evidence is recorded in `TEST-AND-VALIDATION-REPORT.md` and in the release-side hardening/checksum receipts generated beside the ZIP. Any governed source or test change invalidates prior receipts and requires qualification from a new frozen source hash.
