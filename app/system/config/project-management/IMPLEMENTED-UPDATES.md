# Implemented Updates

This is an append-only implementation ledger. New entries go first. Historical version detail from
before this ledger remains in `system/config/CHANGELOG.md` and `docs/advanced/release/RELEASE-NOTES.md`.
Entries before the canonical RTC/STC migration retain former identifiers only as historical records;
they do not define current workflows, menus, reports, Skills, or artifact names.

Entries `IMP-20260914-001` through `IMP-20261011-001` were logged retrospectively on 2026-10-13 from
git history on the non-release `0.02a3` branch, where `VERSION` remains `0.02b1`. Their verification
lines record the suites re-run on 2026-10-13 against `6bce03f`.

### IMP-20261021-005 — Chapters with compile defects are left out, not a reason to stop (completes TODO-20261013-020)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261013`
- **TODO:** `TODO-20261013-020` (now `DONE`)
- **Commits:** the commit that introduced this entry.
- **Implemented:**
  - New `effective_scope.py`. `decide_effective_scope` compiles every bound project for the requested
    RTC/STC scope: WIP, plus REFERENCE (RTC) or the testament OL (STC). It leaves out each chapter that has
    a blocking issue located in it, then recompiles until the rest is ready. Chapter ends for split
    cross-chapter portions come from the effective VRS.
  - An issue that cannot be tied to a chapter still blocks with today's error. Examples: a book-level
    issue, a defect in the book header, or nothing safe left to analyze.
  - `scripture.issue_chapters` shares the coordinate parse with `_issue_intersects_scope`.
  - The decision is made once, in `command_plan`. The plan is made for the effective scope and records
    `requested_scope` and `excluded_portions`. The menu preview lists each chapter that was left out, and
    the menu creates the Run with the effective scope.
  - The other readiness checks are unchanged and pass because the Run's scope is already clean: task
    creation (`REQUESTED_SCOPE_BLOCKED`), approved-plan revalidation, and the Run preview.
  - A left-out chapter is never routed as boundary context (`without_excluded_chapters`).
  - RTC stage plans (`excluded_portion_rows`) and STC plans (`approved_scope_exclusions`) carry the
    left-out chapters as `not_assessed_portions`. `aggregate_act_plan` reports them as `NOT_ASSESSED`
    (`SCOPE_CHAPTER_COMPILE_DEFECT`) outside coverage reconciliation, so they reach the RTC and STC
    chapter reports.
  - Compile-time parser errors:
    - Errors inside a verse already carried a coordinate (`1CH 6:1:...`) and were already located.
    - An error outside any verse was filed against the whole book, for example an unclosed marker in a
      section heading. `_localize_parser_issues` now files it under each chapter that reproduces it on its
      own. An error in the book header still blocks the book.
    - `parser_errors_for_chapters` is the one chapter split, shared with the task-time check in
      `act_evidence.py`.
- **Not changed:**
  - Job creation still refuses a WIP with critical parser errors (`TODO-20261013-022`, product-owner
    decision). This change applies to defects that appear after the Job was created, and to REFERENCE and
    OL defects.
  - Under RTC with OL variance enabled, OL defects still block in the Run preview: OL is optional for RTC
    and is not part of the decision.
  - BIC and NCA are not affected.
  - A replacement Run reuses the effective scope. A full-scope Run after the defect is fixed needs a new Run.
- **Verification:** new `test_effective_scope.py` (6 tests). It covers chapter filing, header defects,
  the decision (multi-portion, whole-book, cross-chapter, all-excluded), and a full RTC composite Run and
  an STC Run with the defect planted after Job creation. Full suite re-run.

### IMP-20261021-004 — Planners leave out an unplannable span instead of stopping (part of TODO-20261013-020)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261013`
- **TODO:** `TODO-20261013-020` (stays `IN_PROGRESS`; only the compile-defect chapters remain)
- **Commits:** the commit that introduced this entry.
- **Finding:** the other parts of the TODO were already done: BIC in `IMP-20261014-004`, STC and RTC
  findings in `IMP-20261014-012`, and partial coverage, missing STC portions, and per-item report
  translation in `46add75`. Over-budget work was already bisected by the planner and `_partition_act_request`.
  What still stopped a Run was a span that no work unit can hold: one verse record over a hard limit, or an
  indivisible bridge or equivalence span over a hard limit.
- **Implemented:**
  - `work_units.py`: both errors now carry `code`, `affected_scope`, and `details.unplannable_references`
    (for a required span, only the records inside the span, not the whole range).
  - `plan_sfm_work_units(..., excluded=[...])`: with a list given, the unplannable span is removed, recorded
    as `{references, code, message}`, and the rest of the scope is planned again. Without the list the error
    is raised as before, so the task-time guards are unchanged.
  - ACT/RTC partitioner, the RTC plan (`plan_rtc_work_units`, `command_plan`, approved-plan reconciliation
    in `act_common.py`, `rtc_tasks.py` stage plans), and STC planning pass the list. The plan carries
    `not_assessed_spans` (STC reuses `not_assessed_portions`); `aggregate_act_plan` reports those
    coordinates as `NOT_ASSESSED` with an exception row, so they are never claimed as reviewed.
- **Not changed:** excluding chapters with compile defects instead of blocking the requested scope.
  Blocking is checked at four independent points (plan, task creation, approved-plan revalidation, Run
  preview), each against the requested scope, and chapter coordinates cannot be expanded to atoms without a
  clean compile. It needs one shared "effective scope" decision.
- **Verification:** new tests in `test_sfm_slicer.py` and `test_exception_reports.py`; full suite re-run.

### IMP-20261021-003 — Model catalog refresh records new models and reasoning levels (TODO-20261020-004)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-02A3`
- **TODO:** `TODO-20261020-004`
- **Commits:** the commit that introduced this entry.
- **Finding:** the live model list was already read from the Codex CLI on every view (a live listing on
  2026-10-21 showed all 7 models with `max` and `ultra`). What was stale was SAGE's own saved snapshot
  (`state/model-catalog/codex.json`), written only at sign-in and task runs, and nothing told the
  Operator what had changed after a CLI or SAGE update. Automatic routing never picks an unlisted model
  (`release_preference` ranks listed models first), which is intended: new routes are
  `PROVISIONAL_UNQUALIFIED` until evaluated.
- **Implemented:**
  - `model_policy.py`: `cache_provider_catalog` (schema 1.1) stores the Codex CLI and SAGE versions and
    compares the new listing with the previous snapshot. A difference in models or reasoning levels is
    kept as `last_change` with its trigger (`PROVIDER_CLI_VERSION`, `SAGE_VERSION`, or
    `PROVIDER_CATALOG`) until a newer difference replaces it. The first snapshot is a baseline.
    `describe_catalog_change` renders it for the Operator.
  - `model_service.py`: `list_models` refreshes the snapshot on every live listing and returns
    `catalog_changes`; `refresh` returns it too.
  - `menu.py`: Available provider models shows what changed and marks new models `(NEW)`; Update Codex
    CLI refreshes the list afterwards and says what is new or that nothing changed. `sage model refresh`
    prints the same lines.
  - No qualification evidence is created or changed and routing is unchanged.
- **Verification:** new `test_model_catalog_refresh.py` (3 tests: baseline, CLI-update additions kept
  across a re-listing, removals and server-side changes); `test_provider_updates.py` update flow shows the
  new model; full suite run (see commit).
  **Not covered:** the tester's exact complaint is unknown (`externaldata/user-feedback.md` is empty); if
  they expected new models to be chosen automatically, that needs qualification (`TODO` for the routing
  override), not a catalog change.

### IMP-20261021-002 — Codex CLI update check at startup and in Configure AI (TODO-20261020-003)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-02A3`
- **TODO:** `TODO-20261020-003`
- **Commits:** the commit that introduced this entry.
- **Implemented:**
  - New `provider_updates.py`: reads the latest published Codex release tag (`openai/codex` GitHub
    releases, GET only, nothing local sent, SAGE's CA-bundle policy), caches it in
    `state/provider-update-check.json` for 12 hours, and compares it with the installed version. It never
    raises: no network and no cache gives "unavailable". `SAGE_DISABLE_UPDATE_CHECK=1` turns the lookup
    off (the test suite sets it).
  - `menu.py`: the lookup starts in a background thread at SAGE start, so startup never waits on it (the
    startup report waits at most 2 s for it). When an update exists, the startup report shows
    `Codex CLI  UPDATE AVAILABLE - <latest> (installed <current>)` and where to update. Configure AI shows
    the same line and has new item 9 "Update Codex CLI": forced check, shows installed and latest, asks
    consent, runs the update, re-verifies the CLI and refreshes the model catalog view.
  - `executors/codex_cli.py`: `update()` runs `codex update` with no stdin and 600 s limit, then
    re-verifies; failure raises `CODEX_UPDATE_FAILED` with the CLI output and the manual install command.
    `model_service.py`: `update_codex()`.
  - Fixed a slip from `IMP-20261021-001`: a global replace had also put `version_timeout` into
    `status()`, where it is undefined (caught by the full suite).
- **Verification:** new `test_provider_updates.py` (7 tests: version parsing, newer-only comparison, cache
  and offline fallback, `codex update` run and failure, consent flow). Live lookup returned
  `rust-v0.163.0`, equal to the installed 0.163.0. `codex update` was not run against the real CLI.
  **Not covered:** the latest-release source is the GitHub API; a host that blocks it shows "unavailable".

### IMP-20261021-001 — First-run Setup offers Codex sign-in right after install (TODO-20261020-002)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-02A3`
- **TODO:** `TODO-20261020-002`
- **Commits:** the commit that introduced this entry.
- **Implemented:**
  - Likely cause (from code reading; not reproduced on Windows 11): the first `codex --version` after a
    fresh install can exceed the 5 s startup budget, so `CodexCLIExecutor.install()` raised
    `CODEX_INSTALL_PATH_REFRESH_REQUIRED` ("close and reopen the terminal") although the binary was
    present, and guided Setup's single `try` block then skipped the sign-in offer.
  - `executors/codex_cli.py`: `quick_status` takes `version_timeout` and `login_timeout`; `install()`
    verifies with 60 s and 30 s, always points `SAGE_CODEX_COMMAND` at the installed binary, and returns
    the status (available, not ready) instead of raising whenever the binary is present.
  - `menu.py`: new `_setup_first_run_ai` replaces the inline install and sign-in block in
    `guided_setup`. An install error is shown, then the CLI is re-probed, and a signed-out CLI always
    gets "Connect ChatGPT now?" in the same flow.
- **Verification:** two new tests (`test_parent_runtime.py` slow first version call on Windows;
  `test_operator_ux.py` sign-in offered after a failed install check); `test_operator_ux.py` and
  `test_parent_runtime.py` pass (54). Not yet confirmed on a real Windows 11 first run.

### IMP-20261020-003 — NCA: restructured quantities are consistency review (TODO-20261018-001)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-02A3`
- **TODO:** `TODO-20261018-001` (partial: the restructured-quantity false alarms)
- **Commits:** the commit that introduced this entry.
- **Implemented:**
  - `numbers/compare.py`: new review kind `RESTRUCTURED` (category `CONSISTENCY`) for two deterministic
    patterns. `REPEAT_STATED_ONCE`: a repeated source number stated fewer times but still stated, plus an
    implied singular made explicit as "one" whose WIP gloss shares no word with any missing source item
    (EZK 45:23). `PAIR_AS_TWO`: one "one" becomes one "two" where the BSB names a "second" that the
    convention does not count (2KI 25:17 "one pillar ... the second" as "the two columns"). "One bull"
    for seven bulls, an unglossed "one", a number no longer stated, and "two" beside a counted "second
    year" all stay FAIL.
  - `numbers/results.py`, `nca_reporting.py`: finding message and translator note ("Check consistency:
    the repeated 7 stated once, and "one" made explicit for male goat"); no Operator input asked.
- **Verification:** new tests in `test_compare.py` (both patterns and four FAIL guards) and
  `test_reporting.py`. Recomputing every saved gate result with and without the rule (development,
  held-out 1-3, 95 text plants) changes only Spanish 2KI 25:17 and EZK 45:23. Held-out 3 replayed
  (no provider calls): false-FAIL rate 1/317 (0.3%) PASS; the one false FAIL left is NUM 33:3, an
  idiom; 2KI 25:27 still a genuine FAIL; planted errors 151/151 and text plants 82/82 unchanged.

### IMP-20261020-002 — NCA release gate: precision-check review, schema 1.2, credit check (TODO-20261018-001)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-02A3`
- **TODO:** `TODO-20261018-001` (measurement part)
- **Commits:** `d8f87af`, `1659fb8`.
- **Implemented:**
  - `tools/qualify_nca.py`: verdict judges answer against the current product policy and name a cause,
    one FAIL per call; code marks each FAIL `READ_CORRECTLY` or `MISREAD`; Wilson 95% intervals with an
    `INSUFFICIENT_EVIDENCE` outcome; the gate checks the false-FAIL rate per verse (at most 0.5%, PO
    decision 2026-10-20) and reports FAIL precision; text plants test detection end to end on real WIP
    text; one tiny request on the route under test before any step that calls it.
  - `numbers/compare.py`: a unit conversion checks every unit a repeated source value carries
    (2CH 2:10, found by text plants).
- **Verification:** `tests/numbers/test_release_gate.py`, `test_compare.py`; held-out 3 rejudged and
  replayed (see [NCA release gate](../../../docs/advanced/release/NCA-RELEASE-GATE.md)); the credit check
  stopped a live run against an empty workspace with exit code 2 before writing anything.

### IMP-20261020-001 — NCA: index referent fix, nested-item association, unit conversions as consistency review (TODO-20261020-001)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-02A3`
- **TODO:** `TODO-20261020-001`
- **Commits:** the commit that introduced this entry.
- **Implemented:**
  - `index_build.build.counted_phrase`: a construct noun closed by a pronominal suffix or a name and
    followed by its own absolute numeral is that numeral's list entry; the number before it takes the
    noun before it instead (EZK 48:34 "west 4500, their gates 3, gate of Gad 1"). A full HEB/GRK
    rebuild changes 4 of 5,347 typed values (EZK 48:34 ×2, EZR 2:66, JOS 12:20), all corrections.
  - `numbers/reference.py`: `_REFERENT_ERRATA` applies those 4 OL referents when
    `SAGE_NUMBERS_TYPED_2026-10-09` loads; the package bytes and checksums are unchanged.
  - `numbers/association.py`: a gloss that lands on a source item whose words contain (or are contained
    in) another item's words may carry that item's number ("tenth" 1/10 and "tenth fine flour" 1,
    LEV 14:21), so it is no longer a `WRONG_ASSOCIATION`.
  - `numbers/compare.py`: new review kind `UNIT_CONVERSION` for two deterministic patterns: an OL
    ordinal hour stated as clock time (`(hour + 6) mod 12`), and OL measures restated in a different
    unit with one scale factor (the WIP gloss shares no word with the OL unit, so "50 cubits" for
    "5 cubits" stays FAIL). The review context lists each conversion with the OL value and unit and
    the WIP value and unit. Findings of this kind have category `CONSISTENCY`.
  - `nca_reporting.py`: the Operator note names each conversion ("5 talents (original language) as
    5000 coins") and the action names what to check ("Check consistency: talents converted to modern
    measures"); it asks for no Operator decision (PO decision 2026-10-20).
  - `.gitignore`: `app/system/config/project-management/private/` holds material the public
    repository must not carry; only its README is tracked. The held-out 2 receipt and notes are there.
- **Verification:** new tests in `tests/numbers/test_index_build.py`, `test_typed_reference.py`,
  `test_compare.py` (nested items, hour and unit conversions, same-unit typo still FAIL) and
  `test_reporting.py`. Offline rescore of the sealed gate extractions (no provider calls): held-out 2
  EZK 48:34 and LEV 14:21 PASS, MAT 20:9, MAT 25:15 and ACT 10:3 `UNIT_CONVERSION`; development
  MRK 6:37 `UNIT_CONVERSION`; no new FAIL in any run. The gate still FAILs on model misreads
  (`TODO-20261018-001`).

### IMP-20261019-001 — NCA runs on Acts: package erratum for the ACT 19:40-41 continuation (TODO-20261018-002)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-02A3`
- **TODO:** `TODO-20261018-002`
- **Commits:** the commit that introduced this entry.
- **Implemented:**
  - `project_scope` (`sage/numbers/scope.py`) keeps a per-package erratum list. For
    `SAGE_NUMBERS_TYPED_2026-10-09` it takes the `&ACT 19:40-41 = ACT 19:40` continuation from the
    configured `eng.vrs`, and only when `eng.vrs` declares exactly that rule. The pinned package stays
    byte-for-byte unchanged. Every other mapping disagreement still stops with
    `NCA_MAPPING_BASELINE_MISMATCH`.
  - Western ACT 19:41 now maps to ORG ACT 19:40, so an org-numbered WIP's ACT 19:40 covers both
    English verses instead of leaving 19:41 unmapped.
  - The release gate no longer has to leave Acts out; it is included on the next run (`TODO-20261018-001`).
- **Verification:** new tests in `tests/numbers/test_scope.py`: the erratum is applied for the pinned
  package and refused for any other package; every indexed book of the pinned package opens a scope
  under `eng.vrs` and `org.vrs` targets (both fail without the erratum). `tests/numbers`: 740 passed, 2 skipped.

### IMP-20261018-001 — NCA release gate for the typed package: built, run, FAIL recorded (TODO-20261013-016)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-02A3`
- **TODO:** `TODO-20261013-016`; follow-ups `TODO-20261018-001` (precision) and `TODO-20261018-002` (Acts)
- **Commits:** the commit that introduced this entry.
- **Implemented:**
  - **Gate tool:** new `system/tools/qualify_nca.py`, with no hand labelling. It makes a seeded gold
    selection stratified over twelve hard classes of the typed package, then runs the production NCA
    route over those verses in each WIP. Two independent Claude judges label the expected values (a verse
    has gold values only when both agree) and give a `GENUINE`/`FALSE_ALARM` verdict on every FAIL. A
    planted-error check changes one index value. The receipt holds coordinates, values and verdict labels,
    never WIP text. Steps are cached: comparison changes reuse sealed extraction phases. Provider failures
    are left out of every measure and make the receipt `INCOMPLETE`. `--exclude` builds a held-out set.
  - **Association check fix:** when one gloss lands different WIP numbers on the same source item
    (1KI 7:25, GEN 47:28, NUM 28:14), the numbers stay undecided instead of becoming a BLOCKING
    `WRONG_ASSOCIATION` FAIL.
  - **Association check, unglossed items:** when a source item has no distinguishing words, a mismatch
    stays undecided (GEN 18:28).
  - **`ONE_ONLY_DIFFERENCE`:** a WIP that differs from the source only by added or missing values of one
    is NEEDS_REVIEW, with its own report wording. Before the change, the judges called 14 of 16 such FAILs
    false alarms.
  - **`VALUE_OMITTED` (PO decision 2026-10-18):** a WIP that leaves out source numbers and adds none is
    NEEDS_REVIEW. The translator note asks whether the omission is a deliberate style choice consistent with
    the rest of the translation. The synthetic benchmark fixture's eight missing-number cases now expect
    NEEDS_REVIEW.
  - **Offline rescoring:** `--replay-route` replays sealed extraction phases under a recorded route with no
    provider call.
- **Evidence:** [NCA release gate](../../../docs/advanced/release/NCA-RELEASE-GATE.md) and both receipts.
  WIPs `ukrNPUv1` and `spaNVIv3`; route codex `gpt-5.6-sol`/medium; judges `claude-opus-5-5` and
  `claude-sonnet-5-5`. Development set (312 verses): FAIL precision 4/32 as found and 3/5 after the changes,
  extraction recall 295/305, planted errors 161/161: **FAIL**. Held-out set, Ukrainian (167 verses):
  precision 0/6 as found and no FAILs after the changes, recall 152/158, planted 91/91. The Spanish held-out half did not run (codex workspace
  out of credits): `INCOMPLETE`. NCA stays `PROVISIONAL_UNQUALIFIED`.
- **Verification:** `pytest system/tests/numbers` (gate, association and one-only tests included).

### IMP-20261016-001 — STC name check: MACULA names aligned with the WIP (TODO-20261015-006, names part)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261015-006` (names; key terms remain open)
- **Commits:** the commit that introduced this entry.
- **Implemented:**
  - **Aligner:** new `name_alignment.py` (`SAGE_NAME_ALIGNMENT_V2`). It aligns MACULA proper names with the
    words of the whole WIP using IBM Model 1 restricted to names, with a NULL word. It learns each name's
    spelling stems and the WIP's inflection endings, measured in letters so that Indic vowel signs do not
    count. It is deterministic and cached per WIP text and package in `system/cache/name-alignment/`.
  - **STC:** the task manifest gains `stc_alignment.name_check` (`CHECKED` or `NOT_CHECKED` with the reason;
    it never blocks). `VARIANT` and `SUBSTITUTION` verses become `NAME` deterministic candidates
    (`NM-<ref>-<hash>`) that the model adjudicates. The STC Skill and task instructions explain how to judge
    them.
  - **ABSENT is withheld from STC:** in an LLM-judged audit of 84 sampled candidates from six WIPs
    (Ukrainian, NIV, Arabic, Swahili, Malayalam, Hindi), 3 of 59 `ABSENT` candidates were worth a reviewer's
    time. The other kinds scored 7 of 25. Detection was correct for 54 of 59 `ABSENT`, 10 of 16 `VARIANT`,
    and 5 of 9 `SUBSTITUTION` candidates.
  - **Docs:** the name check section of `ORIGINAL-LANGUAGE-RESOURCES.md`; measurement tool
    `system/tools/evaluate_name_alignment.py` (synthetic injection, no hand labelling).
- **Verification:** new `test_name_alignment.py`; STC manifest test updated. Synthetic injection on nine WIPs
  (GEN, 1CH, JHN, ACT, 60 planted errors per book). In spaced scripts, each book recovers 67-95% of planted
  misspellings (most 75-95%) and 75-100% of swapped names. In Thai and Chinese, misspellings are not detected by design.
  Counting endings in letters cut false Malayalam `VARIANT`s (3 of the 4 found by the audit). Malayalam
  `VARIANT` volume fell from 125 to 81, and its misspelling recall moved from 56/75 to 53/75. The other five
  audited WIPs were unchanged. Full suite re-run.
- **Known limits (from the audit):** `SUBSTITUTION` can misfire where Greek and WIP verse boundaries differ
  (ACT 13:38). A name's learned rendering can attach to a neighbouring name in a list (1CH Galal). A person
  and a place that share a lemma can mislearn one rendering (Penuel/Peniel, Nazareth/Nazarene).

### IMP-20261015-006 — Model claims about original-language words checked against MACULA (TODO-20261015-007)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261015-007`
- **Commits:** the commit that introduced this entry.
- **Implemented:**
  - **Package:** new pinned original-language analysis package `SAGE_OL_ANALYSIS_2026-10-15`
    (`system/resources/ol-analysis/2026-10-15/`; plain TSV, 50 MB unpacked, about 9.5 MB compressed in git and release ZIPs, because the source package may not contain nested archives). It holds every MACULA Hebrew and Greek word with its
    lemma, Strong's number, morphology fields, and a gloss. It is pinned by `system/config/ol-analysis-reference.json`,
    checksum-verified on load, and built reproducibly by `system/tools/build_ol_analysis.py` (`verify` requires
    byte-identical output). The UBS domain fields are excluded.
  - **Claims:** STC findings, RTC original-language adjudications, and BIC original-language checks now return
    `ol_words`: the source words a conclusion depends on, with lemma and parse fields restricted to MACULA's own
    vocabularies. `ol_analysis.check_ol_words` checks each one for the verse and its neighbours: `VERIFIED`,
    `MISMATCH` (naming MACULA's value), `NOT_FOUND`, or `NOT_CHECKED` (package unavailable).
  - **Effect:** a mismatch keeps the finding, marks it `ol_analysis_verified: false`, and records an
    `OL_CLAIM_UNVERIFIED` exception. Nothing blocks. SAGE computes the checks itself at validation, so
    check results in model output are ignored.
  - **Reports:** RTC original-language adjudications and BIC challenge reports show MACULA's lemma, parse, and
    gloss for checked words.
  - **Docs:** the notices page lists the glosses that now ship (Cherith CC BY, Berean public domain).
    `ORIGINAL-LANGUAGE-RESOURCES.md` documents the checks, and `AUTHORITY-POLICY.md` marks `OL_ANALYSIS`
    as partly implemented.
- **Verification:** new `test_ol_analysis.py`, which covers Hebrew and Greek checks, the schema vocabularies,
  tamper degradation, STC flagging, RTC resolution checks, and report lines. New BIC test in
  `test_rewrite_risk.py`, where a check result planted in the file is overridden. Full suite re-run.

### IMP-20261015-005 — Calibrated token estimator, scaled budgets, accent-free routed Hebrew (TODO-20261015-005)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261015-005`
- **Commits:** the commit that introduced this entry.
- **Implemented:**
  - **Estimator:** `evidence.estimate_tokens` is now `SAGE_MULTILINGUAL_HEURISTIC_2` (`evidence.TOKEN_ESTIMATOR`):
    a cost per character by Unicode script block, fitted against `o200k_base` on John and Psalms from 30 local
    translations in 13 scripts plus `@GRK`/`@HEB`. Held-out books now land within 0.81-1.28x of real tokens,
    against 0.26-1.36x for the old formula.
  - **Budgets:** the BIC, RTC, STC, and legacy combined-analysis profile token budgets were scaled by the measured
    new-to-old ratio for each routed mix (x1.25 for translations, x1.45 for STC, x1.35 for legacy OL Review),
    so typical work units keep their size. Byte limits are unchanged.
  - **Hebrew cantillation:** `stc.strip_hebrew_cantillation` removes U+0591-U+05AF from Hebrew routed to STC
    packets and to RTC original-language adjudication packets, and the STC planner and package projection
    measure that same text (`SfmStream.text_filter`, `routed_ol_text_filter_for_book`). This saves 18-25% of
    the real tokens in those Hebrew packets. The Hebrew authority profile says missing accents are never a
    textual difference. BIC's conditional original-language reads are unchanged.
  - **Effect on existing work:** RTC plans approved under the old estimator become stale through their sealed
    sizing contract and must be rebuilt and approved again.
  - **Docs:** method and results are in `docs/advanced/models-and-ai/TOKEN-ESTIMATOR-CALIBRATION.md`; the RTC
    sizing numbers in `STRUCTURE-PLANNING.md` and `MODEL-HANDOFF-OPTIMIZATION.md` are updated.
- **Verification:** new `test_token_estimator.py` (per-script costs, the cantillation stripper, and the STC
  and RTC packets and STC sizing on accent-free Hebrew). Fixture text in the RTC planner and work-unit tests
  is now sized from the estimator, not character counts. Legacy V4 RTC and V1 STC package fixtures carry the
  new estimator ID and values with an unchanged shape. Full suite re-run.

### IMP-20261015-004 — LEGACY NCA Jobs no longer crash Job management (TODO-20261015-004)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-02A3`
- **TODO:** `TODO-20261015-004`
- **Commits:** the commit that introduced this entry.
- **Implemented:** `JobStore.load_job` reports a Job whose NCA reference package is no longer installed as
  `NCA_JOB_LEGACY_PACKAGE`: its reports stay readable, it cannot run, and the next action is to delete or
  archive it and create a new Job. `JobStore.discover` skips Jobs that fail to load instead of raising, or
  with `include_unloadable=True` returns them from their structure-valid manifest. `remove_job` and a
  status-only `revise_job` (archive) no longer need resource trust. Manage JOBs lists such a Job as
  `[LEGACY - cannot run]`; Delete and Archive offer it, Refresh does not. The Project-in-use check, the
  Project's Jobs list, and the global diagnostics export include unloadable Jobs, so a LEGACY Job still protects its Projects.
- **Verification:** `tests/numbers/test_nca_jobs.py` (two new tests; both fail with the original
  `NCA_REFERENCE_NOT_IMPORTED` crash without the fix); full suite re-run.

### IMP-20261015-003 — Third-party data notices and MACULA attribution (TODO-20261015-003)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-02A3`
- **TODO:** `TODO-20261015-003`
- **Commits:** the commit that introduced this entry.
- **Implemented:** new `docs/advanced/projects-and-resources/THIRD-PARTY-NOTICES.md` lists every data source SAGE ships or quotes with its
  license, required attribution line, and where it is used. It records MACULA Hebrew and Greek as © 2022–2024
  Biblica, Inc. under CC BY 4.0 with the pinned commits and SHA-256 values, and states the changes SAGE makes
  (column selection, NFC normalization, versification mapping, typed number values) as CC BY 4.0 requires. It
  credits the sources inside MACULA (WLC, OSHB, SBLGNT), and notes that the UBS SDBH and MARBLE domain fields are
  "used with permission", are outside Biblica's grant, and are never read. It also says the bundled `@GRK`/`@HEB`
  provenance is still unresolved. The page is linked from `README.md`, `docs/INDEX.md`, `OPERATOR-GUIDE.md`,
  `NCA-CHEAT-SHEET.md`, `RESOURCE-RIGHTS-AND-PROVENANCE.md`, and `AUTHORITY-POLICY.md`. NCA action reports
  that quote original-language verse text now print the MACULA attribution line in **Sources and attribution**,
  with the WLC credit for Hebrew or the SBLGNT copyright credit for Greek
  (`nca_reporting.OL_TEXT_ATTRIBUTION`).
- **Verification:** `tests/numbers/test_reporting.py`; full suite re-run.

### IMP-20261015-002 — RTC/STC multi-portion and planner stale-plan tests (completes TODO-20261014-020)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-020`
- **Commits:** the commit that introduced this entry.
- **Implemented:** `test_rtc_stc_multi_portion.py` runs `1CH 5-6; 24` end to end under canonical `rtc` and
  `stc` Jobs: CLI planning and Operator approval (RTC), one task per review portion, receipt-backed
  submission, aggregation, and Run completion. Both assert exact coverage of the six selected verses,
  Hebrew routing for STC, and chapter reports for 005, 006, and 024 only. `test_rtc_stc_regressions.py`
  now builds a real planner (schema 1.3+) plan and checks every planning-contract staleness cause:
  REFERENCE binding, sizing policy, planner/prompt/schema contract, REFERENCE text, a unit over the size
  limit, and coordinates that no longer reconcile. Each raises `RTC_APPROVED_PLAN_STALE` with its own
  message and a rebuild instruction.
- **Verification:** `test_rtc_stc_multi_portion.py`, `test_rtc_stc_regressions.py`; full suite re-run.

### IMP-20261015-001 — RTC/STC task builders, ACT rendering, sealing, and submit integrity split out (completes TODO-20261014-018)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-018`
- **Commits:** the commit that introduced this entry.
- **Implemented:** the composite RTC builders (`_create_approved_rtc_stage`, `_partition_selective_ol_cases`,
  `_create_rtc_composite`) move to `rtc_tasks.py` and the STC builder to `stc_tasks.py`; both import
  `create_act_task` at call time because `act_tasks` imports them. The per-operation ACT process brief
  moves to `act_render.process_brief_lines`. `task_sealing.seal_task` writes the manifest, ACT.md, and
  control record and makes them read-only for both the generic and STC builders, replacing two copies.
  `act_submit.verify_sealed_submission` holds every integrity check (control record, manifest
  fingerprint, routed inputs, write allowlist, execution receipt) and returns a `SealedSubmission`;
  `submit_act_task` keeps only per-workflow validation and commit. Imports left unused by the split are
  removed from `act_tasks.py`, which drops from 3,997 to about 2,700 lines; every name other modules or
  tests import from it is still re-exported.
- **Verification:** full suite re-run.

### IMP-20261014-025 — Hardening copies the in-tree SQS service (TODO-20261014-023)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-023`
- **Commits:** the commit that introduced this entry.
- **Implemented:** `system/tools/hardening.py` copies the bundle's `services/` tree (without caches) next
  to the clean app copy in each isolated module workspace, so the SQS tests that import it pass under the
  official runner. `services/` is still excluded from release packages and from the source hash.
- **Verification:** `test_hardening_and_segmentation.py` re-run.

### IMP-20261014-024 — RTC/STC documentation drift (TODO-20261014-021)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-021`
- **Commits:** the commit that introduced this entry.
- **Implemented:** `RTC-STC-OPERATOR-MODES.md`, `RTC-STC-CHEAT-SHEET.md`, and `RTC-CHECK-POLICY.md` now say
  that Runs end `COMPLETE`, `COMPLETE_WITH_STRUCTURE_PROBLEMS`, or `COMPLETE_WITH_EXCEPTIONS` (never
  `FINALIZED`); document NOT_ASSESSED work units, the exception reports, and what still stops a Run; place
  quotation checks under the structure/completeness group; replace the unreachable per-Run toggle screen
  with the Job's RTC defaults screen and the "Run RTC on <WIP> with defaults" label; describe the
  Operator-pinned no-data routing default; say that secondary-language rendering calls the model; and
  explain that an RTC chapter report consolidates every Run that reviewed the chapter.
- **Verification:** documentation contract tests re-run.

### IMP-20261014-023 — RTC/STC regression tests (TODO-20261014-020)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-020` (stays `IN_PROGRESS`: the multi-portion `1CH 5-6; 24` end-to-end Runs and the
  approved-plan staleness causes that need the RTC sizing/planner schema are not covered yet)
- **Commits:** the commit that introduced this entry.
- **Implemented:** regression tests for `TODO-20261014-001` through `-008` landed with those items. New
  `test_rtc_stc_regressions.py` covers the reachable approved-plan staleness causes (plan missing, Run
  identity, changed WIP), STC aggregation guards (duplicate primary ownership and coverage drift raise
  `AGGREGATE_COVERAGE_MISMATCH`; another Run's result raises `RESULT_COVERAGE_DRIFT`), and Continue after a
  crash between stage-task creation and plan save.
- **Verification:** `test_rtc_stc_regressions.py`.

### IMP-20261014-022 — act_tasks.py split into layered modules (first part of TODO-20261014-018)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-018` (stays `IN_PROGRESS`: `create_act_task` and its partition and composite
  builders are not yet split into `rtc_tasks` and `stc_tasks`, and ACT rendering is still inline)
- **Commits:** the commit that introduced this entry.
- **Implemented:** `act_tasks.py` keeps only task creation (`create_act_task`, the STC and composite RTC
  builders, and the partitioners). Helpers and constants move to `act_common.py`; evidence packets,
  preflight, structural triage, and budget checks to `act_evidence.py`; submission and its integrity
  checks to `act_submit.py`; aggregation to `act_aggregation.py`. The layers import only downward, and
  `act_tasks` re-exports every moved name, so existing imports keep working. The private names other
  modules used are public: `one_book_file`, `review_portion_for_reference`, and `stage_record` (the old
  names remain as aliases).
- **Verification:** full suite re-run.

### IMP-20261014-021 — RTC/STC performance (TODO-20261014-017)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-017`
- **Commits:** the commit that introduced this entry.
- **Implemented:** `ProjectVerseIndex.cached` reuses one verse index per Project content and effective VRS
  across a Run's tasks (keyed by every record's coordinates and text and the full schema), and RTC/STC task
  creation and composite checks use it. `VersificationSchema.mapping_precision` uses the mapping index
  instead of scanning every mapping per verse (the PSA index-build hotspot). Task creation measures the
  routed handoff and checks the budget once; the identical second measurement, input re-read, and budget
  check after the manifest is built are gone.
- **Verification:** RTC, STC, VRS, and harness suites re-run.

### IMP-20261014-020 — In-process Run driver (TODO-20261014-016)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-016`
- **Commits:** the commit that introduced this entry.
- **Implemented:** the menu runs RTC/STC `task continue`, `task submit`, and `task aggregate` as function
  calls (`_in_process_controller`) instead of `sage.cli` subprocesses; non-SAGE exceptions still surface as
  `MENU_CONTROLLER_COMMAND_FAILED`. `task execute` stays a subprocess so Ctrl-C can still stop a running
  provider call. The work-unit failure policy is one function (`exception_reports.apply_unit_failure`) used
  by the menu and by CLI `task execute` and `task submit` (skipped when the menu drives the CLI, via
  `SAGE_MENU_DRIVER`, so attempts are not counted twice). Continuing an RTC/STC Run takes a Run driver lock
  (`locks/run-driver`, stale same-host owners recovered). The Codex readiness check runs once per Run.
- **Verification:** new tests in `test_exception_reports.py`.

### IMP-20261014-019 — Narrower model contract and prompt hygiene (TODO-20261014-015)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-015`
- **Commits:** the commit that introduced this entry.
- **Implemented:** new `candidates.py`. Deterministic candidates (`\add`/`\nd` differences, numbers that
  differ from the index or are written in words, and STC length outliers) get stable IDs and are listed in
  the task manifest (`deterministic_candidates`) and model assignment. The RTC meaning-stage and STC
  response schemas require `candidate_adjudications` (`CONFIRM`, `REJECT`, `UNSURE`, with the confirming
  `finding_id`); validation keeps one adjudication per candidate, drops unknown ones, turns a CONFIRM
  without a reported finding into UNSURE, and records unadjudicated candidates as UNSURE. The RTC and STC
  Skills describe the narrowed contract (candidates plus an open search for meaning, quotation, and
  participant issues). Prompt hygiene: the three byte-identical per-Skill `EXECUTION-RULES.md` copies are
  removed (ACT step 8 carries the rule), the global execution rules lose lines the sealed model cannot act
  on and the outdated "failures stop the controller" rule, the ACT no longer repeats the
  narrative-language exclusion the prompt already states, and `rtc-findings.schema.yml` is brought up to
  date. Skill hashes in `skills.json` are re-pinned. The handoff byte budget now counts every routed read,
  not only `.sfm` (`measurement_scope: routed_reads_bytes_and_sfm_tokens`); token sizing stays SFM-only to
  match the planner.
- **Verification:** new `test_candidates.py`; harness and STC expectations updated.

### IMP-20261014-018 — Numbers in RTC/STC (TODO-20261014-014)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-014`
- **Commits:** the commit that introduced this entry.
- **Implemented:** new `numeric_candidates.py` reuses `sage/numbers` (`find_numerals` and the qualified
  number index) to classify each WIP verse with numbers as `MATCH`, `DIFFERS`, or `NOT_IN_DIGITS`. RTC
  preflights and STC alignments carry the rows with the index-edition caveat (the index follows WLC and
  SBLGNT, not the bundled OL editions); the ACT tells the model not to report numbers for `MATCH` verses and
  that NCA checks numbers in full. A missing index yields `INDEX_UNAVAILABLE` instead of an error.
- **Verification:** new `test_numeric_candidates.py`.

### IMP-20261014-017 — STC evidence checked in code (TODO-20261014-013)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-013`; also the STC quotation check of `TODO-20261013-008` (which stays `OPEN`
  for the other model-echoed fields).
- **Commits:** the commit that introduced this entry.
- **Implemented:** each STC finding's `wip_evidence` and `ol_evidence` is checked against the routed WIP
  and OL slices (`stc.evidence_is_verbatim`: NFC, USFM markers and ketiv/qere asterisks removed, ellipsis
  parts checked separately, diacritic-insensitive fallback). A quotation that is not found keeps its finding
  but marks it `evidence_verified: false` and records `STC_EVIDENCE_UNVERIFIED`. The HEB authority profile
  now explains the `*ketiv **qere` notation and lists the Biblical Aramaic ranges (GEN 31:47, EZR 4:8–6:18,
  EZR 7:12–26, JER 10:11, DAN 2:4–7:28); the GRK profile explains `[[ ]]`. Each STC unit's alignment carries
  `length_outliers` (WIP verses far shorter or longer than their OL text relative to the book's median
  ratio), sent to the model as `verse_length_outliers` candidates; the STC ACT text tells the model to cite
  WIP numbering, quote verbatim, and not restate code-reported gaps.
- **Verification:** new tests in `test_stc.py`; `test_stc_task.py` expectation updated.

### IMP-20261014-016 — RTC Text policy applied in code (TODO-20261014-012)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-012`
- **Commits:** the commit that introduced this entry.
- **Implemented:** the RTC finding schema requires `usfm_context` (`NONE`, `add`, `nd`, `f`, `x`) and
  `material`, and `grammar_rule_ids` is an enum of the task's project grammar rules. The sealed Text policy
  (`checks` and `usfm_contexts`) is sent in the model assignment, and `validate_analysis_findings` filters
  findings of disabled checks and findings whose USFM context mode does not elevate them
  (`rtc_policy.should_elevate`, now called in production), recording `RTC_FINDING_POLICY_FILTERED`.
  Severity clamping with a correction record landed in `IMP-20261014-012`. `findings.dedupe_findings` drops
  repeated findings (same reference, category, and normalized issue) and model STRUCTURE/VERSIFICATION
  findings at a deterministic finding's verse, in composite finalization and partitioned aggregation; the
  composite result lists `deduplicated_finding_ids`.
- **Verification:** new tests in `test_storage_rtc_boundaries.py`.

### IMP-20261014-015 — Deterministic marker checks (TODO-20261014-011)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-011`; also the `\x` and `\f` marker-sanity part of `TODO-20261013-009` (which
  stays `OPEN` for the other pre-checks).
- **Commits:** the commit that introduced this entry.
- **Implemented:** new `marker_checks.py`. At composite creation SAGE compares each WIP verse's
  cross-reference target numbers (`\xt`, book names ignored because they are localized) with the REFERENCE
  verses at the same canonical coordinates, and checks every footnote for an origin (`\fr`) naming its own
  verse and a text (`\ft`); differences become deterministic STRUCTURE findings. `\add` and `\nd` count
  differences are candidates only: each RTC task preflight lists them as `marker_candidates` and the ACT
  tells the model to report only material ones. The meaning-stage ACT says SAGE compares Scripture target
  numbers and footnote structure in code. The composite compiles WIP and REFERENCE once for all of its
  deterministic checks.
- **Verification:** new `test_marker_checks.py`.

### IMP-20261014-014 — Omission and addition in both directions (TODO-20261014-010)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-010`
- **Commits:** the commit that introduced this entry.
- **Implemented:** new `text_coverage.py` computes the OMISSION direction that was never computed:
  REFERENCE (RTC) or OL (STC) text in the scope's canonical window that no WIP verse carries, empty WIP
  verses, and whole chapters the WIP lacks (one chapter-level row). A WIP Psalm `\d` title is matched to
  the Authority's leading title verse(s) instead of being reported. RTC composites store these rows as
  `coverage_gap_issues`; finalization reports them and promotes every OMISSION and ADDITION gap to a
  deterministic STRUCTURE finding once per coordinate. STC plans (or a one-unit STC task) carry the same
  rows; STC submission and aggregation promote gaps to deterministic OMISSION/ADDITION findings. The RTC
  preflight replaces the empty `direct_findings` with the task's gap findings and adds a
  `REFERENCE_TEXT_COVERAGE` controller check computed from the packets.
- **Verification:** new `test_text_coverage.py`; RTC and STC suites re-run.

### IMP-20261014-013 — Deterministic structural stage (TODO-20261014-009)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-009`
- **Commits:** the commit that introduced this entry.
- **Implemented:** composite RTC creation triages every WIP VRS mapping candidate in code
  (`_structural_triage`) from the WIP↔REFERENCE alignment (`align_records`): identity, shift, merge, or
  split with text on both sides is recorded as a `NO_FINDING` resolution; text missing on one side becomes a
  deterministic `STRUCTURE` finding (`plan.deterministic_findings`, merged with run-global IDs at
  finalization); only an equivalence group the code cannot decide goes to the `STRUCTURAL_ADJUDICATION`
  model stage, and that stage's preflight lists only those candidates. `VERSE_BRIDGE_MAPPING` is no longer a
  model check: bridge mapping is decided from the alignment and its canonical-gap source issues, while the
  model keeps `VERSE_BRIDGE_CONTENT`.
- **Verification:** new tests in `test_storage_rtc_boundaries.py` and `test_exception_reports.py`; the
  structural-stage tests now use an equivalence group whose REFERENCE side has no text.

### IMP-20261014-012 — RTC/STC never-block specifics (TODO-20261014-008)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-008`; also the STC and RTC finding parts of `TODO-20261013-020` (which stays
  `IN_PROGRESS` for planners and report translation).
- **Commits:** the commit that introduced this entry.
- **Implemented:** RTC findings are validated item by item. A finding with a duplicate ID, an unusable,
  out-of-scope, or context-only reference, an unsupported category, no issue text, no routed evidence, a
  grammar category without a project grammar rule, or no OL evidence in an OL stage is dropped and
  recorded (`RTC_FINDING_DROPPED`, `FLAGGED`, with the finding text). Unsupported action levels or
  confidence, `CHANGE`/`BLOCK` with low confidence, a missing required action, unrouted evidence IDs,
  unknown grammar rule IDs, and OL evidence outside an OL stage are corrected and recorded
  (`RTC_FINDING_CORRECTED`). A finding that a structural adjudication or OL resolution points at still
  rejects the unit when defective, so those ledgers stay consistent; extra structural-stage findings are
  dropped. STC drops a finding with an unsupported category, an out-of-scope or unplanned reference,
  missing evidence, or a duplicate (`STC_FINDING_DROPPED`) and flags a report-language mismatch as
  `STC_REPORT_LANGUAGE_UNVERIFIED`. All records go to the Run's exception report. USFM parser errors block
  task creation only when they fall in the requested chapters (`_parser_errors_in_scope`). The selective-OL,
  auto-partition, and STC partitioners roll back the child tasks they created when they fail mid-loop.
- **Verification:** new tests in `test_storage_rtc_boundaries.py`, `test_stc.py`, and `test_stc_task.py`;
  reject-expecting tests updated to the salvage behavior.

### IMP-20261014-011 — RTC/STC engine gaps (TODO-20261014-007)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-007`
- **Commits:** the commit that introduced this entry.
- **Implemented:** a one-unit RTC/STC Run goes through the same retry, NOT_ASSESSED, and stop policy as a
  plan (`_run_single_analysis_unit`), and a NOT_ASSESSED standalone STC task publishes its report.
  Changing RTC/STC Job defaults while a Run is open is refused (`JOB_DEFAULTS_RUN_OPEN`; the RTC defaults
  menu says so up front), because every revision rewrites the sealed runtime settings. `workspace
  initialize` knows the NCA required roles. `task create --workflow rtc` without a Job is refused
  (`RTC_JOB_REQUIRED`) instead of minting an orphan Job.
- **Verification:** new tests in `test_exception_reports.py`.

### IMP-20261014-010 — Failure classification and pre-provider checks (TODO-20261014-006)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-006`
- **Commits:** the commit that introduced this entry.
- **Implemented:** `unit_failure_action` stops the Run for `RUN_STOP_CODES` (`CODEX_EXECUTION_NOT_READY`,
  `MENU_CONTROLLER_COMMAND_FAILED`, `CONFIGURATION_ERROR`, `PROVIDER_ROUTE_UNAVAILABLE`) instead of retrying
  them into NOT_ASSESSED units, and trips a circuit breaker when a non-content code has already sealed
  `CIRCUIT_BREAKER_UNITS` (2) units in the Run. `INTEGRITY_CODES` gains `RTC_/STC_TASK_CONTRACT_INVALID`,
  `STC_OL_AUTHORITY_MISMATCH`, `LLM_RESPONSE_ROUTE_MISMATCH`, the analysis work-unit layout codes,
  `EXECUTION_RECEIPT_MISSING`, and the new `TASK_SUBMISSION_TAMPERED` code now carried by the submit-time
  manifest, prompt, fingerprint, and write-allowlist checks (a changed conditional input is
  `ACT_INPUT_STALE`). The RTC work-unit layout and selective-OL evidence-contract checks run before the
  provider call. RTC and STC output without an execution receipt is rejected instead of being recorded as
  `UNRECORDED`; tests use the new `conftest.submit_with_receipt` helper.
- **Verification:** new tests in `test_exception_reports.py` and `test_storage_rtc_boundaries.py`.

### IMP-20261014-009 — RTC planner headroom and bridge boundaries (TODO-20261014-005)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-005`
- **Commits:** the commit that introduced this entry.
- **Implemented:** RTC planning keeps `RTC_PLAN_HEADROOM_TOKENS` (64) below the task-time WIP and route
  limits (`rtc_plan_wip_limit`), so a unit planned at the edge no longer becomes a permanent
  `RTC_APPROVED_PLAN_STALE`; the composite auto-partition route applies the same WIP stream limit. Required
  span closure first moves a boundary back before an indivisible REFERENCE or VRS span and extends forward
  only when the backward plan does not fit. A canonical gap inside a WIP bridge flags only the local verse
  that owns it (`verse_alignment.missing_by_local_ref`). Structural candidate IDs are derived from the VRS
  mapping (`VRS-<hash>`), so they are unique across a plan.
- **Verification:** updated and new tests in `test_rtc_planner.py`; `test_storage_rtc_boundaries.py`.

### IMP-20261014-008 — Honest STC coverage and Run status (TODO-20261014-004)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-004`
- **Commits:** the commit that introduced this entry.
- **Implemented:** the STC chapter report's Coverage line now reports assessed coverage through
  `coverage_document` (`COMPLETE`, `PARTIAL`, or `NOT_ASSESSED`, with assessed and not-assessed counts)
  instead of repeating the source-comparison status; a fully not-assessed chapter no longer shows
  `COMPLETE (0 coordinates)`. `STC_RUN_RESULT.json` carries a `coverage` record, and its `status` is the
  coverage status when units were NOT_ASSESSED. A Run with NOT_ASSESSED exception records closes as
  `COMPLETE_WITH_EXCEPTIONS` (new `RUN_COMPLETED_STATUSES`; result `DONE`; archivable). The partitioned
  aggregate Markdown is joined with real newlines.
- **Verification:** new and updated tests in `test_exception_reports.py`.

### IMP-20261014-007 — STC references in WIP numbering (TODO-20261014-003)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-003`
- **Commits:** the commit that introduced this entry.
- **Implemented:** STC finding references are matched by exact verse atoms (`MAT 1:2` is no longer
  accepted because `MAT 1:20` is planned). The STC response schema makes `target_reference` an enum of the
  unit's `expected_references` (WIP numbering). The task manifest's `stc_alignment` gains
  `verse_correspondence` (WIP verses whose OL verses carry other numbers, from
  `verse_alignment.record_correspondence`), and the STC model assignment carries it as
  `wip_to_original_language_verses` with `original_language_missing_for`. A current-planner STC scope that
  fits one unit now receives the planner's boundary context verses.
- **Verification:** new tests in `test_stc.py`; updated `test_stc_task.py` expectations.

### IMP-20261014-006 — RTC OL requests under a PROHIBITED policy (TODO-20261014-002)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-002`
- **Commits:** the commit that introduced this entry.
- **Implemented:** `validate_analysis_findings` takes the sealed `source_text_drift_adjudication` policy;
  under anything but `ENABLED` the meaning stage's `ol_review_requests` are dropped at submit and each is
  recorded (`RTC_OL_REQUEST_PROHIBITED`, `FLAGGED`, with the model's question). Composite continuation no
  longer raises on such requests in already sealed outputs; it records them and finalizes. An OL resolution
  whose `decision` contradicts its `outcome` keeps the outcome, reports the decision as `INCONCLUSIVE`, and
  is recorded as `RTC_OL_DECISION_OUTCOME_MISMATCH` (`CORRECTED`). The selective-OL ACT step 5 now names the
  schema `decision` values and their consistent outcomes.
- **Verification:** new tests in `test_storage_rtc_boundaries.py` and `test_exception_reports.py`.

### IMP-20261014-005 — RTC composite NOT_ASSESSED handling (TODO-20261014-001)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261014`
- **TODO:** `TODO-20261014-001`
- **Commits:** the commit that introduced this entry.
- **Implemented:** a NOT_ASSESSED `STRUCTURAL_ADJUDICATION` stage no longer finalizes the composite; the
  meaning stage is created without a structural predecessor and reviews the whole scope. Composite
  finalization unions every stage's not-assessed coordinates and removes them from reviewed coverage, so a
  NOT_ASSESSED `SELECTIVE_OL_ADJUDICATION` stage marks its deferred target verses NOT_ASSESSED and its
  exception survives consolidation. OL resolutions (outcome, decision, rationale, finding) render in a new
  "Original-language adjudications" report section, and OL-stage findings keep `ol_decision` and
  `ol_rationale`.
- **Verification:** new tests in `test_exception_reports.py`.

### IMP-20261014-004 — BIC item-level salvage (first part of TODO-20261013-020)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261013`
- **TODO:** `TODO-20261013-020` (stays `IN_PROGRESS`; the STC, RTC, planner, and report-translation parts
  are still open)
- **Commits:** the commits that introduced this entry (INSPECT part: `46b1d8a`).
- **Implemented:** BIC no longer rejects a whole unit for one defective item.
  - INSPECT: a defective proposal or challenge (bad payload JSON, unsupported type, invalid or
    out-of-scope reference, duplicate id) is dropped and recorded; an INSPECT with nothing in it is accepted
    as no challenges. Header defects stay strict.
  - REWRITE challenge ledger (`rewrite_risk.validate_rewrite_challenges`): a model value that disagrees with
    its locally derived value (lexical-burden total, Longman familiarity, selected candidate, risk urgency,
    `after_ol` without an OL check, OL `candidate_changed`, `resolved`, `after_candidate_id`) is overwritten
    and recorded as `VALUE_CORRECTED`. A missing or unusable message language is left out of the localized
    wording, so the report shows the canonical text and an "untranslated" line, and the ledger records
    `MESSAGE_LANGUAGE_UNTRANSLATED`.
  - OL micro-failure (`llm_tasks`): an unusable micro-response, micro-scope, or over-budget micro read undoes
    only that challenge. Its pass-1 candidate and risk stay, its `ol_referral` becomes
    `{performed: false, unavailable: true, unavailable_code}`, the ledger validator accepts that and records
    `OL_UNAVAILABLE`, and the receipt lists `conditional_ol_micro_failures`. Route mismatch and integrity
    codes still stop the task.
  - REWRITE and SELF-CHECK USFM (`act_outputs.classify_bic_usfm_verses`): validation is verse by verse. A
    verse that is empty, outside the sealed coverage, missing, or whose protected markers differ from its
    SOURCE verse is recorded as `NOT_ASSESSED` ("not rewritten"); SELF-CHECK commits only the passing verses
    (`bounded_target.drop_verse_blocks`, `merge_bounded_usfm(keep_existing=...)`) and failing verses keep their
    existing TARGET text. A passing verse is also held back when it shares continuation (poetry) lines with a
    failing neighbour (`expand_unsafe_drops`, code `BIC_VERSE_SPLICE_RISK`). Markers that cannot be attributed
    to verses, or a candidate with no passing verse, are still rejected as a whole.
  - OL `performed` (`rewrite_risk`): the flag records what actually ran, and the controller no longer
    rejects the unit when it disagrees with the requirement. A required check that did not run (no OL packet
    routed: `OL_NOT_ROUTED`; not performed: `OL_NOT_PERFORMED`; incomplete OL record:
    `OL_EVIDENCE_INCOMPLETE`; micro-call failure: its failure code) keeps the pass-1 candidate and risk and is
    recorded as `OL_UNAVAILABLE`. A claimed check that was not required has its OL fields cleared and is
    recorded as `VALUE_CORRECTED`.
  - Each dropped, corrected, or flagged item is written to the Run's `diagnostics/EXCEPTION-REPORTS.jsonl`.
- **Verification:** new tests in `test_rewrite_risk.py`, `test_llm_harness.py`, `test_core_hardening.py`, and
  `test_hardening_and_segmentation.py`; full suite re-run with the `textual` extra installed.

### IMP-20261014-003 — Shared exception reports; content problems no longer stop a Run

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261013`
- **TODO:** `TODO-20261013-003`
- **Commits:** the commit that introduced this entry.
- **Implemented:** new `exception_reports.py` on top of `execution_events`: one `ExceptionRecord` (tool,
  Job, Run, task, work unit, stage, coordinates, code, message, severity, effect, attempts, evidence path)
  persisted per Run in `diagnostics/EXCEPTION-REPORTS.jsonl`; one `INTEGRITY_CODES` list merging the NCA
  integrity codes (`NCA_INTEGRITY_FAILURE_CODES` is now re-exported from it), the stale-input, binding,
  commit, and finalization codes, and path and pinned-contract guards; and `unit_failure_action`, which
  STOPs on an integrity code or an environment condition (`INPUT_REQUIRED`, `TASK_PAUSED`), RETRYs any other
  failure, and returns NOT_ASSESSED after `MAX_UNIT_ATTEMPTS` (3) failures. The partitioned RTC/STC plan
  loop and the BIC chain apply that policy; the BIC chain now runs INSPECT, REWRITE, and SELF-CHECK in one
  Continue (it stopped after every stage), seals a unit that keeps failing as not rewritten, and leaves
  TARGET text untouched. A NOT_ASSESSED unit is a terminal result (`validation/submission.json` plus
  `validation/not-assessed.json`): `plan_continuation`, `aggregate_act_plan`, `_aggregate_stc_plan`,
  `finalize_stc_run`, composite RTC finalization, chapter documents, and `consolidate_result_documents`
  accept it and derive coverage through `coverage.assess_coverage` (`PARTIAL`, or `NOT_ASSESSED` when nothing
  was assessed) instead of hard-coding `COMPLETE`; a coordinate reviewed by any consolidated input stays
  reviewed. STC now publishes even when every unit was not assessed. One "Exceptions — not assessed"
  section (`render_exceptions_section`) appears in RTC, STC, and NCA reports, and a BIC Run writes
  `diagnostics/EXCEPTIONS-NOT-ASSESSED.md`.
- **Not changed:** a Run that wrote nothing still closes as `COMPLETE` (no new Run status; the completion
  text and exception report say what was lost). NCA does not yet produce records of its own, so its
  section lists only groups already `NOT_ASSESSED`; the NCA hard stops stay with `TODO-20261013-021`.
  Single-task analysis Runs (focused and OL checks) are not plan runs and keep manual retry. Item-level
  salvage inside a unit is `TODO-20261013-020`.
- **Verification:** `tests/test_exception_reports.py` (20 tests: policy matrix, integrity list, records,
  aggregation, STC including all-unassessed, composite RTC, consolidation, the RTC/STC runner, the BIC
  chain, NCA section); full `system/tests` suite on 2026-10-14: 2089 passed, 2 skipped.

### IMP-20261014-002 — BIC identity is controller-injected; BIC output has real JSON schemas

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261013`
- **TODO:** `TODO-20261013-002`
- **Commits:** the commit that introduced this entry.
- **Implemented:** new `bic_output_contract.py`. After the last OL micro merge, `materialize_files`
  sets `schema_version`, `operation_id`, `scope`, `resource_fingerprints` (INSPECT); `schema_version`,
  `task_id`, `scope`, `profile_id`, `profile_sha256`, `output_sha256` (grammar assessment); and
  `schema_version`, `task_id`, `operation`, `scope`, `output_sha256`, `reporting_languages` (challenge
  ledger), so live INSPECT, REWRITE without an OL step, and SELF-CHECK no longer fail for fields the model
  was never given. The OL merge no longer patches `output_sha256`, `urgency`, or `selected_candidate_id`.
  The three BIC files now have strict provider JSON schemas (rule-ID enum from the manifest; record,
  challenge, category, confidence, trigger, band, source, and rejection enums from `bic_memory.py` and
  `rewrite_risk.py`; integer 0–4 scores). Derived fields left the model contract: `submitted_id`,
  `lexical_burden.overall`, `risk.after_ol`, `risk.urgency`, `selected_candidate_id`, the whole
  `ol_referral` (the controller writes `performed: false` and the OL micro merge sets the real record),
  and `minor_summary.total`. INSPECT proposal payloads travel as `payload_json` text and are decoded by the
  controller, because a free-form object cannot satisfy a strict provider schema. The assignment block
  sent for BIC now carries BIC-only keys plus `grammar_rule_ids`, `marker_policy`, and
  `reporting_languages`, and its header no longer says "analysis identity".
- **Not changed:** the `bic-inspect` Skill line that still says to set `operation_id` (the Skill is
  not sent to the model; its cleanup belongs to `TODO-20261013-004`). Item-level salvage and
  OL `performed` derived from what ran remain `TODO-20261013-020`.
- **Verification:** full `system/tests` suite on 2026-10-14: 2069 passed, 2 skipped, 5 failed. Those 5 were
  the new module missing from `VANILLA-INSTALL-MANIFEST.md` (three package and release-builder tests)
  and an undocumented nested test helper, now fixed; the re-run of those files passes (115). The harness
  test feeds the materialized REWRITE output through the real `validate_rewrite_challenges` and
  `validate_grammar_assessment`; new tests cover INSPECT payload decoding and SELF-CHECK binding.

### IMP-20261014-001 — BIC protected contracts reach the model verbatim

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261013`
- **TODO:** `TODO-20261013-001`
- **Commits:** the commit that introduced this entry.
- **Implemented:** BIC REWRITE and SELF-CHECK tasks now send `PROTECTED-REWRITE-DETAIL-RULES.md` and
  `bic-verb-selection-policy.yml` byte-for-byte to the model in a marked `PROTECTED CONTRACTS` block
  placed after the ACT capsule and before (outside) `AUTHORIZED READS`, in the primary prompt, the
  report-language correction prompt, and every OL micro prompt. `llm_tasks._protected_contracts`
  re-loads both pins, requires the task's sealed contract records to match them, and asserts the
  embedded bytes hash to the pin; it runs before any provider contact and fails closed with
  `BIC_PROTECTED_CONTRACT_MISSING`, `_STALE`, or `_HASH_MISMATCH`. The execution receipt and dry run
  record `protected_contracts: [{id, sha256, bytes}]` (schema updated). One controller line states that
  each routed SFM read is the deterministic projection of the USJ input the rewrite-detail contract
  names. Neither contract file, pin, nor the Process brief wording changed.
- **Verification:** full `system/tests` suite on 2026-10-14: 2066 passed, 2 skipped, and one failure that
  was bytecode caches left by the test run itself (removed; passes clean). The conditional-OL harness test
  now asserts both contracts appear verbatim in both phases, in the required position, with the receipt
  record; a new test covers the missing and stale cases without provider contact.

### IMP-20261013-001 — Rejected provider output no longer resubmits forever

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-REVIEW-20261013`
- **TODO:** `TODO-20261013-019`
- **Commits:** the commit that introduced this entry.
- **Implemented:** BIC INSPECT, USFM, grammar-assessment, and translation-challenge validators and
  the STC submission validator now run inside `task_retry.provider_output_contract`, which re-codes
  generic `VALIDATION_ERROR` and `MEMORY_GOVERNANCE_ERROR` failures to `BIC_OUTPUT_INVALID` or
  `STC_OUTPUT_INVALID` (RTC already did this inline; it now shares the helper). Specific output codes
  that matched no output fragment are now classified `TASK_OUTPUT_REJECTED`: every `*_OL_REFERRAL_*`
  code, `USFM_PROTECTED_MARKER_MISMATCH`, `STC_REPORT_LANGUAGE_MISMATCH`,
  `LLM_REPORT_LANGUAGE_RETRY_EXHAUSTED`, `LLM_CONDITIONAL_SCOPE_INVALID`, the three `INSPECT_*`
  output codes, and `BIC_OL_MICROSCOPE_INVALID` / `_NOT_SINGLE_VERSE`. A context overflow in a
  follow-up phase (language correction or OL micro step) is now `LLM_FOLLOWUP_CONTEXT_LIMIT_EXCEEDED`
  and retries the task; the first-phase `LLM_HANDOFF_CONTEXT_LIMIT_EXCEEDED` is unchanged. Rejected
  submissions are therefore archived and the sealed task reopens instead of being resubmitted on every
  Continue. Raw provider responses are kept verbatim: on success under
  `validation/provider-responses/` (listed with hashes in the execution receipt, and archived with
  any later rejected attempt), and on any failure after the first response under
  `attempts/attempt-NNN-rejected|failed-*/provider-responses/`. The menu shows the preserved path.
  Task, evidence, and integrity codes (for example `ACT_REPORT_LANGUAGE_MISMATCH`,
  `BIC_OL_MICROSCOPE_EVIDENCE_INVALID`, `EXECUTION_RECEIPT_*`) keep their previous classification.
- **Verification:** full `system/tests` suite on 2026-10-14: 2065 passed, 2 skipped, 1 failed. The
  failure, `test_bootstrap_runtime.py::test_runtime_state_records_python_platform_and_dependency_contract`,
  is host-dependent (the development Mac resolves `approved-host-python` instead of the pinned
  runtime path) and fails identically on `6bce03f`.
  New regression tests cover classification, the re-coding helper, response preservation on
  execution failure and success, archiving, and BIC submit codes.

### IMP-20261011-001 — NCA 0.02a3 runtime and tester feedback 2a3

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-02A3`
- **Commits:** `6bce03f` (squashed `0.02a3` work), building on `11a5176`, `a50cb30`, `4f44c70`,
  `ce1c09c`, and `e9dee08`.
- **Implemented:** Rewrote the numeric check as a proportionate extract-and-compare pipeline that
  extracts only indexed coordinates in scope. Pinned the typed MACULA/NIV number index
  `SAGE_NUMBERS_TYPED_2026-10-09` (BSB-quoted, no NIV Scripture text) with counting convention 2.0
  (quantities and dates) and extraction contract 3.0. BLOCKING FAIL now applies only against
  original-language readings the index vouches for. Added copy-paste translator notes, apparatus-backed
  text-critical decisions, the association check, and the number-style consistency report. NCA never
  stops a Run on Scripture content; damaged verses report `NOT_ASSESSED`. Tester feedback 2a3: one
  standard Job menu shape for RTC, STC, and NCA (`job_menus.py`), two-step Job delete (delete all, or
  keep reports), Operator reports under `localdata/reports/`, PASS groups removed from final reports,
  and EZR 1:10 no longer presents a normalized index reading as the original-language text.
- **Verification:** `system/tests/numbers`, `test_primary_workflow_menus.py`, and
  `test_menu_localization.py`: 747 passed, 2 skipped. Open: live-model qualification and the
  typed-package release receipt (`TODO-20261013-016`).

### IMP-20260928-001 — Run termination, routing parity, language data, and incomplete-portion detection

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-02A3`
- **Commits:** `b546384`, `e4c7a52`, `49cd2a6`, `95a5afc`, `d11feb8`.
- **Implemented:** Ctrl-C gracefully terminates an actively executing Run. Model routing on `0.02a3`
  matches main's no-data default override, including the reasoning-picker fix. CLDR locale-facts data
  and regional grammar-profile coverage expanded. WIP import detects
  incomplete (empty visible body) portions and no longer crashes on bad encoding.
- **Verification:** Covered by the commits' own regression tests; the full-suite result for this
  branch is recorded under `IMP-20261011-001`.

### IMP-20260925-001 — SQS service recovered and integrated on the SAGE side

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-SQS`
- **Commits:** `33368fc` through `847e298` (2026-09-18 to 2026-09-25).
- **Implemented:** Recovered the SQS service into `services/sqs/` and locked the integration
  decisions. Delivered integration plan Tasks 1–6: provider and execution-channel onboarding, language
  onboarding, recovery defect fixes and hardening, bounded rate-limit backoff, SAGE-side cache,
  validation, transport, discovery, qualification lookup, `sage model sqs-sync`, submission keys,
  provider bridge, list/run/submit orchestration, server-side submission review, and user-initiated
  language-profile validation requests. An end-to-end review fixed three findings, and the ingest
  watcher survives unreadable entries.
- **Verification:** SAGE-side SQS suites (`system/tests/test_sqs_*.py`): 104 passed. The
  `services/sqs/tests` suite needs its own environment and was not re-run. Deployment and acceptance
  remain open (`TODO-20261013-017`).

### IMP-20260917-001 — Shared workflow plumbing and legacy menu removal

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-02A3`
- **Commits:** `8d95a6c`, `6752cef`, `0960742`, `eeb9408`, `c2abc1f`, `236c487`, `49a8274`, `1d26b96`.
- **Implemented:** Migrated the legacy analysis Skills to RTC and STC with shared contracts. Centralized
  Scripture scope validation across workflow entry points. Folded NCA task create, execute, and submit
  onto the shared BIC, RTC, and STC helpers and gave NCA the shared guided scope picker. Removed the
  dead legacy compatibility menu, unified task-execution progress rendering, and made STC derive real
  coverage status. Recorded WIP update propagation as future architecture (`TODO-20260914-001`).
- **Verification:** Covered by the commits' own regression tests; the full-suite result for this
  branch is recorded under `IMP-20261011-001`.

### IMP-20260914-001 — First NCA implementation (superseded)

- **Version:** `0.02a3` (development branch)
- **Milestone:** `MS-02A3`
- **Commits:** `f31ce13` through `0eb6ce5` (2026-09-09 to 2026-09-14).
- **Implemented:** First governed NCA lifecycle: routed numeric evidence validation, style profiles,
  qualified reference packages, Operator menu and CLI flow, batched extraction with checkpoints and
  crash recovery, hybrid full-scope analysis, bridged-verse comparison, and number-usage reporting.
  Its analysis core was replaced by the `11a5176` rewrite recorded in `IMP-20261011-001`.
- **Verification:** Superseded behavior is not re-verified; current behavior is verified under
  `IMP-20261011-001`.

### IMP-20260909-02B1 — Full development branch promoted to Beta 1

- **Version:** `0.02b1`
- **Milestone:** `MS-02B1-QUALIFY`
- **Implemented:** Consolidated the complete `0.02a1` branch into the mainline checkpoint, including canonical VRS alignment across BIC/RTC/STC and Settings.xml-governed Scripture filename discovery and snapshot validation. Synchronized release identity and included NCA/SQS planning artifacts without activating those workflows.
- **Verification:** Targeted filename/snapshot checks passed against synthetic fixtures and the real 66-book faTMNv4 Project. The final checkpoint requires clean staged-source schema, package, audit and full-suite verification; source data and prior sealed Runs remain unchanged by the repair.

### IMP-20260903-003 — RTC/STC canonical identity and progress convergence

- **Version:** `0.01beta2`
- **Milestone:** `MS-BETA2-QUALIFY`
- **Implemented:** Made Reference Text Comparison (RTC) and Source Text Correspondence (STC) the owning identities for new Jobs, Runs, plans, ACT tasks, findings, events, diagnostics, model routes, reports, Skills, menus, and current documentation. Sealed pre-migration data remains readable through explicitly labeled legacy compatibility. Current progress renders as one live bounded row, and redirected output emits one milestone per stage without accumulated review-portion lines.
- **Verification:** Current-artifact, menu/error/report, Skill-routing, scope, bridge, legacy-read, package, schema, and source-audit regressions cover the identity boundary. The source audit now rejects reintroduction of the retired umbrella identity in current operating and Skill material.

### IMP-20260903-002 — Immutable RTC/STC bindings and complete Job deletion

- **Version:** `0.01beta2`
- **Milestone:** `MS-BETA2-QUALIFY`
- **Implemented:** Removed WIP replacement and RTC REFERENCE update from **Manage Job**. RTC/STC Project bindings are now rejected as immutable by Job persistence. Added **Delete Job** with a complete Job-work/controller-state scope, a separate default-preserve decision for published `reports/<job-id>/`, a final negative-default confirmation, and guaranteed preservation of SAGE Projects and Paratext files. Interactive busy/progress indicators now redraw in one bounded row and erase without adding scrollback lines.
- **Verification:** Storage and menu regressions cover RTC/STC binding immutability, complete Run/task/compiled-USJ/controller deletion, both published-report dispositions, Project preservation, and bounded non-stacking terminal status output.

### IMP-20260903-001 — Numbered-book RTC citation parsing corrected

- **Version:** `0.01beta2`
- **Milestone:** `MS-BETA2-QUALIFY`
- **Implemented:** Corrected semicolon-separated Scripture reference parsing so a repeated numeric USFM book code such as `1CH` is parsed as the next explicit book reference rather than mistaken for a chapter-only continuation. Both `1CH 5:1; 1CH 5:7-8` and the shorthand `1CH 5:1; 5:7-8` now normalize correctly.
- **Verification:** A numbered-book scope-set regression passes, and the exact archived RTC output previously rejected with `Unknown Scripture book: '1CH 1CH'` now validates all three findings against its unchanged sealed task manifest.

### IMP-20260902-001 — RTC versification differences made report-only

- **Version:** `0.01beta2`
- **Milestone:** `MS-BETA2-QUALIFY`
- **Implemented:** RTC planner V4 now distinguishes actual multi-coordinate WIP/REFERENCE source records from VRS mapping ranges. Actual source bridges remain indivisible; VRS ranges no longer join work-unit boundaries or raise an unsplittable-bridge error. Structural candidates that cross approved review portions are projected into each affected portion and remain visible to the governed structural stage and final Action Report.
- **Verification:** Planner and CLI regressions prove VRS ranges do not block slicing while genuine source bridges remain protected; composite-stage coverage proves one VRS candidate can cross two approved portions without losing exact structural coordinates. Full managed-runtime and release-gate verification remains required before promotion.

### IMP-20260831-001 — Cross-chapter RTC staging restored

- **Version:** `0.01beta2`
- **Milestone:** `MS-BETA2-QUALIFY`
- **Implemented:** Replaced the RTC progress path's misuse of strict coverage expansion with direct Scripture-scope containment, so an approved compact portion such as `GEN 32:1-33:20` can create its task from the plan's already sealed exact verse atoms. Strict coverage parsing remains unchanged. Structural-stage references are now normalized and sorted as numeric Scripture coordinates instead of lexically sorted labels. Approved multi-child stage creation also rolls back task and control records created by the unpublished attempt if a later child fails.
- **Verification:** Real cross-chapter approved-plan regressions prove exact RTC task coverage with and without structural adjudication, including verse numbers above nine, and a two-child failure regression proves no unregistered child task or control survives. The complete managed-runtime suite, schema/package gates, and source deep audit must pass on the final source.

### IMP-20260830-BETA2 — STC and Alpha hardening integrated into 0.01beta2

- **Version:** `0.01beta2`
- **Milestone:** `MS-BETA2-QUALIFY`
- **Implemented:** Merged the approved `alpha/0.02alpha1` development work into main while retaining the 0.01 release line; promoted the active identity to Beta 2; included independent SAW Source Text Correspondence, strict RTC source-referral admission, stable review-portion progress, and provider-neutral per-Skill routing with a universal no-data Medium fallback.
- **Verification:** The merged Beta source must pass the complete managed-runtime suite, schema/package gates, and deep source audit before this checkpoint is committed; exact-source release hardening and native acceptance remain separate promotion gates.

### IMP-20260828-ALPHA1 — 0.02alpha1 release line approved

- **Version:** `0.02alpha1`
- **Implemented:** Promoted the active development identity to Alpha 1 for the 0.02 line, retaining `public_release_ready=false`; synchronized STC, routed-SFM sizing, linguistic-profile governance, and BASIC/STANDARD/ADVANCED hardening policy as the release scope.
- **Verification:** Exact-source hardening, deterministic dual-build, checksum, extraction, and final artifact audits are required before the release record can close.

## 2026-08-28

### IMP-20260828-001 — STC, routed-SFM sizing, and universal linguistic specificity

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-REQUALIFY`
- **Implemented:** Added independent SAW Source Text Correspondence (STC) with WIP+PRIMARY-OL evidence only; unified BIC/RTC/STC work planning under the general deterministic SFM slicer; removed provider-handoff/controller material from Scripture sizing authority; routed complete canonical LANGUAGE_PROFILE and OL_AUTHORITY_PROFILE context through all bounded model-facing operations and secondary report translation; and retained future 0..n SECONDARY OL authority registrations as inert unless explicitly routed.
- **Verification:** Dedicated STC registration/task/finalization, SFM-slicer, RTC, language-specificity, OL-authority, BIC microtransaction, report-translation, schema/package, and deep-audit regressions enforce the architecture. Final exact-source release qualification remains governed by `RCLEAN-0.01beta-001` and its external hardening/checksum receipts.

## 2026-08-27

### IMP-20260827-002 — RTC bridge-safe slicing and atomic finalization

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-REQUALIFY`
- **Implemented:** Made canonical verse atoms authoritative for work-unit ownership and aggregation
  while retaining WIP/REFERENCE bridge labels as source metadata. RTC planner V2 now closes every
  proposed internal boundary across WIP bridges, REFERENCE bridges, and active local VRS
  equivalence spans before complete-package measurement. New stage plans persist per-unit atoms;
  legacy partition plans expand raw ranged keys deterministically during retry. Exact aggregate
  reconciliation remains fail-closed and now reports missing, extra, duplicate, ownership, and
  result-drift details. Routine Run preflight silently retains non-blocking VRS advisories instead
  of rendering them in the interactive UI.
- **Verification:** Regressions cover REFERENCE bridge boundary extension, atomic source-span
  metadata, legacy raw-bridge finalization, duplicate primary ownership, and silent-but-persisted
  VRS advisories. The complete test suite passes with two platform-dependent skips.

### IMP-20260827-001 — Job-owned canonical report-language enforcement

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-REQUALIFY`
- **Implemented:** Made primary report language required and Job-owned, retained secondary report
  language as optional downstream localization, and limited the global Operator language to the
  default snapshotted for new Jobs. Narrative-generating ACTs and provider schemas now bind the
  concrete Job language explicitly, canonical SAW findings record that authority, and a
  conservative post-response check performs at most one correction retry for a clear mismatch.
  Interface and secondary-language values are not sent as canonical narrative authority.
- **Verification:** Regression coverage proves existing Jobs keep their primary language, legacy
  Jobs receive one deterministic compatibility upgrade, missing ACT language blocks handoff, and
  clear Spanish narrative is rejected and retried before English canonical findings are written.

## 2026-08-26

### IMP-20260826-022 — Approved SAW verse-bridge plan reconciliation fixed

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-REQUALIFY`
- **Implemented:** Reconciled both the approved work-unit inventory and the current WIP inventory as
  atomic Scripture coordinates. An unchanged indivisible verse bridge such as `JHN 1:1-2` no longer
  produces a false `SAW_APPROVED_PLAN_STALE` result when runtime validation expands it to verses 1
  and 2. Genuine missing, extra, duplicated, or reordered coordinates still fail closed. The later
  RTC task separately seals `VERSE_BRIDGE_MAPPING` as a structure/completeness check and
  `VERSE_BRIDGE_CONTENT` as a translation/meaning check.
- **Verification:** The existing exact approved-partition regression passes, and end-to-end cases
  create the composite SAW RTC stage for a bridged WIP only, a bridged REFERENCE only, and both
  resources bridged, without rebuilding the valid approved plan.

### IMP-20260826-021 — Direct safe Project-removal action

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Promoted **Remove Project from SAGE** to the primary Scripture Projects menu while
  retaining the Project-detail action. The direct selector uses negative-default confirmation. When
  active or archived Jobs bind the Project, it lists them and requires explicit cascade confirmation
  before removing those Jobs, their Job-local data, and the Project inventory/mapping. It preserves
  the Paratext/PTLite folder, Scripture files, and root-level published reports.
- **Verification:** Menu regressions prove the action is directly visible, unbound removal preserves
  Scripture while clearing SAGE state, bound cascade removal requires explicit confirmation, and
  cancellation preserves the Project, mapping, and Jobs.

### IMP-20260826-020 — Self-contained governed Python bootstrap

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-REQUALIFY`
- **Implemented:** Added Python-free POSIX and Windows first-stage launchers. They detect the
  supported OS/CPU target, install exact CPython 3.12.14 from governed immutable URLs and SHA-256
  pins into `localdata/.system/runtime/python/`, build or repair the pinned environment under
  `localdata/.system/runtime/venv/`, and launch SAGE without system Python, Homebrew, or a copied
  virtual environment. A bootstrap failure now renders a **SAGE Runtime Installation Report** with
  the blocking reason and asks the Operator to **Install the SAGE Python runtime again** or **Exit
  SAGE**. Non-interactive launches emit the same report and exit with status 2.
- **Verification:** The macOS ARM64 artifact was downloaded, hash-verified, installed, and used to
  run SAGE under CPython 3.12.14. Launcher regression tests make `python`, `python3`, and `py` fail
  while proving SAGE uses its managed runtime; a real non-interactive boundary test pins the BLOCKED
  report and both actions. Cross-platform manifest, CMD/PowerShell, package, schema, and source-audit
  contracts pass. Native Windows, macOS Intel, and Linux artifact acceptance remains a release gate.

### IMP-20260826-019 — Workflow-owned Job-configuration rebuild fixed

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Moved **Rebuild Job configuration** from system recovery into the workflow-owned
  BIC and SAW Job-storage menus. Each action now rebuilds only that workflow's Jobs and reports the
  `job_id`; the former action had crashed while reading a nonexistent `project_id` from a Job.
- **Verification:** Regressions rebuild fixture BIC and SAW Jobs from their respective storage menus,
  verify runtime files and displayed Job IDs, and reject the action from system recovery.

### IMP-20260826-018 — Boxed classic-menu hierarchy and aligned footer

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Added shared Unicode presentation for classic menus: `╔═╗ / ║ / ╚═╝` for major
  headings, a `> `-prefixed label plus an unindented full-width `─` underline for minor headings, and
  `┌─┐ / │ / └─┘` for A-F footers, with one blank line before and after each block. Footer rows
  begin with two spaces before `A.`/`D.` to match numeric-choice indentation.
  Reference Text Comparison (RTC) and Configure AI now use the same renderer instead of private separator layouts.
  System Information is nested below its recovery-menu heading, with a single-line **System
  Actions** divider before the numbered operations. SAGE data folders are displayed as information
  inside that block instead of consuming a numbered action. The redundant **LLM status** subheading
  is omitted because the status rows already sit directly beneath **Configure AI**. Provider,
  model, and reasoning values appear only in those status rows; the numbered list contains concise
  change actions and rerenders the status after each change. When no model is explicitly pinned,
  changing reasoning uses and persists the concrete model resolved by the entry connection check.
  Cycle and explicit connection-check actions do not print intermediate values because the refreshed
  status block is the single state display. The nested configuration surfaces are explicitly named
  **Configure Hosted AI** and **Configure Local AI**; global `F. Status` reports both states.
  Configure Local AI limits its own summary to the enabled switch and configured model/install
  state; host/runtime metadata remains available through Status and diagnostic actions. The menu
  places enablement first, cycles Ollama start/stop in one position, delegates model installation
  to an extensible model-management submenu, refreshes after actions, and presents model source and
  integrity as information instead of an action. Secondary-language Jobs no longer block Local AI
  globally; only their Hosted-AI-dependent secondary rendering is rejected at the Job/report boundary.
- **Verification:** Menu presentation tests pin major/minor line styles, 72-column boundaries,
  blank-line separation, two-space footer keys, localization, and ANSI-free scrollback output.

### IMP-20260826-017 — Guided maintenance and governed out-of-box reset

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Removed the duplicate interface-language action from SAGE Maintenance because
  footer `D. Language` is globally available; moved Job-storage maintenance to BIC and SAW; merged
  system information with the system recovery/diagnostics panel; and added **Reset SAGE to
  out-of-box state**. The reset requires a negative-default confirmation plus exact `RESET SAGE`
  text, removes all local operating data and configuration, preserves `localdata/.system/runtime/` and packaged
  Core resources, writes a reset receipt, and exits for first-use Setup on relaunch.
- **Verification:** Isolated reset tests verify Project/Job/Run/report/profile removal, vanilla
  configuration reconstruction, packaged-profile restoration, managed-runtime preservation, receipt
  creation, and the revised menu ownership/localization contract.

### IMP-20260826-016 — Main navigation grouped by functional ownership

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Reduced Main to **Manage SAGE Scripture Projects**, **BIC**, **SAW**, and
  **SAGE Maintenance**. Reports and Job recovery now live under their respective BIC/SAW menus;
  system recovery, diagnostics, settings, paths, AI, and storage maintenance live under SAGE
  Maintenance. An uninitialized active Job no longer replaces Main with Manage Jobs; validation is
  deferred to workflow entry. Rebuilt affected labels across all six interface locales and aligned
  the experimental TUI navigation.
- **Verification:** Menu contracts reject top-level Reports/Recovery, require workflow-owned report
  and recovery routes, and pin the four-entry classic/TUI navigation grammar.

### IMP-20260826-015 — Continuous, non-blocking classic-menu flow

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Removed ANSI full-screen clearing between classic-menu forms and made routine
  completion pauses non-blocking. The terminal retains one continuous scrollback, with strong
  `=` title boundaries identifying each new form and no `Press Enter to continue...` prompts.
- **Verification:** TTY and captured-output contracts reject ANSI clear sequences, and a dedicated
  pause contract proves no prompt is printed and no input is consumed.

### IMP-20260826-014 — Audience-language recommendation for secondary reports

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Added a guided secondary-reporting-language chooser. It recommends the SAW WIP
  language or BIC TARGET language when distinct from the primary Operator language, and exposes
  explicit other-language and no-secondary choices. Rebuilt the changed menu text for all six
  interface locales.
- **Verification:** Menu persistence and localization contracts cover the recommendation, manual
  alternative, primary/secondary conflict boundary, and complete localized menu catalog.

### IMP-20260826-013 — All Job resource-assignment roles highlighted

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Extended angle-bracket role emphasis to all centralized Job Project assignment
  headings: BIC `<SOURCE>`, `<DONOR>`, `<TARGET>` and SAW `<WIP>`, `<REFERENCE>`. Rebuilt all five
  localization entries across the six interface locales.
- **Verification:** An AST contract inventories every `choose_or_add_resource()` call and requires
  the complete highlighted-role heading set, including future changes to this assignment path.

### IMP-20260826-012 — SAW chooser roles visually highlighted

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Changed the SAW Project chooser headings to `CHOOSE SAW <WIP>` and
  `CHOOSE SAW <REFERENCE>`, using angle brackets as deliberate visual role emphasis, and rebuilt
  the associated entry across all six interface locales.
- **Verification:** Localization contracts require the exact highlighted headings and the UI
  presentation contract defines their role-specific angle-bracket meaning.

### IMP-20260826-011 — Project loading no longer emits competency tables

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Removed the automatic model-competency registry lookup from successful Project
  registration. Adding or opening a Project now completes without provider probing or displaying a
  global language table; competency remains an explicit language action.
- **Verification:** A regression makes `ModelService` construction fail during Project registration
  and confirms the Project still registers without competency output.

### IMP-20260826-010 — Main-menu Project label simplified

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Replaced the redundant `Scripture Projects >> Manage SAGE Scripture Projects`
  Main-menu entry with `Manage SAGE Scripture Projects` and rebuilt the corresponding localization
  entry for all six supported interface locales.
- **Verification:** Menu, documentation, and localization contracts reject the former duplicated
  parent-context prefix.

### IMP-20260826-009 — Localization rebuild added to release tasks

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-REQUALIFY`
- **Implemented:** Added a mandatory pre-freeze task to rebuild every changed canonical menu phrase
  in the governed localization source, complete all six supported locale values, and reject missing,
  duplicate, blank, or stale changed-menu entries.
- **Verification:** Release Cleanup, Release Gates, Versioning Policy, and Menu Localization guidance
  require the rebuild and the complete `test_menu_localization.py` contract suite.

### IMP-20260826-008 — TUI marked experimental and unstable

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-TUI`
- **Implemented:** Added governed feature-maturity state `EXPERIMENTAL_UNSTABLE`, with exact display
  label `EXPERIMENTAL / UNSTABLE`, to the machine release definition and versioning policy. Bound
  the Textual TUI to it across the CLI, visible TUI header, Operator documentation, development
  status, package description, and roadmap. The classic menu and scriptable CLI remain authoritative.
- **Verification:** Documentation and CLI contract tests pin the warning so incomplete TUI parity
  cannot be presented as supported or authoritative during the Beta.

### IMP-20260826-007 — Project versioning policy

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-PM`
- **Implemented:** Added internal governance for canonical version spelling, Beta-to-RC promotion,
  release-state mapping, qualification gates, synchronized version surfaces, tags, artifact names,
  state reset, contract-version independence, and historical records.
- **Verification:** The PM inventory, vanilla manifest, project tree, and documentation contract all
  include the policy and pin the `0.01beta` → `0.01rc1` progression.

### IMP-20260826-006 — Version baseline reset

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-PM`
- **Implemented:** Reset current runtime, package, schema, documentation, test, release, and PM
  identity to `v0.01beta`, with `BETA` as the machine release state. Unpublished pre-Beta development labels are intentionally omitted from the group-testing distribution.
- **Verification:** Canonical version surfaces agree; compact `0.01beta` activates the governed
  pre-release boundary; existing operator localdata is preserved across Core/version updates; current documentation claims only Beta group-testing qualification and keeps production promotion gated separately.

### IMP-20260826-005 — Documentation grouped by audience and topic

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-PM`
- **Implemented:** Kept eight short daily-use Operator documents at the `docs/` root and moved
  technical material under `docs/advanced/`, grouped into architecture, projects/resources,
  workflows, models/AI, maintenance, release, and future-work topics.
- **Verification:** Documentation links, source path contracts, package inventory, deep-audit paths,
  and regression tests use the grouped layout. A contract test pins the compact root inventory and
  advanced topic set.

### IMP-20260826-004 — Internal development-record ownership

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-PM`
- **Implemented:** Moved Development Status, Next Development Work, and the project-management
  ledgers out of the Operator-facing `docs/` catalog and beside the changelog under
  `system/config/`.
- **Verification:** The Operator documentation index no longer exposes the internal records; the
  project tree, vanilla manifest, and PM documentation contract point to their new authority paths.

### IMP-20260826-003 — Standard release-cleanup checklist

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-PM`
- **Implemented:** Added a repeatable release-cleanup and evidence checklist covering scope freeze,
  active-data preservation, clean staging, forbidden artifacts, exact-source gates, deterministic
  packaging, native acceptance, handover, and milestone closeout.
- **Verification:** The checklist is linked from the internal PM index and recorded in the
  vanilla-install inventory and PM documentation contract.

### IMP-20260826-002 — Project-management ledger

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-PM`
- **Implemented:** Added governed Build Issues, TODO, Implemented Updates, and Milestones ledgers
  under `system/config/project-management/`, with stable identifiers and explicit links to version,
  changelog, release, status, and roadmap authorities.
- **Verification:** Documentation links and the vanilla-install inventory include the new governed
  files.

### IMP-20260826-001 — Consistent menu action grammar

- **Version:** `0.01beta`
- **Milestone:** `MS-BETA-UX`
- **Implemented:** Standardized operator-facing menu instructions on **Choose**, including BIC/SAW
  resource setup, Scripture scope, Runs, Language Profiles, AI settings, countries, localization,
  and operator documentation. State-reporting and internal API concepts remain technically named.
- **Verification:** 62 focused menu/localization/operator-UX tests pass. A regression test prevents
  standalone **Select** instructions from returning to menu literals.

## Entry format

Each future entry must include an ID, date, version, milestone, implemented outcome, and verification
evidence. Release-significant entries must also be summarized in the product changelog and release
notes.
