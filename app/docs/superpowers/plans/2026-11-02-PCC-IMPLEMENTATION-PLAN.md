# Phrase Consistency Checker (PCC) — implementation plan

**Status:** 2026-11-02: PO decisions D1–D6, D10 and D11 recorded (§3). P1a (backend skeleton) built; P1b (menu) next. No analysis code exists yet. Tracked as `TODO-20261102-001` (`0.02a3`,
`MS-02A3`); it supersedes ATT (`TODO-20261015-001`, `-002`).

**Handover:** `externaldata/pcc/MASTER_HANDOVER.md` and
`externaldata/pcc/SAGE_PCC_Stage1_Claude_Handover.zip`. The ZIP's SHA-256 is
`e78ffcda9763760bf3cb0f9de9c9e4f103f722dc8f6f69c4347fc0cfcd027079`, and all 55 of its internal
`FILE_CHECKSUMS.json` entries were verified. The master document is byte-identical to the copy in the
ZIP. The handover says it is a specification: its paths, commands and schemas are proposals, not
SAGE interfaces. This plan is its repository fit (`PCC_REPO_FIT`), taken from a read-only survey of
`main` at `acc0182`.

## 1. Product shape (PO, 2026-11-02)

PCC has **two functions** on one Job, one translation project:

| Function | When | Input | Output | For |
|---|---|---|---|---|
| **A. Terms list** (`pcc/terms`) | Project start, before any TARGET exists | Controlling SOURCE (+ optional secondary) | A ranked list of recurring SOURCE terms and phrases with senses, occurrences and blank rendering columns. The team's answers come back as the **project glossary**. | The translation team: a rendering guide |
| **B. Consistency check** (`pcc/check`) | Any time after drafting starts | Same Job + the WIP + the glossary | Forward and reverse findings (`PC00`–`PC25`), an occurrence audit and coverage | Operator / reviewers |

The two functions feed each other. This answers the handover's biggest practical gap:

- The handover's checker needs **approved TARGET renderings** (otherwise `PC00` cannot be reached,
  and uniform renderings stay `PC02`). It also needs **confirmed senses** (otherwise everything is
  `PC20`). Neither the handover nor SAGE supplies them.
- Function A is where a team naturally makes those decisions: "for *stand firm* (steadfast sense) we
  render X". Each decision becomes an approved, scoped variant rule. Function B then checks the WIP
  against those decisions, and against the renderings it observes where no decision exists.
- Function A can be re-run as the team adds `phrases.txt` entries. Decisions persist in the Job's
  journal across Runs.

**Low-resource languages (PO, 2026-11-02).** Both functions must work for TARGET languages with
minimal language data in the LLM. No step on the deterministic path uses an LLM or an external
resource for the TARGET language. Whatever varies by language is learned from the Job's own texts or
supplied by the team, never chosen by language code (§7).

## 2. Critical comparison with ATT (summary)

PCC is the governing contract. It fixes ATT's two worst flaws: ATT has no sense model ("light" for
weight and "light" for illumination become one group), and ATT treats the majority rendering as
correct. This plan keeps four things from ATT:

1. **Rendering distribution as evidence.** Every `PC10` shows the observed TARGET renderings with
   counts and references (ATT's dominant rendering and outliers). It is evidence only, never a verdict.
2. **SOURCE-side related forms.** PCC groups only on exact normalized wording, so "stand firm",
   "stood firm" and "standing firm" are separate groups. The terms list and report show related
   groups together, but never merge their obligations (PCC `SRC07`).
3. **Names in the terms list.** A team needs name guidance. In Function B, name groups are
   SOURCE-anchored; STC's MACULA name check is OL-anchored. They do not duplicate each other, and the
   report says which one applies.
4. **Co-authoritative references** stay a possible later stage. Stage 1 offers single SOURCE and
   primary + secondary only, so `PC24` cannot arise at run time (see D7).

## 3. Decisions

| ID | Decision | Recommendation | State |
|---|---|---|---|
| D1 | Two functions, terms list + consistency check | — | **DECIDED** (PO 2026-11-02) |
| D2 | May OL (MACULA) be **sense evidence**? The handover bans OL inside PCC. | **Yes, evidence only, never authority** (deviation from handover invariant 2): same SOURCE wording aligned to one consistent OL lemma confirms the sense under rule `SENSE-OL-LEMMA`; diverging lemmas split the group; ambiguity → `PC20`. Uses only the CC BY 4.0 fields (`lemma`, `strong`, morphology, `subjref`/`participantref`). | **DECIDED** (PO 2026-11-02) |
| D3 | Restricted MACULA fields (Louw-Nida `ln`/`domain`, SDBH `*domain`), which are real sense IDs | **Never used.** Sense evidence is CC BY lemma data only. Hebrew `sensenumber` (unverified provenance) is excluded too. | **DECIDED** (PO 2026-11-02) |
| D4 | Terms-list format for teams | Markdown (read) + XLSX (fill in renderings, re-import with validation and hashing). `openpyxl` is already a runtime dependency, so this is a deviation from the handover's "JSON/JSONL/MD/TXT only" (output format, not storage). | **DECIDED** (PO 2026-11-02) |
| D5 | Shipped SOURCE phrase indexes | BSB (public domain) ships in `app/system/resources/phrase-index/<date>/`. An NIV index is **built locally only** into `localdata/inputs/resources/phrase-index/<id>` and never committed (public repo; NIV fair-use limit). Other SOURCE editions are built locally the same way. | **DECIDED** (PO 2026-11-02) |
| D6 | Menu name and placement | Main Menu **#6 "Phrase Consistency Checker (PCC)"** after NCA; SAGE Maintenance moves to #7. The terms list is a sub-option inside PCC. Workflow ID `pcc`. | **DECIDED** (PO 2026-11-02) |
| D7 | Two equally authoritative SOURCEs | Not offered in Stage 1. Job validation rejects an unresolved authority, so `PC24` becomes a Job-creation error, not a Run finding. | Recommended |
| D8 | Contract format | SAGE YAML contracts (`config/schemas/*.schema.yml`) with hand-written validators, as for all other workflows. The handover's JSON Schema 2020-12 files are kept as test fixtures and validated in tests only (`jsonschema` stays dev-only). | Recommended |
| D9 | Blocking codes vs "never hard-block" | `PC25` (integrity) may stop a Run. `PC23` marks only its group `NOT_ASSESSED` + exception report. Content problems are never blocking. | Recommended |
| D10 | Paratext Biblical Terms / TermRenderings interop | **Read-only import in P5.** Existing renderings become *proposed* glossary entries the Operator confirms; SAGE never writes back to Paratext. Biblical Terms are keyed by OL lemma, so mapping them onto PCC SOURCE expressions uses the D2 lemma alignment. | **DECIDED** (PO 2026-11-02) |
| D11 | Low-resource TARGET languages with minimal LLM data | No LLM or TARGET-language resource on the deterministic path; language traits measured from the WIP; checks qualified per WIP (§7) | **DECIDED** (PO 2026-11-02) |

## 4. Repository fit: what exists and what PCC must add

### Reuse

| Need | Existing seam |
|---|---|
| Job/Run lifecycle | `jobs.py` (`Job`, `Run`, `JobStore`), `workflow_identity.py`, `job_menus.py` standard Job screens, `registry.py` `WorkflowSpec` + `app/ecosystem.yml` |
| Read-only project text | `scripture.compile_project` → `usj.py` verse records → `work_units.EvidenceRecord`; `usj.visible_text` already drops notes, cross-refs, figures and headings (PCC `SRC10`) |
| Separate body/notes/headings streams with code-point offsets | `numbers/target.py` (`target_units`, `TargetNote`), the pattern to follow for PCC offsets |
| Versification and verse mapping | `vrs.py`, `versification_service.py`, `verse_alignment.ProjectVerseIndex` / `align_records` (`COORDINATE` / `EQUIVALENCE_GROUP`) |
| Rendering learning, inflection, folding | `name_alignment.py`: `fold`, `words`, `is_unspaced`, `stems`, learned suffixes, IBM Model 1 EM alignment, cached by SHA-256 |
| Deterministic candidate → model verdict | `candidates.py` (`CONFIRM` / `REJECT` / `UNSURE`) for any advisory model step |
| Pinned immutable packages | `numbers/resources.py` + `numbers/reference.py` pattern: `MANIFEST.json`, `CHECKSUMS.sha256`, Core pin file, load-time errata keyed by package |
| MACULA (D2) | `ol_analysis.load_ol_analysis` (pinned `SAGE_OL_ANALYSIS_2026-10-15`, lemma/strong/gloss/morphology); `numbers/index_build/versify.py` for MACULA versification |
| Decision receipts | `grammar_governance.record_grammar_profile_review` (hash-bound, supersede-never-delete), `bic_memory.py` state transitions, `state.append_event` (fsync'd JSONL) |
| Atomicity / locking | `atomic.py`, `locking.WorkspaceLock`, `transactions.FileTransaction` |
| Coverage honesty | `coverage.py` (`NOT_ASSESSED`, never manufacture an all-clear), `exception_reports.py` |
| Reports | `report_authority.py` (`localdata/reports/<job>/<BOOK>/<CCC>/`, `JOB-SUMMARY.md`, authority header), `human_output.py` labels, `report_translation.py` |
| Synthetic evaluation | `tools/evaluate_name_alignment.py` (plant, relearn, measure recall); NCA release gate method (`docs/advanced/release/NCA-RELEASE-GATE.md`) |

### Missing (PCC builds)

1. **SOURCE authority on a Job.** There is no Translation Brief; every Job binds exactly one project
   per role. Add the `pcc` bindings `source: exactly_one`, `secondary_source: zero_or_one`,
   `wip: zero_or_one`. Function A needs no WIP; Function B requires one. The SOURCE must differ from
   the WIP (`_validate_analysis_role_separation`).
2. **A segmenter with offsets.** There is no tokenizer and no ICU. Build `pcc/segment.py` from the
   `name_alignment` helpers: NFC, letter-run tokens, Unicode code-point offsets into the visible body
   text, and a profile-driven case mode. Diacritics are never stripped by default. Unspaced scripts
   report `segmentation: PARTIAL` and limit claims (AT26).
3. **Sub-verse alignment.** Alignment exists only at verse and bridge level. PCC locates TARGET spans
   inside the mapped verse(s) (§6 B2). When it cannot, the result is `PC21`, never `PC11`.
4. **A finding decision mechanism.** SAGE has no way to accept or reject a finding. PCC adds a
   Job-level append-only journal plus a rebuildable materialized rule view (handover doc 04).
5. **Phrase matching.** There is no Aho-Corasick or trie. Add a token-sequence trie over normalized
   tokens (standard library only).

### Touch list (from NCA's precedent)

`registry.py`, `workflow_identity.py`, `jobs.py` (`TOOL_IDS`, Job-ID regex, defaults validation),
`job_menus.py`, `menu.py` (D6), `ui_services.py`, `cli.py` (`task create|execute|submit`),
`act_common.py` (`ACT_OPERATIONS["pcc"] = {"terms", "check"}`), `act_tasks.py`, `act_submit.py`,
`llm_tasks.py` (only if an advisory model step ships), `evidence_policy.py`, `profiles.py`,
`execution_events.py` (`PCC_*` reason codes), `exception_reports.py`, `human_output.py`,
`job_snapshots.py`, `schema_validation.SCHEMA_OWNERS`, `validation.py` required files. Also
`config/workflows/pcc/profile.yml`, `app/ecosystem.yml`, schemas `job` / `run` / `act-task` /
`act-control` / `workflow-profile`, and `localization/menu-localization.json`. The experimental TUI
leaves PCC out, as it does NCA. Job ID: `PCC-<SOURCE>_<date>`, or `PCC-<WIP>_<date>` once a WIP is
bound (decide in P1).

### Storage mapping (handover → SAGE)

| Handover path | SAGE location |
|---|---|
| `resources/phrase-indexes/` | `app/system/resources/phrase-index/<YYYY-MM-DD>/` (BSB only) + pin `app/system/config/phrase-index-reference.json`; local builds in `localdata/inputs/resources/phrase-index/<id>/` |
| `resources/language-profiles/` | Extend `config/profiles/grammar/<tag>/wip.yml` contracts with a PCC capability block, or add a sibling `pcc` profile; decide in P2 |
| `input/phrases.txt` | `localdata/work/jobs/pcc/<job>/input/phrases.txt` (one file; a single-token line is a term) |
| `config/phrase-check.json` | Job defaults in `job.yml` + sealed Run snapshot (NCA `build_nca_run_snapshot` pattern) |
| `data/phrase-check/` | `localdata/work/jobs/pcc/<job>/state/` (glossary journal, materialized rules, cached discovery) |
| `output/phrase-check/<run>/` | Run root `validation/` (machine JSON/JSONL) + `localdata/reports/<job>/` (Markdown, XLSX terms list) |

## 5. Function A — terms list

**A1. Load.** Compile the SOURCE (and secondary) body text for the Job scope. Load the pinned index if
one exists for that exact edition and hash. Load `phrases.txt`. An index built for another edition
gives **candidates only**, which must be re-verified against the actual SOURCE (`SRC04`, AT30).

**A2. Discover.** Candidates come from three places:

- the curated index;
- `phrases.txt`, where a phrase not found in the SOURCE is reported, never dropped (AT30);
- normalized 1–6 token n-grams within a verse, frequency ≥ 2, ranked by distinct-verse count and
  distinctiveness, with a stoplist per language profile.

Nested phrases are kept as separate evidence with a display dedupe map (AT21). Occurrences carry the
handover's occurrence fields, with `offset_units: UNICODE_CODE_POINT` over the visible body text.

**A3. Sense evidence (D2, D3).** CC BY lemma fields only:

- Align SOURCE tokens to MACULA lemmas per verse, generalizing the IBM Model 1 aligner (BSB first;
  any SOURCE works, since alignment is learned, not supplied).
- Identical wording with one consistent lemma family gets `CONFIRMED` sense via `SENSE-OL-LEMMA`.
- Divergent lemmas split the group into senses keyed `SENSE-<lemma-set-hash>`.
- Weak alignment, or a lemma the curated index flags as polysemous (e.g. πνεῦμα spirit/wind), gives
  `UNRESOLVED` → `PC20`.

Curated entries keep their curated senses. A team decision (`RECLASSIFY_SENSE`) overrides lemma evidence for that occurrence, and is recorded in the journal.

**A4. Output.**

- `TERMS-LIST.md` + `TERMS-LIST.xlsx`, by category (term, fixed phrase, formula, idiom, name). Each
  row shows wording, sense label (OL lemma shown as evidence), occurrence and distinct-verse
  counts, book spread, three example references, related forms, and blank columns: *chosen
  rendering(s)*, *scope*, *notes*.
- Machine `expressions.jsonl` / `occurrences.jsonl` in the Run.
- Reports quote references, not long SOURCE passages. NIV is never quoted beyond the fair-use limit.

**A5. Glossary import.** The Operator imports the filled XLSX (or answers in the menu).

- Each row is validated: the expression and sense exist, the hash of the terms list it answers is
  unchanged, and the scope is legal.
- Each row becomes a `review_event` (`APPROVE`, `REJECT`, `CONTEXT_ONLY`, `RECLASSIFY_SENSE`) in the
  Job journal, with the actor and evidence.
- A malformed row is reported with its row number and the reason, and is never silently skipped. The
  rest still imports (never hard-block).

## 6. Function B — consistency check

**B1. Groups.** Rebuild the confirmed groups (SECGs) from the current SOURCE hash and the journal.
Fewer than two confirmed occurrences → `INFORMATIONAL` (AT16). A SOURCE hash change marks dependent
decisions `STALE` (AT13).

**B2. Locate the TARGET span** inside the VRS-mapped verse(s), in this order:

- (a) approved renderings from the glossary, with learned TARGET inflection (the `name_alignment`
  suffix learning generalized from names to rendering tokens);
- (b) otherwise, renderings learned by EM across the group's occurrences, which give the observed
  distribution;
- (c) neither, with reliable alignment → `PC11` candidate;
- (d) unreliable alignment → `PC21` (AT12).

**B3. Classify** with the handover's decision logic (doc 02 sample). Protected features (negation,
polarity, agency, number) are checked only where the profile declares the capability. Where it does
not, the outcome is review, never pass (AT26, doc 14). Identical but unapproved forms → `PC02` (AT27).

**B4. Rule resolution.** Specificity order: occurrence > passage > group (SECG) > language profile.
A more specific `REJECT` wins. Equal-scope conflict → `PC23` for that group only. `PROPOSED`,
`REVOKED` and `STALE` rules never accept (AT14, AT23, AT24).

**B5. Reverse scan.**

- For every approved or learned TARGET rendering, scan TARGET verses outside its group.
- Check other SOURCE support: another group or SOURCE expression maps to that rendering there; with
  D2, also an OL `subjref` / `participantref` for an added referent.
- What remains is a `PC12` review candidate with lower confidence (AT08, AT09).
- A `PC12` and a forward `PC11` on the same problem share an `issue_cluster_id` (AT29).

**B6. Optional advisory model.** Off by default. If enabled later, it adjudicates `PC10` / `PC13` /
`PC12` candidates through `candidates.py` verdicts with SAGE receipts. It can never write rules
(handover invariant). This is a separate later milestone, not part of the deterministic Stage 1
critical path. It runs only under the competency gate in §7 L6.

## 7. Low-resource languages (D11)

Rule: what PCC knows about the TARGET language comes from three places only. It is measured from the
WIP, declared by the team, or not checked, and the report says which. This follows the rule already
set for the name check (`TODO-20261016-001`): branch on traits measured in the WIP, not on language
codes.

**L1. Measured traits, no profile required.** Each check Run measures these from the WIP and records
them in the Run snapshot:

- script, and whether the text is spaced or unspaced (`name_alignment.is_unspaced`);
- the letter and punctuation inventory, including apostrophe-like code points used as letters
  (U+0027, U+2019, U+02BC, U+A78C);
- learned suffixes and prefixes (prefix learning per `TODO-20261016-003`, for Bantu noun classes)
  and frequent clitics.

Unlike RTC, a PCC Job does **not** require a grammar profile for the WIP language. An existing profile
in `config/profiles/grammar/<tag>/` is used where present, but nothing depends on one.

**L2. Team-declared language facts (optional).** A short sheet, filled in alongside the glossary
import (P5):

- negation markers or affixes;
- which apostrophe or glottal-stop code point is correct;
- declared spelling variants;
- word-break conventions.

These facts switch on the negation part of `PC13` and approved orthographic equivalences. Without
them those checks are reported `NOT_CHECKED`, never assumed. This is product configuration by the
team, not evaluation labelling.

**L3. Spelling variation is its own class.** Low-resource orthographies are often unsettled, so
PCC sorts a difference into one of three kinds:

| Difference | Reported as |
|---|---|
| Only a team-declared spelling equivalence, a confusable code point, or edit distance 1 on a learned stem | `PC10` subkind `ORTHOGRAPHIC`, low severity (ATT's `ORTHOGRAPHIC_VARIANT`) |
| Only a learned inflection | Accepted as a morphological variant of an approved rendering (`TGT02`) |
| Anything else | `PC10` rendering variation |

Nothing is normalized away unless the team approved it; diacritics are never stripped by default.

**L4. Self-qualification per WIP.** Each check Run plants synthetic substitutions and removals into
an in-memory copy of the WIP's own text, runs the matcher, and measures recall per kind (the
`evaluate_name_alignment.py` method; one extra cached pass). Where measured recall is below the bar
(proposed 80%, set in P6), that kind is reported `NOT_CHECKED` with the measured recall. This covers
small WIPs (one book early in drafting), unusual morphology and unspaced scripts automatically,
without per-language code.

**L5. Too little parallel text.** A group whose verses give too little alignment evidence gets
`PC21`, never `PC11`. The evidence minimum is measured in L4, not fixed.

**L6. LLM competency gate.** The optional model step (B6, P10) runs for a finding only when
`model_language_competency` rates the TARGET language at least `GOOD` for the selected model, and the
route is qualified. Otherwise the step is skipped and the report says so (e.g. "model review not used:
competency UNASSESSED"). The finding still stands as deterministic review.

**L7. Sense evidence does not depend on the TARGET.** MACULA lemma alignment (D2) works for any
SOURCE language without an LLM. Sense quality is then the same for every TARGET language, which is
a further argument for D2.

**L8. Reports.** Written in the Operator's language. TARGET strings are quoted verbatim with
references. No LLM-written explanation of what TARGET wording means.

## 8. Phases

Each phase leaves tests green and updates this plan. The handover's M0–M8 map as shown.

| Phase | Scope | Handover | Gate |
|---|---|---|---|
| **P0** | This plan; PO decisions D2–D6 | M0 | Decisions recorded |
| **P1** | `pcc` tool skeleton: ecosystem, profile, Job bindings, Job ID, menu entry (D6), YAML contracts + validators for all handover records (D8), deterministic IDs, Run snapshot, journal writer | M1 | Synthetic Job creates and runs empty end to end; handover samples validate in tests; no new runtime dependency |
| **P2** | `pcc/segment.py`, normalization, offsets, capability matrix; trie matcher; measured WIP traits (§7 L1) | M2 (part) | Unicode NFC/NFD equivalence, offsets reconstruct spans byte-exact, unspaced → `PARTIAL`; traits measured identically for fabricated spaced, unspaced, prefixing and apostrophe-letter fixtures |
| **P3** | Function A discovery + local list + index builder tool (`tools/build_phrase_index.py` with a byte-identical `verify` mode, like `build_ol_analysis.py`); BSB package (D5) | M2, doc 13 | Reproducible counts; every occurrence traces to raw SOURCE; package checksums verified on load |
| **P4** | Sense evidence (D2 path or curated-only) + grouping | M3 | AT03, AT11, AT16, AT22; no cross-sense obligation |
| **P5** | Terms-list Markdown/XLSX + glossary import into the journal + optional language-facts sheet (§7 L2); read-only Paratext TermRenderings import as proposed entries (D10) | new (D1, D4, D10, D11) | Round trip: export → fill → import → materialized rules; malformed rows reported with row numbers |
| **P6** | Function B forward: span location, rendering learning with learned affixes, `ORTHOGRAPHIC` subkind, per-WIP self-qualification (§7 L3–L5), classification, occurrence audit, coverage | M4 | AT01, AT02, AT04–AT07, AT10, AT12, AT25–AT27; every eligible occurrence has a disposition |
| **P7** | Rule resolver: specificity, `REJECT`, `STALE`, `PC23` | M5 | AT13, AT14, AT23, AT24; every acceptance names its rule |
| **P8** | Reverse scan + clusters | M6 | AT08, AT09, AT29 |
| **P9** | Reports in SAGE conventions, `PCC-CHEAT-SHEET.md`, Operator guide, known limitations, third-party notices; full acceptance AT01–AT30 + Function A tests; benchmark on a whole Bible | M7, M8 | Handover acceptance checklist complete or deviations accepted |
| **P10** (later) | Optional advisory model step with qualification | M6 (assisted) | Qualified route; never approves |

### P1a as built (2026-11-02)

- `sage/pcc/`: `contracts.py` (all handover record contracts restated in the JSON Schema subset they
  use, plus `job_defaults` and `run_snapshot`; tests cross-check every sample and its mutations
  against the handover schemas with `jsonschema`); `ids.py` (namespaced SHA-256 IDs, collision
  guard); `jsonl.py` (strict UTF-8 JSON/JSONL, duplicate keys and NaN rejected, file+line errors,
  sorted atomic writes); `journal.py` (append-only, hash-chained decision journal at
  `<job>/glossary/review-journal.jsonl`; edits or reordering fail closed); `run.py` (sealed
  `validation/pcc-run-snapshot.json`; execution re-checks SOURCE, secondary, WIP and decision hashes
  and stops on change with `PCC_RUN_INPUT_STALE`; P1 writes schema-valid empty outputs, status
  `COMPLETE_WITH_EXCEPTIONS` and a `PCC_ANALYSIS_NOT_IMPLEMENTED` / `NOT_ASSESSED` exception report).
- Job contract: bindings `source` (REFERENCE role, LOCKED), optional `secondary_source`
  (AUXILIARY_SCRIPTURE), optional `wip`; all distinct. Defaults: immutable `target_language`
  (must equal the WIP's language), discovery thresholds, analysis flags (`semantic_assistance` only
  `OFF`). No grammar profile (D11). Job ID `PCC_<SOURCE>-<WIP or target language>`. Operations
  `terms` and `check`; one open Run per Job; a check needs a WIP.
- Shared wiring: `workflow_identity`, `jobs`, `registry`, `profiles`, `schema_validation`,
  `validation`, `app/ecosystem.yml`, `config/workflows/pcc/profile.yml`,
  `config/schemas/pcc-run-snapshot.schema.yml`, `job.schema.yml`, `workflow-profile.schema.yml`,
  the vanilla install manifest, and the shared test workspace.
- Deviations recorded for later phases: a WIP can be bound only at Job creation (Job bindings are
  immutable in SAGE); attaching one later is a P6 item, and the Job ID would then still name the
  target language. `OPERATOR_WORKFLOWS` (menus and UI listings) is left for P1b.
- Tests: `tests/pcc/test_pcc_p1.py`, 41 tests; three deliberate code breaks (validator, journal
  chain, stale-input guard) were each caught. Full suite: 2370 passed, 2 failed; both failures are
  local-environment artifacts outside the repo's tracked files (an untracked file in the git-ignored
  `project-management/private/`, and a `system/tools/__pycache__` from 2026-10-29).

P1–P6 form a usable first slice: a team can get a terms list and a forward check. The handover says
Stage 1 is not complete without governance (P7) and the reverse scan (P8).

## 9. Evaluation (no hand labelling)

- **Golden fixtures:** the handover's synthetic corpus (4 scenarios) plus new fabricated fixtures for
  every AT case. No real Scripture in tests.
- **Planted errors on real WIPs** (the `evaluate_name_alignment.py` method):
  - pick groups with a uniform rendering;
  - plant a substitution (`PC10`), a removal (`PC11`, or `PC21` when alignment breaks), a negation flip
    (`PC13`, where the profile supports it), and an inserted rendering elsewhere (`PC12`);
  - measure recall per kind;
  - receipts hold coordinates only, and WIP text stays in `localdata/.system/`.
- **False-alarm rate:** a seeded stratified sample of `PC10` / `PC12` findings on unplanted WIPs,
  judged by two LLMs that must agree (NCA gate method, Wilson intervals, `INSUFFICIENT_EVIDENCE`
  outcome).
- **Low-resource set:** planted-error recall is language-independent, so it runs on WIPs whose
  languages the selected model rates `FAIR` or `UNASSESSED`. Choose them from the local Paratext
  collection: at least one Bantu prefixing language (e.g. swhNEN14), one unspaced script and one
  agglutinative language. Release gate: recall bars hold on this set, not only on major languages.
- **No LLM-judged precision where the judge doesn't know the language.** Two-LLM false-alarm judging
  runs only for languages rated `GOOD` or better. For the low-resource set, report the review workload
  (findings per 1,000 verses) and planted recall, and state "precision not measured" in
  `KNOWN-LIMITATIONS.md`.
- **Function A quality:** an LLM-judged sample of discovered candidates ("would a translation team
  want this on the list?"). MACULA cannot score sense splits, because it is their input (D2). Instead, two LLM
  judges review a seeded sample of splits and merges in SOURCE context. The SOURCE is a gateway
  language, so the judges are competent there.
- **Benchmark:** runtime, peak memory, candidate count and review workload per Bible, recorded in the
  docs. No promised service levels.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Discovered n-grams flood the list | Distinctiveness + stoplist + distinct-verse ranking; curated and local entries are never pruned; the list is paginated by category |
| Reverse scan false alarms | Review-only, low confidence, other-SOURCE-support check first; measured false-alarm rate before release |
| TARGET morphology (agglutinative, prefixing, unspaced) | Learned suffixes; prefixes per `TODO-20261016-003`; capability-gated `PARTIAL` outcomes rather than claims |
| Low-resource language: unsettled spelling floods `PC10` | `ORTHOGRAPHIC` subkind at low severity; team-declared spelling equivalences (§7 L2–L3) |
| Low-resource language: too little drafted text to learn from | Per-WIP self-qualification reports `NOT_CHECKED` with measured recall instead of guessing (§7 L4–L5) |
| NIV text leaking into the public repo | Local-only builds; tests use fabricated text; a release-builder check that no `phrase-index` package outside BSB is committed |
| Journal grows inconsistent with the SOURCE | Hash-bound decisions, `STALE` on change, materialized view rebuilt from events |

## 11. Next step

All product decisions are recorded. D7–D9 are technical defaults adopted unless the PO objects. Start P1.
