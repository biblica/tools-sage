# Phrase Consistency Checker (PCC) — implementation plan

**Status:** 2026-11-02: PO decisions D1–D6, D10 and D11 recorded (§3). P1a (backend skeleton), P1b (menu) and P2 (segmenter, trie, traits) P3a (discovery, index packages, builder tool) and P4 (sense evidence, groups) built. P3b (shipped BSB package) is open, see below. No consistency analysis exists yet. 2026-11-25: reference lists split from the Job and rebuilt top-down from OL concepts (D12–D20, §5b, review §5b.7); P5b-R (PCC original-language package), P5b-0 (aligner), P5b-1 (RL packages), P5b-2 (top-down build), P5b-3 (Job pin, terms Run from the list), P5b-4 (list workbook), P6 (forward check), P7 (rule resolver and decisions) and P8 (reverse scan and issue clusters) built; P5b-5..7 open. Tracked as `TODO-20261102-001` (`0.02a3`,
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
| D3 | Restricted MACULA fields (Louw-Nida `ln`/`domain`, SDBH `*domain`), which are real sense IDs | **Never used.** Sense evidence is CC BY data only. **Revised 2026-11-25:** the MACULA licenses (macula-greek `LICENSE.md` item 3, macula-hebrew `LICENSE.md` item 10) state that Clear's word senses (Greek `sources/Clear/wordsense`, Hebrew `@sensenumber`) are distinct from the UBS senses and covered by Biblica's CC BY grant, so they are now **allowed as OL-side sense evidence** (shipped in `SAGE_PCC_OL`). The UBS fields (`ln`, `domain`, `sdbh`, `lexdomain`, `coredomain`, `contextualdomain`) stay never read | **DECIDED** (PO 2026-11-02); provenance correction 2026-11-25 |
| D4 | Terms-list format for teams | Markdown (read) + XLSX (fill in renderings, re-import with validation and hashing). `openpyxl` is already a runtime dependency, so this is a deviation from the handover's "JSON/JSONL/MD/TXT only" (output format, not storage). | **DECIDED** (PO 2026-11-02) |
| D5 | Shipped SOURCE phrase indexes | BSB (public domain) ships in `app/system/resources/phrase-index/<date>/`. An NIV index is **built locally only** into `localdata/inputs/resources/phrase-index/<id>` and never committed (public repo; NIV fair-use limit). Other SOURCE editions are built locally the same way. | **DECIDED** (PO 2026-11-02) |
| D6 | Menu name and placement | Main Menu **#6 "Phrase Consistency Checker (PCC)"** after NCA; SAGE Maintenance moves to #7. The terms list is a sub-option inside PCC. Workflow ID `pcc`. | **DECIDED** (PO 2026-11-02) |
| D7 | Two equally authoritative SOURCEs | Not offered in Stage 1. Job validation rejects an unresolved authority, so `PC24` becomes a Job-creation error, not a Run finding. | Recommended |
| D8 | Contract format | SAGE YAML contracts (`config/schemas/*.schema.yml`) with hand-written validators, as for all other workflows. The handover's JSON Schema 2020-12 files are kept as test fixtures and validated in tests only (`jsonschema` stays dev-only). | Recommended |
| D9 | Blocking codes vs "never hard-block" | `PC25` (integrity) may stop a Run. `PC23` marks only its group `NOT_ASSESSED` + exception report. Content problems are never blocking. | Recommended |
| D10 | Paratext Biblical Terms / TermRenderings interop | **Read-only import in P5.** Existing renderings become *proposed* glossary entries the Operator confirms; SAGE never writes back to Paratext. Biblical Terms are keyed by OL lemma, so mapping them onto PCC SOURCE expressions uses the D2 lemma alignment. | **DECIDED** (PO 2026-11-02) |
| D11 | Low-resource TARGET languages with minimal LLM data | No LLM or TARGET-language resource on the deterministic path; language traits measured from the WIP; checks qualified per WIP (§7) | **DECIDED** (PO 2026-11-02) |
| D12 | Where the SOURCE phrase list lives | **A Reference List (RL) is its own versioned, immutable package, built for one REFERENCE edition, independent of any Job** (§5b). Any Operator builds RLs on their own SAGE instance and may export and import them as files. Sharing between Operators happens outside SAGE and SAGE does not manage it. | **DECIDED** (PO 2026-11-25) |
| D13 | Stable identity of list entries and decisions | Entries are **concepts** (D18). `concept_key` is language-neutral wherever the OL allows:

- `H("OL", lemma key, sense)` for a key-term lemma;
- `H("BT", term id)` for a Biblical Terms multi-word term;
- `H("OLSEQ", lemma sequence)` for a seed-list concept;
- `H(language_tag, normalized wording)` only for a declared phrase with no OL anchor.

Book scope, discovery settings, RL version and reference are **not** in the key, so decisions carry across scopes, RL versions and (through inherited curation) references. SOURCE wordings are realizations under a concept. Glossary rules are keyed by `concept_key`; scope is a rule attribute. This replaces the scope-bound `group_id` of P4. No migration (PCC is alpha; clean instance). | Recommended |
| D14 | How an RL is built | **Revised 2026-11-25 (§5b.7).** The build is top-down from OL concepts: **align** the reference to the OL word by word → take the concept **inventory** → **realize** each concept occurrence as the aligned reference span → **partition senses** (D19) → **select** recurring ones (D17). Deriving from another RL means **inheriting its curation** (KEEP / DROP, declared phrases, notes) by `concept_key`; no wording pivot is needed. `RELOCATE` remains only for declared phrases without an OL anchor. `MERGE` applies the Operator workbook. Inherited and derived entries are always `PROPOSED`. *Superseded:* SCRATCH via n-gram discovery and the Jaccard `PIVOT` of §5b.3 | Recommended |
| D15 | Operator editing of an RL | An RL workbook (XLSX), separate from the glossary workbook: export → edit → import creates a **new version** plus a diff report, applied row by row by `concept_key`. The global core-list overlay (`overlay.py`) moves into RL versions. | **DECIDED** (PO 2026-11-25: XLSX import/export) |
| D17 | What is traced | **Only recurring key terms and concepts. Common words are ignored** (user feedback, 2026-11-25). An entry is traced only when all three hold: **(1) anchor:** its confirmed OL lemma is on a key-term inventory, or the Operator added or kept it (phrases.txt, RL workbook); **(2) recurrence:** at least 3 distinct verses in the reference (RL build setting); **(3) shape:** a multi-word entry must be a semantic identity (D18); nested wordings fold into their concept. Everything else is left out of the list and counted in the "left out" summary. See §5b.5. **Inventory revised 2026-11-25 (§5b.7):** Paratext Biblical Terms when the Operator imports it, otherwise the shipped SAGE **Key Concepts** package (single- and multi-lemma, D18 S4b). The content-word fallback and the frequency ceiling are dropped, because measurement showed neither separates key terms from common words | **DECIDED** in principle (feedback); thresholds recommended |
| D19 | Senses inside a concept | A concept is partitioned into senses by the **reference's own lexical choice**: the head word of the aligned span. Inflections, and multi-word renderings that share the head, merge. Capitalization counts as a sense feature outside sentence-initial position. Rare wordings go to "other renderings" for the team. The team merges or splits senses in the RL workbook; OL lemma splits (AT03) still apply. This refines the per-concept decision: one decision per concept **sense**. Measured need: NIV renders Ἰουδαῖος as *Jews* (30 verses) and as *Jewish leaders* (11), a deliberate sense distinction | **DECIDED** (PO 2026-11-25) |
| D20 | BSB tables as first-party data | `bsb_tables.xlsx` derives from MACULA (Biblica-owned, CC BY 4.0) plus BSB (public domain). It becomes a **build-time input**: gold word alignment for a BSB RL and for the Key Concepts package, not only evaluation data. Only the columns needed are read (verse, word orders, Strong's, English); no restricted fields (D3). **SAGE is based on BSB (PO 2026-11-25):** Biblica holds no MACULA alignment of the NIV; the BSB derives from NIV84, so an NIV (or other English) reference is aligned to BSB (same language) and through BSB's gold alignment to the OL, with direct EM alignment as fallback and for other languages. Shipped as `SAGE_PCC_OL_2026-11-25` (P5b-R) | **DECIDED** (PO 2026-11-25) |
| D18 | What a "phrase" is | **A phrase is a semantic identity (one unit of meaning), never a frequent word combination** (user feedback, 2026-11-25). Frequency n-grams and co-occurrence statistics never create list entries; they only help locate wordings. A multi-word entry is admitted only as: **S1** a curated multi-word key term (Biblical Terms multi-word OL term); **S2** a multi-word SOURCE rendering of **one** OL key-term lemma (e.g. *chief priests* for ἀρχιερεύς), filed as a wording of that key term; **S3** declared by the team or Operator; **S4** (open, PO) an advisory proposal (§5b.6). The list entry becomes the **concept** (key-term lemma + sense, a curated multi-word term, or a declared phrase), and its SOURCE wordings are its realizations | **DECIDED** (PO 2026-11-25): S4 = (b) concept seed list; concept-level grouping accepted |
| D16 | Job ↔ RL binding | A Job pins one RL version for its SOURCE. A re-pin is explicit, rules carry over by `concept_key`, and missing or changed entries make their rules `STALE`. `phrases.txt` stays Job-local, with *promote to the RL*. The terms bundle narrows to a **glossary bundle** (TARGET renderings only). A Job created without a WIP may attach one WIP once (journaled; the Job ID is unchanged). | Recommended; `phrases.txt` part **superseded by D21** (2026-11-26) |
| D21 | Two functions; SOURCE lists independent of Jobs | PCC is two separate functions: (1) build and maintain **reference lists** from complete REFERENCE texts, including building one text's list from another's (usNIV curated list → Spanish NVI base list); (2) build and maintain a **WIP list** (a PCC Job) from a reference list, e.g. idKKH list → an untranslated Karon Dori WIP, maintained while it is drafted. Reference lists are kept independently of Jobs: a list curated during Karon Dori work is pinned by a Bonerate Job without a rebuild. Every SOURCE-side change made from inside a Job (Operator wordings, Biblical Terms, workbook) writes a new version of the shared list and offers the Job a re-pin; a Job keeps no SOURCE wordings of its own | **DECIDED** (PO 2026-11-26) |
| D22 | Master list and WIP list | A Job **clones** the master list it pins into its own **WIP list** (an RL in the shared store, build mode `LOCAL`, `build.parent` = master version, `build.local` = its changes, recomputed on every save). All changes made in a Job go to the WIP list (refines D21, which sent them to the shared list). The Operator merges chosen additions and omissions into the master: all, chosen by number, or through the changes workbook (`Merge = YES`, Category/Notes editable). Merges start from the newest master version. Update from a newer master re-applies the changes: a change the master now has retires; **a master drop wins unless the WIP list explicitly kept the concept**; a concept the master removed takes its changes with it | **DECIDED** (PO 2026-11-26) |

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

## 5b. Reference lists (D12–D16, review of 2026-11-25)

### 5b.1 Why the list leaves the Job

As built in P3a–P5, the phrase list is rebuilt inside each Job by its `terms` Run, and the Job's
decisions are tied to that Run's scope. Four defects follow:

- **Decisions don't survive a scope change.** `group_id = H(scope_policy, expression, sense)`, and the
  scope policy holds the book scope and the discovery settings. Approving a rendering for a phrase in MAT
  does not carry it to the same phrase in MRK, and neither does changing a threshold.
- **One REFERENCE, several translations, no reuse.** Every Job on NIV curates the same SOURCE list
  again.
- **The overlay has no reference in its keys.** `core-overlay.jsonl` keys verdicts by wording (+ lemma)
  with no reference ID, so a verdict made on one reference applies to every reference that happens to
  share the wording.
- **A single-book scope distorts discovery.** A single book distorts the measured stoplist: frequent
  content words such as *God* and *Lord* are dropped (P4 note). An RL is built over the whole reference.

### 5b.2 Model

| Layer | Belongs to | Key | Shared |
|---|---|---|---|
| **Reference List (RL):** wording, category, senses (OL lemma evidence), key-term flag, status, provenance | one REFERENCE edition | `concept_key` (D13) | every Job on that edition; exportable as a file |
| **Glossary:** chosen renderings, rule scope, notes, language facts | one Job (one WIP / target language) | `concept_key` + sense (D19) + target language | glossary bundle, arriving as `PROPOSED` |

**Package.** Stored at `localdata/inputs/resources/reference-lists/<rl_id>/<version>/`, using the
`index.py` package pattern:

- `MANIFEST.json` contains:
  - `rl_id`, `version` and `title`;
  - the reference: project, edition, `language_tag`, `content_sha256`, versification, license;
  - the build: mode, base version, `derived_from` (RL ID and version), engine version and settings;
  - counts.
- `entries.jsonl` has one entry per `concept_key` (revised by §5b.7):
  - OL anchor (lemma(s), Strong's, gloss), category, inventory source;
  - senses `[{sense_key, label, wordings [{wording, verses}], state}]` (D19);
  - `status` (ACTIVE / PROPOSED / DROPPED), origin, verse count, three example references, notes.
- `CHECKSUMS.sha256`.

**Occurrences are not stored.** A Run recomputes them in under a minute. The whole-Bible occurrence
file is 458 MB (P4).

**Identity across instances.** `rl_id = <slug>-<8 hex of H(instance id, created time)>`. An imported RL
whose ID and version already exist with different content is stored as a fork (new suffix), never
overwritten. An import with a checksum mismatch is refused; this is an integrity guard, allowed under
D9.

**License travels with the RL.** An RL built from, or derived from, NIV carries the NIV license flag. It
is local-only and never committed, and an export shows a fair-use warning. The workbook carries wordings
and references only, never verse text. Only a BSB-based RL could ever ship in the repo.

### 5b.3 Deriving an RL from another reference (research, 2026-11-25)

**Method.** Both references are run through the P3a/P4 engine (n-gram discovery + OL lemma senses). For
each entry `(wording, lemma)` of the base RL, a *pivot* proposes the target-reference entry with the same
lemma whose confirmed verses best overlap the base entry's verses (Jaccard J). Without hand labelling,
the deterministic proxy is the **round trip**: derive A → B → A and check whether the original wording
comes back. *Re-location* is the simple same-language alternative: find the same wording in B and
check its lemma.

Corpus: JHN + ROM, Biblica projects (local only, counts only). Base: NIV 2011, 1,672 lemma-confirmed
entries in at least 2 verses.

| Target | Re-located by wording (same lemma) | Pivot proposals | Round trip (top-1) | Restricted pivot¹ yield of single-word pool (339) |
|---|---|---|---|---|
| NIV Anglicised (related) | 99% (98%) | 100% | 71%² | 97% |
| NIrV (related, simplified) | 72% (58%) | 85% | 63% | 74% |
| BSB (unrelated English) | 85% (74%) | 92% | 64% | 83% |
| Spanish NVI | 1% | 74% | 53% | 46% |
| French Semeur | 3% | 77% | 52% | 40% |
| Swahili Neno (Bantu, prefixing) | 0% | 73% | 52% | 39% |
| Chinese CCB (unspaced) | 0% | 0%³ | — | 0% |

¹ Single-word entries, at least 5 verses, J ≥ 0.5, round-trip consistent.
² Top-1 under-states the result: nested phrases with identical verses tie.
³ Automatic discovery is skipped for unspaced scripts (P3a), so there is nothing to pivot onto.

The public-domain eBible texts (BSB → WEB / LSG / RV1909) gave the same picture: restricted pivot 75% /
52% / 46%.

**Findings.**

1. **Same-language editions: re-location works.** For a related edition it is near-complete (99%). For
   an unrelated English text it re-locates 85% of entries, 74% with the same lemma. Entries that are not
   found, or found with another lemma, are exactly the ones an Operator must look at.
2. **Cross-language: restricted pivot only.**
   - **It works for single-word content terms.** A spot check of the round-trip-consistent output looks
     clean: *father → padre / baba*, *law → ley*, *world → ulimwengu*, *spirit → espíritu*,
     *scripture → maandiko*. It covers about 40–46% of the frequent single-word terms in Spanish, French
     and Swahili.
   - **It does not carry phrases.** A phrase's sense is one anchor lemma, so the pivot finds *some*
     target phrase containing that lemma, not the corresponding phrase. Matches at J = 1.0 on 2-verse
     sets are coincidence.
   - **Top-1 round trip is about 50% for the unrestricted pivot.** That is too noisy for anything but
     filtered proposals.
3. **Unspaced scripts** get no pivot until segmentation exists. Only `RELOCATE`, `MERGE` and Operator
   lists apply.
4. **Tokenizer issue found in passing:** French elided articles stay attached (*l'écriture*, *d'autres*)
   because the apostrophe is measured as a letter. The fix is to split a known elision prefix when the
   remainder is itself a frequent token, measured, not by language code. This is a P5b item.

**Recommendation (D14).** *Superseded by §5b.7:* once concepts are OL-keyed and realized through word
alignment, every reference is built the same way, and derivation only inherits curation. The table above
still stands as a measurement of verse-level evidence. The spot-checked examples are informal, not a
precision measurement.

- `RELOCATE` for related editions in the same language. This is what we have now, made explicit:
  carry senses, flag lemma changes, report unfound entries.
- `PIVOT` restricted to single-word, lemma-confirmed entries that pass all four filters: at least 5
  verses, J ≥ 0.5, round-trip consistency, and one proposal per lemma.
  - Every derived entry is `PROPOSED` and carries its J and round-trip evidence.
  - Phrases are not derived. The target reference's own `SCRATCH` discovery supplies its phrases, and
    the derived anchor terms rank them.
- `PIVOT` stays a **proposal generator, not a list builder**. Before it is offered by default, measure
  precision with the two-LLM judge (§9) on gateway languages: Spanish, French, Portuguese. For the
  Swahili-type set, report yield and round-trip rate only, and say "precision not measured".

### 5b.4 Operator workbook (D15)

- **Sheet `Entries`:**
  - locked `concept_key`;
  - wording, category, lemma + gloss, sense label;
  - verse count, three example references;
  - **status** (`KEEP` / `DROP` / `NEW`), notes;
  - provenance (origin, J / round trip for derived entries).
- **Sheet `About`:** RL ID, base version, hash.
- **Import** always writes a new version plus `RL-DIFF.md` (added / dropped / changed).
  - Rows are applied by `concept_key`. A row whose key no longer exists in the base is reported, and the
    other rows still import (never hard-block).
  - `NEW` rows without a key are located in the reference text. Zero occurrences is reported and the row
    is kept (AT30).
- **Formula injection:** cells starting with `=`, `+`, `-` or `@` are written as text (openpyxl writes
  a leading `=` as a formula).

### 5b.5 Key terms only (D17, feedback 2026-11-25)

**Feedback.** Common terms must be ignored. Only key terms, meaning recurring or repeated concepts and
terms, are traced. The P5 list keeps every discovered wording that has OL evidence, so it is dominated
by function words and everyday vocabulary (*from, because, all, know, come, your*).

**Key-term inventory.**

- **Primary:** Paratext `BiblicalTerms.xml`. The Operator imports it read-only from their Paratext
  installation (D10); it is never shipped.
  - It is keyed by Strong's number (zero-padded, sometimes with a suffix letter, e.g. `G0932`,
    `H0218b`), and every term has a category.
  - The NIV project's list has 8,640 terms: PN 5,726, RE 885, AT 626, MI 489, FA 310, BE 247,
    FL 202, RI 154.
  - Its `References` are **word-level** (`BBBCCCVVVWWWWW`). They can confirm which OL word in a verse is
    the term: occurrence-level evidence that is better than the P4 position window. This is a P5b-2
    option.
- **Fallback** (no Biblical Terms file): ~~MACULA content words minus the most frequent lemmas~~.
  **Dropped (§5b.7 R5):** the shipped Key Concepts package replaces it.

**Measured (NIV, John + Romans, Biblica project, counts only).** 1,672 lemma-confirmed entries:

| Filter | Entries | Single words | Phrases |
|---|---|---|---|
| Lemma on Biblical Terms, at least 2 verses | 634 | 373 | 261 |
| … at least 3 verses | 322 | 234 | 88 |
| … at least 5 verses | 158 | 132 | 26 |

**What the filter does.**

- **Removes:** function words and everyday words, as intended.
- **Keeps:** the expected key terms (*world, law, God, Lord, believe, Spirit, sin, righteousness, glory,
  truth, faith, grace, eternal life, Son of Man, Holy Spirit, chief priests, high priest, kingdom*) and
  names.
- **Three gaps remain:**
  *(Gaps 1 and 2 are superseded by §5b.7: fragments cannot arise in a top-down build, and the frequency
  ceiling was measured to be ineffective.)*
  1. **Phrase fragments survive** (*down from, brother or, lay down, my name*). The shape rule (content
     token at both ends) plus folding fragments into the longest form removes them. Folding at an
     overlap of at least 90% of verses replaces today's "exactly the same verses".
  2. **Some MI lemmas are common speech verbs** (λέγω *say*). The inventory's most frequent lemmas get
     a ceiling: on the list only if the Operator keeps them. Category switches are an RL build setting,
     all on by default.
  3. **Some concepts a team cares about are not on the inventory.** πατήρ (*Father*, in John) is one.
     The Operator adds them through `phrases.txt` or the RL workbook (`NEW` / `KEEP`), and they then
     count as anchored.

**Consequences.**

- **RL:** an RL entry's `status` is `ACTIVE` only for anchored, recurring entries. Other entries are not
  stored. The left-out summary gives counts by reason (common word, below recurrence, fragment).
- **Check:** Function B (P6) builds groups only from `ACTIVE` RL entries and Operator additions. The
  reverse scan (P8) only scans renderings of those entries. This also shrinks the review workload.
- **Pivot:** cross-language derivation (§5b.3) was strong only for single words, which are exactly the
  key terms, so D14 and D17 fit together.

### 5b.6 Phrases are semantic identities (D18, feedback 2026-11-25)

**Feedback.** "Phrases" must be semantic identities, not word pairs that are commonly combined.

**Statistics cannot decide this (measured).** Adjacent-lemma association in MACULA scores real units
and plain collocations alike:

| Pair | PMI | Unit of meaning? |
|---|---|---|
| *Son of Man* | 4.9 | yes |
| *kingdom of God* | 4.5 | yes |
| *Holy Spirit* | 6.0 | yes |
| *come down + heaven* | 5.6 | no |
| *raise + dead* | 6.9 | no |
| *answer + say* | 4.3 | no |

So cohesion, frequency or PMI must never admit a phrase. Meaning has to come from a curated source, the
OL structure, or a person.

**Sources measured (NIV, John + Romans, counts only):**

- **S1, Biblical Terms multi-word terms.** About 1,860 Greek and 2,100 Hebrew multi-word IDs exist
  (*Son of Man, Holy Spirit, unclean spirit, outer darkness, tent of meeting, abomination of
  desolation*), but most are OT names and places.
  - Only 6 have references in John and Romans. *Son of Man* (J = 1.00) and *Holy Spirit* (J = 0.89)
    were found exactly in NIV.
  - *forever* (one NIV word) and *in Christ* need word-level location: the term's word-level references
    plus alignment, not verse overlap.
  - Precise, but **narrow**.
- **S2, one-lemma multi-word renderings.** 18 phrases in at least 3 verses whose content words all
  render the same lemma: *brothers and sisters* (ἀδελφός), *chief priests* / *high priest* (ἀρχιερεύς),
  *Jewish leaders* (Ἰουδαῖος), *demon-possessed*, *strips of linen*, *adoption to sonship*, *basis for a
  charge*, *little while*.
  - Noise at verse-level evidence: *ancestors ate*, *trying to kill*, *offer yourselves*. P5b-2's
    word-level evidence (Biblical Terms references, learned alignment) should remove it.
  - These are wordings of a key term, not separate concepts.
- **What is not covered:** 158 multi-lemma phrases remain, mixing real concepts (*eternal life*,
  *kingdom of God*, *in Christ*) with collocations (*down from heaven*, *raised from the dead*). No
  deterministic test separates them.

**Recommendation.**

1. The list is a list of **concepts**: key-term lemma + sense (D17), S1 terms and S3 declared phrases.
   S2 wordings sit under their lemma's concept.
2. **(DECIDED, PO 2026-11-25)** Glossary decisions and consistency obligations are made per **concept**, with the SOURCE wording
   distribution kept as evidence. *believe / believed / believes* and *brothers / brothers and sisters*
   are one decision each.
   - This is a **deviation from handover SRC07** (exact-wording groups), justified by this feedback.
   - Sense splits (AT03) still apply inside a concept.
3. The automatic n-gram engine stays only as a **locator** of a concept's SOURCE wordings. It never
   creates entries.
4. **S4 (PO decision).** The remaining multi-lemma concepts (*eternal life*, *kingdom of God*) can come
   from:
   - **(a)** the team only, through phrases.txt and the RL workbook; or
   - **(b)** a SAGE-built, OL-keyed **concept seed list**. Candidates are deterministic: OL lemma
     sequences with at least one key-term lemma, in at least 3 verses. An advisory LLM judges "single
     unit of meaning?" in the gateway SOURCE language, and the results are PROPOSED only. The list is
     built once over MACULA + BSB, and could ship publicly: OL keys + CC BY glosses, which would close
     P3b. Being keyed by OL, it serves every reference and pivots like single key terms.

   **PO decision 2026-11-25: (b)**, with (a) always available. Its precision is measured by two LLM judges (§9), and it
   never becomes authority.

### 5b.7 Critical review of the builder design (2026-11-25) and the refined builder

A second pass over §5b.1–5b.6, with new measurements. All data is local, counts only. Biblica projects
come from the local Paratext folder; eBible BSB is used for the alignment check.

**Findings.**

| # | Finding | Evidence | Consequence |
|---|---|---|---|
| R1 | **The builder works bottom-up, and that produced both defects the feedback named.** P3a/P4 start from English n-grams and attach lemmas afterwards, so English frequency shapes the list (common words, collocations). D17 and D18 then only filter that output | §5b.5, §5b.6 | Invert it: build **top-down from OL concepts**. The reference text only supplies realizations, and n-gram discovery leaves the builder |
| R2 | **Concept = lemma merges senses that the reference's translators separated** | NIV John: Ἰουδαῖος → *Jews* (30 verses), *Jewish leaders* (11); πνεῦμα → *Spirit* / *spirit* collapse under casefolding | D19: senses inside a concept come from the reference's lexical choice, with case kept as a feature |
| R3 | **Verse-level lemma evidence pollutes concepts.** Under concept grouping every stray wording becomes a false realization, and then a false `PC10` | NIV John + Romans: πνεῦμα → *through* (4), *whom* (3); σάρξ → *according* (4), *eats* (2); νόμος → *from* (4); ψυχή → *lay down*, *down my* | **Word alignment is a prerequisite (P5b-0)**, not a later precision step |
| R4 | **Word alignment is feasible for Greek and weak for Hebrew as prototyped.** IBM Model 1 + position prior, trained on the NT (7,936 verses) and on the OT (22,965), checked against eBible BSB word-level Strong's tags, content words only (9,430 Greek / 55,413 Hebrew tokens). Greek gets close to a usable bar; Hebrew needs MACULA's prefix/suffix segments as separate tokens (the prototype collapsed them), and must be re-measured | See the alignment results table below | Gate: Greek ≥ 90% precision at ≥ 70% coverage; Hebrew bar set after the segment fix. Measured with the BSB tables (D20) |
| R5 | **The content-word fallback inventory does not work.** Key-ness is not frequency or POS. The Biblical Terms list is itself a reference, not truth: it keeps λέγω *say* and lacks πατήρ *father* and υἱός *son* (but has *Son of Man*) | MACULA noun/verb/adj over lemmas in ≥ 3 verses covers 99% of Biblical Terms lemmas, but only 42% (JHN+ROM) / 31% (GEN+PSA) of its selection is on Biblical Terms. A ceiling on the 50/100/200 most frequent lemmas leaves that share unchanged (42% → 42%) and only cuts recall (97% → 76%) | The shipped default inventory is the **Key Concepts** package (D18 S4b extended to single lemmas), LLM-judged once and **measured against Biblical Terms locally** (tagged reference data, no hand labelling). The frequency ceiling is dropped |
| R6 | **The Jaccard pivot and round trip are unnecessary.** With OL-keyed concepts and alignment, every reference is built the same way. Derivation only needs to carry curation. The "looks clean" pivot samples were an informal spot check, not a measurement | §5b.3 | D14 revised; P5b-5 shrinks to curation inheritance + `RELOCATE` for unanchored phrases |
| R7 | **The seed-list candidate rule is too broad and too order-bound** | 7,203 Greek and 28,931 Hebrew lemma pairs (gap ≤ 2) occur in ≥ 3 verses before any filter. *ζωὴ αἰώνιος* also appears as *αἰώνιος ζωή* | Candidates: unordered lemma sets in a short window, at least one noun, and a translation signal from the gold BSB alignment (BSB renders the set as one contiguous unit in most occurrences). The LLM still decides. Count and budget the LLM calls before running. Option: add MACULA word-group (syntax) IDs to the OL package for principled phrase candidates |
| R8 | **Some claims are unverified or untested** | — | Biblical Terms word-level reference numbering ↔ MACULA word IDs: not checked. D17's threshold of 3 verses: measured on two books, not the whole reference. Hebrew: untested for D17 and D18. Biblical Terms license: Operator-supplied, read-only, used only locally; it never filters or enters a shipped package (it may *measure* the Key Concepts package locally) |
| R9 | **Casefolding loses reference-side sense signals** | P2 `norm` casefolds cased scripts. NIV *Spirit* / *spirit*; *LORD* marked with `\nd` in USFM | Keep case (outside sentence start) and `\nd` as features for D19. *LORD* vs *Lord* is separated anyway by the OL key (YHWH vs adonai) |
| R10 | **Builder quality gates were proxies or spot checks** | — | Deterministic gates per step (below) |

**Alignment results (R4):**

| Testament | Method | Linked | Precision |
|---|---|---|---|
| Greek NT | one direction | 98% | 75% |
| Greek NT | both directions agree | 72% | 90% |
| Greek NT | both directions agree + posterior ≥ 0.5 | 70% | 92% |
| Hebrew OT | one direction | 80% | 45% |
| Hebrew OT | both directions agree | 37% | 76% |

For comparison, the P4 verse-level method reached 79% precision on 52% of occurrences (a different
metric).

**BSB tables checked (D20).** Same file as P4 (SHA-256 `4763b1fa…`). Sheet `biblosinterlinear96` has
one row per OL word, with:

- `Heb Sort` / `Greek Sort` (OL word order);
- `BSB Sort` (BSB English order);
- `Str Heb` / `Str Grk`;
- `VerseId`;
- ` BSB version ` (the English chunk; `-` when the word is untranslated, e.g. the direct-object marker);
- `pnc`.

That is a **gold word-level alignment**: OL word ↔ English chunk, with both orders. For Hebrew it is
per whole word (prefix and suffix included), not per MACULA segment. Mapping a row to a MACULA word uses
verse + OL order + Strong's. The heading, cross-reference and footnote columns are not read.

**Refined builder (replaces SCRATCH in §5b.2–5b.6).**

1. **Align (P5b-0).** Word-align reference ↔ OL.
   - BSB uses the gold alignment from the BSB tables (D20).
   - Other references use Model 1 + position prior in both directions, keeping the links both directions
     agree on, with a posterior threshold. Hebrew uses segments as tokens.
   - English references may use the transitive route via BSB if it measures better.
   - Cached by (reference hash, OL package hash, aligner version).
   - **The same engine serves P6 (SOURCE ↔ TARGET).**
2. **Inventory.** The union of:
   - Biblical Terms (if imported);
   - the SAGE Key Concepts package (single- and multi-lemma);
   - concepts declared by the Operator or team, anchored to OL words through the alignment on import, so
     they become portable;
   - KEEPs inherited from a base RL.

   DROPs are removed.
3. **Realize.** Start from every **OL occurrence** of a concept and take the aligned reference span (a
   contiguous span; multi-word renderings appear naturally, as S2). An unaligned occurrence is counted as
   `NO_REALIZATION`, never guessed. Starting from the OL side also shows where the reference renders a
   concept with no word.
4. **Partition senses (D19).** By head stem (learned suffixes) and case feature; S2 renderings merge with
   their head; wordings in fewer than 2 verses go to "other renderings".
5. **Select (D17).** At least 3 verses per concept sense over the whole reference (a setting). Everything
   else is left out, with counts by reason.
6. **Package.** One row per concept, with sense sub-rows. Each sense carries its wordings with counts,
   three example references, provenance (inventory source, alignment method, realization coverage) and
   the license.

**Deterministic gates.**

| Step | Gate |
|---|---|
| Align | Precision and coverage against the BSB tables, per testament |
| Inventory | Key Concepts recall and precision against Biblical Terms (local) |
| Realize | Realization coverage per concept |
| Partition | Sense splits on a seeded sample judged by two LLMs in the SOURCE gateway language (§9) |
| Whole build | Byte-identical rebuild |

**PO answers (2026-11-25).**

1. **No NIV MACULA alignment exists; base SAGE on BSB** (BSB derives from NIV84). An NIV reference is
   aligned NIV → BSB → OL (D20).
2. **Yes: ship the MACULA syntax-tree word groups**, from
   [macula-greek](https://github.com/Clear-Bible/macula-greek/) (`SBLGNT/lowfat`, commit `076282a…`) and
   [macula-hebrew](https://github.com/Clear-Bible/macula-hebrew/) (`WLC/lowfat`, commit `df1ea5d…`), the same
   pinned commits as the OL analysis package. Built as P5b-R.
3. **D19 accepted.**

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
| **P5b** | Reference lists (D12–D20): word aligner, RL package + store, `concept_key`, top-down build, Job pin, RL workbook round trip, Key Concepts package, inheritance, RL export/import, glossary bundle, overlay folded in | new | Plan "P5b plan" below |
| **P6** | Function B forward: span location, rendering learning with learned affixes, `ORTHOGRAPHIC` subkind, per-WIP self-qualification (§7 L3–L5), classification, occurrence audit, coverage | M4 | AT01, AT02, AT04–AT07, AT10, AT12, AT25–AT27; every eligible occurrence has a disposition; planted-error recall on Biblica WIPs (plan "P6 plan") |
| **P7** | Rule resolver: specificity, `REJECT`, `STALE`, `PC23`; finding decisions (review workbook) become scoped rules | M5 | AT13, AT14, AT18, AT23, AT24; every acceptance names its rule (plan "P7 plan") |
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
  target language. `OPERATOR_WORKFLOWS` (UI listings, reports home) is deliberately still left out; see P1b.
- Tests: `tests/pcc/test_pcc_p1.py`, 41 tests; three deliberate code breaks (validator, journal
  chain, stale-input guard) were each caught. Full suite: 2370 passed, 2 failed; both failures are
  local-environment artifacts outside the repo's tracked files (an untracked file in the git-ignored
  `project-management/private/`, and a `system/tools/__pycache__` from 2026-10-29).

### P1b as built (2026-11-03)

- Main Menu: **6. Phrase Consistency Checker (PCC)**, **7. SAGE Maintenance** (moved from 6); the menu
  also shows `PCC active Job`. `sage/pcc_menu.py` holds the PCC home (add/open/set active), the Job
  wizard (SOURCE, optional secondary SOURCE, optional WIP, or a target-language tag for a terms-only
  Job), the Job menu (Build SOURCE terms list / Check WIP against the glossary / Manage) and the
  Run adapter that seals the snapshot and calls `execute_pcc_run`.
- `ensure_initialized` skips the controller workspace for PCC (local, deterministic).
- Not yet: the terms-list sub-option (P5), PCC in the Reports home and UI service views, report
  languages, and the operator guide entry.
- Tests: `tests/pcc/test_pcc_menu.py`; existing menu-numbering tests updated.

### P2 as built (2026-11-03)

- `pcc/segment.py`: `tokenize` returns `Token(text, norm, start, end)` with code-point offsets into the
  text as given, so `text[start:end] == token.text` always holds. `norm` is NFC, casefolded only when the
  measured `cased` trait is true. Diacritics are never stripped. Apostrophe-like code points count as
  letters only when passed in as measured `letter_marks`. Unspaced scripts get one token per character
  cluster and must be reported `PARTIAL`.
- `pcc/trie.py`: `TokenTrie` (standard library); `find_all` returns every match, nested and overlapping
  (AT21), with several payloads per key.
- `pcc/traits.py`: `measure_traits` measures script, unspaced, cased, letter/punctuation inventory,
  apostrophe letters (inside a word in at least 80% of uses and at least 5 times) and learned
  suffixes/prefixes (endings alternating across at least 5 shared stems). It never consults a language
  code. `capability_matrix` gives `SUPPORTED`/`PARTIAL`/`UNAVAILABLE`; negation and orthographic
  equivalence turn on only from team-declared facts (P5).
- Decision: no PCC capability block was added to the grammar profiles; traits are measured per Run and
  go into the Run snapshot in P6.
- Not yet: frequent clitics (§7 L1) and wiring traits into the Run snapshot (P6).
- Tests: `tests/pcc/test_pcc_p2.py`; P1 + P2 = 52 passed.

### P3a as built (2026-11-03)

- `pcc/discovery.py`: `discover` finds curated, local and automatic expressions and locates every
  occurrence in the actual SOURCE (`expression` / `occurrence` records, code-point spans reconstruct the
  raw text). Automatic n-grams (1-6 tokens, in at least 2 distinct verses) are built level-wise inside
  clause chunks and never cross clause punctuation; the stoplist is measured from the SOURCE (tokens in
  at least 5% of verses and at least 20 verses). Unspaced SOURCE scripts skip automatic discovery and
  say so. Curated and local entries are never pruned. Phrases absent from the SOURCE come back as
  `unfound` (AT30). A nested phrase with the same count as its container is mapped for display dedupe;
  both stay as evidence. Every occurrence is `UNRESOLVED` with a provisional "unassessed" sense (P4).
- `pcc/phrases.py`: `input/phrases.txt` parser; blank/`#` lines skipped, a line without letters or a
  duplicate is a reported problem with its line number.
- `pcc/source_text.py`: SOURCE verse units from a Project (visible body text only, via `numbers.target`).
- `pcc/index.py` + `tools/build_phrase_index.py`: package = `MANIFEST.json`, `expressions.jsonl`,
  `occurrences.jsonl`, `CHECKSUMS.sha256`; `build` refuses a non-empty folder; `verify` checks checksums,
  contracts and references, and with `--project-path` rebuilds and requires byte-identical files.
  `curated_seeds` uses only curated entries of a package, PROVISIONAL unless the content hash matches.
- Run: a `terms` Run now writes `expressions.jsonl`, `occurrences.jsonl`, `expression-stats.jsonl` and
  `source-traits.json`, reports unfound phrases and bad lines as exceptions, and is `COMPLETE` when
  nothing needs reporting. `check` is unchanged.
- Trait fix from P2: `cased` now means some capitals and mostly lowercase letters (the 5% rule missed
  normal text).
- Open: a Run does not yet load a pinned index (no pin file exists); a terms Run takes one book scope.
  **P3b (BSB package):** the BSB text is not in this checkout (it is fetched into the cache by
  `build_numbers_index.py`), and no curated term/idiom list exists. Needs a PO decision: ship a
  discovery-only BSB index, or supply a curated list first.
- Tests: `test_pcc_p3.py`, `test_pcc_p3_index.py`; P1-P3 = 69 passed.

### P4 as built (2026-11-03)

- `pcc/sense.py` (`assign_senses`): original-language lemmas as evidence only (D2, D3: lemma, Strong's
  number and gloss; no restricted fields). A lemma is a candidate for an expression when it is in at least
  2 of the expression's verses, in at least 15% of them, and the expression is in at least 20% of the
  lemma's own verses (so function words fail). Candidates are chosen greedily by coverage; each chosen
  lemma is one `PROVISIONAL` sense keyed by the expression and lemma (`SENSE-OL-LEMMA`), so divergent
  lemmas split into separate groups. An occurrence is `CONFIRMED` for the one chosen lemma in its verse;
  none, several, a polysemous-flagged lemma, or no OL data give `UNRESOLVED` with the reason (`PC20`).
  Curated senses are kept: one confirms all occurrences, several wait for the team (P5).
- `pcc/ol_evidence.py`: maps SOURCE verses through the project VRS to canonical (`org`) numbering and
  reads the shipped MACULA package (`SAGE_OL_ANALYSIS_2026-10-15`); no raw MACULA fetch is needed.
- Run: a `terms` Run also writes `groups.jsonl` (ELIGIBLE at 2+ confirmed verses, else INFORMATIONAL, AT16)
  and `sense-unresolved.jsonl`; without the OL package it reports `PCC_SENSE_NOT_ASSESSED`.
- `source_text` and `tools/build_phrase_index.py` also read a plain folder of `*.usfm` files (eBible layout).
- Stoplist threshold raised to 15% of verses, because 5% removed content words (`world`) in a single book.
  Frequent content words and names (God, the Lord) are still skipped in a single-book scope; list them in
  `phrases.txt`.
- Real-data check (BSB as SOURCE, MACULA lemmas): JHN 878 units, 12,284 occurrences, 6,835 confirmed
  (`world` -> κόσμος, `eternal life` -> αἰώνιος); PSA 2,524 units mapped across the Hebrew numbering;
  `salvation` split into two Hebrew lemmas. Whole BSB discovery: 39 s, 102,496 expressions,
  800,723 occurrences. BSB's own `\w strong=` tags were not used.
- Limits: verse-level evidence only (word position is not used); apostrophe-s stays inside the token
  (`Lord’s` is not `Lord`), by SRC07 a separate group.
- **P3b decision (made while measuring):** a whole-BSB discovery index is **458 MB** (occurrences
  alone 420 MB) and a Run recomputes it in under a minute, so it must not ship in the public repo. Ship
  only a compact curated-entries package when a curated list exists; otherwise nothing. The eBible BSB
  (`engbsb_usfm.zip`, SHA-256 `75ca91d5…fbc4`) is now in the local cache
  `localdata/.system/cache/witnesses/engbsb` (not committed).
- Tests: `test_pcc_p4.py`; P1-P4 = 77 passed.

### P4 evaluation against the BSB tables (2026-11-03)

- `bsb_tables.xlsx` (bereanbible.com, public domain; SHA-256 `4763b1fa…cf3d`, 754,647 word rows) gives
  the BSB English each Hebrew/Greek word is rendered by. It is tagged data, so it measures sense
  evidence without hand labelling (§9). It stays in the local cache
  `localdata/.system/cache/witnesses/bsb-tables`; `tools/evaluate_pcc_senses.py` reads it and prints counts only.
- Result (BSB as SOURCE, `CONFIRMED` lemma against the table's Strong's number for the same words):

| Scope | Window | Precision of CONFIRMED | Confirmed share |
|---|---|---|---|
| JHN + ROM | none (verse only) | 73.9% | 56.1% |
| JHN + ROM | 0.25 (default) | 79.4% | 51.6% |
| JHN + ROM | 0.15 | 81.6% | 45.8% |
| GEN + PSA | none | 63.1% | 48.3% |
| GEN + PSA | 0.25 | 68.6% | 42.7% |

- Errors are mostly closed-class words (`may`, `your`, `these`, `had`), where verse-level evidence cannot
  say which Greek or Hebrew word was rendered. The relative-position window (`DEFAULT_WINDOW = 0.25`,
  `OUT_OF_POSITION` when no chosen lemma is near) is now the Run default: an unresolved occurrence costs
  a team look, a wrong `CONFIRMED` costs a wrong obligation. Hebrew is weaker (word order, prefixed
  segments; the table counts the Strong's of the whole word row).
- Senses stay `PROVISIONAL` and the team confirms them in P5. No release bar is set yet; next step to
  raise precision is learned word alignment (IBM Model 1 per plan A3) and a lexical-word filter, and the
  tool is the gate to measure it.
- ~~The table is not shipped and not used at run time; it is evaluation data.~~ Revised 2026-11-25 (D20):
  the table derives from MACULA (Biblica, CC BY 4.0), so it is a build-time input (gold BSB alignment)
  as well as evaluation data.

### P5 as built (2026-11-03)

- `pcc/glossary.py`: `terms_rows` turns a `terms` Run's outputs into one row per expression and sense
  (an unresolved remainder gets its own "UNRESOLVED (team decides)" row). `write_terms_list` writes
  `TERMS-LIST.md` and `TERMS-LIST.xlsx` to `localdata/reports/<job>/`; the workbook has sheets `Terms`
  (blank *Chosen rendering(s)*, *Scope*, *Notes*), `Language facts` (negation markers, apostrophe,
  spelling variants, word-break) and `About` (list hash, Job, Run).
- Import (`import_filled_list`): renderings split on `;` or line breaks; a leading `!` records a rejected
  rendering; scope is blank (whole group) or `PASSAGE:<reference>`. Each rendering is a `variant_rule`
  stored by content hash in `glossary/records/` plus a chained `review_event`; `current_rules` rebuilds the
  rule view from the journal and fails closed (`PCC_GLOSSARY_RECORD_TAMPERED`) on an edited record.
  A bad row is reported with its sheet row number and the rest still imports; a sheet that answers a
  different terms list (hash mismatch) imports nothing. Re-importing is idempotent. Removing a rendering
  from the sheet does not revoke it (revocation is a later menu action).
- Language facts are validated (one-character apostrophe, `a=b` pairs) and journaled as `FACTS-<lang>`;
  `current_language_facts` feeds `capability_matrix`. Not yet wired into a Run (P6).
- Paratext (D10): `read_term_renderings` parses `TermRenderings.xml` read-only (DTD/entities refused);
  an `Id` matching an entry's OL lemma proposes each rendering as a `PROPOSED` rule, with the file SHA-256
  as evidence. Leading/trailing `*` affix marks are stripped; other patterns are listed and not used. The
  Operator approves all, or one by one (`decide_proposals`). Nothing is written back to Paratext.
- Menu: PCC Job menu gains **Terms list and glossary** (export, import filled list, import Paratext,
  review proposed renderings).
- Not yet: reclassifying senses from the sheet (`RECLASSIFY_SENSE`), revoking a rule from the menu, rules
  used by a Run (P6/P7).
- P5 additions (2026-11-04): terms lists show key phrases only (`curate_rows`: empty and nested rows folded,
  routine wording left out and summarised at the end of the report); Paratext `BiblicalTerms.xml` lemmas are
  always listed as `KEY_TERM`; `pcc/transfer.py` exports/imports a checksummed JSON terms bundle between Jobs
  (renderings arrive as PROPOSED, same target language only) and imports Operator lists (CSV/TSV/TXT/XLSX);
  `pcc/overlay.py` keeps Operator verdicts on core lists (OL senses, key terms, index entries) as a local
  overlay in `localdata/inputs/pcc/core-overlay.jsonl`, shared by all Jobs, never editing shipped packages.
  The phrase index is not yet loaded by a Run, so INDEX_ENTRY verdicts are honoured by `curated_seeds` only.
- Tests: `test_pcc_p5.py`; P1-P5 = 92 passed.

### P5b-R as built (2026-11-25): PCC original-language package in the distro

- `SAGE_PCC_OL_2026-11-25` in `system/resources/pcc-ol/2026-11-25/` (pin `system/config/pcc-ol-reference.json`),
  three TSV tables keyed by MACULA word ref (26 MB unpacked):
  - `bsb-alignment.tsv` (442,870 rows): BSB verse, position, English, punctuation per OL word.
    - Hebrew 289,477 words paired by Strong's sequence + 15,951 by position (1–3-word equal gaps between
      anchors: form-specific Strong's such as 846/848, 1510/2258, object marker + suffix) = 305,428 of
      305,517 (99.97%).
    - Greek 127,896 + 9,546 = 137,442 of 137,741 (99.8%). The remainder are text differences: the BSB base
      text vs SBLGNT, e.g. 315 Greek words not in SBLGNT.
    - Aramaic rows count as Hebrew, as in MACULA. Spot checks (GEN 1:1, DAN 2:4, JHN 1:1, JHN 3:16) are
      correct, and JHN 5:4 is correctly absent.
  - `ol-senses.tsv` (240,855): Clear senses, Greek joined by MACULA id (60,353 of 60,574; 221 ids not in
    SBLGNT) and Hebrew `@sensenumber`.
  - `ol-groups.tsv` (153,993): `np` / `adjp` / `pp` groups of 2–6 words from the lowfat trees.
- Clear senses are evidence, not the sense split. Greek πνεῦμα 366 / 3 / 2 / 1, Ἰουδαῖος 177 / 9 / 1 (no
  *Jews* / *Jewish leaders* split); Hebrew רוּחַ 229 / 110 / 35 / … So D19's reference-side split stays
  primary.
- Code:
  - `sage/pcc/ol_build.py` (build-time: pins, input verification, table reader, per-book Strong's pairing
    with gap fill, lowfat group extraction reading only structure attributes, deterministic package
    writer);
  - `sage/pcc/ol_resources.py` (loader: pin + checksums, lazy tables, `groups_by_ref`);
  - `tools/build_pcc_ol_resources.py` (`fetch` / `build` / `verify`; `verify` reports IDENTICAL).
- Inputs (cache only, never in the repo): BSB tables (SHA-256 pinned), MACULA word tables (existing pins),
  Clear Greek senses (SHA-256), lowfat trees (git tree SHA + listing digest; every file checked against its
  git blob SHA).
- Notices: `THIRD-PARTY-NOTICES.md` (pins, Groves Center credit for the Hebrew trees, Clear senses, BSB
  tables) and `ORIGINAL-LANGUAGE-RESOURCES.md`.
- Distro inventory `VANILLA-INSTALL-MANIFEST.md` updated. It also gained `pcc/overlay.py` and
  `pcc/transfer.py`, missing since 7ac8ee2.
- Source audit: two prohibited target-text verbs reworded (one pre-existing in `glossary.py`); the plan's spelling is
  US English.
- Tests: `tests/pcc/test_pcc_ol_resources.py`, fabricated inputs plus an integrity check of the shipped
  package. PCC 103 passed; `test_package.py` 19 passed.
- Environment note: python.org Python on the build machine has no CA certificates, so `fetch` over
  `urllib` failed there; the inputs were fetched with curl from the same pinned URLs and verified by the
  same pins.

### P5b-0 as built (2026-11-25): word aligner

- `sage/pcc/align.py`. Each reference token gets at most one link to a MACULA word.
  - **Through the BSB:** ordered token matching against the BSB English of the same verse, from
    `SAGE_PCC_OL`. A verse in which every BSB token is found in order is the BSB: `gold`. Otherwise matched
    tokens become `transitive`, e.g. for the NIV.
  - **Direct:** IBM Model 1 with a relative-position prior (λ = 8), trained in both directions over the
    whole reference. A link is kept only when both directions agree and its posterior is ≥ 0.6. Hebrew
    prefix and suffix segments are separate tokens.
  - BSB links win over direct ones; unlinked tokens stay unlinked. `cache_key` covers the reference hash,
    the package ids and `ALIGNER_VERSION`. A persistent cache is not built yet; P5b-2 adds it.
- `tools/evaluate_pcc_alignment.py`: on the BSB (eBible `engbsb`, local cache), the direct path is scored
  against the gold links on content words. Counts only:

| Testament | Content words found | Token precision | Threshold |
|---|---|---|---|
| Greek NT (70,616 gold content tokens) | 74.7% | 92.7% | 0.5 |
| Greek NT | 73.1% | **94.2%** | **0.6 (default)** |
| Hebrew OT (196,112 content words) | 75.5% | 89.8% | 0.5 |
| Hebrew OT | 73.1% | **91.6%** | **0.6 (default)** |

  Both gates pass at 0.6 (≥ 90% precision, ≥ 70% coverage). The §5b.7 prototype, which collapsed Hebrew
  segments, had 76% precision at 37% coverage.
- NIV (local, `--coverage-only`, no gold exists):

| Books | Tokens linked through BSB | Either path | Agreement where both link |
|---|---|---|---|
| John + Romans | 80% | 84% | 91.2% |
| Genesis + Psalms | 74% | 83% | 89.6% |

  The agreement matches the direct path's measured precision, so the NIV → BSB route is consistent. That
  is a proxy, not a precision measurement.
- Run time: whole OT ~100 s, whole NT ~30 s (pure Python).
- Tests: `tests/pcc/test_pcc_align.py`, 7 tests on fabricated data. PCC 110 passed.

### P5b-1 as built (2026-11-25): concept keys and reference-list packages

- `ids.concept_key(kind, anchor)` (D13). Kinds:
  - `OL`: sorted original-language keys, one lemma or a multi-lemma set;
  - `BT`: a Biblical Terms term id;
  - `WORDING`: `<language>|<wording>`.

  `ids.sense_key(concept, sense)` identifies a sense inside a concept (D19). `ids.group_id(concept, sense)`
  no longer contains the scope policy, so a group keeps its id across book scopes and discovery settings.
  The P4 groups, still expression-based until P5b-2, are keyed by a `WORDING` concept. The
  `scope_policy_sha256` argument is gone from `assign_senses`, `run.py`, the tests and
  `tools/evaluate_pcc_senses.py`.
- Contracts `reference_list_manifest` and `reference_list_entry` (`contracts.py`):
  - the manifest holds the reference identity, the license (`local_only`), the build (mode
    `SCRATCH`/`INHERIT`/`MERGE`/`IMPORT`, `base_version`, `derived_from`, `imported_from`, settings),
    counts per status, the entries' SHA-256 and the creation time;
  - an entry holds the concept key, the anchor, label, category, status (`ACTIVE`/`PROPOSED`/`DROPPED`),
    origin, senses with wordings and verse counts, Clear OL senses and state, verses, examples and notes.
- `sage/pcc/reflist.py`:
  - `write_reference_list` is deterministic: the caller supplies the creation time, and a used folder is
    refused;
  - `verify_reference_list` checks checksums, contracts, sort order, uniqueness and counts;
  - `new_rl_id` is a slug plus 8 hex of (instance, time);
  - `ReferenceListStore` keeps lists at `<resources>/reference-lists/<rl_id>/<version>/`. It writes a new
    version on every save, loads the newest or a named version, lists all lists, and imports a package
    (`kept` if identical, `imported` if new, `forked` under a new id if the id and version exist with
    other content; it never overwrites).
- Tests: `tests/pcc/test_pcc_reflist.py`, 6 tests. PCC 116 passed.

### P5b-2 as built (2026-11-25): top-down reference-list build

- `sage/pcc/rlbuild.py`, following §5b.7 steps 2–5. N-gram discovery is not used.
  - **Inventory.** The sources are Biblical Terms (`glossary.read_biblical_term_entries`, read-only), declared
    phrases, and the entries of a base RL. A `DROPPED` base entry removes its concept. Concepts merge by
    `concept_key`: sources are joined, and `ACTIVE` wins over `PROPOSED`.
    - A one-word term, or a phrase with a Strong's number for each content word, gets an `OL` key. So
      `πνεῦμα-1/-2/-3` become one concept, and the reference decides its senses (D19).
    - A phrase that names fewer lemmas than it has words (*in Christ*: only χριστός) keeps its `BT` id. It is
      found through its listed verses and its original-language words.
    - The Key Concepts package (P5b-5a) is not built yet. Without Biblical Terms, the inventory is
      therefore only declared and inherited concepts.
  - **Occurrences** are every MACULA word with the concept's key, through versification.
    - A multi-lemma concept counts only where all its lemmas fall inside one MACULA phrase group (R7),
      in any order. Without groups, a window of `len + 3` words is used.
  - **Realize.** An occurrence takes only the tokens linked to the concept's own segment: in a
    prefixed Hebrew word, *and the earth* gives *earth*.
    - An unlinked neighbor is added when three things hold: the aligner's hint for it is the same word
      with posterior ≥ 0.5; it is not a function token; and no other word of the verse carries the lemma
      it usually renders (*leaders* in *Jewish leaders*).
    - A span stops at clause punctuation and at a token that renders another content word.
    - Function tokens at the edges are trimmed, and so is a linked edge token with < 5% of its links on
      the concept (a copula the BSB puts in a chunk).
    - Results are counted as `realized`, `function_only` (e.g. a pronoun for a name) or `no_realization`.
  - **Function tokens are measured** from the alignment, never listed. A form is one when:
    - its most frequent lemma is non-content; or
    - it is spread over ≥ 20 lemmas, none above 20%, and is a word's only linked token in ≤ 15% of its
      links (auxiliaries); or
    - it is linked to ≥ 5 lemmas and is almost never a word's only linked token (vocative *O*).

    Content words spread over many lemmas (*leaders*, *life*) are often the only token, so they stay.
  - **Senses (D19).** The key is the stems of the wording (learned suffixes, stripped to a fixpoint,
    so *brother*/*brothers* agree) plus the case of its first token outside a sentence start.
    - A sentence-start occurrence joins the case its stem usually has.
    - **Deviation from §5b.7 step 4:** a multi-word wording that recurs is a sense of its own, because a
      head-only key merged *Jewish leaders* with adjectival *Jewish*. A rarer multi-word wording still
      joins its first word's sense (S2).
  - **Select (D17).** A sense needs ≥ `min_verses` (3) verses. Other senses are pooled as one `OTHER`
    sense, which is evidence only. A concept with no recurring sense is left out.
    - Left-out reasons: `CATEGORY_OFF`, `DROPPED_IN_BASE`, `NOT_LOCATABLE`, `NOT_IN_REFERENCE`,
      `NO_REALIZATION`, `FUNCTION_ONLY`, `BELOW_RECURRENCE`.
    - A declared phrase that is not found is kept with no senses (AT30) and reported.
  - **Declared phrases** are anchored on the content lemmas linked inside them in ≥ 50% of their
    occurrences. *eternal life* gets {αἰώνιος, ζωή} and is then built top-down like any OL concept.
    Without an anchor, the key is a `WORDING` key and the located spans are used.
  - Clear senses of each sense's occurrences are kept as evidence (`ol_senses`).
- **Contract changes** (P5b-1 contracts, not released):
  - entry gains `sources` and `realization` (counts per outcome and method);
  - sense gains `kind` (`SENSE`/`OTHER`), `verses` and `examples`;
  - manifest `build` gains `summary` (left-out counts, stats, declared problems).
- **Aligner changes** (`ALIGNER_VERSION` 3):
  - every link names the segment it renders: the direct model assigns BSB-chunk tokens to segments;
  - unlinked tokens keep a hint (word, segment, posterior);
  - elided prefixes (*l'*) are split where the text shows them (`segment.measure_elisions`, §5b.3
    finding 4);
  - `AlignmentCache` (`localdata/.system/cache/pcc-alignment`, gzip, deterministic bytes) is keyed by
    reference hash, packages, versification and settings;
  - `segment_key` keeps MACULA's letter on non-content segments. The article is `1886a` while the name
    Dothan is `1886`, so before this fix Biblical Terms names (Dothan, Atharim, Jetheth) took 33% of all
    occurrences.
  - Re-measured on the BSB per testament: Greek 73.1% words at 94.2% (unchanged), Hebrew 73.6% at 91.1%
    (was 73.1% / 91.6%). Gates still met.
- **R8 answered (counts only).**
  - Biblical Terms word references are MACULA word numbers × 2 for Greek: 9,327 of 9,637 sampled
    references (97%).
  - Hebrew does not map: 57% by segment count. So occurrences come from MACULA Strong's numbers, and the
    references are used only for `BT`-kind phrases.
- `segment.at_sentence_start` / `case_feature` keep case beside `norm`. `\nd` is not read, because the
  visible text has no character styles; *LORD* and *Lord* are separated by their OL keys anyway.
- `tools/build_pcc_reference_list.py` writes a new version into the store (`--dry-run`, `--rebuild-check`,
  `--base`, `--phrases`, `--categories`, `--min-verses`). It prints counts. `--show` prints chosen
  concepts' senses on the local console only.
- **Gates.** NIV (`usNIVv2`) with its Biblical Terms list, local only:

| Gate | Result |
|---|---|
| Whole Bible in a few minutes | Align 157 s uncached, ~7 s cached; build ~10 s |
| Byte-identical rebuild | Yes |
| NIV John: *Jews* and *Jewish leaders* separate senses of Ἰουδαῖος | Yes: *Jews* 32, *Jewish* 12, *Jewish leaders* 8 verses (whole Bible 127 / 29 / 14) |
| No function words among realizations of πνεῦμα / σάρξ / νόμος | Yes: *Spirit*, *spirit*, *breath*; *flesh*, *body*, *people*; *law*, *Law*. Rare wordings are pooled in `OTHER` |
| *God*, *Lord*, *Son of Man* present | Yes |
| *eternal life* present | Only as a declared phrase: Biblical Terms has no such term. The Key Concepts package (P5b-5a) is meant to supply it |

- Whole NIV with Biblical Terms: 6,825 concepts → 2,236 entries. Left out: 1,872 not in the reference,
  2,593 below recurrence, 100 not realized, 27 function only.
- Included entries realize 88% of their 96,396 occurrences: 3% function only, 9% unaligned.
- Known noise, about 1 in 500 wordings: a BSB-path duplicate match can join two renderings of one word
  (*God … God's*), and a strong hint can add an adverb (*Jews there*).
- Tests: `tests/pcc/test_pcc_rlbuild.py` (14) and a segment-key test in `test_pcc_align.py`. PCC 131
  passed; `test_package.py` 19 passed; source audit PASS.

### P5b-3 as built (2026-11-25): Job pin and terms Run from the reference list

- **Pin.** `job.defaults.reference_list = {rl_id, version, sha256}` (contract `RL_PIN`). `sha256` is the
  SHA-256 of the package's `CHECKSUMS.sha256`.
  - `jobs._validate_pcc_defaults` checks the shape. Defaults written before reference lists load with
    `null`.
  - `pcc/pin.py`: `pin_for`, and `resolve_pin`, which stops with `PCC_RL_MISSING` or `PCC_RL_CHANGED`.
- **Snapshot.** `run_snapshot.reference_list` seals the pin plus the list's reference content hash. Execute
  compares it like the other inputs. A missing, changed or corrupt package, or a different pin, gives
  `PCC_RUN_INPUT_STALE`. The run manifest's `reference_index_version` is `<rl_id>@<version>`.
- **Terms Run** (`pcc/rlterms.py`). With a pin, the Run no longer discovers wordings.
  - It aligns the whole SOURCE through the shared cache (the list build's cache entry when it is the same
    text) and builds the same `BuildContext` as the list. The suffixes and case setting come from the
    list's build settings.
  - It locates every listed concept inside the scope. A concept without lemma keys (`BT`, `WORDING`) is
    located by the list's own wordings.
  - **Fixed candidates.** Each occurrence matches one of the list's senses for its concept, by the sense
    key the list was built with: the whole wording first, then the first word. Senses are never chosen
    again. An occurrence with no match is `UNRESOLVED` (`PC20`), with reason `RARE_RENDERING` (pooled
    `OTHER` on the list) or `NEW_WORDING`. The plan put this mode in `sense.assign_senses`; it lives in
    `rlterms.py` because occurrences already start from the list's lemma keys.
  - **Same text** (SOURCE content hash equals the list's): matched occurrences are `CONFIRMED`.
    **Another text**: they are `PROVISIONAL`, and the Run reports `PCC_RL_OTHER_EDITION` (`RELOCATE` at run
    time). The terms list now counts a `PROVISIONAL` occurrence under its sense.
  - The Job's `phrases.txt` lines that are not already concepts on the list are located too, as
    `LOCAL_INPUT` expressions with senses from their own wording. A line not found gives
    `PCC_PHRASE_NOT_IN_SOURCE`.
  - Output keeps the P4 contracts (expressions, occurrences, groups), so the terms list, glossary import,
    Paratext proposals and bundles work unchanged. A group id is `group_id(concept_key, sense_key)`, and
    groups gain `concept_key` and `state`. Only concepts that occur in the scope are emitted.
  - Without a pin, the P4 discovery path still runs, as before.
- **Re-pin** (`pin.repin`) is refused while a Run is open.
  - Rules whose group (concept + sense) is still on the new version carry over unchanged. Any other live
    rule gets a `MARK_STALE` journal event and state `STALE`; both are new contract values. A `STALE` rule
    is never deleted and never accepting.
  - It writes `localdata/reports/<job>/PCC-REPIN-<rl_id>-v<n>.md`: concepts added, dropped, changed and
    unchanged; rules carried and made stale.
- **WIP attach** (`JobStore.attach_pcc_wip`, D16). A Job without a WIP may bind one once, in the WIP's
  language, with no Run open.
  - It is recorded in the manifest as `wip_attached` (Project and time), and the Job ID keeps its
    target-language form; the loader accepts that identity when `wip_attached` is present.
  - A second attach gives `PCC_WIP_ALREADY_BOUND`.
- **Menu** (`pcc_menu.py`).
  - The Job wizard ends with **Reference list**. The Operator chooses a stored list (lists for this
    SOURCE first), builds one from the SOURCE now (`rlservice.build_reference_list_for`, which offers the
    SOURCE's own Paratext `BiblicalTerms.xml` and uses the Job's `phrases.txt`), or keeps none.
  - Manage PCC JOB gains **Reference list (pin or re-pin)** and, without a WIP, **Attach a WIP (once)**.
    The Job header shows the pinned list.
  - `tools/build_pcc_reference_list.py` now calls the same service. The list's `content_sha256` is the
    SOURCE file hash a Run seals (`source_text.source_content_sha256`), and the reference is read in
    canonical book order (`source_text.reference_units`).
- **Real data** (NIV with its Biblical Terms list, local only; list built in memory). A terms Run over
  John, all cached, takes about 3 s after context indexing:

| Scope | Concepts in scope | Occurrences | Matched to a listed sense |
|---|---|---|---|
| John | 287 | 2,669 | 2,329 (87%) |
| Genesis | 520 | 4,925 | 4,244 (86%) |

  - Ἰουδαῖος in John: *Jews* 36, *Jewish leaders* 14, *Jewish* 10, 2 unresolved.
  - The unmatched 13% are wordings the list pooled as too rare to be a sense. They appear on the terms
    list as "meaning not identified" rows for the team.
- **Gates met** (`tests/pcc/test_pcc_pin.py`, 7 tests, and a menu test):
  - rules survive a re-pin by concept and sense;
  - a dropped concept's rule becomes `STALE`;
  - the snapshot seals the list hash;
  - a changed package stops the sealed Run with `PCC_RUN_INPUT_STALE`.
- PCC 139 passed, `test_package.py` 19 passed, source audit PASS.

### P5b-4 as built (2026-11-25): reference-list workbook

- `pcc/reflist_xlsx.py`.
  - `export_workbook` writes `RL-<id>-v<n>.xlsx`. The **Entries** sheet has the concept key (the only
    locked column), label, category, recurring senses with verse counts, verses, examples, **Status**
    (`KEEP` / `DROP` / blank for undecided; `PROPOSED` exports as blank), notes and origin. The **About**
    sheet has the id, base version and entries hash.
  - `import_workbook` applies rows by concept key to the **base version named in the workbook** and always
    stores a **new version** (build mode `MERGE`, `base_version` = the workbook's base). It writes
    `RL-DIFF-<id>-v<n>.md` (added / dropped / kept / other edits / rows not used).
  - A bad status, an unknown key or a keyless row that is not `NEW` is reported by row number, and the
    other rows still apply.
  - A workbook naming a version this instance lacks is refused (`PCC_RL_WORKBOOK_BASE_MISSING`).
  - No change means no version is written.
- **`NEW` rows** carry a wording in *Wordings*. With the reference text available
  (`rlservice.reference_context`, through the alignment cache) a row is anchored and realized like a
  declared phrase. A wording found nowhere is kept with no senses and reported (AT30). Without the text it
  is kept as a `WORDING` concept and reported.
- **Formula safety:** cells starting with `= + - @` are written with a protective quote, and import
  removes it.
- **Overlay removed.** `pcc/overlay.py` and "Review core lists" are gone; verdicts now live in list
  versions.
  - Terms bundles no longer carry verdicts. An older bundle's verdicts are counted and reported, not used.
  - `glossary.curate_rows` keeps its pure `verdicts` argument, but nothing writes a global file.
- **Menu.** The Reference list menu gains export and import of the workbook for the pinned list. Import
  then offers to pin the new version, through the re-pin carry-over.
- Tests: `tests/pcc/test_pcc_reflist_xlsx.py` (3).

### P6 as built (2026-11-25): forward consistency check

- `pcc/check.py` is the engine; `pcc/check_run.py` handles the Run integration and reports.
  - A check Run runs the terms analysis of the scope first (pinned list or discovery). It then checks
    those occurrence, group and expression records, so it works with or without a pin.
- **P6-1 verse pairing** (`pair_verses`). SOURCE and WIP units that share a canonical verse (through
  each Project's VRS) are one pair; a bridge or split forms an `EQUIVALENCE_GROUP`. A SOURCE verse
  without a WIP verse is `PC21` (`NO_TARGET_VERSE`).
- **P6-2 groups.** Groups are concept + sense. A group with fewer than 2 verses in scope is listed
  `INFORMATIONAL`: audit row with result `PC02` and that reason, never compared (AT16). Unresolved
  senses are `PC20` (AT11). Groups of entries the list only `PROPOSED` are not traced (D17).
- **P6-3 learned alignment.**
  - Model: IBM Model 1 both ways (the P5b-0 engine) over SOURCE ↔ WIP token pairs. It is trained per
    testament of the scope: NT only for a John Run, 37–84 s instead of 639 s for the whole Bible. It is
    cached under `cache/pcc-alignment/model-<key>.json.gz` (pruned at p ≥ 0.005).
  - Span: target tokens linked to the occurrence in either direction with a **real** probability
    (t ≥ 0.05), not only a relative posterior. At least one forward link is required. Gaps of one token
    are bridged; edge tokens that are measured stop forms or weakly linked are trimmed. Position prior
    λ = 4 (softer than the OL aligner's 8: languages reorder).
  - A span is **reliable** when a link inside it agrees in both directions at posterior ≥ 0.5.
  - **No span** where the SOURCE context words (±5 tokens, else the whole verse) are linked in at
    least 40% of cases gives `OMISSION` → `PC11`. Otherwise it is `UNCERTAIN` → `PC21` (AT07, AT12).
- **P6-4 glossary forms first.** Every glossary form of the group (any state; group or passage scope)
  is matched before the learned span: exactly, through a team-declared spelling equivalence (L2), or
  through learned TARGET prefixes and suffixes (L1; `Morphology`). Only `APPROVED` `ACCEPT` accepts;
  an approved `REJECT` form found is reported. Equal-scope approved ACCEPT + REJECT of one form gives
  `PC23` for that group only (AT14).
- **P6-5 classification** follows the handover's decision order. Negation is checked **before** an
  all-approved group can pass: a negated approved form must not pass (protected feature, AT06), which
  deviates from doc 02's literal order.
  - `PC00`: every occurrence carries an approved form exactly, senses confirmed (AT01).
  - `PC01`: approved variants or inflection (AT02, AT05).
  - `PC02`: uniform but unapproved, or senses only `PROVISIONAL` (AT27).
  - `PC10`: differing unapproved forms, or a rejected form. Subkind `ORTHOGRAPHIC` at LOW severity when
    all forms are one edit from the main one (L3) (AT04).
  - `PC11`, `PC13` (only with declared negation markers, else `PCC_NEGATION_NOT_CHECKED`), `PC21`,
    `PC23` (`BLOCKED`).
  - Severity comes from code and category: key-term categories one level higher. Every finding carries
    the rendering distribution `form (n): refs`.
- **P6-6 self-qualification** (L4). Planted cases are drawn per occurrence from each group's majority
  rendering (up to 60 per kind in a Run, seeded). The verse copy is located again with the same model.
  - **Substitution:** another rendering the model knows for the same SOURCE word, a synonym, must give
    `PC10`; a random word, used only when none is known, may give `PC10` or `PC11`.
  - **Removal** must give `PC11`.
  - A rendering that occurs twice in the verse is not planted.
  - A kind at or above 80% recall, with at least 20 planted cases, is `CHECKED`.
  - **PO decision 2026-11-25: the check is best effort.** A kind below the bar, or with too few cases, is
    `BEST_EFFORT`, not withheld.
    - Its findings are still reported, each with an evidence line giving the measured recall (or "not
      measured"), and its detection confidence capped at that recall.
    - An exception report (`PCC_KIND_BEST_EFFORT`) says that some cases may be missed.
    - The Operator tunes the result through the reference-list workbook and the glossary import/export.
    - Nothing below the bar is ever counted as a pass.
- **P6-7 outputs.**
  - Run `validation/pcc/`: `findings.jsonl`, `occurrence-audit.jsonl` (every eligible occurrence exactly
    once, AT18), `summary.json` (no green total with open review), `qualification.json`.
  - Reports `localdata/reports/<job>/`: `PCC-CHECK.md` and `PCC-FINDINGS.xlsx` (formula-safe, blank
    *Decision* / *Scope* / *Note* columns for P7).
  - The menu prints counts and the report paths.
- **P6-8 evaluation** (`tools/evaluate_pcc_check.py`, local, counts only).
  - Setup: NIV SOURCE with its Biblical Terms list, scope John + Romans (1,312 verses, 315 groups
    compared), no glossary, so every group is learned-only. Self-qualification is the planted-error
    measure; up to 300 cases per kind, of which 225–264 could be planted. Real WIPs come from the local
    Paratext folder.

| WIP | Substitution recall (synonyms) | Removal recall | PC11 / 1000 verses (where checked) | Uncertain occurrences | Outcome |
|---|---|---|---|---|---|
| Spanish NVI | 79.8% (96 of 253 synonyms) | 84.8% | 108 | 7% | PC10 best effort (just under the bar), PC11 checked |
| Swahili Neno (prefixing) | 70.6% | 83.5% | 104 | 9% | PC10 best effort, PC11 checked |
| Hindi HCV | 72.9% | 87.9% | 104 | 10% | PC10 best effort, PC11 checked |
| Thai NCV (unspaced) | 58.7% | 33.2% | — | 27% | both best effort |
| Chinese CCB (unspaced) | no cases (character tokens) | 75.4% | — | 9% | both best effort |

  - Unspaced scripts fall below the bar automatically and are labelled best effort. No language code is
    used.
  - **Not measured:**
    - **Precision.** The `PC11` rate (about 10% of verses) is surely inflated by paraphrase and pronoun
      renderings. Measuring it needs the two-LLM false-alarm judging of §9, which waits for an LLM
      provider.
    - **Substitution recall.** It is under-stated by noisy plants: for a name, the model's
      second-best rendering is often a co-occurring word (*Judas* for *Iscariote*), not a synonym.
  - Both are open: plant quality, and the `PC11` false-alarm rate before the bar is relaxed or `PC11` is
    shown by default.
- Not in P6: the reverse scan (`PC12`, P8), the full rule resolver and the decision import (P7), and the
  advisory model (P10).
- Tests: `tests/pcc/test_pcc_check.py` (11).
  - The handover's fictional synthetic corpus covers syn-S1 (PC10 → PC01 once approved) and syn-S4
    (PC02 → PC00).
  - AT05 inflection and spelling, AT06 negation, AT07/AT12 omission vs uncertain, AT11, AT14, AT16,
    AT18, AT25 bridges, and self-qualification on a consistent fabricated corpus.
  - A Run-level check in `test_pcc_pin.py`.
- PCC 154 passed, `test_package.py` 19 passed, source audit PASS.

### P7 as built (2026-11-25): rule scopes, resolver, staleness and finding decisions

- **P7-1 scopes** (`pcc/resolver.py`). The existing contract levels are used. The plan's `GROUP` is
  `SECG`, and `LANGUAGE` is `LANGUAGE_PROFILE`.
  - `OCCURRENCE`: `<ref>|<nth occurrence of the group in the verse>|<verse hash>`. The hash covers the
    SOURCE verse and the paired WIP verse(s).
  - `PASSAGE`: `<range>#<hash of the WIP verses of the range>`. Passages from the P5 terms-list import
    (`PASSAGE:<ref>` without `#`) stay unbound.
  - `SECG`: the concept + sense group.
  - `LANGUAGE_PROFILE`: group `LANGUAGE`. An approved `a=b` form is a spelling equivalence added to the
    check's morphology; any other form is a rendering rule for every group.
  - Effects `ACCEPT` / `REJECT` / `CONTEXT_ONLY` (the existing enum).
- **P7-2 resolver** (`resolve`, pure).
  - All of a group's rules, in any state, help **locate** a rendering. Only approved rules that apply
    at the site and match its form class **decide**. The most specific scope wins (occurrence >
    passage > group > language), so a more specific `REJECT` beats a broader `ACCEPT` (AT24).
  - `PROPOSED` / `REVOKED` / `STALE` never accept (AT23).
  - Approved `ACCEPT` or `CONTEXT_ONLY` and `REJECT` of one form at the same, highest level is
    `CONFLICT`: the group is `PC23` and `BLOCKED`, with a `PCC_RULE_CONFLICT` exception report, and the
    Run continues (AT14, D9).
  - Each audit row names the deciding rule ids and level.
  - This replaces P6's group-level conflict test and the "approved forms only" lookup.
- **P7-3 staleness.**
  - Text-bound rules whose verse or passage text changed are not applied. They are reported per Run
    (`stale-rules.json`, `PCC_RULES_STALE`). A Run never writes the journal, because that would stale its
    own sealed decision snapshot.
  - The Operator marks them `STALE` (`MARK_STALE`) or revokes them under **Review stale rules**.
  - Group rules whose concept or sense is gone are marked `STALE` at re-pin (P5b-3). A changed entry
    whose sense key still exists keeps its rules: marking every rule of an edited concept stale was judged
    too aggressive.
- **P7-4 decisions** (`pcc/decisions.py`). The Operator imports a filled `PCC-FINDINGS.xlsx`; the
    workbook must come from the latest check Run (`PCC_FINDINGS_RUN_MISMATCH` otherwise).
  - `APPROVE_VARIANT` / `REJECT_FORM` turn the finding's unapproved forms into approved rules. The scope
    cell is blank/`GROUP`, `PASSAGE:<range>` (text-bound) or `OCCURRENCE` (one rule per occurrence,
    text-bound).
  - `CONFIRMED_ISSUE` / `DISMISS` / `DEFER` become `FINDING` review events (new operations
    `CONFIRM_ISSUE`, `DISMISS`, `DEFER`), and the stored record holds the decision and note.
  - Bad rows are reported by row number. A repeated import is idempotent.
  - **Finding identity is now stable:** `H(group, code, subkind, [(ref, nth, form class, verse hash)])`,
    with no Run input. A decided finding keeps `DISMISSED` / `CONFIRMED_ISSUE` / `DEFERRED` in later Runs
    until its evidence changes; then it is a new `OPEN` finding.
  - The check Run writes `finding-detail.jsonl` (each finding's occurrences, forms and statuses) and
    `wip-verse-hashes.json` for the import.
- **Menu** (Terms list and glossary, numeric keys as the menu contract requires):
  - 9: import decisions on check findings;
  - 10: review stale rules;
  - 11: revoke an approved rendering (`glossary.change_rule_state`).

  The Reference list menu's workbook actions moved to numeric keys as well. The letter keys of P5b-4
  would have been refused at run time once a list was pinned.
- **P7-5 determinism.** The same inputs and journal give identical findings, ids, details and audit, in
  any rule order. The rule view is rebuilt from the journal alone, and an edited or reordered journal
  still fails closed (P1).
- Tests: `tests/pcc/test_pcc_p7.py` (10) covers AT13, AT14, AT23, AT24, occurrence-scoped approval,
  stale binding, APPROVE_VARIANT → PC01, DISMISS persistence and expiry, bad rows, foreign workbooks,
  journaled state changes and determinism. Two menu tests were added. PCC 166 passed, `test_package.py`
  19 passed, source audit PASS.

### P8 as built (2026-11-26): reverse scan and issue clusters

- **P8-1 forms to scan** (`check.scan_forms`, REV01).
  - Each compared group's approved group-scope `ACCEPT` / `CONTEXT_ONLY` forms, plus forms the forward check located at
    two or more of the group's occurrences. `PC23` groups are skipped.
  - A form found in at least 15% of the scope's verses without the concept is not traced (`reverse_common_forms`).
    The WIP stop-word filter of P6 was tried first; it dropped frequent key-term renderings (a word for *God* in Romans).
- **P8-2 scan.** Only the Run's scope (`CheckInput.scope_units`; the WIP of other books is not scanned). An index of WIP
  comparison tokens (declared spellings applied, learned inflection removed) gives candidate verses; `find_form`
  confirms. One hit per group and verse pair; the group's own verses are skipped.
- **P8-3 SOURCE support, in order** (REV02, AT09). The first that holds decides:
  1. `SUPPORTED_RENDERING`: another compared concept is rendered with the same form in that verse.
  2. `SUPPORTED_WORDING`: the group's SOURCE wording is in the verse, in another sense or not compared.
  3. `SUPPORTED_ALIGNMENT`: some SOURCE word of the verse has t(WIP word | SOURCE word) or t(SOURCE word | WIP word)
     ≥ 0.05. There is no position prior, since languages reorder. This covers alternate constructions and explicit
     referents (a name for *he*).
  4. `UNCERTAIN`: less than 40% of the verse's SOURCE content words link. Nothing is claimed (REV03).
  5. Otherwise `ADDED` → `PC12`.
- **P8-4 findings.**
  - One `PC12` per group: `LOW`, detection confidence 0.3 (capped by measured recall), `OPEN`, never blocking. SOURCE
    and WIP are given by reference; the WIP form is quoted.
  - Subkind `NEAR_OMISSION` when the hit is within one verse pair of the same group's `PC11` in the same book. It then
    shares that `PC11`'s `issue_cluster_id` (AT29); both evidence traces stay.
  - **Clusters changed:** each finding is now its own issue (group, code, subkind) unless linked. Before, every `PC1x`
    of a group shared one cluster, so an unrelated `PC12` would have merged with a `PC10`.
  - `summary.json` gains `issue_clusters` (review and blocked findings, linked ones once) and `reverse_scan`
    (dispositions). Both are optional in the contract (terms Runs lack them).
  - `reverse-audit.jsonl` has one row per hit with its disposition and reason. `PCC-CHECK.md` gives the issue and
    reverse-scan counts. `PCC-FINDINGS.xlsx` gains an *Issue* column (the decision import reads columns by name).
  - Decisions: `PC12` takes `CONFIRMED_ISSUE` / `DISMISS` / `DEFER` only. A rendering decision on it is refused with the
    row number.
- **P8-5 self-qualification `INSERTION`.** A learned group rendering is planted at a random place in a scope verse
  without the group, its wording or that form. It must come out `ADDED`. Same bar, minimum and best-effort labelling
  as P6-6 (`PCC_KIND_BEST_EFFORT`).
- **Deviations.**
  - The OL `subjref` / `participantref` check of B5 is not done: the `SAGE_PCC_OL` package does not carry them. Explicit
    referents are covered by alignment support (P8-3 step 3).
  - The handover's optional "salient TARGET phrase" discovery is not built.
- **P8-6 evaluation** (`tools/evaluate_pcc_check.py`, same setup as P6-8: NIV, John + Romans, 1,312 verses, no glossary,
  300 planted insertions):

| WIP | Hits outside the group | Supported (rendering / wording / alignment) | Uncertain | `ADDED` | `PC12` findings / 1000 verses | Insertion recall |
|---|---|---|---|---|---|---|
| Spanish NVI | 3,245 | 1,220 / 198 / 1,721 | 7 | 99 | 29.7 | 75.3% (best effort) |
| Swahili Neno | 3,062 | 911 / 290 / 1,761 | 16 | 84 | 32.8 | 55.7% (best effort) |
| Hindi HCV | 3,223 | 966 / 271 / 1,815 | 16 | 155 | 35.1 | 71.7% (best effort) |

  - **Why insertions are missed (Spanish, 74 of 300).** 5 were uncertain verses. 69 were "supported" by alignment;
    for 34 of these the only link was backward from a SOURCE function word.
  - **Trade-off.** Ignoring that path would give 86.7% recall (checked). It would also add 58 real candidates
    (99 → 157), likely explicit referents, at unmeasured precision. Because false alarms are the named reverse-scan
    risk (§10), the permissive rule is kept and `INSERTION` is best effort.
  - **Open:** the `PC12` false-alarm rate, by two-LLM judging (§9). This waits for an LLM provider, as for `PC11`.
- Tests: `tests/pcc/test_pcc_p8.py` (7) covers:
  - AT08: an unsupported addition is `PC12`, low, open and contract-valid; a clean text has none.
  - AT09: an alternate SOURCE word rendered the same way suppresses it.
  - REV02/REV03: the same wording in another sense is supported; a verse that does not align is uncertain.
  - AT29: a moved rendering shares the `PC11` cluster, and an unrelated addition is its own issue.
  - The scope bounds the scan.
  - Insertion self-qualification, and determinism.
  - `PC12` decisions: `DISMISS` holds in the next Run, and `APPROVE_VARIANT` is refused.

  The pin test checks `reverse-audit.jsonl` and `issue_clusters`. PCC 173 passed, `test_package.py` 19 passed,
  source audit PASS.

### P5b plan (reference lists, D12–D20)

PCC is alpha and this is a clean instance, so there is no migration. P4/P5 Job-local list data is
replaced, not converted.

| Step | Work | Files | Done when |
|---|---|---|---|
| **P5b-0** Word aligner (§5b.7 step 1, R3/R4) | `pcc/align.py`: **gold path** for a BSB reference from `SAGE_PCC_OL` `bsb-alignment.tsv` (P5b-R); **transitive path** for NIV and other English references: reference ↔ BSB (same language; identical and stem-equal tokens anchor, EM fills the rest) composed with the BSB gold; **direct path** (other languages, fallback): IBM Model 1 + position prior, both directions, keeping only links both agree on, with a posterior threshold, Hebrew prefix/suffix segments as OL tokens; cache by (reference hash, OL package hash, aligner version). `tools/evaluate_pcc_alignment.py`: precision/coverage against the BSB tables per testament, counts only. Shared with P6-3 (SOURCE ↔ TARGET) | new `align.py`, new tool, `name_alignment.py` (shared helpers) | Greek ≥ 90% precision at ≥ 70% coverage (prototype: 92% / 70%); Hebrew bar set and met after the segment fix; deterministic output |
| **P5b-1** Identity and package | `ids.concept_key` (D13), wordings as realizations under a concept; `pcc/reflist.py`: RL contract (`reference_list_manifest`, `reference_list_entry` in `contracts.py`), `build` / `verify` / `load`, store under `localdata/inputs/resources/reference-lists/`, fork-on-clash import, license flag; replace `group_id`'s scope policy by `concept_key` + sense | `ids.py`, `contracts.py`, new `reflist.py`, `sense.py`, `glossary.py` | Same inputs → byte-identical package; a changed byte fails `verify`; a group ID is unchanged across scope and threshold changes |
| **P5b-2** Top-down build (D14 revised, D17, D19) | Inventory (Biblical Terms if imported ∪ Key Concepts package ∪ declared ∪ inherited KEEP − DROP) → realize every OL occurrence through the P5b-0 alignment (`NO_REALIZATION` counted) → partition senses by head stem + case feature (outside sentence start, `\nd` kept), S2 renderings merged, rare wordings to "other renderings" → select at least 3 verses per concept sense over the whole reference → left-out summary by reason. N-gram discovery no longer creates entries (kept only to locate unanchored declared phrases). Elision split (§5b.3 finding 4). Progress per book | `reflist.py`, `align.py`, `sense.py` (OL splits), `segment.py` (case kept beside `norm`), `traits.py` | Whole Bible in a few minutes (aligner cached); NIV JHN: *Jews* and *Jewish leaders* are separate senses of Ἰουδαῖος; no function words among the realizations of πνεῦμα / σάρξ / νόμος; *God*, *Lord*, *eternal life*, *Son of Man* present; byte-identical rebuild |
| **P5b-3** Job pin and terms Run | Job wizard picks (or builds) an RL for the SOURCE edition; `job.defaults.reference_list = {rl_id, version, sha256}`. A terms Run = RL entries ∩ scope + `phrases.txt`, located in the Job's SOURCE. `assign_senses` gets a **fixed-candidates** mode (the RL's lemma keys, per occurrence; no re-choosing). SOURCE hash ≠ RL hash → entries `PROVISIONAL` (`RELOCATE` at run time). Re-pin action with carry-over report and `STALE` rules. One-time WIP attach (D16) | `run.py`, `pcc_menu.py`, `jobs.py` defaults validation, `sense.py` | Rules survive a re-pin by `concept_key`; dropped entries → `STALE`; snapshot seals the RL hash; stale RL hash → `PCC_RUN_INPUT_STALE` |
| **P5b-4** RL workbook | Export `RL-<id>-v<n>.xlsx` (§5b.4); import → new version + `RL-DIFF.md`; formula-safe cells. Move the overlay verdicts into RL entry status; delete `overlay.py` and the "Review core lists" overlay path (the review screens edit a new RL version instead) | `reflist.py`, new `reflist_xlsx.py`, `pcc_menu.py` | Export → edit → import round trip; bad rows reported by row number and the rest applied; no global overlay file is written |
| **P5b-5a** Key Concepts package (D18 S4b, R5, R7) | `tools/build_pcc_concepts.py`. **Single-lemma candidates:** MACULA content lemmas in ≥ 3 verses. **Multi-lemma candidates:** unordered lemma sets in a short window with at least one noun, rendered by BSB as one contiguous unit in most occurrences (gold alignment, D20), or MACULA word groups if the package gains them. Count candidates and budget LLM calls first. Advisory verdict ("key concept a team must render consistently?" / "single unit of meaning?") `CONFIRM`/`REJECT`/`UNSURE` through `candidates.py` with receipts, on the selected provider (Claude Phase 4 or Codex). Only `CONFIRM` ships, as `PROPOSED` concepts. Package `app/system/resources/pcc-concepts/<date>/`: OL keys, MACULA CC BY glosses, BSB example wording, no NIV, no Biblical Terms content; pin file, `verify` mode; closes P3b | new tool, `resources/pcc-concepts/`, `reflist.py` | Recall and precision against Biblical Terms recorded (local only); *eternal life*, *kingdom of God*, *Son of Man* in; *down from heaven* out; two-LLM agreement on a seeded sample (§9); byte-identical verify |
| **P5b-5** Inheritance (D14 revised) | Build an RL for reference B with a base RL A: concept KEEP / DROP, declared phrases (with OL anchors), notes and category switches carry by `concept_key` as `PROPOSED`; B's own realizations come from B's alignment. Declared phrases without an OL anchor are `RELOCATE`d by wording (same language only) or reported. Lineage in the manifest | `reflist.py` | NIV → NIV Anglicised and NIV → Spanish NVI inheritance runs; carried / not-realized counts reported; nothing derived is `ACTIVE` without review |
| **P5b-6** Exchange | RL export/import as one checksummed `.sagerl.zip` (package folder). `transfer.py` becomes the **glossary bundle**: renderings keyed by `concept_key` + wording + lemma (re-matched by key, else by wording + lemma), same target language | `reflist.py`, `transfer.py`, `pcc_menu.py` | Export on one instance, import on another (test: two temp workspaces); tampered bundle refused; license warning shown for NIV-derived RLs |
| **P5b-7** Menu | PCC home gains **Reference lists** (list, build, derive, export, import, edit via workbook, show diff), outside any Job. The Job's terms menu keeps the glossary actions only | `pcc_menu.py`, `menu-localization.json` | Menu tests; an Operator can build and pin an RL without creating a Job first |

Evaluation (P5b): alignment against the BSB tables, Key Concepts against Biblical Terms (local), sense
partition and Key Concepts precision by two LLM judges (§9); there is no hand labelling.

### P6 plan (Function B forward)

**Inputs sealed in the Run snapshot:**

- the pinned RL hash;
- the glossary rule view hash (journal head);
- SOURCE, secondary and WIP hashes;
- WIP traits (§7 L1) and language facts (§7 L2);
- the alignment and qualification settings.

| Step | Work | Done when |
|---|---|---|
| **P6-1** Verse pairing | WIP verse units (`numbers.target.target_units`, visible body text); SOURCE ↔ WIP pairing through `verse_alignment.align_records` and both VRS files; bridges and splits become `EQUIVALENCE_GROUP` units (AT25). Unpaired SOURCE verses → occurrences `PC21` with reason `NO_TARGET_VERSE` | Fabricated split/merged verses pair correctly or give `PC21` |
| **P6-2** Groups | Only `ACTIVE` (key-term) RL entries and Operator additions form groups (D17); common words are never traced. Eligible groups from the terms analysis (P5b-3): confirmed occurrences per `concept_key` + sense; fewer than 2 confirmed verses → `INFORMATIONAL` (AT16); unresolved sense → `PC20` (AT11). Secondary SOURCE is advisory only (AT15) | AT11, AT15, AT16 |
| **P6-3** Learned alignment | The P5b-0 aligner (`pcc/align.py`; cached by SOURCE + WIP hash), run once per Run over all paired verses in scope, both directions; per-occurrence TARGET span = the contiguous TARGET token run that maximises the expression's alignment mass. Each span gets a reliability score (agreement of both directions + mass); unreliable → `PC21` (AT12). One SOURCE phrase → several TARGET units: span set, never auto-`PC11` (AT10). Learned TARGET affixes (suffixes now; prefixes per `TODO-20261016-003`) reduce forms to stems for comparison only | AT10, AT12; spans reconstruct exactly from offsets |
| **P6-4** Approved-rendering match | For each occurrence: does an approved rendering (glossary rule, D13 key) occur in the mapped verse(s), allowing learned inflection (`TGT02`) and approved orthographic equivalences (L2)? A match beats a learned span. Rule resolution here is the simple form (group-scope `APPROVED` / `REJECTED`); P7 replaces it | Approved match with inflection on fabricated prefixing and suffixing languages |
| **P6-5** Classification per group | **Pass outcomes:** `PC00` (all occurrences carry approved renderings, sense confirmed, entry reviewed) (AT01), `PC01` (differences explained by approved variants or learned inflection) (AT02, AT05), `PC02` (uniform but unapproved, or sense only provisional) (AT27). **Review:** `PC10` (differing unapproved forms; subkind `ORTHOGRAPHIC` at `LOW` severity per L3) (AT04), `PC11` (reliable alignment, adequate context, no TARGET support) (AT07), `PC13` (negation or polarity, only when negation facts are declared, else `NOT_CHECKED`) (AT06). Every `PC10` / `PC11` carries the rendering distribution (counts + references). Severity from the code and category (key terms higher), never from confidence | AT01, AT02, AT04–AT07, AT27 |
| **P6-6** Self-qualification (§7 L4–L5) | Plant substitutions and removals into an in-memory WIP copy, seeded, over eligible groups; measure recall per kind; below the bar (80%, tunable in the snapshot) → that kind `NOT_CHECKED` with the measured recall. Evidence minimum for `PC11` set from the same pass | A tiny or unspaced fabricated WIP reports `NOT_CHECKED`, not a pass |
| **P6-7** Outputs | Run `validation/`: `findings.jsonl`, `occurrence-audit.jsonl` (one disposition for **every** eligible occurrence), `summary.json` (handover coverage formulas; never a green total with open review). Reports: `localdata/reports/<job>/PCC-CHECK.md` + `PCC-FINDINGS.xlsx` (one row per finding, blank *decision* / *scope* / *note* columns for P7), exception reports for `NOT_ASSESSED` areas. TARGET quoted verbatim with references; SOURCE by reference (NIV limit) | Every eligible occurrence appears exactly once in the audit; stable ordering (AT18) |
| **P6-8** Evaluation | Planted-error recall per kind on real WIPs, local only, counts only. Use Biblica projects from the local Paratext folder: NIV as SOURCE; WIPs Spanish NVI, Swahili Neno (prefixing), Hindi and one unspaced script (Thai or Chinese). A prefixing language and an unspaced script are part of the gate (§9). False-alarm sample via two LLM judges for `GOOD`-rated languages only | Recall bars recorded per language; unspaced → `PARTIAL` reported honestly |

Out of P6: specificity and conflicts (P7), reverse scan (P8), advisory model (P10).

### P5b-5 (part) and P5b-7 as built (2026-11-26): shared reference lists, two-function menu (D21)

- **Menu** (`pcc_menu.py`). PCC home: *Reference lists* (function 1, no Job needed), *Open / Set / Add new PCC
  JOB* (function 2). Reference lists: show lists and versions (with the Jobs that pin them), build from a text,
  build from an existing list, export / import the curation workbook, add Operator wordings, add Paratext Biblical
  Terms, compare two versions. Inside a Job the same menu adds *pin / re-pin* and, for older Jobs, *move this Job's
  own wordings into its list*. The Job menu keeps the WIP side: terms Run, check Run, **Glossary** (fill-in sheet,
  TermRenderings, review, glossary bundle, own renderings list, findings decisions, stale rules, revoke), Reference
  list, Manage (delete, recovery, attach a WIP once). Skip choices use key `3` (menu keys must be numeric).
- **Inheritance** (`rlservice.inheritable_entries`): a base list on **another text** gives a **new `rl_id`**;
  kept concepts arrive `PROPOSED`, `DROPPED` stay out, `WORDING` concepts carry only into the same language (the
  others are listed in `build.summary.inherited`). A base on the **same text** is a rebuild: next version of the same
  list, statuses kept. Previously any base reused the base's `rl_id`, so a list for another text would have
  become a version of the base list.
- **Operator wordings and Biblical Terms** write a new version (`reflist_xlsx.add_wordings`,
  `rlservice.add_biblical_terms`, both `MERGE` with a summary and an `RL-DIFF` report);
  `reflist_xlsx.compare_versions` writes `RL-COMPARE-<id>-v<a>-v<b>.md`. List reports go to
  `localdata/reports/pcc-reference-lists/`.
- **No Job-local SOURCE wordings.** `transfer.import_bundle` and `import_operator_list` no longer write
  `input/phrases.txt` or the Job key-terms file; wordings not on the terms list come back in
  `ImportReport.missing_wordings` and the menu offers to add them to the pinned list (new version + re-pin). An older
  Job's `phrases.txt` is still located by terms Runs until moved (`phrases.job_phrase_lines`,
  `retire_job_phrases` keeps the file as `phrases.moved-<date>.txt`). The Job key-terms file is still read for
  older Jobs; the menu no longer writes it. The bundle export file is now `<job>-glossary-bundle.json`.
- **Measured** (scratch store, John): usNIV list with Paratext Biblical Terms, 141 concepts → idKKHv0 built from
  it: new list, 108 concepts `PROPOSED`, 31 below recurrence in idKKH, 1 multi-word Biblical Terms phrase
  `NOT_LOCATABLE` (inheritance does not carry a `BT` concept's verse list yet), 1 `NO_REALIZATION`; base list
  unchanged. About 9 s each with the alignment cached.
- **Docs**: Operator guide `docs/PCC-CHEAT-SHEET.md`, flow `docs/advanced/workflows/PCC-FLOW.md`.
- **Tests**: `tests/pcc/test_pcc_shared_lists.py` (derive to another text / rebuild, wordings, compare, missing
  wordings, phrases move), `test_pcc_menu.py` rewritten for the new menus. PCC + package tests: 220 passed.
- **Still open**: P5b-5 notes/declared-phrase relocation beyond the above and carrying `BT` verse lists; P5b-6
  (`.sagerl.zip` exchange); P5b-5a (Key Concepts package).

### WIP lists as built (2026-11-26, D22)

- `sage/pcc/layers.py`: `create_clone`, `diff_changes` (ADD with full entry / SET of status, category, notes;
  a master concept missing from the clone is a SET DROPPED), `apply_changes`, `update_clone`, `merge_to_master`
  (chosen change ids + Operator edits, from the newest master), `export_changes` / `read_changes`
  (`RL-CHANGES-<list>-v<n>.xlsx`). Reports `RL-UPDATE-*`, `RL-MERGE-*`.
- `reflist_xlsx.store_changes` keeps a clone in mode `LOCAL` and recomputes `build.local` against its parent, so
  workbook import, Operator wordings and Biblical Terms work on clones unchanged. Contract: `build.parent` and
  `build.local` optional; mode `LOCAL` added.
- Menu: a Job pins a master by cloning it (at creation, Reference list -> 11, and after building a master from a
  Job); inside a Job, list actions act on the Job's WIP list (an older Job pinned to a master is offered a clone);
  Reference lists -> 9 Update a WIP list from its master, 10 Merge (all / choose / export / import workbook);
  Show lists nests WIP lists under their master with added / left-out counts.
- Tests: `tests/pcc/test_pcc_wip_lists.py` (record, add, update with master-drop rule, merge all/chosen/workbook),
  menu merge flow in `test_pcc_menu.py`.

### P5b-6 as built (2026-11-26): list exchange and concept-keyed glossary bundle

- `sage/pcc/rlexchange.py`: `export_list` writes `<rl_id>-v<n>.sagerl.zip` (index `SAGERL.json` with format,
  main list, packages with their `CHECKSUMS.sha256` hashes, `local_only`, license ids and an index SHA-256; members
  `packages/<rl_id>/<v>/{MANIFEST.json, entries.jsonl, CHECKSUMS.sha256}`; fixed zip timestamps, so exports are
  byte-reproducible). A WIP list is exported with its master version. `read_package` refuses non-zips, duplicate
  or unexpected member names (no path traversal), oversize packages (512 MB), a changed index, and packages that
  differ from the index or fail their own checksums, before anything reaches the store. `import_list` imports
  masters first through `ReferenceListStore.import_package` (kept / imported / forked, never overwrites) and notes a
  forked master of a WIP list and the local-only flag.
- Glossary bundle (`transfer.py`): rules carry `group_id`; `_propose` matches the group first, then wording +
  lemma. Bundles without `group_id` still import by wording.
- Menu: Reference lists -> 11 Export a list to share (local-only lists ask first), 12 Import a shared list (inside
  a Job: offer to clone a master or pin a WIP list); Job-only options move to 13 (pin) and 14 (move phrases).
- Tests: `tests/pcc/test_pcc_exchange.py` (two stores: move, reproducible bytes, kept, WIP list with master then
  merge, fork, tampered index / entries / unsafe member / non-zip refused, group-keyed bundle match) and a menu
  export -> import test. Real data: the idKKH John WIP list with its master is a 33 KB package; imported into an
  empty store with the local-only note.
- Not done: exporting all versions of a list (history) in one package.

### Widening a list when the reference text grows (2026-11-26)

- Lists are built on every book of the reference text present at build time (menu); the tool may restrict books.
  The list records `build.settings.books`. WIP growth needs no list change: Runs take the Operator's scope.
- Same-text rebuild (Build from an existing list, same text) reads all present books, offers Biblical Terms again
  (previously only for another text, so new-book-only concepts could not enter), keeps inherited statuses, keeps base
  `DROPPED` entries (previously removed, losing the decision for later builds), and keeps any non-dropped concept it
  cannot locate again unchanged (`inherited.kept_unchanged`; e.g. multi-word `BT` phrases without their verse list).
- `add_biblical_terms` reports when the text has more books than the list covers. `PCC_RL_NO_TEXT` stops a build that
  reads no verses (found when a mis-split book list read 0 verses and would have written an empty-text version).
- Show lists: coverage line (`source_text.books_label`, e.g. "30 books (NT and 3 OT books)") and warnings when the
  text gained books or its content hash changed.
- Measured: usNIV John list 141 -> NT 686 concepts, 7,958 verses, 39 s, all 141 carried.

### P9 acceptance matrix AT01–AT30 (audit 2026-11-26)

Each handover acceptance case (doc 08) against the test that proves it, a decided deviation, or an open gap.
Tests are in `app/system/tests/pcc/`.

| AT | Expected | Status | Evidence |
|---|---|---|---|
| 01 | PC00 | covered | `test_pcc_check::test_synthetic_s4_…` |
| 02 | PC01 | covered | `test_pcc_check::test_synthetic_s1_…` |
| 03 | two senses, no cross obligation | covered | `test_pcc_p4::test_divergent_lemmas_split…`, `test_pcc_rlbuild::test_senses_split_by_case…` |
| 04 | PC10 | covered | `test_synthetic_s1` |
| 05 | PC01 through grammar | covered | `test_learned_inflection_and_declared_spelling…` |
| 06 | PC13 | covered | `test_negation_shift_only_with_declared_markers` |
| 07 | PC11 | covered | `test_omission_with_reliable_alignment_is_pc11…` |
| 08 | PC12 | covered | `test_pcc_p8::test_rendering_without_source_support…` |
| 09 | no PC12 | covered | `test_pcc_p8::test_alternate_source_construction…` |
| 10 | multi-unit rendering, no automatic PC11 | **open** | no PC11 (a learned span is found), but a rendering split by other words gives a spurious PC10: `check.learned_span` keeps one contiguous run (gaps of 1 bridged), not the span set P6-3 describes. Needs a recall re-measure before changing |
| 11 | PC20 | covered | `test_single_verse_groups_…_pc20` |
| 12 | PC21, not PC11 | covered, **fixed** | `test_omission_…weak_alignment_is_pc21`; `test_pcc_acceptance::test_at12_…` (a group with PC21 occurrences was PC02 in one branch; now PC21) |
| 13 | STALE | covered | `test_pcc_p7::test_text_bound_rules_go_stale…`, `test_pcc_pin::test_repin…stale` |
| 14 | PC23 | covered; D9 | the group only is `BLOCKED`; the Run continues |
| 15 | secondary SOURCE advisory | covered (no advisory output) | `test_pcc_acceptance::test_at15_…`: same groups, audit and findings with and without a secondary; `PRIMARY_CONTROLS` sealed. No advisory comparison is produced yet |
| 16 | informational | covered | `test_single_verse_groups_are_informational…` |
| 17 | footnotes and headings excluded | covered | `test_pcc_acceptance::test_at17_…` (behavior was already correct) |
| 18 | deterministic | covered | `test_pcc_p7::test_check_outputs…deterministic`, `test_pcc_p1::test_run_outputs_are_identical…` |
| 19 | PC24 | D7 | Job-creation errors: `test_pcc_p1::test_pcc_job_creation_rejects_invalid_contracts` (now also secondary = SOURCE, a WIP as secondary, an unknown Project) |
| 20 | PC25 / integrity | covered, **fixed** | hash changes stop the Run (`test_run_stops_when_the_source_changes…`, `test_changed_list_package_stops…`, tamper tests); malformed Biblical Terms references are now reported (`test_pcc_acceptance::test_at20_…`). Open: a verse record the USFM compiler cannot read is dropped by the shared `numbers.target.target_units` without a PCC report |
| 21 | nested phrases, no issue inflation | covered, **fixed** | `test_pcc_p3::test_nested_phrase_deduped…`; `test_pcc_acceptance::test_at21_…` (same-code findings on overlapping SOURCE spans now share one issue cluster: `check.merge_overlapping_clusters`) |
| 22 | lexically different forms separate | D18/D19 | groups are concept + head-word sense; different heads split |
| 23 | no automatic pass | covered | `test_pcc_p7::test_proposed_revoked_and_stale_rules_never_accept` |
| 24 | REJECT wins | covered | `test_pcc_p7::test_most_specific_rule_wins…` |
| 25 | versification spans or PC21 | covered | `test_bridged_and_missing_verses` |
| 26 | other scripts | covered, **fixed** | `test_pcc_p2::test_unspaced_script_gets_character_tokens`; `test_pcc_acceptance::test_at26_…` (an approved multi-character form never matched an unspaced WIP's single-character tokens; `check.form_tokens` now cuts forms the way the WIP side is cut) |
| 27 | PC02 | covered | `test_synthetic_s4` |
| 28 | REFERENCE byte-identical | covered | `test_pcc_p1::test_reference_resources_stay_byte_identical` |
| 29 | linked issue cluster | covered | `test_pcc_p8::test_moved_rendering_shares_the_omission_cluster` |
| 30 | absent phrase is a candidate | covered | `test_pcc_p3::test_local_phrase_never_pruned…`, `test_pcc_p1::test_terms_run…` |

### P9 whole-Bible benchmark (2026-11-26, Apple silicon laptop)

| Step | Text | Result | Time | Peak memory |
|---|---|---|---|---|
| Build a list (alignment cached) | usNIVv2, 66 books, Paratext Biblical Terms | 31,219 verses, 2,233 concepts | 28 s | 2.4 GB |
| Build from that list (cold alignment) | spaNVIv3, 66 books | 1,906 concepts carried and located (all PROPOSED), 291 below recurrence, 34 not rendered | 184 s | 2.9 GB |
| Check, no glossary (every group learned-only), self-qualification on | usNIVv2 -> spaNVIv3, 66 books | 31,215 verse pairs, 3,235 groups compared; outcomes PC10 1,362, PC02 943, PC11 903, PC21 27; 6,615 issue clusters; per 1,000 verses PC10 44, PC11 51, PC12 45, PC20 31, PC21 43; planted recall substitution 78%, removal 78%, insertion 75% (all below the 80% bar: BEST_EFFORT) | 2,423 s (model training 1,135 s; ran alongside the test suite, so slower than alone) | 4.1 GB |

Reading: a whole-Bible check runs in one go on a laptop. With no approved renderings the review load is high
(6,615 issues), because every uniform-but-unapproved and every differing learned rendering is reported; approved
renderings turn most groups into PC00/PC01. The model training step dominates and is the first optimization target.

### P7 plan (rule resolver and decisions)

| Step | Work | Done when |
|---|---|---|
| **P7-1** Rule scopes | `variant_rule.scope`: `OCCURRENCE` (`concept_key` + verse ref + nth occurrence + verse-text hash), `PASSAGE` (reference range + text hash of its verses), `GROUP` (`concept_key` + sense), `LANGUAGE` (inflection or orthographic rule for the WIP language). Effects `APPROVE` / `REJECT` / `CONTEXT_ONLY` | Contracts and validators; journal round trip |
| **P7-2** Resolver | Pure function: applicable rules for an occurrence ordered occurrence > passage > group > language; the most specific decision wins; a more specific `REJECT` beats a broader `APPROVE` (AT24); `PROPOSED`, `REVOKED`, `STALE` never accept (AT23); equal-scope `APPROVE` + `REJECT` for the same form → `PC23` for that group only: group `NOT_ASSESSED` + exception report, the Run continues (D9) (AT14). Each audit row names the rule ID it used | AT14, AT23, AT24; every acceptance names its rule |
| **P7-3** Staleness | A rule is `STALE` when: its `concept_key` is gone from the pinned RL; its sense changed; the SOURCE or WIP text hash bound to its scope changed (AT13); or the RL is re-pinned and the entry changed. `STALE` rules are listed for re-review and never deleted | AT13 |
| **P7-4** Finding decisions | Import the filled `PCC-FINDINGS.xlsx`: decisions `APPROVE_VARIANT` (→ rule at the chosen scope), `CONFIRMED_ISSUE`, `DISMISS`, `DEFER`, `REJECT_FORM`. Each one is a `review_event` in the Job journal with actor and evidence. Finding identity is stable: `H(concept_key, sense, code, coordinate, TARGET form, verse-text hash)`. A decided finding keeps its `review_status` in later Runs until its evidence changes. Menu: revoke a rule; review stale rules | Decide → re-run → `PC10` becomes `PC01` with the rule named; dismissed findings stay dismissed until the text changes |
| **P7-5** Determinism | Same inputs + same journal → byte-identical outputs and IDs (AT18); the materialized rule view rebuilds from the journal alone | AT18 test with shuffled journal replay refused and identical rebuild |

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

2026-11-25: D12, D15, D17 (in principle), D18, D19 and D20 decided by the PO; D3 corrected for Clear word
senses; D13, D14 (revised) and D16 recommended. P5b-R (the `SAGE_PCC_OL` package) is built and in the
distro; P5b-0 (word aligner), P5b-1 (concept keys, RL packages and store) and P5b-2 (top-down build,
alignment cache) and P5b-3 (Job pin, terms Run from the list, re-pin, WIP attach) are built. P5b-4 (RL
workbook, overlay removed) and P6 (forward check with self-qualification) are built. Open from P6: PC11
false-alarm rate and substitution plant quality (§ P6 as built). P7 (scopes, resolver, staleness, finding decisions) is built.
P8 (reverse scan, `PC12`, issue clusters) is built (2026-11-26), so the handover's Stage 1 functions (M0–M6) exist.
2026-11-26: D21 and D22 decided (WIP lists: Job clones the master, Operator merges changes); P5b-7 (reference-list menu outside a Job, two-function menu) and the core of P5b-5
(building a list from another list) are built, with an Operator guide and a flow document.
P5b-6 (list exchange, concept-keyed glossary bundle) built 2026-11-26; P5b-5 completed (Biblical Terms phrases
carry their verse lists); P9: SAGE Help, limitations, notices, acceptance matrix (AT10 open) and whole-Bible benchmark done.
Open: P5b-5a (Key Concepts package), AT10 (span sets), PCC report layout in SAGE conventions, and the `PC11` / `PC12` false-alarm rates (two-LLM judging, waits for a provider). Order: P5b-0 → P5b-1 → P5b-2 → P5b-3 → P6, with
P5b-4..7 alongside P6 (P5b-5a needs an LLM provider) → P7. Revised 2026-11-25 after the §5b.7 review.
