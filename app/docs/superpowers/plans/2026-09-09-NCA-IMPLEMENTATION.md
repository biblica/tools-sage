# Number Consistency & Accuracy (NCA) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read the finalized design and current/future SQS note together; this plan records implementation work, not completed product functionality.

**Goal:** Add SAGE NUMBERS CHECK as an independent NCA workflow that validates target numeric meaning against immutable OL reference values, evaluates registered alternatives and target footnotes, then checks configured numeric style.

**Architecture:** Build an LLM-assisted `sage.numbers` domain package with deterministic evidence, reference, numeric and style validation and a narrow `nca` adapter to SAGE's existing Job/Run, Scripture, VRS, findings and report infrastructure. Explicitly separate WIP-local, SAGE canonical and Western reference identities. Unsupported semantics remain visible as insufficient evidence.

**Tech Stack:** Existing SAGE model provider/task routing, Python runtime, standard-library `csv`, `fractions`, `dataclasses`, `decimal` where needed for input parsing, JSON/YAML, existing USJ/VRS code and pytest. No new runtime dependency is proposed; XLSX is audit-only using existing openpyxl.

**Spec:** [2026-09-09-NCA-DESIGN.md](../specs/2026-09-09-NCA-DESIGN.md), [current/future SQS behavior](../specs/2026-09-09-NCA-SQS-INTEGRATION.md), and [style setup questionnaire](../specs/2026-09-09-NCA-STYLE-QUESTIONNAIRE.md)

## Global Constraints

- User-facing name: Number Consistency & Accuracy (NCA), also SAGE NUMBERS CHECK.
- Confirmed independent workflow identifier: `nca`; check identifier: `NUMBERS`.
- Main Menu #5: Number Consistency & Accuracy (NCA), immediately after STC at #4; SAGE Maintenance moves to #6.
- The user-confirmed authoritative indexes govern accuracy; the selected style guide governs presentation consistency; registered notes/provenance govern uncertain readings and footnote recommendations.
- Require exactly one validated NCA Number Style Profile at Job setup, following RTC's language-profile pattern. Ship a standard template and support compatible existing profiles. This binding remains mandatory with presentation OFF.
- Before each Run, offer RTC-style ON/OFF toggles for number accuracy, presentation consistency, and footnote review/recommendations. Default all three ON; require at least one enabled check. Toggles control assessment execution, not mandatory Job profile bindings.
- OL HEB/GRK is Authority 1; NIV is secondary evidence only.
- Runtime lookup is Western BK/CH/VS; SAGE's global `canonical_file: org.vrs` remains unchanged.
- Preserve immutable supplied OL values, nullable OL_REF, target spans and evidence provenance.
- Accuracy precedes footnote-dependent final classification and numeric style.
- Do not modify Scripture, Paratext Notes XML, reference datasets or existing sealed Jobs/Runs.
- Runtime resources belong in resolved localdata; no operator packages or source archives in Core.
- Preserve Python 3.10 compatibility and existing Linux/macOS/Windows CI coverage.
- Do not introduce a new general job/check framework or revive legacy SAW operations.
- No all-clear result when required evidence, language capability or scope coverage is insufficient.
- Every report/export, including zero-finding output, states that findings are limited by the selected LLM's language understanding and numeric-interpretation capabilities and that SQS confidence checks have not been applied.
- SQS confidence checks are future functionality, not a current prerequisite. Do not invent a confidence cutoff or measured qualification claim.
- The inherited PENDING_FINAL_RUN gate stays in the source artifact; issue separate qualification receipts.

## Plan status and dependencies

The user confirmed the independent workflow, Main Menu #5 placement and authoritative index hierarchy. Target-language interpretation uses the configured LLM. The user deferred SQS confidence checks to future functionality and requires current reports to disclose LLM capability limitations. No fixed launch-language list is required. The [final reference audit](../specs/2026-09-09-NCA-FINAL-REFERENCE-AUDIT.md) is part of this implementation contract.

**Reference warning R1:** the two authoritative indexes agree on all OL/NIV values. The supplementary expression audit has 51 fewer values across 47 rows, including 16 fewer numeric rows. Runtime counts are 4,392 numeric rows / 6,800 values; supplementary counts are 4,376 source verses / 6,749 expressions. Use authoritative values unchanged and record `REFERENCE_LINEAGE_INCOMPLETE`. This warning does not block index use. Qualification must still reject corrupt files, invalid encodings, duplicate keys, unresolved required source IDs or contradictory authoritative registry/policy records.

Dependency sequence:

```text
1 contracts/reference -> 2 target projection -> 3 LLM extraction and evidence validation -> 4 comparison
4 -> 5 variants/units -> 6 footnotes -> 7 style -> 8 evaluation/reporting
8 -> 9 Jobs/Run/ACT integration -> 10 operator surfaces -> 11 qualification
R1 supplementary-lineage warning --------------------------> 11 recorded limitation
```

Paths below are relative to `app/`. Shell commands explicitly state their working directory. Proposed functions/files do not exist yet. This is divided into reviewable deliveries; each implementation delivery must leave independently testable behavior.

## File and interface map

| New file | Responsibility |
|---|---|
| `system/src/sage/numbers/__init__.py` | Public domain API only |
| `numbers/models.py` | Immutable typed values, expressions, source/target records and outcomes |
| `numbers/reference.py` | Validate/load operator index and supporting registries |
| `numbers/resources.py` | Import unchanged resource package and manage qualification receipts |
| `numbers/target.py` | Visit USJ body/note nodes and preserve source locators |
| `numbers/projection.py` | Existing VRS adapter and Western lookup/coverage groups |
| `numbers/extraction.py` | Validate structured LLM extraction against exact target spans and numeric contracts |
| `numbers/model_tasks.py` | NCA extraction, correspondence and footnote prompts through existing provider routing |
| `numbers/compare.py` | Exact and approved expression equivalence, differences |
| `numbers/variants.py` | Whole-reading alternate lookup and policy selection |
| `numbers/units.py` | Typed adapters for the 12 registered conversion examples |
| `numbers/footnotes.py` | Reading-dependent target-note assessment |
| `numbers/style.py` | Numeric style profile validation and assessment |
| `numbers/policy.py` | NCA pre-Run toggles, prerequisite validation and immutable policy snapshot |
| `numbers/engine.py` | Compose model interpretation with deterministic policy and coverage validation |
| `numbers/results.py` | Machine serialization and strict payload validation |
| `system/src/sage/nca.py` | Existing SAGE lifecycle/task adapter |
| `system/src/sage/nca_reporting.py` | NCA ACT/operator report projection |
| `system/src/sage/nca_cli.py` | NCA command argument handling and dispatch helpers |

The shorthand `numbers/` in this table means `system/src/sage/numbers/`. Tests use `system/tests/numbers/` with an explicit `__init__.py`; fixtures are under its `fixtures/` directory. All source-owned fixtures are synthetic or minimal authorized acceptance values, not copied full Scripture corpora.

### Shared data contract to implement in Task 1

```python
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional, Tuple
from sage.vrs import VerseRef

@dataclass(frozen=True)
class NumericExpression:
    values: Tuple[Fraction, ...]
    kind: str  # CARDINAL, ORDINAL, FRACTION, RANGE, RATIO
    surface: str
    span: Tuple[int, int]  # offsets into the named original text stream
    unit: Optional[str] = None
    qualifier: str = "EXACT"  # ABOUT, LESS_THAN, MORE_THAN also allowed
    role: Optional[str] = None

@dataclass(frozen=True)
class Extraction:
    expressions: Tuple[NumericExpression, ...]
    status: str  # COMPLETE, PARTIAL, UNSUPPORTED
    limitations: Tuple[str, ...] = ()

@dataclass(frozen=True)
class SemanticDecision:
    outcome: str
    evidence_ids: Tuple[str, ...] = ()
    reason_codes: Tuple[str, ...] = ()

@dataclass(frozen=True)
class FootnoteDecision:
    action: str  # NONE, RECOMMEND, REQUIRE
    status: str  # ADEQUATE, MISSING, INADEQUATE, NOT_REQUIRED, NOT_ASSESSED
    outcome: str  # NONE, ADVISORY, REVIEW_MISSING_FOOTNOTE, INSUFFICIENT_EVIDENCE
    evidence_spans: Tuple[Tuple[int, int], ...] = ()
```

Also define these immutable aggregate records before their consumers:

- `ReferenceRow`: `western_reference: VerseRef`, `ol_reference: Optional[str]`, `language: str`, `ol_text: str`, `ol_values: tuple[Fraction, ...]`, `niv_text: str`, `niv_values: tuple[Fraction, ...]`, `metadata: Mapping[str, str]`. Metadata retains every remaining TSV column; freeze the mapping rather than only the dataclass shell.
- `ReferenceBundle`: `package_id: str`, `sha256: str`, `rows: Mapping[VerseRef, ReferenceRow]`, immutable `variants`, `footnote_guidance`, `units`, `provenance` keyed by their documented identifiers; `qualification_status: str`, `diagnostics: tuple[Mapping[str, object], ...]`. Add explicit methods `lookup(ref: VerseRef) -> Optional[ReferenceRow]` and `require_qualified() -> None`.
- `TargetUnit`: `unit_id: str`, `target_references: tuple[VerseRef, ...]`, `main_text: str`, `notes: tuple[TargetNote, ...]`, `source_sha256: str`, `source_locator: Mapping[str, int]`.
- `TargetNote`: `note_id: str`, `marker: str`, `text: str`, `anchor_references: tuple[VerseRef, ...]`, `content_spans: tuple[Mapping[str, object], ...]`. Note text excludes fr/fv locator fields; retain those separately in spans for provenance.
- `ProjectedUnit`: `target: TargetUnit`, `western_references: tuple[VerseRef, ...]`, `canonical_references: tuple[VerseRef, ...]`, `precision: str`, `status: str` (READY, AMBIGUOUS, UNMAPPED, REGISTERED_ABSENCE).
- `ReadingDecision`: `selected: str` (OL, ALT, UNSUPPORTED, UNASSESSED), `semantic: SemanticDecision`, `footnote_action: str`, `registry_id: Optional[str]`, `source_ids: tuple[str, ...]`, `source_validation_outcome: Optional[str] = None`. The last field retains the exact source-policy outcome, including the minority-reading caution and registered OL absence.
- `UnitResult`: projected identities, extraction, reading, footnote decision, final outcome, style findings and limitations. `RunResult`: tuple of UnitResult, findings, coverage and summary mappings. All serialized fractions use reduced strings, never float numbers.

Do not use arbitrary metadata strings as executable instructions. Validators constrain all outcome enums and reject unknown values.

## Task 1: Reference contracts, immutable loading and qualification diagnostics

**Create:** `numbers/models.py`, `numbers/reference.py`, `numbers/resources.py`, `system/config/schemas/numbers-reference.schema.yml`, `system/tests/numbers/test_reference.py`, `fixtures/reference/`.
**Modify:** `system/src/sage/schema_validation.py` to register the schema owner.

**Interfaces:**

```python
parse_values(raw: str) -> tuple[Fraction, ...]
normalize_footnote_action(raw: str) -> str
load_reference(root: Path, *, qualification: str = "STRICT") -> ReferenceBundle
import_reference(config: EcosystemConfig, archive: Path) -> Path
```

- [ ] Write parser/loader tests before implementation, including exact fractions, unsupported encodings, duplicate Western keys, missing columns, missing provenance, checksum failure and mutable nested mappings.

```python
def test_exact_reference_encoding():
    assert parse_values("22000;10000;5/2") == (
        Fraction(22000), Fraction(10000), Fraction(5, 2)
    )
    assert parse_values("") == ()
    assert normalize_footnote_action("NONE_TEXT_CRITICAL") == "NONE"
    assert normalize_footnote_action("N/A") == "NONE"
```

- [ ] Add a synthetic package with agreeing operator/canonical `OL_VALUES=3;4`, an expression audit containing only `3`, and no matching override. STRICT and DIAGNOSTIC loading both retain `3;4`; record `REFERENCE_LINEAGE_INCOMPLETE` without failing qualification solely for supplementary incompleteness. A contradictory authoritative canonical/variant value still fails with `NCA_REFERENCE_CONTRACT_CONFLICT`.
- [ ] Run `python -m pytest -q system/tests/numbers/test_reference.py` from `app/`; witness the intended missing implementation failure.
- [ ] Implement exact parsing, complete checksummed file inventory, registry joins and a separate qualification receipt. Reject malformed numeric encodings rather than relying on Fraction's permissive grammar. Enforce expected cardinalities through the versioned package manifest; synthetic fixtures have their own manifests and do not bypass production counts.
- [ ] Implement bounded archive import: reject absolute/traversal entries and symlink entries; copy into a new package directory and verify before atomic publication. Preserve original bytes. Do not auto-import during startup.
- [ ] Re-run reference tests. Verify all 47 supplementary differences, three unit-text spacing differences and two numeric-source boundary exceptions are reported without changing files. Preserve the two special reading-validation outcomes listed in the final audit. Commit this bounded delivery when execution is authorized.

**Acceptance:** authoritative-table validity, supplementary lineage completeness and software qualification are distinct states. A valid authoritative package can be used with explicit lineage/display/boundary limitations. No warnings or incomplete provenance may be silently erased.

## Task 2: USJ target/footnote extraction and Western projection

**Create:** `numbers/target.py`, `numbers/projection.py`, `system/tests/numbers/test_target.py`, `test_projection.py`.
**Reuse:** `usj.py`, `scripture.py`, `versification_service.py`, `vrs.py`, `verse_alignment.py`; modify shared parser only if a demonstrated required case is absent.

**Interfaces:**

```python
target_units(usj: Mapping[str, object], *, source_sha256: str) -> tuple[TargetUnit, ...]
project_units(units: tuple[TargetUnit, ...], *, target_schema: VersificationSchema,
              western_schema: VersificationSchema) -> tuple[ProjectedUnit, ...]
```

- [ ] Test preserved body/note separation using the existing compiler:

```python
def test_note_digits_do_not_enter_main_text():
    usj = compile_usfm_text(
        "\\id MAT Fixture\n\\c 1\n"
        "\\v 1 Three men.\\f + \\fr 1:1 \\ft Other witnesses read thirty.\\f*\n"
    )
    unit, = target_units(usj, source_sha256="0" * 64)
    assert unit.main_text == "Three men."
    assert unit.notes[0].text == "Other witnesses read thirty."
```

- [ ] Add explicit cases for nested note styles; note-only verses; x/ex exclusions; unclosed note parser errors; attributes containing digits; headings; bridge 1–2 with one shared body; PSA 51:0 repeated mappings; 1KI 4:26→OL 5:6 and 1KI 5:11→OL 5:25.
- [ ] Add PSA 60:0 as an accuracy-bearing canonical superscription with value 12000 and OL_REF=PSA 60:2. Recover the target `\d` structural node when no `\v 0` exists; ordinary editorial-heading exclusion must not skip this indexed row.
- [ ] Add Western 1SA 20:42 / 1CH 12:4 tests preserving stored OL_REF=1SA 20:42 / 1CH 12:4 despite the supplied mapping projecting to 1SA 21:1 / 1CH 12:5. Western lookup uses the authoritative row; non-Western target units require boundary grouping rather than comparing against the continuation alone. Never regenerate OL_REF from the map.
- [ ] Use the indexed NIV values unchanged at section continuations such as NEH 7:73 and HAG 1:15. Retain a readback limitation for source continuation numbers absent from indexed NIV_TEXT; source text must not silently augment the authoritative secondary numeric sequence.
- [ ] Add NEH 7:68 missing-WIP/empty-OL registry coverage cases. An adjacent verse's note is insufficient without unambiguous explicit anchoring; identity fallback cannot create an OL source verse.
- [ ] Run `python -m pytest -q system/tests/numbers/test_target.py system/tests/numbers/test_projection.py` from `app/` and witness failures.
- [ ] Implement tree visitors and mapping adapters; return explicit AMBIGUOUS/UNMAPPED states. Reconcile expected coverage separately from observed WIP records so absent coordinates are assessed.
- [ ] Re-run new tests plus `system/tests/test_usj_and_scripture.py`, `test_versification_service.py`, `test_verse_alignment.py`; commit after review.

## Task 3: LLM numeric interpretation and exact evidence validation

**Create:** `numbers/extraction.py`, `numbers/model_tasks.py`, `system/config/schemas/nca-extraction.schema.yml`, `system/tests/numbers/test_extraction.py`, `test_model_tasks.py`, and the NCA task/skill material required by existing SAGE routing.
**Modify:** schema ownership and existing task/skill registries as required by their actual contracts. Reuse Project language identity and current model selection; no English-only runtime parser gate.

**Interfaces:**

```python
build_extraction_payload(unit: TargetUnit, *, language: str,
                         style_profile: Mapping[str, object]) -> Mapping[str, object]
validate_extraction_response(unit: TargetUnit,
                             response: Mapping[str, object]) -> Extraction
```

The extraction payload contains only the target text streams, language, parsing-relevant style conventions and output schema. Keep expected OL/NIV quantities out of this extraction step. Each returned expression has an exact target stream/span, normalized fraction strings, kind, unit, qualifier and referent evidence where applicable. Later correspondence tasks may receive the specific authoritative reference row.

- [ ] Write a synthetic response fixture for `three hundred and eighteen men`: one span `0:26`, one CARDINAL value `318`. Validate exact span equality, parse with `Fraction`, and preserve the original surface. Reject a fabricated quotation, out-of-range span or value encoded as an unsupported JSON type.
- [ ] Write separate fixtures for `the third man` (ORDINAL `3`) and `a third of the men` (FRACTION `1/3`). Include an explicitly ambiguous response that remains PARTIAL; the validator must not upgrade uncertainty based on a model confidence claim.
- [ ] Test Unicode digits, grouping/decimal ambiguity, mixed `2 1/2`, repeated quantities, ratios, ranges and qualifiers. For words plus parenthesized digits, preserve both spans and require equal values before treating them as one expression.
- [ ] Test schema violations, absent work units, duplicate expression IDs, unrelated note/locator digits, invented source evidence and provider failures. A self-reported high score cannot bypass structural validation.
- [ ] Run `python -m pytest -q system/tests/numbers/test_extraction.py system/tests/numbers/test_model_tasks.py` before implementation and witness the intended failures.
- [ ] Implement bounded prompts and response validation, then wire model requests through existing SAGE provider/task execution. Keep recorded synthetic provider responses in tests; no live paid calls in ordinary CI.
- [ ] Preserve PARTIAL/UNSUPPORTED results and report limitations where the model cannot interpret the target adequately. Do not claim full language support from zero extracted digits or successful schema validation.
- [ ] Register task material and capture the actual provider/model, task version and input hashes. Apply existing routing requirements; SQS is not a current dependency. Re-run tests and commit the bounded delivery when execution is authorized.

## Task 4: Conservative numeric correspondence

**Create:** `numbers/compare.py`, `system/tests/numbers/test_compare.py`.

**Interface:** `compare_expressions(ol: tuple[NumericExpression, ...], target: Extraction, *, allow_reordering: bool = False) -> SemanticDecision`.

- [ ] Define a small test-only constructor in this test module:

```python
def quantity(value: int, role: str) -> NumericExpression:
    return NumericExpression((Fraction(value),), "CARDINAL", str(value),
                             (0, len(str(value))), role=role)

def test_equal_value_bag_does_not_justify_reassigned_quantities():
    ol = (quantity(3, "sheep"), quantity(7, "goats"))
    target = Extraction((quantity(7, "sheep"), quantity(3, "goats")), "COMPLETE")
    assert compare_expressions(ol, target, allow_reordering=True).outcome == "REVIEW_VALUE_DIFFERENCE"

def test_reordered_corresponding_quantities_can_pass():
    ol = (quantity(3, "sheep"), quantity(7, "goats"))
    target = Extraction((quantity(7, "goats"), quantity(3, "sheep")), "COMPLETE")
    assert compare_expressions(ol, target, allow_reordering=True).outcome == "PASS_EQUIVALENT_NUMERIC_EXPRESSION"
```

- [ ] Add cases for exact sequences; surface-only digit/word differences; missing/added/replaced values; repeated values; qualifier/unit changes; ordinal versus partitive; ratio preservation; PARTIAL extraction; unavailable OL expression-role evidence.
- [ ] Run `python -m pytest -q system/tests/numbers/test_compare.py` and witness failures. Implement relationship-preserving matching and explicit insufficient-evidence decisions where correspondence is unsupported.
- [ ] Keep value agreement separate from full semantic evidence. The engine must not create fully typed OL expressions from a flat value list by inventing roles, kinds or units.
- [ ] Verify all tests, especially swapped-role negatives; commit.

## Task 5: Registered alternates and scoped unit examples

**Create:** `numbers/variants.py`, `numbers/units.py`, `system/tests/numbers/test_variants.py`, `test_units.py`.

**Interfaces:**

```python
select_reading(row: ReferenceRow, target_values: tuple[Fraction, ...], *,
               bundle: ReferenceBundle, semantic: SemanticDecision) -> ReadingDecision
parse_registered_quantity(raw: str) -> tuple[NumericExpression, ...]
compare_registered_units(row: ReferenceRow, target: Extraction, *,
                         bundle: ReferenceBundle) -> SemanticDecision
```

- [ ] Test the full 21-row reading matrix using small numeric/policy fixtures copied with source IDs and expected values; each fixture's package integrity is validated as in Task 1. Require registry authorization, not just NIV equality.
- [ ] Unit adapter contract test:

```python
def test_registered_range_and_qualifier_are_retained():
    expression, = parse_registered_quantity("about 3-4 miles")
    assert expression.kind == "RANGE"
    assert expression.values == (Fraction(3), Fraction(4))
    assert expression.unit == "mile"
    assert expression.qualifier == "ABOUT"
```

- [ ] Add whole-sequence tests: 2CH 22:2 alternate `22;1` can select ALT; `22;2` cannot. NEH 7:68 OL omission and ALT inclusion have distinct reading states. Test unit equivalence at all 12 registered keys plus wrong verse, wrong unit, missing qualifier and changed unrelated quantity negatives.
- [ ] Preserve the source-policy subtypes `CAUTION_ACCEPTABLE_ATTESTED_MINOR_READING_WITH_FOOTNOTE` (1SA 6:19 alternate) and `NO_CONFIGURED_OL_READING` (NEH 7:68 OL absence). Use operator NIV_TEXT for the three unit examples whose copied text omits spaces; do not edit their registry bytes or quantities.
- [ ] Run `python -m pytest -q system/tests/numbers/test_variants.py system/tests/numbers/test_units.py`; implement typed adapters derived from supplied fields and joins, preserving original prose and hashes.
- [ ] Never infer scholarship from source URLs or runtime model recall. Preserve the OL row even for NIV_FAVORED. Reject unprovided conversion formulas/tolerances. Treat an unrecognized registry quantity as unsupported, not a fabricated conversion.
- [ ] Re-run tests and reference immutability checks; commit.

## Task 6: Reading-dependent footnote adequacy

**Create:** `numbers/footnotes.py`, `system/tests/numbers/test_footnotes.py`.

**Interface:** `assess_footnote(reading: ReadingDecision, notes: tuple[TargetNote, ...], *, bundle: ReferenceBundle, language: str) -> FootnoteDecision`.

- [ ] Test missing-required and recommended outcomes independently of numeric accuracy:

```python
def test_divided_ol_reading_still_requires_disclosure(empty_bundle):
    reading = ReadingDecision("OL", SemanticDecision("PASS_AUTHORITY1"),
                              "REQUIRE", "1SA 13:5", ())
    decision = assess_footnote(reading, (), bundle=empty_bundle, language="en")
    assert decision.status == "MISSING"
    assert decision.outcome == "REVIEW_MISSING_FOOTNOTE"
```

For this test, add a fixture in `system/tests/numbers/conftest.py` that returns an immutable `ReferenceBundle` with empty registries, no rows, diagnostic status and hash `"0" * 64`. The missing-note branch uses the already selected reading/action; tests requiring material assessment supply the actual synthetic registry row.

- [ ] Cover alternative values stated in words/digits, witness-only numeric difference disclosure, reconstruction disclosure, an unrelated note containing the same number, locator-only digits, cross-reference notes, wrong-verse notes, NIV notes and unsupported note language. Test all four actual DIVIDED rows, including both choices.
- [ ] Run `python -m pytest -q system/tests/numbers/test_footnotes.py`; implement LLM disclosure assessment using the selected registered reading and exact target-note evidence, then validate the returned evidence and policy result. Unknown adequacy yields NOT_ASSESSED/INSUFFICIENT_EVIDENCE; absence and known inadequacy yield distinct statuses.
- [ ] Preserve the semantic pass for OL+RECOMMEND even when the final report adds an advisory. Never accept a documented alternate with unassessed required disclosure.
- [ ] Recommend adding or revising a footnote only when the selected reading's policy calls for disclosure and the existing target note is absent or inadequate. Supply the relevant suggested wording, alternate/uncertainty explanation and source IDs. An adequate existing note produces no duplicate add-note recommendation. Unregistered uncertainty remains operator review, never invented manuscript evidence.
- [ ] Re-run tests; commit. Reuse Task 3 model routing; do not introduce a separate provider or confidence service.

## Task 7: Numeric style without changing semantic results

**Create:** `numbers/style.py`, `system/config/profiles/numbers/number-style-template.yml`, `system/config/schemas/number-style-profile.schema.yml`, `system/tests/numbers/test_style.py`.
**Modify:** schema owners and native profile resource selection.

**Interfaces:**

```python
validate_style_profile(raw: Mapping[str, object]) -> Mapping[str, object]
assess_style(extraction: Extraction, *, profile: Mapping[str, object],
             location: str, context: Optional[str]) -> tuple[Mapping[str, object], ...]
```

- [ ] Cover missing/invalid profiles, blank draft templates, incompatible language/script, required metadata, rule IDs, words/digits bands, grouping/decimal conventions, ordinal/fraction/range notation, approximation, age/date/count context exceptions and location-specific unit abbreviations. Each rule area requires a rule or an explicit NOT_SPECIFIED/NOT_APPLICABLE decision. Profile absence is a setup error; explicitly unspecified rules in a valid profile remain unassessed.

```python
def test_empty_template_cannot_be_used_as_active_profile():
    with pytest.raises(ValidationError) as exc:
        validate_style_profile({})
    assert exc.value.code == "NCA_STYLE_PROFILE_INVALID"
```

- [ ] Run `python -m pytest -q system/tests/numbers/test_style.py`; implement the governed template, validated rules and context limitations. The shipped template is a draft for configuration, not an automatically active Western style guide. Include profile ID/version, Project/language/script applicability, source guide, status and stable rule IDs. Create configured copies through the existing local profile storage/registration conventions, outside replaceable Core.
- [ ] Ensure body, heading and note style streams remain separate; no numbers from those latter streams enter body accuracy. Unavailable map/table material is not claimed as assessed.
- [ ] Require profile selection and validation at Job setup regardless of the presentation toggle. Test that presentation OFF does not bypass an absent/invalid profile, and that a valid bound profile is snapshotted even when its assessment is disabled. No mutation of normalized values is allowed during style assessment.
- [ ] Evaluate presentation consistency across comparable expressions within the selected scope using the same guide rule, location and context. Test mixed digits/words/grouping/abbreviations, approved context exceptions and a majority presentation that violates the guide. Missing guide rules yield an unassessed area, not an inferred rule. Canonical superscriptions retain their explicit accuracy-bearing role from Task 2.
- [ ] Re-run tests; commit.

## Task 8: Engine, result schema, coverage and deterministic ACT rendering

**Create:** `numbers/engine.py`, `numbers/results.py`, `system/src/sage/nca_reporting.py`, `system/config/schemas/numbers-result.schema.yml`, `system/tests/numbers/test_engine.py`, `test_results.py`, `test_reporting.py`.
**Modify:** schema owners; use existing `findings.py`, `coverage.py`, `human_output.py`, `report_authority.py` helpers through explicit adapters.

**Interfaces:**

```python
evaluate_unit(unit: ProjectedUnit, *, bundle: ReferenceBundle,
              language: str, language_profile: Mapping[str, object],
              style_profile: Mapping[str, object],
              check_policy: Mapping[str, object]) -> UnitResult
summarize(results: tuple[UnitResult, ...]) -> Mapping[str, int]
validate_numbers_result(document: Mapping[str, object], *,
                        expected_unit_ids: tuple[str, ...],
                        allowed_evidence_ids: tuple[str, ...]) -> Mapping[str, object]
render_nca_report(document: Mapping[str, object]) -> str
```

- [ ] Create complete synthetic UnitResult fixtures and serialization tests before engine implementation. The tests must mutate outcome enums, evidence IDs, coverage, profile hashes and fractions and verify rejection, not just round-trip the same implementation.
- [ ] Add pipeline cases: OL pass plus recommended-note advisory; alternate+adequate note; alternate+missing note; unindexed target number; no digits in unsupported language; known OL number with absent target text; bridge count once; style disabled but numeric accuracy assessed.
- [ ] Apply the snapshotted check policy: OFF checks emit no findings and are NOT ASSESSED, never passes. Test footnote-only reading identification without accuracy findings; accuracy-only registered alternate without a claim of fulfilled footnote requirements; presentation-only assessment without an OL-accuracy claim. Internal prerequisites may run without enabling a disabled assessment. In particular, footnotes OFF prohibits `ACCEPTABLE_VARIANT_WITH_FOOTNOTE`.
- [ ] Add exact report assertions for Western and differing OL_REF, target-local navigation, SOURCE_IDS, selected reading, footnote status/action and suggested note. Preserve NUMBERS-only scope; seed unrelated grammar/theology/name issues and assert no findings for them.
- [ ] Run `python -m pytest -q system/tests/numbers/test_engine.py system/tests/numbers/test_results.py system/tests/numbers/test_reporting.py`; implement the composed pipeline and typed result validation. Reuse run-global finding IDs instead of independent NUM-0001 counters.
- [ ] Require the LLM capability limitation in every human report, export, zero-finding result and incomplete-result summary. Machine output carries the same limitation, actual provider/model identity and an explicit statement that SQS checks were not applied. Add a report-contract test that fails when the limitation is absent, including localized output.
- [ ] Require `expected_unit_ids` to reconcile exactly once. Summaries derive from actual assessed expressions and results; include insufficient evidence, reference-not-indexed and parser coverage. Completion and all-clear are distinct.
- [ ] Re-run tests and `system/tests/test_findings_and_coverage.py`, `test_report_authority.py`; commit.

## Task 9: NCA workflow, Jobs/Runs and ACT dispatch

**Create:** `system/src/sage/nca.py`, `numbers/policy.py`, `system/config/workflows/nca/profile.yml`, `system/config/schemas/nca-check-policy.schema.yml`, `system/tests/numbers/test_policy.py`, `test_nca_jobs.py`, `test_nca_tasks.py`.
**Modify:** `workflow_identity.py`, `jobs.py`, `job_snapshots.py`, `job_layout.py`, `act_tasks.py`, `profiles.py`, `registry.py`, `runtime_status.py`, `progress.py`, `execution_events.py`, `system/config/schemas/{job,run,active-jobs,act-task,act-control,workflow-profile,ecosystem}.schema.yml`, `ecosystem.yml`.

Audit dependent shared branches in `state.py`, `validation.py`, `evidence.py`, `report_translation.py`, `job_data_reset.py`, `out_of_box_reset.py` before including NCA. Modify only branches required for its actual lifecycle. Update `schema_validation.py` if ownership changes.

**Interfaces:**

```python
create_nca_task(config: EcosystemConfig, *, job_id: str, run_id: str,
                scope_value: str) -> Mapping[str, object]
execute_nca_task(config: EcosystemConfig, task_manifest: Path) -> Mapping[str, object]
finalize_nca_run(config: EcosystemConfig, *, job_id: str,
                 run_id: str) -> Mapping[str, object]
```

- [ ] Add binding/identity tests: one WIP; no required REFERENCE; one package selector and hash; exactly one required `number_style` profile binding; Project language and configured model route; project import-date identity `NCA-<Project>_<YYYYMMDD>`. Follow the RTC Job profile resolver: one compatible candidate resolves automatically and is shown; multiple candidates require selection; none requires configuration/import. Keep resource selectors outside Scripture binding role dictionaries.
- [ ] Implement an NCA-owned policy using the pattern in `rtc_policy.py`: `checks.number_accuracy`, `checks.presentation_consistency`, `checks.footnote_review`, all boolean and initially true. Reject all-OFF. Validate mandatory Job bindings first, then prerequisites for enabled assessments and their internal dependencies. Keep saved Job defaults editable, and write immutable Run `check-policy.json` including the required style profile ID/version/hash even when presentation is OFF. Register the new schema owner.
- [ ] In `test_policy.py`, exercise all eight toggle combinations with a valid bound profile (all-OFF rejected), missing/invalid profile with presentation ON and OFF (both rejected), exact snapshot replay and attempted mid-Run policy changes. Changes in Job defaults or profile contents must not alter a resumed Run.
- [ ] Test creation, immutable snapshot reuse, input/profile/package change detection, stale runs, restart/resume, active-job discovery, exactly one active execution and read-only WIP. Old RTC/STC/SAW artifacts retain their serialized identities and contracts.
- [ ] Run `python -m pytest -q system/tests/numbers/test_nca_jobs.py system/tests/numbers/test_nca_tasks.py` and witness failures.
- [ ] Implement explicit workflow predicates and dispatch. Do not insert NCA into RTC/STC-only sets and rely on fallback branches. Existing RTC semantic/OL policy and STC no-reference-evidence rules remain unchanged.
- [ ] Add explicit NCA model task dispatch in the shared ACT contract using existing provider/skill routing and readiness requirements. Fingerprint target data, mapping, package, style profile, model and prompt/task identities; write only inside existing governed Run paths. Record actual provider usage and distinguish local validation from model execution. Reconcile coverage-based progress without changing other workflows' progress contracts.
- [ ] Preserve provider readiness for model-dependent NCA execution; local reference/profile inspection need not call the model. Test missing provider remediation, failed model calls and partial results. SQS checks are future functionality and must not become a current setup blocker.
- [ ] Validate authoritative reference contracts before real accuracy execution. R1 and documented text-copy differences remain visible warnings, not blanket blockers. Distinguish usable authoritative-reference status from software release qualification. Run failure cannot leave a partial report marked complete.
- [ ] Verify with new tests plus `test_primary_analysis_jobs.py`, `test_authority_boundaries.py`, `test_job_snapshots.py`, `test_progress_tracking.py`, `test_storage_layout.py`; commit.

**Design limit:** NCA does not call BIC/RTC/STC or automatically share their jobs. Model interpretation uses the explicit NCA tasks and existing routing. Future SQS confidence checks are tracked separately.

## Task 10: Operator CLI/menu, profiles and documentation

**Create:** `system/src/sage/nca_cli.py`, `docs/NCA-CHEAT-SHEET.md`, `system/tests/numbers/test_nca_cli.py`, `test_nca_menu.py`.
**Modify:** `cli.py`, `menu.py`, `ui_services.py`, `human_output.py`, `system/config/localization/menu-localization.json`, `docs/INDEX.md`, `docs/OPERATOR-GUIDE.md`, `docs/advanced/workflows/BIC-RTC-STC-AUTHORITY-BOUNDARIES.md` (extend scope/title to include NCA), `docs/advanced/architecture/SAGE-SYSTEM-GRAMMAR.md`.

- [ ] Test one complete menu/CLI scenario: import reference → inspect qualification diagnostic → select WIP/language/style → create NCA Job → select scope → execute qualified synthetic task → show accuracy/footnote/style/coverage report. Also test cancellation, unavailable package, unsupported language and missing style.
- [ ] During Job setup, require selection of a compatible NCA Number Style Profile or configuration of a copy of the standard template, following RTC's language-profile interaction. Offer RTC-style numbered check toggles before Run creation: Number accuracy; Presentation consistency; Footnote review and recommendations. Show the mandatory bound profile and a Job-profile change action beside presentation settings. Reuse Job defaults and expose the same policy through CLI options.
- [ ] Test switching each toggle, restoring defaults, all-OFF readiness, missing-profile remediation, compatible-profile reuse and presentation-OFF execution with a valid profile. Presentation OFF cannot complete setup without the required profile. Reports list enabled/disabled checks, bound profile version and NOT ASSESSED status for every disabled assessment. Do not infer toggle state from whether a resource happens to be available.
- [ ] Follow the actual existing command grammar for Job/Run operations. Add workflow `nca` and operation `numbers` to canonical routes; keep detailed NCA argument handling in `nca_cli.py`. Add a reference inspection/import command under the existing resource command family rather than a parallel installer.
- [ ] Insert **5. Number Consistency & Accuracy (NCA)** immediately after **4. Source Text Correspondence (STC)** in `main_menu`; change `run()` dispatch so 5 opens NCA and 6 opens SAGE Maintenance. Move the maintenance separator from `blank_before=("2", "5")` to `("2", "6")`. Update active-Job summary, localization, help/cheat-sheet references and tests together. Preserve Projects=1, BIC=2, RTC=3, STC=4, Exit=X. Test both displayed labels and actual dispatch for 5/6.
- [ ] Run `python -m pytest -q system/tests/numbers/test_nca_cli.py system/tests/numbers/test_nca_menu.py` before and after implementation. Confirm machine codes remain canonical while human labels use the current localization catalog and Job report language.
- [ ] Document the distinction between semantic outcomes, recommended notes, required notes and insufficient evidence; explain no automatic text edits. Include input language capability and numeric reference coverage in preflight, visible beside accuracy/style readiness.
- [ ] Preserve TUI execution limitations and original BIC/RTC/STC navigation behavior. Test `test_command_contract.py`, `test_primary_workflow_menus.py`, `test_menu_localization.py`, `test_documentation_contracts.py`; commit.

## Task 11: Full acceptance, reference release gate and packaging

**Create:** `system/tests/numbers/test_acceptance.py`, `test_reference_release.py`, `system/tools/validate_numbers_reference.py`, `docs/advanced/release/NCA-QUALIFICATION.md`.
**Modify:** `.github/workflows/ci.yml` at repository root only if an additional NCA qualification command is needed; `system/tools/build_release.py` / `validate_package.py` / `deep_audit.py` only for demonstrated new resource-boundary checks.

- [ ] Use an isolated qualification environment with the existing pinned dependencies and record Python/dependency versions. The preceding filename-template repair passed 80 targeted tests; it also identified existing workspace artifacts and release/documentation failures. Preserve that distinction and establish an NCA baseline before implementation; the repair tests are not NCA acceptance evidence.
- [ ] Verify authoritative-table and registry integrity against the final audit. Keep R1 as a recorded supplementary-lineage warning, using 6,800 as the runtime value count and 6,749 as the supplementary audit count. Reference maintenance, if later undertaken, gets a new package identity. Do not hide actual contract errors with xfail or broad skips.
- [ ] Implement an explicit real-resource qualification mode. Synthetic CI stays self-contained; release qualification requires the authorized package and fails when missing. Do not publish the supplied OL/NIV source bundles or their full-text derived index without resolving the handover's stated distribution metadata through existing resource-rights governance.
- [ ] Run the complete acceptance matrix below and publish exact environment, package hashes, counts, outcomes and limits in a separate receipt. Do not edit workbook gate cells.
- [ ] From `app/`, run the existing gates in the qualification interpreter:

```sh
python -m pytest -q system/tests/numbers
python system/tools/validate_schemas.py
python system/tools/validate_package.py
python -m pytest -p no:cacheprovider system/tests
python system/tools/deep_audit.py . --mode source
```

- [ ] Run the future dedicated command `python system/tools/validate_numbers_reference.py --package <authorized-package-directory> --release`; its exit status must be nonzero for corrupt or contradictory authoritative records, absent sources required for acceptance, or failed golden fixtures. The documented supplementary-lineage warning alone must not cause failure. The path is supplied at execution; it is not bundled Core configuration.
- [ ] Check supported CI platforms/Python versions, release contents, reproducible reports, no writes to Scripture/reference inputs and no runtime files in Core. Record observed timing/memory on the full dataset; set performance targets from this measured baseline rather than inventing a guarantee in the plan.
- [ ] Review the final diff and qualification evidence, then complete the authorized development-branch workflow. No publish/deploy action is included in this planning request.

## Mandatory acceptance traceability

| Handover requirement | Implementation/test owner | Required evidence |
|---|---|---|
| A: 6,244 unique rows; 21 critical; 12 unit; 341 classified tokens; provenance | Tasks 1, 11 | Counts, hashes, enum/number/schema checks and cross-table joins |
| A: 4,376 verses / 6,749 expressions | Tasks 1, 11 + R1 | Preserve supplementary count definitions and 4,392/6,800 authoritative runtime counts; retain all 47 differences as lineage warnings |
| B: GEN 14:14 | Tasks 1, 3, 11 | OL `318`; compound target yields one quantity |
| B: JDG 7:3 / JDG 20:10 | Tasks 3, 4, 11 | `22000;10000`; ratio `10;100;100;1000;1000;10000` not collapsed |
| B: 1SA 25:2 / PSA 91:7 | Tasks 4, 11 | `3000;1000` and `1000;10000`; relationship-preserving reordering only |
| B: EXO 25:10 | Tasks 1, 3, 11 | Exact `5/2;3/2;3/2` with multiplicity |
| B: 1CH 24:11 / 1KI 18:44 | Tasks 1, 3, 11 | `9;10` and `7`, ordinal evidence retained |
| B: ZEC 3:9 / DAN 1:10 | Tasks 1, 4, 11 | `1;7;1`; no false drink/verbal `2`; DAN absent runtime row is not a zero-value row |
| B: REV 5:11 / REV 4:7 / REV 6:8 | Tasks 3, 4, 11 | Independent `10000;10000;1000;1000`; ordinals `1;2;3;4`; partitive `1/4` |
| C: 1KI and Psalm title shifts | Tasks 2, 11 | Actual existing VRS projection; no one-to-many loss or duplicated expressions |
| Canonical superscription and numeric-source boundary cases | Tasks 2, 11 | PSA 60:0=12000 is assessed from structural content; 1SA 20:42 and 1CH 12:4 retain stored source attribution |
| D: exact/equivalent/missing/added/different/unit/alternate/note outcomes | Tasks 4–8 | Positive and adversarial negative examples, including partial evidence |
| E: 1SA 6:19 | Tasks 5, 6, 11 | OL `70;50000` retains OL-favored policy; alt `70` requires note; OL missing recommended note is advisory |
| E: 1SA 13:5 | Tasks 5, 6, 11 | `30000;6000` / `3000;6000`; either requires disclosure |
| E: 2SA 15:7 / 2CH 22:2 | Tasks 5, 6, 11 | Registered alternate 4 / `22;1`; whole reading and note required |
| E: NEH 7:68 | Tasks 2, 5, 6, 11 | Registered OL omission versus `736;245` inclusion; both disclosure paths, no fabricated OL_REF |
| E: EZK 40:49 / EZK 42:4 | Tasks 5, 6, 11 | `20;11;1;1` / `20;12`; `10;1` / `10;100`; divided-note decisions |
| F: negative scope | Tasks 8, 11 | No vocabulary/name/theology/general grammar/punctuation findings |
| G: immutability | Tasks 1, 5, 9, 11 | Hashes before/after runs; attempted mutations rejected; NIV/alternate never replaces OL |
| Output fields and all summary counters | Tasks 8, 10, 11 | Schema validation, stable IDs, operator-language reporting, complete nonduplicated coverage |
| Mandatory style template/profile | Tasks 7, 9–11 | Standard template supplied; exactly one compatible configured profile required at Job setup; blank draft invalid; profile ID/version/hash snapshotted for every Run |
| Unsupported languages/unindexed verses | Tasks 2–4, 8, 11 | Explicit incomplete coverage and insufficient evidence, never silent passes |
| Current LLM capability disclosure; future SQS | Tasks 3, 6, 8–11 | Every report/export includes the limitation; no SQS prerequisite or qualification claim; exact evidence validation remains enforced |
| Existing SAGE behavior | Tasks 9–11 | Full regression/CI suite; old workflow identity and authority contracts preserved |
| Confirmed Main Menu placement | Tasks 9–11 | NCA=5 after STC=4; Maintenance=6; matching display/dispatch/help/localization; model execution checks provider readiness; local inspection does not invoke the model |
| Confirmed RTC-style pre-Run toggles | Tasks 7–11 | Three independent toggles; mandatory style-profile binding retained even when presentation OFF; all-OFF rejected; immutable Run policy; disabled checks never reported as passes |

## Review checklist before implementation handoff

- [x] Independent NCA workflow, Main Menu #5 after STC and authoritative OL-primary/NIV-secondary indexes confirmed by user.
- [x] Use configured LLM interpretation; defer SQS confidence checks; require the report capability limitation in the current version.
- [ ] Read design and audit together; separate data qualification from successful software execution.
- [ ] Keep authoritative contract validation and documented supplementary-lineage limitations visible throughout development.
- [ ] Implement/test domain deliveries before broad menu/lifecycle integration.
- [ ] Keep every new outcome, field and interface consistent across schema, engine, reports and tests.
- [ ] Require task-specific failing/passing tests and reviewer-visible commits during execution.

The planning deliverables are complete when this plan, the design and the audit are available for review. Product completion requires all implementation and qualification gates above; none is claimed by this planning document.

## Future functionality: shared SQS confidence checks

Add SQS integration only when its shared specification exists. Map the real assessment states, service interface, policy versioning, thresholds and review/retry rules then. Preserve the current evidence/authority separation and immutable Run history. This future work does not block the implementation described above and must not be represented as already performed in its reports.
