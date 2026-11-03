# SAGE PCC Stage 1 — Consolidated Claude Handover
**Important:** This is a specification; no checker has been implemented. Stage 1 uses local JSON/JSONL/Markdown/TXT only and excludes database and remote service dependencies.
Use the ZIP for schemas, editable examples, fixtures and the QA script. This master is for reading/copying into Claude as one document.


---

<!-- SOURCE FILE: README.md -->

# SAGE Phrase Consistency Checker (PCC) — Stage 1

**Claude Code / VS Code engineering handover**  
**Status:** Implementation specification and example contracts, **not an implemented SAGE feature**.  
**Date:** 2026-11-02  
**Architecture:** local files + existing SAGE execution environment; **no SQL, no databases, no SQS**.

## Purpose
Implement a source-anchored, bidirectional phrase/term consistency check in SAGE. A recurrence obligation exists only for the **same normalized SOURCE wording in the same contextual sense**. TARGET expressions may vary if equivalent under approved linguistic rules or specifically approved contextual exceptions. Search TARGET independently for *probable* semantic additions, but report them for review; do not assert errors without evidence.

## Essential invariants
1. SOURCE authority derives exclusively from the translation brief; in a primary/secondary brief, the primary controls and the secondary supplies comparative evidence.
2. Do not use Hebrew/Greek or original-language indexes within PCC. Existing OL review is a separate optional escalation path.
3. SOURCE expression + contextual sense + controlling SOURCE version + brief scope form a **Source Expression Consistency Group (SECG)**.
4. Minimum **two confirmed eligible same-sense occurrences** for a recurring consistency obligation; other cases remain informational.
5. Identical TARGET wording does **not** establish semantic equivalence; nonidentical TARGET wording does **not** establish an error.
6. Probable additions, omissions, semantic shifts, and ambiguities are review findings, never automated verdicts.
7. Preserve source text, spans, traceability, version hashes, approved exceptions, and reviewer decisions.
8. Shipped authorized REFERENCE resources are immutable. Project-local discovery and overrides are separate.
9. Do not overwrite SOURCE/TARGET, silently rewrite approved decisions, or suppress unresolved findings.
10. Only use local text storage: **UTF-8 .json, .jsonl, .md, .txt**. No database layer.

## Reading order
1. `CLAUDE.md` — mandatory Claude implementation guardrails.
2. `docs/00_SCOPE_AND_DECISIONS.md`
3. `docs/01_ARCHITECTURE_AND_INTEGRATION.md`
4. `docs/02_MATCHING_ENGINE.md`
5. `docs/03_TEXT_STORAGE_AND_SCHEMAS.md`
6. `docs/04_EXCEPTION_GOVERNANCE.md`
7. `docs/05_FINDINGS_AND_REPORTS.md`
8. `docs/06_OPERATOR_WORKFLOW.md`
9. `docs/07_MILESTONES_AND_TASKS.md`
10. `docs/08_TESTS_AND_ACCEPTANCE.md`
11. `docs/09_SECURITY_AND_REPRODUCIBILITY.md`
12. `docs/10_REPO_DISCOVERY_AND_OPEN_ITEMS.md`
13. `docs/11_CLAUDE_START_PROMPT.md`
14. `docs/12_GLOSSARY.md`
15. `docs/13_REFERENCE_INDEX_BUILDER.md`
16. `docs/14_LANGUAGE_AND_CULTURE_RULES.md`
17. `docs/15_CLAUDE_IMPLEMENTATION_WORKPACKS.md`
18. `PCC_REPO_FIT_TEMPLATE.md`

Supporting material: `contracts/*.schema.json`, `samples/*`, `fixtures/synthetic/*`, and `tools/validate_package.py`.

**Before installing in SAGE:** Do not replace an existing project `CLAUDE.md` blindly. Give Claude the handover folder or merge these scoped guardrails into the repository's existing agent instructions after inspecting them.

**Local QA:** `python tools/validate_package.py` (requires QA-only `jsonschema` dependency from `tools/requirements-dev.txt`).

## Integration caveat
The actual SAGE repository, language/runtime, CLI, importer, existing check result format, and authentic authorized REFERENCE files were **not supplied**. Claude must inspect the real repository first, reusing its existing entry points and conventions. The paths and commands in this handover are **proposed interfaces**, not claims about existing SAGE functionality. No copyrighted source translation is bundled.

## Deliverable definition
The result must be a working, tested local SAGE module (not a separate hosted service) with versioned REFERENCE phrase indexes, local input phrases, deterministic matching, scoped linguistic exceptions, candidate reverse matching, JSON/JSONL and Markdown reporting, CI fixtures, documentation, and graceful behavior when no semantic reviewer is configured.


---

<!-- SOURCE FILE: CLAUDE.md -->

# Claude Code implementation contract — SAGE PCC Stage 1

You are implementing the SAGE **Phrase Consistency Checker (PCC)** from the attached handover inside the existing SAGE repository. **Inspect repo reality before changing anything.**

## Nonnegotiable scope
- Stage 1 is **local only**: UTF-8 `json`, `jsonl`, `md`, `txt`; use in-memory lookups and rebuildable text-derived indexes. **No SQL, SQLite, relational database, SQS, hosted cache, cloud service, or schema migrations.**
- Use SAGE's existing runtime, CLI/executor, check conventions, and logging. Do not introduce an unrelated language/framework or a new stand-alone application unless required by existing architecture.
- No original-language/OL index dependency or OL-based decision in this checker.
- Do not invent, embed, fetch, or redistribute copyrighted Bible translations. Tests use explicitly fictional synthetic text.
- Do not assume the provided illustrative command syntax is already supported.
- SOURCE text and TARGET text are read-only; authorized REFERENCE indexes are read-only; persist decisions in project-local text files.

## First task (discovery gate)
1. Inspect repo structure, project entrypoints, CLI, test harness, configured input formats, book/verse parser, versification rules, source/target authority model, language profiles, findings/report contracts, and any existing file locks/atomic writes.
2. Create a concise `PCC_REPO_FIT.md`: confirmed reuse points, integration gaps, decisions to clarify, implementation file map, and acceptance-test invocation.
3. Where specification conflicts with established SAGE contracts, follow SAGE conventions **without changing semantic invariants**; record adaptations in `PCC_REPO_FIT.md`.
4. Implement in small, verifiable milestones. After each milestone run relevant tests and report changed files, tests, blockers, and next milestone.

## Engine requirements
- Group only same normalized SOURCE expression + confirmed same contextual sense. A mere embedding/synonym match is not a recurrence obligation.
- Minimum two confirmed eligible occurrences per SECG; ambiguous senses stay outside confirmed groups and are surfaced as `PC20`.
- Preserve raw text, Unicode offsets, Scripture reference mappings, versification identity, sentence/cross-verse spans, input hashes.
- Normalize conservatively; never erase negation, diacritics by default, case where significant, number, grammatical roles, or distinct lexical wording.
- Target accepted forms follow approved exact form > scoped variant/exception > validated language rule; contradictory same-scope rules create `PC23`.
- Semantic/model assistance is optional and **advisory**, cannot approve rules, alter authority, assign definite mistranslation, or suppress evidence.
- Reverse matching identifies probable *unsupported* TARGET concept introductions after checking alternative SOURCE support; it is not a dictionary ban.
- Distinguish finding type, review status, severity, detection confidence, semantic confidence, and coverage. Unknown != pass.

## Storage and execution
- Use streaming JSONL for large line-oriented records; manifest/config/summary JSON; Markdown report; plain phrase list.
- Implement strict schema validation, bounded resource processing, atomic writes via temp file and rename where platform supports it, sorted deterministic outputs, and human-readable validation errors.
- All files local; never write to read-only bundled resources, and never upload input text to any external model without explicit existing SAGE authorization.
- Track source hashes, index/rule/profile/model/prompt versions and decisions. If dependencies change, mark cached or approved contextual evidence stale where applicable.
- Avoid materializing all possible n-grams unnecessarily. Design for efficient term lookup and test against representative project size.

## Definition of done
The repository's check entrypoint can execute PCC end-to-end on synthetic fixtures; docs and CLI/help show how to operate; fixtures validate `PC00`–`PC25` as applicable; all accepted renderings and suppressions are explainable; no unresolved source occurrence is silently counted consistent; output is deterministic given fixed inputs and fixed semantic evidence; static resources are immutable; Stage 1 requires no SQL or external service.


---

<!-- SOURCE FILE: docs/00_SCOPE_AND_DECISIONS.md -->

# 00 — Scope, authority, decisions and boundaries

## Locked decisions
- **Consistency obligation:** same SOURCE wording (under conservative normalization) **and** same contextual sense.
- **Reverse detection:** report *probable* unsupported TARGET additions for human review.
- **Morphological/cultural variance:** allow validated language rules and scoped contextual decisions.
- **Stage 1 persistence:** local text files only (JSON, JSONL, MD, TXT); no database and no remote service.
- **OL:** not involved; the checker evaluates authorized SOURCE translation(s) rather than original-language equivalence.

## Terminology
- **REFERENCE:** an authorized, versioned translation used to build a bundled static lookup resource.
- **SOURCE:** the translation designated as controlling by the active brief, often drawn from the REFERENCE set.
- **TARGET:** candidate translation to be evaluated.
- **SECG:** Source Expression Consistency Group, grouped by normalized SOURCE phrase, same contextual sense, controlling SOURCE version, and brief scope.
- **Sense:** specific contextual meaning/function, not a dictionary gloss alone.
- **Rendering family:** approved TARGET equivalents and language-conditional forms for one SECG.
- **Reverse candidate:** TARGET expression for which corresponding SOURCE meaning is not yet supported by alignment/context.

## Scope
In scope: read authorized local indexes; scan current SOURCE for more candidates; use simple `input/phrases.txt` for additional literal SOURCE entries; segment/normalize under language profiles; detect recurring same-sense groups; align to TARGET; compare approved renderings and morphological/syntactic rules; invoke optional existing semantic reviewer for ambiguity; reverse check; operator decisions and scoped exceptions; fully auditable reports.

Out of scope: translation rewriting; proof of theological accuracy; online reference retrieval; remote indexes; SQL or other databases; general purpose multilingual lexicography; unrestricted auto-learning or auto-approval; full OL comparison; new service/API infrastructure.

## SOURCE authority matrix
| Brief | Control | Secondary use |
|---|---|---|
| Single SOURCE | Sole designated SOURCE | None |
| Primary + secondary | Primary governs obligations | Candidate discovery, alternatives and explanation only |
| Coequal / not resolved | **Block authoritative classification** with `PC24` | Obtain explicit arbitration policy |

If secondary SOURCE differs in phrase or sense, do not silently impose secondary wording on TARGET. If an index was built for another corpus/version, it supplies **candidates only** until occurrences are verified against the actual controlling SOURCE.

## Inclusion policy
- Curated key terms/formulae may be tracked even when appearing once: informational only, not a recurring consistency claim.
- Automatic discovery candidates must meet configurable minimum frequency and distinctiveness. Default: >=2 occurrences of the same normalized form, candidate n-grams 1–6 tokens (language-adjustable).
- Group eligibility: >=2 **confirmed** occurrences of the same normalized wording and sense within comparison scope. Occurrences can be within the same verse, but preserve distinct positions and avoid inflated counts caused by overlapping extraction.
- Stop-phrase lists, n-gram length limits, and distinctiveness are language-profile settings, not universal semantic rules.
- The list of candidate phrases is not exhaustive and does not define every possible TARGET concept.

## Fail-safe principle
If SOURCE version, identity, alignment, sense, licensing, normalization, rule provenance, or input integrity is uncertain: preserve the evidence and label review/blocked state. Never substitute `PASS` for missing analysis.


---

<!-- SOURCE FILE: docs/01_ARCHITECTURE_AND_INTEGRATION.md -->

# 01 — Architecture, modules and integration contracts

## Data flow
```
translation brief + source/target text + authorized local REFERENCE resources
              |
    validate identities, hashes, rights, versification
              |
     SOURCE expression candidate discovery
              |
  normalized span recognition and sense assignment
              |
         eligible SECG construction
              |
 SOURCE-to-TARGET alignment + alternate support check
              |
    approved variants + language-specific rules
              |
        selective semantic/context review
              |
          forward and reverse findings
              |
     exception resolver + provenance audit
              |
        JSON/JSONL + Markdown reports
```

## Logical components (adapt names to actual repo)
1. `PCCAdapter`: binds SAGE translation briefs, text importer, existing check runner, report writer.
2. `ResourceLoader`: validates manifests, versions, SHA-256, normalization/profile compat, rights; reads authorized resources read-only.
3. `SourceScanner`: discovers known and new literal SOURCE expressions without adding authority.
4. `NormalizerTokenizer`: language-profile-driven Unicode-aware mapping back to raw offsets; preserve linguistic features.
5. `SenseResolver`: curated discriminator + optional existing contextual reviewer. Must support `UNRESOLVED`.
6. `GroupBuilder`: groups only confirmed same-sense/source-wording occurrences; enforces recurrence threshold.
7. `TargetAligner`: reuses SAGE verse/phrase correspondence; supports one-to-many, many-to-one, cross-verse spans and blank/unresolved states.
8. `RenderingMatcher`: accepted forms, morphology, syntax and contextual equivalence; preserves semantic-feature constraints.
9. `ReverseScanner`: scans approved/proposed TARGET rendering families and repeated salient terminology, checks alternative SOURCE semantic support.
10. `ExceptionResolver`: deterministic specificity/approval precedence, conflict detection, stale decisions.
11. `FindingsWriter`: JSONL details, JSON summary, Markdown report; distinct coverage stats.
12. `DecisionManager`: explicit operator actions to approve/reject/context-limit/revoke variants/exceptions; append-only journal recommended.

## Proposed interface sketch (pseudocode; do not assume implementation language)
```
runPcc(translationBrief, sourceCorpus, targetCorpus, settings, localResources)
  -> {runManifest, summary, findings, occurrenceAudit}

scanSource(sourceText, expressionRegistry, languageProfile)
  -> candidateOccurrences[]

groupOccurrences(candidateOccurrences, senseEvidence, scope)
  -> groups[], unresolved[]

align(groupOccurrence, targetCorpus, versificationMap)
  -> alignments[]  // can be unresolved or multi-span

evaluate(group, alignments, approvedVariants, linguisticRules)
  -> decisions[], reviewCandidates[]

reverseCheck(targetCorpus, targetRenderings, sourceSupportMap)
  -> candidateFindings[]

resolveRules(candidate, scope, decisionJournal)
  -> resolved|review|conflict
```

## Stable IDs and hashes
- `corpus_id`: human-readable resource identifier **plus immutable edition/version** in manifest.
- `expression_id`: deterministic ID from SHA-256 of `{source corpus version, normalized form}` with a namespaced prefix (avoid human wording as key).
- `sense_id`: stable within expression resource version; never inferred from gloss text.
- `occurrence_id`: deterministic hash of `{corpus content SHA, reference(s), raw span coordinates, expression_id}`.
- `group_id`: deterministic hash of `{brief/scope policy hash, expression_id, sense_id}`.
- `finding_id`: deterministic hash of `{run input fingerprint, finding type, scope/occurrence IDs, candidate fingerprint}`; presentation order does not change IDs.
- Raw/context offsets must specify **coordinate system**. Recommended normalized parser's Unicode code-point indices after extraction of the Scripture body; also keep original text span text and raw reference coordinate if original file supports it. Never mix byte/UTF-16/Unicode indices silently.

## No-new-infrastructure rule
Reuse SAGE's existing importer, CLI/check orchestration, language settings and reports. Maintain read-only `resources/phrase-indexes/` and project-local `data/phrase-check/` / `output/phrase-check/`; do not add network services, servers or databases.

## Alignment and verse addressing
Store native Scripture references, canonical Western reference mappings, and mapping status. Chapter/verse assignment alone may not map one-to-one across editions. A SOURCE term may span verses or align to a paraphrase elsewhere within an explicitly bounded context; do not emit `PC11` when alignment is actually unresolved (`PC21`).

## Complexity controls
Use term trie, Aho–Corasick, or equivalent in-memory streaming matching for prebuilt literal expressions; n-gram discovery only within configured text boundaries and maximum lengths; postings lists/offset arrays as needed. Avoid quadratic target-pair comparisons across whole corpora. Measure throughput/memory on the repo's representative real-sized inputs without embedding licensed data in tests.


---

<!-- SOURCE FILE: docs/02_MATCHING_ENGINE.md -->

# 02 — Matching rules and semantic adjudication

## Rule IDs and precedence
1. **SRC01** candidate from authorized index; **SRC02** candidate from controlling SOURCE discovery; **SRC03** candidate from local literal `phrases.txt`.
2. **SRC04** verify candidate occurs in **current controlling SOURCE** before making a group. REF index occurrences are not presumed valid across editions.
3. **SRC05** normalized same SOURCE wording, with conservative profile, is a surface match.
4. **SRC06** same normalized form but different contextual sense -> different SECG; uncertain sense -> `PC20`.
5. **SRC07** same sense but *different SOURCE wording* -> separate group by default. Semantic relation may aid discovery, **never silently merge**.
6. **SRC08** group eligible only with >=2 confirmed distinct occurrences within scope.
7. **SRC09** preserve nested/overlapping phrases as distinct evidence; use longest-match display preference but do not erase shorter independent meaningful occurrences.
8. **SRC10** annotation, footnote, heading, cross-reference and versification exclusions follow controlling text importer/brief; Scripture body only by default.
9. **TGT01** exact approved normalized TARGET rendering -> accepted if semantic feature constraints match.
10. **TGT02** approved morphological variant -> accepted if material features preserved.
11. **TGT03** approved contextual semantic/syntactic/cultural equivalent -> accepted only within stated scope/predicates.
12. **TGT04** unapproved differing renderings -> `PC10`, even when model predicts high similarity (until valid contextual rule or review).
13. **TGT05** probable material semantic feature shift -> `PC13` (separate from mere wording variation).
14. **TGT06** no TARGET equivalent **with reliable alignment and adequate review** -> `PC11`.
15. **TGT07** weak/absent alignment -> `PC21`, **not** automatic omission.
16. **REV01** known TARGET rendering family found outside its expected SOURCE group -> inspect alternative SOURCE support before suggesting `PC12`.
17. **REV02** TARGET term with clear alternative SOURCE support -> do not call unsupported addition; may be independently classified if useful.
18. **REV03** if SOURCE support ambiguous -> possible overuse `PC12` for human review with lower confidence; never final error verdict.
19. **DEC01** operator-accepted scoped rule can resolve eligible findings; rejected variants cannot be auto-approved by model.
20. **DEC02** equal-specificity incompatible approved rules -> `PC23`.

## Normalization pipeline
Preserve raw Scripture-body text and exact span mapping. Apply Unicode **NFC**, then profile-authorized case handling, whitespace normalization and punctuation separation/tokenization. Keep diacritics by default; do not apply NFKC or stemming indiscriminately. Preserve negation and meaningful grammatical distinctions. The comparison key is `normalization_profile_version`-dependent, so a profile change invalidates matching caches.

## Candidate discovery and frequency
- Sources: shipped curated index; `input/phrases.txt`; automatic normalized 1..N token n-grams or language-aware segment windows.
- Default recurrence candidate threshold: 2 occurrences; configurable distinctiveness/stoplist to limit generic phrases.
- Different occurrences with identical surface wording are not assumed same sense; use sense evidence or produce pending review.
- Phrases selected from only the secondary source are *advisory* until current primary SOURCE independently contains them.
- Expressions in non-whitespace-segmented languages require an appropriate tokenizer or explicit phrase span matching; whitespace n-grams are not an adequate fallback for authoritative pass/fail.

## Sense assignment
Supported evidence, highest first: operator-reviewed occurrence sense; curated sense discriminators tested in context; validated deterministic language rules; optional semantic reviewer suggestion. For a new ambiguous sense, store `UNRESOLVED`; do not assign random/default sense to satisfy recurrence. A suggested `sense_id` must be linked to stored evidence; model proposals never create approved sense definitions unilaterally.

## TARGET equivalence
TARGET alignment may be many-to-many. Evaluate whole expression in bounded context and preserved semantic feature set: polarity/negation, participant roles, agency, number where material, tense/aspect/modality where meaningful, possession/reference, and phrase relations. Configurable features may differ by language; *never normalize these away as mere surface spelling*. Distinguish textual rendering variant vs actually equivalent meaning.

## Reverse detection
1. Build a TARGET-side lookup of approved and proposed rendering forms associated with known groups; optionally discover frequent salient TARGET phrases.
2. Scan TARGET occurrences independent of the forward matched locations.
3. For each hit, seek corresponding SOURCE alignment and contextual semantic support, including source formulations outside the indexed group.
4. Emit `PC12` if addition is probable; attach SOURCE and TARGET spans, unmatched concept, confidence and a concise reason; no automatic condemnation.
5. Dedupe reverse and forward findings referring to the same semantic problem; retain both evidence traces.

## Sample decision logic
```
if sourceAuthorityInvalid: PC24 / BLOCK
elif sourceTextInvalid: PC25 / BLOCK
elif senseUnresolved: PC20 / REVIEW
elif groupConfirmedCount < 2: INFORMATIONAL
elif alignmentUncertain: PC21 / REVIEW
elif approvedRuleConflict: PC23 / BLOCK
elif approvedRenderingApplicable: PC00 or PC01
elif semanticFeatureShiftSupported: PC13 / REVIEW
elif noSupportedRenderingWithReliableAlignment: PC11 / REVIEW
elif differingUnapprovedRenderings: PC10 / REVIEW
elif uniformFormButMeaningUnvalidated: PC02 / INFO
else: PC00 only with verified equivalent analysis

independent_target_scan(): candidate PC12 after alternate SOURCE support evaluation
```

## Avoid common mistakes
- No global embedding-based merging of SOURCE expressions.
- No `PC00` just because text strings match.
- No automatic issue closure from a single model's confidence score.
- No propagation of one verse's exception to all verses unless scope is explicitly broadened and approved.
- No treating an exact SOURCE phrase match in a different *sense* as fulfilling another group's occurrence requirement.


---

<!-- SOURCE FILE: docs/03_TEXT_STORAGE_AND_SCHEMAS.md -->

# 03 — Text-file persistence and JSON contracts

## Proposed local layout (adapt to actual SAGE repo)
```
SAGE/
  resources/phrase-indexes/
    manifest.json                 # read-only: authorized index release
    expressions.jsonl            # read-only: phrase + sense definitions
    occurrences.jsonl            # read-only: verified REFERENCE occurrences
  resources/language-profiles/
    <lang>.json                   # read-only shipped profile(s)
  input/
    phrases.txt                   # optional operator additions: one literal SOURCE phrase per line
  config/
    phrase-check.json             # project settings
  data/phrase-check/
    discovered-expressions.jsonl  # generated/rebuildable project-local entries
    occurrences.jsonl            # generated/rebuildable from current SOURCE
    alignments.jsonl             # generated and optionally reviewed
    approved-rules.jsonl         # project decisions
    exceptions.jsonl             # project exceptions
    review-journal.jsonl         # append-only decisions/events
  output/phrase-check/<run-id>/
    run-manifest.json
    summary.json
    findings.jsonl
    occurrence-audit.jsonl
    report.md
```
No `.db` files or database engine. JSONL is line-delimited independent JSON objects. All files UTF-8; prefer LF output, accept platform-native read line endings.

## Roles and ownership
- `resources/` bundled static, versioned, immutable.
- `config/` user-editable declarative configuration, schema validated.
- `input/` literal SOURCE phrases, optional, comment lines begin `#`, blank lines ignored; no semantic annotations in flat text; richer annotation stored as JSONL reviews.
- `data/` local versioned operational state; generated caches can be rebuilt but explicit operator decisions must not be discarded.
- `output/` immutable per-run artifacts. May regenerate only under a new run identifier or controlled `--overwrite` according to existing SAGE policy.

## Contract files
The accompanying `contracts/*.schema.json` use JSON Schema Draft 2020-12. Validate each JSONL line separately against its matching record schema. Examples under `samples/` should validate and are **illustrative**, not a substitute for project runtime integration.

| File | Purpose |
|---|---|
| `config.schema.json` | execution settings / source authority |
| `corpus_manifest.schema.json` | immutable corpus identity, rights, canonical mapping |
| `language_profile.schema.json` | normalization, segmentation, feature guards |
| `expression.schema.json` | expression & sense definitions |
| `occurrence.schema.json` | SOURCE spans and sense evidence |
| `variant_rule.schema.json` | approved / rejected / proposed TARGET forms |
| `exception.schema.json` | scoped exception & invalidation dependencies |
| `finding.schema.json` | actionable and audit finding record |
| `summary.schema.json` | report counters / provenance |
| `alignment.schema.json` | multi-span target correspondence |
| `occurrence_audit.schema.json` | per-occurrence audit disposition |
| `review_event.schema.json` | journal event |
| `run_manifest.schema.json` | reproducible run metadata |

## ID and version rules
- Stable deterministic namespaced IDs (`EXPR-`, `SENSE-`, `OCC-`, `SECG-`, `RUN-`, `PCF-`). IDs can use truncated SHA-256 with collision checks; the full hash remains in manifest/provenance.
- Never treat a user-editable phrase label as immutable primary identity.
- Store SHA-256 of **actual exact source bytes**, plus normalized-text/profile hashes where relevant.
- Source corpus version+hash, target version+hash, reference index version+hash, translation brief, rule/exceptions snapshot and model/prompt versions must be in the run manifest.
- All report record IDs and record sort order deterministic for a fixed input snapshot.

## Consistency/atomicity
- Write temporary file in target directory, flush/close, validate, then atomically replace where supported; if full atomic replacement is unavailable, preserve previous file and report failure.
- For operator decisions, use append-only event journal plus a rebuildable materialized JSONL view to avoid silent history loss.
- If workflow supports concurrent runs, use existing SAGE lock/concurrency behavior or add minimal filesystem lock with recovery policy, never a database.
- On corrupted JSONL line: report file, line, parser error; fail closed for authoritative resources and approved decisions. Never silently skip malformed rules.

## Input scope and import adapters
Do not force users to move existing SAGE translation inputs to JSONL. Reuse SAGE's existing importer (e.g., USFM if supported) and expose normalized internal text units. `fixtures/synthetic/*.jsonl` is only an isolated test format. Do not include notes, headings or reference labels in Scripture-body matching unless the active brief explicitly opts in.

## Human phrase list examples
```
# SOURCE phrases, not TARGET translations
stand firm
fear of the LORD
kingdom of heaven
```
Do not infer a sense or a permitted TARGET equivalent solely from presence in this list.


---

<!-- SOURCE FILE: docs/04_EXCEPTION_GOVERNANCE.md -->

# 04 — Variants, exceptions, precedence and reviews

## Governing idea
Exceptions are constrained approvals or denials with evidence, scope, review provenance and dependency version. An exception cannot silently apply outside the supporting context. SOURCE authority and data integrity are **non-overridable gates**.

## Order of evaluation
0. Check immutable source/brief identity, validation and authorized index integrity. Failure -> `PC24` or `PC25`.
1. Gather all APPROVED rules whose predicates match the current SOURCE group, TARGET language, context, policy and dependency hashes.
2. Drop revoked/stale/proposed rules from acceptance calculations, but retain for audit.
3. Rank by exactness/specificity: occurrence-specific > bounded passage/context > SECG-specific > language-profile > generic safe normalization.
4. If rules of **equal maximum applicable specificity** have contradictory `ACCEPT`/`REJECT` effects -> `PC23` and human review; never arbitrary last-write-wins.
5. A more specific REJECT forbids the form in that scope; a broader ACCEPT does not override it. A more specific ACCEPT can override a broader prohibition **only if explicitly approved as an exception to that prohibition**; otherwise flag conflict for reviewer. This avoids silent weakening of negative decisions.
6. Deterministic rules can accept a form only if all semantic-feature conditions hold; if features cannot be evaluated -> review, not pass.
7. Suggested model equivalents and proposed rules are evidence only.

## Exception types and typical scope
| Type | Default scope | Interpretation |
|---|---|---|
| `MORPHOLOGICAL` | language profile or SECG | Grammatical inflection required by TARGET |
| `SYNTACTIC` | language or SECG | Order, agreement and construction changes |
| `SEMANTIC_VARIANT` | SECG | Verified context-compatible synonym |
| `CULTURAL_EQUIVALENT` | context, passage | Idiomatic/culturally conventional rendering |
| `DISCOURSE_ADAPTATION` | exact passage/occurrence | Context-dependent discourse realization |
| `ALIGNMENT_CORRECTION` | occurrence | Multi-span mapping correction |
| `SENSE_RECLASSIFICATION` | occurrence | Reassigns SOURCE sense and rebuilds groups |
| `FALSE_POSITIVE` | exact finding input fingerprint | Previously disproven issue, no global suppression |

## Lifecycle
`PROPOSED -> APPROVED -> REVOKED` (or rejection). An APPROVED item may become **STALE**, which is a computed invalidation condition, when SOURCE/TARGET/context/rule/profile dependencies change. Do not erase old decisions: append reversal/supersession event.

## Review decision actions
- `ACCEPT`: approved under stated scope/predicates.
- `REJECT`: known non-equivalence under stated scope/predicates.
- `CONTEXT_ONLY`: accept only for bounded context; cannot promote automatically.
- `UNDECIDED`: keep review open.
- `REVOKE`: previous approval no longer holds, preserve historical record.

## Required event journal fields
`event_id`, `time_utc`, `actor_id`, `operation`, `subject_type`, `subject_id`, `before_hash`, `after_hash`, `evidence_refs`, `rationale`, `brief_id`, `source_corpus_sha256`, `target_language`, `scope`, `policy_version`. Actor ID follows existing SAGE access/logging, not new accounts.

## Default governance
- Operator approval is mandatory before extending approved variants beyond exact prevalidated/curated rules.
- An instance-specific exception never broadens merely because another occurrence resembles it.
- Approval is per TARGET language and context. Do not share across languages by string similarity.
- Revoking a rule triggers recalculation of affected groups and findings on next run.
- Secondary SOURCE readings can be cited in explanations but cannot create new obligations on their own.
- Keep a negative-equivalence register. Rejecting a rendering must be representable and cannot be overruled by model suggestion.


---

<!-- SOURCE FILE: docs/05_FINDINGS_AND_REPORTS.md -->

# 05 — Finding classification, evidence and coverage

## Codes
| Code | Name | Classification |
|---|---|---|
| `PC00` | CONSISTENT | Every eligible occurrence has verified accepted equivalent rendering |
| `PC01` | APPROVED_VARIANT | Differences explained by approved scoped variant |
| `PC02` | FORM_CONSISTENT_UNVALIDATED | TARGET looks uniform but equivalence not established |
| `PC10` | UNEXPLAINED_VARIATION | Same SECG has differing unapproved TARGET forms |
| `PC11` | POSSIBLE_OMISSION | Reliable alignment + adequate contextual analysis, no TARGET support |
| `PC12` | POSSIBLE_OVERUSE | TARGET term/concept probably added without SOURCE support |
| `PC13` | SEMANTIC_FEATURE_SHIFT | Possible meaningful polarity/agency/number/etc change |
| `PC20` | SENSE_AMBIGUITY | SOURCE sense unresolved |
| `PC21` | ALIGNMENT_UNCERTAIN | SOURCE/TARGET span relationship unresolved |
| `PC22` | INDEX_GAP | Newly discovered relevant expression absent shipped index |
| `PC23` | RULE_CONFLICT | Approved applicable rules conflict; blocks classification |
| `PC24` | SOURCE_AUTHORITY_CONFLICT | Controlling SOURCE cannot be established; blocks classification |
| `PC25` | DATA_INTEGRITY_FAILURE | Corpus, reference, file, profile or schema failure; blocks classification |

`PC00`–`PC02`: audit outcome records (not error counts); `PC10`–`PC13`: review candidates; `PC20`–`PC22`: attention/incomplete state; `PC23`–`PC25`: blocking.

## Orthogonal fields
- `review_status`: RESOLVED, OPEN, IN_REVIEW, APPROVED_VARIANT, CONFIRMED_ISSUE, DISMISSED, DEFERRED, STALE.
- `severity`: INFO, LOW, MEDIUM, HIGH, CRITICAL; based on documented editorial significance, not model confidence.
- `detection_confidence`: optional calibrated 0..1; confidence in observed textual/alignment signal.
- `semantic_confidence`: optional calibrated 0..1; confidence in contextual inference. Null if not assessed.
- `is_blocking`: boolean from the code or authoritative integrity requirements.
- `evidence`: source/target snippets, offsets, references, linked group and rule IDs, counterevidence/alternative source support, reason and model provenance if used.

## Report files
- `run-manifest.json`: all corpus/resource hashes, policy/profile versions, timestamp, run settings, model/prompt evidence hash.
- `findings.jsonl`: all actionable issues and informational audit outcomes per report level; stable order.
- `occurrence-audit.jsonl`: one normalized disposition per eligible SOURCE occurrence; no dropped entries.
- `summary.json`: counts, denominators, coverage, incomplete and blocked totals.
- `report.md`: decision-focused overview with group, source/target references, variants, reason, status, links to IDs; do not quote large licensed corpus passages unnecessarily.

## Coverage formulas
- Expression coverage = evaluated eligible SECGs / total eligible SECGs.
- Occurrence coverage = evaluated eligible SOURCE occurrences / all eligible occurrences.
- Fully resolved group = **every** occurrence is accepted or has an explicit approved disposition, with no unresolved blocking dependency.
- Resolved group rate = fully resolved groups / total eligible groups.
- Unexplained variation rate = groups with unresolved PC10 / evaluated groups.
- Reverse detection yield = reviewer-confirmed unsupported additions / all reviewed PC12 suggestions; mark undefined if denominator zero.
- Blocked coverage = affected groups/occurrences whose result cannot be classified due to conflict/integrity.
- Never report a green total pass while review/blocked records remain without a clear qualification.

## Deduplication
Same semantic problem may trigger PC10 and PC13, or reverse PC12 and forward PC11. Store distinct evidence signals but group linked findings under a shared `issue_cluster_id`; do not inflate one problem into several unique editorial issues.

## Result integrity
- PC00 cannot be reached from mere identical string matches if semantic equivalence has not been established; PC02 is appropriate.
- PC11 cannot be reached from missing alignment; use PC21.
- PC12 cannot be reached only because the standard SOURCE phrase is absent; first test alternate SOURCE semantic support.
- One unreviewed SOURCE occurrence means the group cannot be reported fully resolved.


---

<!-- SOURCE FILE: docs/06_OPERATOR_WORKFLOW.md -->

# 06 — Operator workflow and proposed CLI surface

Commands are **illustrative interface requirements**, not asserted existing SAGE commands. Adapt to SAGE's current runner and naming.

## Installation and input
1. Run PCC as part of existing SAGE (no extra server or database).
2. Select SOURCE authority in translation brief: single or controlling primary; optional secondary evidence.
3. Place authorized REFERENCE phrase resource release in bundled `resources/phrase-indexes/` following SAGE resource convention.
4. Optionally add literal SOURCE phrases to `input/phrases.txt`, one per line; comments start with `#`.
5. Configure local language profile, comparison scope, output verbosity and optional semantic-review interface.
6. Run validation before analysis; only proceed if resource and text integrity pass.

## Proposed command behaviors
| Intended operation | Example command shape | Required behavior |
|---|---|---|
| Inspect | `sage phrase-check status` | Show installed resources/config/authority readiness |
| Validate | `sage phrase-check validate --config ...` | Schemas, hashes, source roles, profile, versification |
| Run | `sage phrase-check run --config ...` | Read-only analysis + new run directory |
| Review | `sage phrase-check inspect PCF-...` | Show source/target spans, evidence and rules |
| Decision | `sage phrase-check decide --finding PCF-... --decision ...` | Append an audited local review event |
| Explain | `sage phrase-check explain --group SECG-...` | Group membership, sense and accepted variants |
| Export | `sage phrase-check export --run RUN-...` | Rebuild Markdown from saved snapshot |

If SAGE uses `RUN <name>` or other invocation style, maintain it and map these logical operations to equivalent existing commands. Avoid introducing a divergent CLI.

## Recommended runtime modes
- `strict`: no model-assisted acceptance, unresolved sense and equivalence leave review state.
- `assisted`: existing SAGE semantic reviewer may propose context/variant evidence; operator still approves persistent rules.
- `audit`: produce full occurrence-level JSONL, including resolved forms.
- `summary`: human report and actionable findings, with coverage denominators.

## Typical review sequence
```
validate -> run -> review PC10/PC11/PC12/PC13/PC20/PC21
         -> decide ACCEPT / REJECT / CONTEXT_ONLY / UNDECIDED
         -> append local decision event
         -> rerun from immutable text snapshot
         -> compare findings, affected groups, coverage
```

## Operator prompts
For every proposed equivalence show: same SOURCE wording? same sense? grammatical features preserved? distinct accepted TARGET forms? scope of approval? context? alternative SOURCE support? known negative decisions? reviewer rationale? Do not offer a one-click *approve all semantic similarity matches* action.

## Reports and statuses
Expose total indexed expressions, confirmed eligible SECGs, occurrences evaluated, unresolved sense/alignment, approved variants, probable additions and conflicts. For each finding provide reason, exact references, provenance, and suggested review task rather than an unqualified verdict.


---

<!-- SOURCE FILE: docs/07_MILESTONES_AND_TASKS.md -->

# 07 — Claude implementation plan, milestones and dependency gates

This is a work breakdown for Claude Code inside the **actual SAGE repository**. Do not assume a language or directory layout until M0 discovery is complete. Every milestone must leave runnable tests and documentation updates.

## M0 — Repository fit and baseline
**Discover:** existing translation brief conventions; SOURCE/REFERENCE/TARGET terminology; parser(s); normalization; verse mapping; CLI or ACT operations; project config; resource loader; language profile storage; issue schema; tests; packaging; performance; licencing. **Output:** `PCC_REPO_FIT.md` with concrete files, adapters and unresolved decisions. Establish baseline test pass, create branch under existing workflow. **Gate:** no unknown required integration point; non-overridable scope remains intact.

## M1 — Contracts, settings and local persistence
Implement schema validation for config, resource manifest, expression/sense records, occurrences, language profiles, variants, exceptions, findings and summary. Implement UTF-8 JSON/JSONL read/write, strict parse failures, integrity hashing, deterministic IDs/sort and atomic outputs. **Tests:** malformed JSONL, wrong sha, duplicates, invalid schema/versification, path traversal, concurrent write policy. **Gate:** no hidden state or SQL; resource files remain read-only.

## M2 — Source scanning and discovery
Load authorized REFERENCE expression list read-only; verify candidates against actual primary SOURCE; parse `input/phrases.txt`; discover repeated normalized expressions using language-aware segmentation; record source span evidence and provenance; avoid importing notes/headers by default. **Tests:** Unicode canonical equivalence, stop phrases, overlapping spans, cross-verse phrases, same-verse multiple occurrences, punctuation, script lacking spaces. **Gate:** all extraction counts reproducible and traceable to raw SOURCE.

## M3 — Senses and SECGs
Implement explicit expression+sense model, reviewed assignments and unresolved tracking; group confirmed occurrences only. Minimum 2 confirmed eligible occurrences. Support configurable book/section/corpus scope. **Tests:** same wording/different senses separated, different wording/same concept not automatically merged, single occurrence informational, unresolved sense PC20. **Gate:** no accidental cross-sense obligations.

## M4 — Alignment and forward comparison
Reuse SAGE verse/target alignment; include canonical/native reference maps, one-to-many, many-to-one, bounded cross-verse alignment; build TARGET variant matcher with profile feature preservation. **Tests:** PC00, PC01, PC02, PC10, PC11, PC13, PC21, not confusing omission with missing alignments. **Gate:** every eligible occurrence has disposition or review reason.

## M5 — Rule/exception resolver and decision journal
Implement approved rule application, specificity, explicit ACCEPT/REJECT, context-limited exceptions, hash-based stale detection, journal append, conflict PC23. Build operator decision interface adapted to SAGE. **Tests:** scoped overrides, two equal-scope conflicts, revoked/stale cannot accept, negative decision prevents model approval, immutable bundled resources. **Gate:** every accepted variation has explainable basis.

## M6 — Reverse matching and optional semantic assistance
Independent TARGET known-form scan and salient phrase proposals; check alternate SOURCE concept support; classify likely additions PC12 without declaring errors. Expose semantic reviewer adapter as **optional and advisory**: must work offline with inconclusive statuses. Log reviewer evidence/provenance and keep approvals human-controlled. **Tests:** target-only term, alternate source construction, false positive suppression with evidence, missing model adapter, repeatability with recorded evidence. **Gate:** reverse candidates actionable but not authoritative.

## M7 — Reports, coverage and operator UX
Write per-run manifest, JSONL findings/audit, JSON summary, Markdown report; link cluster IDs, dual confidence and severity, blocked denominators and exact review status. Integrate into existing SAGE run/report lifecycle and CLI/help. **Tests:** schema validation, stable IDs/order, report counts, summary reconciliation, unresolved not green, dry-run does not alter source. **Gate:** report usable without reading internals.

## M8 — Full QA, corpus-scale benchmark and handover
Run synthetic golden fixtures, fuzz/edge corpus tests, integration tests against repository's permitted test text, baseline regressions, performance benchmark, license and privacy review, CLI help, upgrade/version compatibility docs. Document limitations and deferred non-Stage-1 features without adding their scaffolding. **Gate:** final acceptance checklist in `08_TESTS_AND_ACCEPTANCE.md` all satisfied or explicitly reported as blockers.

## Claude operating cadence
For each milestone: (1) report intended edits; (2) implement minimal changes; (3) run formatting/lint/schema/unit/integration tests relevant to repo; (4) update `PCC_REPO_FIT.md`, report results with commands and log excerpts; (5) commit or present diff according to repo practice. Avoid speculative integration refactors. Preserve backwards compatibility of existing checks.

## Priority if time constrained
M0–M4 deterministic SOURCE and forward checking are a coherent first vertical slice; M5 governance and M6 reverse check are required for **Stage 1 completion**. Do not declare Stage 1 finished if M5–M8 remain unimplemented.


---

<!-- SOURCE FILE: docs/08_TESTS_AND_ACCEPTANCE.md -->

# 08 — Required test matrix and final acceptance

## Deterministic unit cases
| ID | Scenario | Required result |
|---|---|---|
| AT01 | Identical SOURCE wording+sense, verified TARGET equivalent across occurrences | PC00 |
| AT02 | Two approved TARGET renderings in one SECG | PC01 |
| AT03 | Identical SOURCE wording, two contextual senses | Two groups, no cross-sense obligation |
| AT04 | Same wording/sense, differing unapproved TARGET forms | PC10 |
| AT05 | TARGET only varies through validated grammar rule | PC01 |
| AT06 | SOURCE/TARGET polarity or agency materially shifts | PC13 candidate |
| AT07 | Good alignment and no supported TARGET equivalent | PC11 candidate |
| AT08 | TARGET term probably introduced without SOURCE semantic support | PC12 candidate |
| AT09 | TARGET term's meaning supported by alternate SOURCE construction | No PC12 for that occurrence |
| AT10 | One SOURCE phrase corresponds to multiple TARGET units | No automatic PC11 |
| AT11 | SOURCE sense unresolved | PC20, not guessed sense |
| AT12 | SOURCE/TARGET alignment unclear | PC21, not PC11 |
| AT13 | Content hash changes invalidate contextual approval | STALE + reevaluate |
| AT14 | Equal-scope approved rules contradict | PC23 blocking |
| AT15 | Secondary SOURCE differs from primary | Advisory only; primary determines group |
| AT16 | Only one confirmed occurrence of expression+sense | Informational, no recurrence claim |
| AT17 | Phrase in footnotes/headings only | Excluded by default |
| AT18 | Fixed inputs+rule snapshots | Deterministic IDs and record order |
| AT19 | Invalid/unknown controlling SOURCE roles | PC24 / blocking |
| AT20 | Wrong resource hash, malformed line, bad coordinate | PC25 / blocking |
| AT21 | Nested phrases with meaningful independent roles | Both evidence spans retained; no duplicate issue inflation |
| AT22 | SOURCE form differs lexically, same apparent broad concept | Separate group by default |
| AT23 | Proposed semantic variant without approval | PC10/review; no automatic pass |
| AT24 | More-specific REJECT conflicts with broad ACCEPT | REJECT or reviewed conflict, never broad auto-accept |
| AT25 | Scripture split/recombined by versification mapping | Accurate span disposition or PC21 |
| AT26 | TARGET and SOURCE have different token scripts | Language-aware segmentation or explicit incomplete state |
| AT27 | All TARGET forms match but semantic evidence not validated | PC02, not PC00 |
| AT28 | Read-only REFERENCE resources | Byte-identical before/after run |
| AT29 | Reverse/forward overlap on same problem | Linked issue cluster, not double issue count |
| AT30 | Input phrase absent from controlling SOURCE | Candidate not an obligation; explain no match |

## Synthetic fixture expectations
`fixtures/synthetic/source.jsonl` and `target.jsonl` are entirely fabricated prose mapped to common Western verse IDs **only to exercise parsers**. They are not Bible text. `cases.json` contains isolated expectations; do not assume a fictional fixture's sense should be detected automatically without curated sense assignments. Use optional fixtures for language morphology, multispan alignment and secondary source authority.

## Validation checks
- Validate every `samples/*.json` and each `samples/*.jsonl` record against corresponding JSON schema.
- Validate that reference IDs, occurrence IDs, corpus IDs and rule links resolve or are explicitly marked synthetic placeholders.
- Check every emitted occurrence has `EVALUATED`, `REVIEW`, `INFORMATIONAL` or `BLOCKED`, and totals reconcile.
- Check same inputs and already-recorded semantic decisions yield stable output hashes except designated run timestamp.
- Test missing/empty phrases list, corrupted JSONL, forbidden path, invalid UTF-8, duplicate IDs, unavailable optional semantic reviewer.
- Benchmark on a permitted representative corpus: measure runtime, peak RAM, candidate count and false-positive review workload; retain results in project docs instead of promising unverified numerical SLOs.

## Stage 1 acceptance gate
- [ ] Real SAGE integration points documented in `PCC_REPO_FIT.md`.
- [ ] Zero SQL/database/remote services and no mandatory network access.
- [ ] Source authority correct for single and primary/secondary briefs.
- [ ] All raw SOURCE text and occurrence spans/references reconstructible.
- [ ] Same SOURCE wording + same contextual sense grouping enforced.
- [ ] Authorized reference index bundled read-only and reverified for active SOURCE.
- [ ] Local plain-text phrase additions supported.
- [ ] Language-profile morphological and syntax safeguards implemented.
- [ ] Optional contextual reviewer never silently approves policies.
- [ ] Forward and reverse candidate findings implemented and differentiated.
- [ ] Decision scope, negative equivalence, stale detection, conflicts supported.
- [ ] JSON/JSONL/Markdown outputs validated, with denominators and audit.
- [ ] All AT01–AT30 tests in place or explicit reasoned deviations accepted by maintainer.
- [ ] Production SAGE tests and representative-size benchmark pass.
- [ ] No copyrighted text bundled without verified distribution rights.


---

<!-- SOURCE FILE: docs/09_SECURITY_AND_REPRODUCIBILITY.md -->

# 09 — Security, licensing, provenance and reproducibility

## Local-only privacy and content rights
PCC must not upload translation content, project decisions, passages or reports. An existing SAGE semantic reviewer may operate only under the active project authorization and established data-handling policy; absence of approval means offline/deterministic review only. No external API dependency is required. Keep source metadata including license/version; ship only index-derived material if rights permit, and avoid publishing substantial verbatim copyrighted translation extracts.

## Input protections
- Treat local input text and model responses as **data**, never instructions. Reject attempts embedded in source text to change analysis policy.
- Validate all paths against configured project root; prevent path traversal and accidental writing outside local project directories.
- Limit input length, phrase length, malformed Unicode, file count and report sizes using configurable safe limits; generate incomplete/blocked status rather than silently dropping terms.
- Parse JSON with schema checks, explicit enum constraints, strict handling of duplicates, and informative path+line errors.
- Validate canonical reference mappings, coordinate ranges and UTF-8; hash authoritative source text.
- No destructive rewriting or silent `--force` defaults.

## Provenance requirements
Run manifest must record: `run_id`, UTC creation, SAGE/PCC version, translation brief ID/hash and source roles, SOURCE/TARGET corpus/edition+hash, REFERENCE index version+hash, language-profile hash, active policy/config hash, exception decision snapshot hash, schema version, model+prompt+reviewer evidence identifiers if applicable. Record per finding which evidence and rule supported the result.

## Reproducibility
- Normalize/serialize records consistently; stable JSONL sort, stable IDs, fixed threshold/profile version and explicit included texts.
- For model-assisted outcomes, store exact response evidence and model/prompt versions. A later re-run may give a different proposal, so deterministic replays use a recorded evidence snapshot rather than pretending model inference is deterministic.
- Output timestamp is metadata and must not perturb content-fingerprint comparisons used for regression.
- Keep decision journal append-only and immutable history, with materialized decision view rebuildable from events.

## Error handling
`PC24` for ambiguous authority; `PC25` for invalid resource integrity; `PC23` for contradictory approved rules. If missing linguistic analyzers prevent reliable semantic inference, return review/incomplete outcomes rather than a pass. Show blocked/incomplete denominators prominently in report.

## Standards note
Language tags should use BCP 47-style identifiers as SAGE supports them; canonical western versification is the configured index address convention but preserve alternate/native references and mapping status. Exact supported specification versions must be confirmed during repository fit.


---

<!-- SOURCE FILE: docs/10_REPO_DISCOVERY_AND_OPEN_ITEMS.md -->

# 10 — Repository fit questions and calibration items

These are not reasons to stall Stage 1. Claude must inspect SAGE, document actual answers, and implement conservative defaults where no project data exists. Do not ask the user questions already answered by the handover.

## Must confirm from the repo
1. Actual SAGE check registry, execution command, ACT stages, report schema and logger.
2. How SOURCE/REFERENCE/TARGET and primary/secondary designations are represented in translation briefs.
3. Current book/verse and source-body parser, footnote/heading filtering, cross-verse spans and Western canon reference utilities.
4. Project directory settings for `input`, `resources`, `data`, `output`; whether existing resources are bundled in code or flat files.
5. Available language tokenizer/morphology and existing optional semantic reviewer interface.
6. Existing decision persistence and audit mechanisms, and how operators review findings.
7. CI/test environment, style guides, versioning, supported platforms, and legal notices.

## Adjustable calibration — defaults proposed
| Setting | Proposed default | Why not permanent |
|---|---|---|
| Same-sense recurrence | 2 confirmed occurrences | Editorial needs differ by brief |
| N-gram window | 1–6 language-aware tokens | Scripts/term lengths differ |
| SOURCE comparison scope | Current active translation-brief corpus | Some projects need book/section boundaries |
| Orthographic normalize | Unicode NFC, spaces; case by profile | Language-sensitive |
| Diacritic stripping | Never by default | Can change meaning |
| Semantic reviewer | Optional/advisory | Network, rights and costs vary |
| Reverse detection | Probable additions review | Language evidence varies |
| Auto-expansion of approved variants | Disabled | Requires reviewed scope |
| Generated index persistence | Rebuildable JSONL | Simpler than premature cache infrastructure |

## Explicit non-decisions
- Whether SAGE already has internal finding IDs, or whether the proposed PC codes should be mapped into existing namespace.
- Whether a preinstalled authorized REFERENCE phrase list includes occurrence-sense labels. If not, default unknown senses to review; do not fabricate them in bulk.
- Whether existing SAGE language profiles are sufficient for segmentation and grammatical features; if not, implement a capability matrix with incomplete states.
- Whether decisions are stored in a global local project history or a per-corpus history; the semantics must preserve provenance and scope either way.

## Deliverables from repo discovery
`PCC_REPO_FIT.md` must list observed file paths, actual commands (tested), integration decisions, deviations from illustrative directory names, expected fixtures, execution mode and a dependency-free Stage 1 completion plan.


---

<!-- SOURCE FILE: docs/11_CLAUDE_START_PROMPT.md -->

# 11 — Copy/paste prompt for Claude Code in VS Code

Open the actual SAGE repository in VS Code and place this handover folder somewhere Claude can read. Then use:

```text
You are implementing the SAGE Phrase Consistency Checker (PCC) — Stage 1.
Read all of this handover's README.md and CLAUDE.md, then the full docs/ series and contracts/. Treat these as requirements; example code paths and commands are only illustrative.

Nonnegotiable: local JSON/JSONL/Markdown/TXT only; no SQL, database, remote service or SQS; no OL dependency; no redistribution of restricted translation material. A recurring consistency obligation requires the same normalized controlling SOURCE wording AND the same contextual sense. Reverse TARGET findings are probable additions for review only. Linguistic variance uses approved rules and scoped contextual exceptions. No automatic model approval.

Before editing: inspect the actual SAGE repository and run its current tests. Produce PCC_REPO_FIT.md documenting actual integration points, existing commands, any contradictions, proposed file changes and milestone mapping. Show the M0 discovery results. Then implement milestones M1–M8 sequentially, respecting the existing SAGE architecture and checking tests at each milestone. Reuse current parsers, language profiles, translation brief contracts, semantic-review adapters and report conventions where present. Do not invent those interfaces.

Generate and execute unit, golden fixture, regression and performance tests. Verify that reference resources remain byte-identical, decisions are auditable and no unresolved occurrence is reported as consistent. At each milestone summarize changed files, tests actually run and remaining blockers. Never claim a test passes if it was not run. Record deviations and complete the acceptance checklist before declaring Stage 1 finished.
```

## If Claude encounters missing project assets
Do not fabricate actual REFERENCE corpora. Implement resource-loader and schema acceptance using the synthetic fixture, mark live index construction blocked on availability/licensing of authorized local data, and continue remaining reproducible components. Do not substitute internet texts or OL sources.


---

<!-- SOURCE FILE: docs/12_GLOSSARY.md -->

# 12 — Glossary and rules-at-a-glance

- **PCC:** Phrase Consistency Checker.
- **REFERENCE:** approved translation version used to build an authorized static phrase lookup.
- **SOURCE:** designated translation text governing current check; can be primary + secondary with explicit authority.
- **TARGET:** translation being evaluated.
- **SECG:** same normalized SOURCE expression + same confirmed sense + controlling SOURCE identity + comparison scope.
- **SAE:** sense-anchored expression, an expression associated with meaning/function; useful for discovery, not automatically a consistency group.
- **Surface match:** identical normalized SOURCE wording, without assuming meaning.
- **Contextual sense:** contextual interpretation distinguishing polysemy.
- **Rendering:** TARGET text that realizes SOURCE meaning in context.
- **Variant:** permissible TARGET form under an approved conditional rule, not any semantically similar string.
- **Reverse candidate:** TARGET expression without clear supported SOURCE counterpart; investigation, not proof.
- **Alignment:** traceable SOURCE-to-TARGET span relationship (may be one-to-many/many-to-one).
- **Normalization profile:** conservative language-specific orthographic/token comparison rules.
- **Linguistic profile:** normalization, segmentation, morphology and protected semantic features.
- **Rule:** scoped generalization approved for application.
- **Exception:** documented context-dependent departure with scope, provenance, decision and invalidation dependencies.
- **Stale decision:** previous approval no longer safe to apply because a material dependency changed.
- **PCxx:** report classification code; PC00/01 may be passes, PC10+ typically require review or block.
- **Stage 1:** integrated local SAGE capability, no database/SQL/remote infrastructure.


---

<!-- SOURCE FILE: docs/13_REFERENCE_INDEX_BUILDER.md -->

# 13 — Local REFERENCE phrase-index builder and release protocol

## Purpose
Stage 1 needs **authorized, prebuilt, local REFERENCE phrase resources**. The index builder is a local maintainer operation, separate from the runtime checker. It may consume a legally authorized REFERENCE translation already available to SAGE. It must never look up remote sources or derive obligations from an OL index.

## Builder inputs
- SAGE-supported local translation file(s) plus immutable text/edition identity and permission/redistribution status.
- Project-approved reference version and language/segmentation profile.
- Curated list of key terms, formulae and idioms; optional `phrases.txt` for additional SOURCE wording.
- Local stoplist, frequency and candidate-length settings.
- Existing reviewed sense registry if available; otherwise new occurrences remain unreviewed/provisional.
- Canonical Western reference mapper and raw/native ref support.

## Build stages
```
authorized local REFERENCE corpus
  -> verify rights, SHA-256 and supported text format
  -> parse Scripture-body spans using existing SAGE importer
  -> tokenize conservatively / preserve raw offsets
  -> collect curated, input-listed and repeated phrase candidates
  -> prune generic candidates under configured filters (never delete curated)
  -> locate exact normalized occurrences and contextual windows
  -> assign only *reviewed/curated* senses; mark others UNRESOLVED
  -> produce sorted expressions.jsonl and occurrences.jsonl
  -> verify every span reconstructs identical original text
  -> produce manifest.json with identity/version/checksums
  -> validate, freeze release, mark read-only
```

## Candidate discovery rules
1. Short phrases and single-word terms can be included if curated or distinctive; length alone is not a quality metric.
2. For automatic discovery, default normalized 1–6 token windows, frequency >=2; avoid crossing punctuation/verse boundaries unless the parser explicitly supports and documents boundary semantics.
3. Count occurrences, not only distinct verses. Store distinct book/verse counts separately for ranking so repetition within one verse does not inflate significance.
4. Apply frequency and stop-phrase controls as candidate ranking/selection only; do not suppress explicitly curated expressions.
5. Keep nested expression spans if they carry independent meaning. Create a presentation dedupe map rather than throwing away evidence.
6. Same phrase with multiple meanings receives distinct `sense_id` values only after justified sense definition. Unresolved sense cannot silently be collapsed into a predominant sense.
7. Different SOURCE phrases with similar meaning are recorded as *related candidates* if needed but never merged into a recurrence obligation by semantic similarity.
8. `input/phrases.txt` is literal SOURCE text only; no implicit TARGET synonyms or meanings.

## Index verification gates
- Every normalized hit points back to exact text, valid canonical/native reference(s) and offset coordinates.
- All release files sorted deterministically and schema-validated; SHA-256 hash list included in manifest or a release checksum file.
- Registry IDs unique; sense references resolve; no occurrence references a missing expression.
- No duplicate occurrence at the same exact text span for the same expression.
- No copyrighted content shipped unless indexing/distribution rights permit it. For restricted content, index must remain inside permitted local deployment and obey source rights.
- Build operation is repeatable for same input, builder version, profile and reviewed sense decisions.

## Runtime obligations
REFERENCE index is a **candidate and location accelerator** for the *actual controlling SOURCE*. If the user's SOURCE version differs from indexed REFERENCE, re-verify occurrences against SOURCE; don't import stale occurrence assignments. Locally discovered phrases may supplement but may not mutate shipped resources. If the index is not licensed or absent, process current local SOURCE with explicit limitation, retaining incomplete/curation notices.

## Index release strategy
Use a read-only manifest + expressions JSONL + occurrences JSONL, with versioned immutable folder. Never overwrite a released index in place; generate new version and preserve ability to reproduce earlier checks. Include method, parser version, normalization version, source edition, canonical mapping, stoplist revision and sense curation revision.


---

<!-- SOURCE FILE: docs/14_LANGUAGE_AND_CULTURE_RULES.md -->

# 14 — Linguistic variation and cultural equivalence specification

## Normative position
The checker matches SOURCE expressions **literally and by contextual sense**, but judges TARGET renderings by their contextual meaning. Do not use identical wording as a shortcut for equivalent translation. Conversely, a paraphrase is not a violation merely because it differs lexically.

## Profiles and capabilities
Language profile specifies script/normalization, tokenizer, casing, diacritic policy, sentence boundaries, morphological coverage, syntactic coverage and protected semantic features. Each capability must report `SUPPORTED`, `PARTIAL` or `UNAVAILABLE` in the runtime adapter. If unavailable, use conservative exact matching and review, not a claimed pass.

## Morphology categories
| Phenomenon | How to handle | Failure to avoid |
|---|---|---|
| Noun case and agreement | Language-specific feature matching | Treating agent/patient reversal as equivalent |
| Gender/class agreement | Validate grammatical vs referential distinction | Erasing referential sex/gender where meaningful |
| Verb conjugation | Compare relevant aspect, tense, person, voice | Erasing agency or polarity |
| Clitics, affixes, incorporation | Morphological segmentation / span mapping | Assuming spaces delimit meanings |
| Agglutinative forms | Multi-feature parse and canonical morpheme representation | Collapsing negation or possession |
| Word order | Syntactic/relational alignment | Treating role reversal as innocent reorder |
| Compounds | Lexeme decomposition and approved equivalents | False unrelated term match |
| Honorific/register | Pragmatic equivalence in context | Ignoring social/deferential force |
| Idioms/cultural metaphors | Context-limited equivalence | Globally equating idioms in all senses |
| Dialect/orthography | Profile-approved normalization | Unapproved diacritic or lexical stripping |

## Protected features
At minimum consider negation, polarity, agent/patient roles, reference, number, modality, possession and aspect. Configure which features are evaluable per language; don't presume all features must be encoded in the same grammatical form. Absence of overt morphology is not automatically loss of meaning, but an unsupported contextual inference remains reviewable.

## Equivalence decision levels
1. **Surface identical TARGET form:** not sufficient alone for PC00; semantic relation must be established.
2. **Approved grammatical form:** equivalent if rule's conditions hold in this context.
3. **Approved SECG rendering variant:** equivalent if sense and constraints hold.
4. **Approved contextual/cultural exception:** equivalent only within bounded context.
5. **Unapproved semantic proposal:** request review; never a persistent approval.

## Examples (fictional, no actual Scripture interpretation)
- SOURCE "stand firm" may appear as TARGET "remain steadfast" or "do not give up". Both are candidates; neither receives automatic blanket approval without the relevant sense and context evidence.
- SOURCE "light" describing weight is not the same sense as "light" describing illumination. They form separate groups despite the same surface spelling.
- In a target language with incorporated negation, lack of a separate word "not" is not an omission if morphology reliably expresses negation.
- A culturally conventional idiom may replace a SOURCE idiom, but its scope must be approved and constrained: it may have other uses with different meaning.

## Sensitivity and fallback
Do not use a universal synonym dictionary or embedding threshold to declare translation correctness. For low-resource languages, return transparent `PC02`, `PC20`, `PC21` or review candidates as appropriate. Keep reports explicit about which features were checked and which were not. Operator decisions may seed a future in-project rule but must not be automatically propagated beyond evidence.

## Linguistic tests
Include cases for clitics, empty copula, different word order, inflection-only change, polarity in an affix, case-based participant roles, lexical polysemy, honorific, culturally localized idiom, cross-verse construction and non-whitespace segmented script. Any test without a capable analyzer must assert an **incomplete/review** outcome rather than inventing a PASS.


---

<!-- SOURCE FILE: docs/15_CLAUDE_IMPLEMENTATION_WORKPACKS.md -->

# 15 — Claude Code workpacks, verification commands and done criteria

These are small Claude tasks to run inside VS Code after `docs/11_CLAUDE_START_PROMPT.md`. Do not begin by writing files in arbitrary paths; follow discovered repo conventions and use its test runner.

## Workpack A — Establish integration contract (M0)
**Prompt:** "Inspect SAGE and produce PCC_REPO_FIT.md: actual source/target brief fields, canonical verse parser, input file formats, language profiles, check result contract, CLI, tests, resource packaging. Quote concrete repo file paths. No code changes until you report integration seams and conflicting assumptions."
**Gate:** one-page fit report + existing test invocation and baseline, no fabricated APIs.

## Workpack B — Text contracts and data persistence (M1)
**Prompt:** "Implement schema validation and local UTF-8 JSON/JSONL resource access using existing SAGE conventions. Validate supplied synthetic records, strict IDs/hashes, version gates and atomic writes. Never add SQL/databases or network requirements. Add parsing failure fixtures."
**Gate:** JSONL read/write and config validation tested; source resources byte-identical.

## Workpack C — SOURCE scanner/index builder (M2–M3)
**Prompt:** "Implement local REFERENCE phrase loader, input/phrases.txt, source phrase candidate discovery and group construction. Exact normalized controlling SOURCE wording AND reviewed contextual sense define SECG. Unknown sense PC20; single occurrence informative. Add overlap and cross-verse span tests."
**Gate:** no cross-sense or cross-version false grouping, no lost spans.

## Workpack D — TARGET alignment and forward findings (M4)
**Prompt:** "Reuse existing alignment/versification infrastructure. Match accepted target forms conservatively with protected semantic features; output PC00/PC01/PC02/PC10/PC11/PC13/PC21 and an occurrence disposition audit. Missing alignment is PC21, not PC11."
**Gate:** all relevant golden tests pass and no unevaluated group is counted consistent.

## Workpack E — Governance and reverse checking (M5–M6)
**Prompt:** "Implement local approval/rejection/CONTEXT_ONLY decisions with specificity, append-only review journal, stale hash invalidation and conflict PC23. Independently scan target known/proposed terms; check alternative SOURCE support; emit possible PC12 only for review. No automated model approval."
**Gate:** negative decisions respected and synthetic unsupported addition reported without declaring confirmed error.

## Workpack F — Reports and product integration (M7–M8)
**Prompt:** "Integrate PCC into existing SAGE check runner; emit run-manifest.json, summary.json, findings.jsonl, occurrence-audit.jsonl, report.md. Document status/validate/run/inspect/decide/explain behavior using actual repo commands. Complete all AT01–AT30 and benchmark on allowed corpus." 
**Gate:** operator can run and review, all resources reproducible, acceptance checklist complete.

## Suggested verification sequence
1. Run repository formatter/linter/build tests discovered in M0 (don't guess commands).
2. Validate schemas/examples and synthetic file hashes using provided `tools/validate_package.py`.
3. Run targeted PCC unit/golden tests after each workpack.
4. Run existing SAGE regression suite after integration changes.
5. Compare deterministic snapshots; investigate changes in IDs, ordering and group totals.
6. Confirm no unexpected network calls or new persistent dependencies.

## Required Claude status at every workpack
Report: **files changed**, **functional behavior implemented**, **tests actually run and results**, **schema/contract deviations**, **remaining open issues**, and **next workpack**. Avoid claiming completion where only design stubs exist.


---

<!-- SOURCE FILE: PCC_REPO_FIT_TEMPLATE.md -->

# PCC_REPO_FIT — Fill in after inspecting actual SAGE repo

**SAGE repository:** [path/version/commit]  
**Existing test command and baseline:** [command / result]  
**Existing check registration file(s):** [actual paths]  
**Brief SOURCE authority fields:** [actual paths, shape]  
**Scripture-body parser and reference mapper:** [actual paths]  
**Language profiles and semantic adapter:** [actual paths or none]  
**Existing findings / status / reports:** [actual paths]  
**Allowed local resources and generated file directories:** [paths]  
**Existing operator commands/ACT workflow:** [commands]  
**Licensing constraints for authorized REFERENCE resources:** [verified provenance]  

## Differences from handover example paths
[Document exact adaptations without weakening SOURCE/sense/authority requirements.]

## Workpack-to-file mapping
| Workpack | Proposed files | Tests |
|---|---|---|
| M0 | | |
| M1 | | |
| M2 | | |
| M3 | | |
| M4 | | |
| M5 | | |
| M6 | | |
| M7 | | |
| M8 | | |

## Confirmed blocker(s)
[Only real blockers. Do not invent assets or APIs.]

## Tests and acceptance
[Include actual invocations and results, benchmark methodology, and known limitations.]


---

<!-- SOURCE FILE: contracts/README.md -->

# Schema registry

JSON Schema draft 2020-12. Use one record per JSONL line and validate each line against its corresponding schema (`expression`, `occurrence`, `variant_rule`, `exception`, `alignment`, `finding`, `occurrence_audit`, `review_event`). JSON objects (`config`, `corpus_manifest`, `language_profile`, `run_manifest`, `summary`) validate as whole files. These are **minimum example interfaces**; they should be adapted to the real SAGE internal contracts while preserving the invariants in `docs/`. Note illustrative run output is not generated by an implemented module.


---

<!-- SOURCE FILE: fixtures/synthetic/README.md -->

# Fictional corpus fixtures

All SOURCE/TARGET sentences in this directory are **invented**. The canonical-looking `GEN.1.x` IDs only exercise Western-style Scripture reference parsing. **These are not Genesis verses or any Bible translation.**

`source.jsonl` / `target.jsonl` are minimal isolated test adapters, **not required SAGE production input format**. Each unit contains `scripture_body` only. Real SAGE importers must be reused. See `cases.json` for proposed scenarios. Because this is a handover, reports in `samples/` are illustrative, not executed output.
