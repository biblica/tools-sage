"""NCA engine composition keeps accuracy, footnotes, and style independent."""

from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace

from sage.numbers.engine import evaluate_run, evaluate_unit
from sage.numbers.model_tasks import CorrespondenceEvidence
from sage.numbers.models import (
    Extraction,
    FootnoteDecision,
    NumericExpression,
    ProjectedUnit,
    ReferenceBundle,
    ReferenceRow,
    TargetNote,
    TargetUnit,
)
from sage.numbers.results import numbers_result_document, validate_numbers_result
from sage.vrs import VerseRef


AREAS = (
    "digits", "bands", "grouping", "decimal", "ordinals",
    "fractions", "ranges", "qualifiers", "contexts", "units",
)


def style_profile(*, words: bool = False) -> dict[str, object]:
    """Create a complete configured guide with optional words-only bands."""
    rules = {area: {"id": f"NCA-{area.upper()}", "status": "NOT_SPECIFIED"} for area in AREAS}
    if words:
        rules["bands"] = {
            "id": "NCA-BANDS",
            "status": "CONFIGURED",
            "bands": [{"min": "0", "max": None, "form": "WORDS"}],
        }
    return {
        "schema_version": "1.0",
        "profile": {
            "id": "fixture-en",
            "version": "1",
            "language": "en",
            "script": "Latn",
            "projects": ["*"],
            "source_guide": "Synthetic guide",
            "recorded_by": "Fixture operator",
            "recorded_date": "2026-09-09",
            "status": "CONFIGURED",
        },
        "rules": rules,
    }


def check_policy(*, accuracy: bool = True, presentation: bool = True,
                 footnotes: bool = True) -> dict[str, object]:
    """Build the exact three-check policy snapshot."""
    return {
        "checks": {
            "number_accuracy": accuracy,
            "presentation_consistency": presentation,
            "footnote_review": footnotes,
        }
    }


def phase_receipt(phase: str) -> dict[str, object]:
    """Build one exact deterministic receipt for canonical engine-result validation."""
    return {
        "phase": phase,
        "task_version": f"nca-{phase.casefold()}-1.0",
        "provider": "fixture-provider",
        "model": "fixture-model",
        "reasoning_effort": "medium",
        "route_id": "nca-numbers",
        "routing_mode": "AUTOMATIC",
        "qualification_status": "PROVISIONAL_UNQUALIFIED",
        "prompt_sha256": "c" * 64,
        "input_sha256": "d" * 64,
        "response_sha256": "e" * 64,
        "provider_metadata": {},
    }


def expression(text: str, value: int, *, role: str = "men", expression_id: str = "target-1",
               stream_id: str = "main", unit: str | None = None) -> NumericExpression:
    """Create one exact role-bound numeric expression for a controlled stream."""
    surface = next(part for part in text.split() if any(char.isdecimal() for char in part))
    start = text.index(surface)
    return NumericExpression(
        (Fraction(value),),
        "CARDINAL",
        surface,
        (start, start + len(surface)),
        unit=unit,
        role=role,
        expression_id=expression_id,
        stream_id=stream_id,
        role_spans=((0, len(text)),),
    )


def expression_at(
    text: str,
    surface: str,
    value: int,
    *,
    role: str,
    expression_id: str,
    stream_id: str,
) -> NumericExpression:
    """Create one expression at the exact occurrence selected by its surface."""
    start = text.index(surface)
    role_start = text.index(role)
    return NumericExpression(
        (Fraction(value),),
        "CARDINAL",
        surface,
        (start, start + len(surface)),
        role=role,
        expression_id=expression_id,
        stream_id=stream_id,
        role_spans=((role_start, role_start + len(role)),),
    )


def projected(ref: VerseRef, text: str, *, notes: tuple[TargetNote, ...] = (),
              end: int | None = None, western: tuple[VerseRef, ...] | None = None) -> ProjectedUnit:
    """Create one ready target projection, optionally spanning a bridge."""
    references = tuple(VerseRef(ref.book, ref.chapter, verse) for verse in range(ref.verse, (end or ref.verse) + 1))
    target = TargetUnit("unit-1", references, text, notes, "a" * 64, {"line_start": 1, "line_end": 1})
    western_refs = western if western is not None else (ref,)
    precision = "EQUIVALENCE_GROUP" if len(references) > 1 or len(western_refs) > 1 else "COORDINATE"
    return ProjectedUnit(target, western_refs, references, precision, "READY")


def reference_bundle(ref: VerseRef, *, ol: int = 3, niv: int = 3,
                     registered: bool = False, unit_record: dict[str, str] | None = None,
                     ol_action: str = "NONE") -> ReferenceBundle:
    """Build one qualified immutable authority row with optional policy records."""
    row = ReferenceRow(
        ref,
        ref.label(),
        "GRK",
        f"{ol} men",
        (Fraction(ol),),
        f"{niv} men",
        (Fraction(niv),),
        {"SOURCE_IDS": "SRC-1", "FOOTNOTE_IF_TARGET_FOLLOWS_OL": ol_action},
    )
    variants = {}
    guidance = {}
    if registered:
        variants[ref] = {
            "OL_VALUE_RESEARCHED": str(ol),
            "NIV_VALUE_RESEARCHED": str(niv),
            "SOURCE_IDS": "SRC-1",
            "CLASS": "TEXTUAL_VARIANT",
            "SCHOLARSHIP_STATUS": "SUPPORTED",
        }
        guidance[ref] = {
            "OL_VALUES": str(ol),
            "ALT_NIV_VALUES": str(niv),
            "SOURCE_IDS": "SRC-1",
            "CLASS": "TEXTUAL_VARIANT",
            "SCHOLARSHIP_STATUS": "SUPPORTED",
            "FOOTNOTE_IF_TARGET_FOLLOWS_OL": ol_action,
            "FOOTNOTE_IF_TARGET_FOLLOWS_ALT": "REQUIRE",
            "VALIDATION_IF_TARGET_FOLLOWS_OL": "PASS_AUTHORITY1",
            "VALIDATION_IF_TARGET_FOLLOWS_ALT": "ACCEPTABLE_VARIANT_WITH_FOOTNOTE",
            "SUGGESTED_NOTE_IF_OL_SELECTED": "A note is recommended.",
            "SUGGESTED_NOTE_IF_ALT_SELECTED": "Other witnesses read four.",
            "MANUSCRIPT_EVIDENCE": "Synthetic witness",
            "SCHOLARSHIP_POSITION": "Synthetic position",
        }
    units = {ref: unit_record} if unit_record is not None else {}
    return ReferenceBundle(
        "fixture",
        "b" * 64,
        {ref: row},
        variants,
        guidance,
        units,
        {"SRC-1": {"SOURCE_ID": "SRC-1"}},
        "QUALIFIED",
    )


class ControlledModelTasks:
    """Return typed interpretation evidence without issuing live provider calls."""

    def __init__(self, extraction: Extraction, source: tuple[NumericExpression, ...], *,
                 registered: tuple[NumericExpression, ...] = (),
                 footnote: FootnoteDecision | None = None):
        """Capture controlled phase values and observable call counts."""
        self.extraction = extraction
        self.source = source
        self.registered = registered
        self.footnote = footnote
        self.extract_calls = 0
        self.correspond_calls = 0
        self.reading_contexts = []

    def extract(self, unit, *, language, style_profile):
        """Return the supplied target-only extraction."""
        self.extract_calls += 1
        return SimpleNamespace(value=self.extraction)

    def correspond(self, unit, target, reference, *, reading_context=None):
        """Return independently typed OL and optional registered evidence."""
        self.correspond_calls += 1
        self.reading_contexts.append(reading_context)
        registered_status = "COMPLETE" if reading_context is not None and self.registered else (
            "UNSUPPORTED" if reading_context is not None else "NOT_APPLICABLE"
        )
        limitations = () if registered_status in {"COMPLETE", "NOT_APPLICABLE"} else ("Candidate unsupported",)
        value = CorrespondenceEvidence(
            self.source,
            target,
            "COMPLETE",
            (),
            self.registered if registered_status == "COMPLETE" else (),
            registered_status,
            limitations,
        )
        return SimpleNamespace(value=value)

    def assess_footnote(self, unit, note, guidance, *, required_action):
        """Return a supplied note decision for the eligible exact target note."""
        return SimpleNamespace(value=self.footnote)


def ol_tasks(target_text: str, *, value: int = 3,
             extraction_status: str = "COMPLETE") -> ControlledModelTasks:
    """Create matching target and OL correspondence for one quantity."""
    target_expressions = () if extraction_status != "COMPLETE" else (expression(target_text, value),)
    limitations = () if extraction_status == "COMPLETE" else ("Unsupported language",)
    target = Extraction(target_expressions, extraction_status, limitations)
    source_text = f"{value} men"
    source = (expression(source_text, value, expression_id="ol-1", stream_id="ol"),)
    return ControlledModelTasks(target, source)


def test_ol_pass_keeps_recommended_note_as_advisory():
    """A recommended missing note does not replace an OL semantic pass."""
    ref = VerseRef("MAT", 1, 1)
    bundle = reference_bundle(ref, registered=True, ol_action="RECOMMEND")
    tasks = ol_tasks("3 men")

    result = evaluate_unit(
        projected(ref, "3 men"), bundle=bundle, language="en",
        language_profile={"id": "fixture"}, style_profile=style_profile(),
        check_policy=check_policy(), model_tasks=tasks,
    )

    assert result.final_outcome == "PASS_AUTHORITY1"
    assert (result.footnote.status, result.footnote.outcome) == ("MISSING", "ADVISORY")


def test_ol_reordering_requires_the_same_typed_referents():
    """A reordered OL sequence passes only when each quantity keeps its referent."""
    ref = VerseRef("1SA", 25, 2)
    source_text = "3000 sheep and 1000 goats"
    target_text = "1000 goats and 3000 sheep"
    source = (
        expression_at(source_text, "3000", 3000, role="sheep", expression_id="ol-1", stream_id="ol"),
        expression_at(source_text, "1000", 1000, role="goats", expression_id="ol-2", stream_id="ol"),
    )
    reordered = Extraction(
        (
            expression_at(target_text, "1000", 1000, role="goats", expression_id="target-1", stream_id="main"),
            expression_at(target_text, "3000", 3000, role="sheep", expression_id="target-2", stream_id="main"),
        ),
        "COMPLETE",
    )
    swapped = Extraction(
        (
            expression_at(target_text, "1000", 1000, role="sheep", expression_id="target-1", stream_id="main"),
            expression_at(target_text, "3000", 3000, role="goats", expression_id="target-2", stream_id="main"),
        ),
        "COMPLETE",
    )
    row = ReferenceRow(
        ref, ref.label(), "HEB", source_text, (Fraction(3000), Fraction(1000)),
        target_text, (Fraction(1000), Fraction(3000)), {"SOURCE_IDS": "SRC-1"},
    )
    bundle = ReferenceBundle(
        "fixture", "b" * 64, {ref: row}, {}, {}, {},
        {"SRC-1": {"SOURCE_ID": "SRC-1"}}, "QUALIFIED",
    )

    positive = evaluate_unit(
        projected(ref, target_text), bundle=bundle, language="en", language_profile={},
        style_profile=style_profile(),
        check_policy=check_policy(presentation=False, footnotes=False),
        model_tasks=ControlledModelTasks(reordered, source),
    )
    negative = evaluate_unit(
        projected(ref, target_text), bundle=bundle, language="en", language_profile={},
        style_profile=style_profile(),
        check_policy=check_policy(presentation=False, footnotes=False),
        model_tasks=ControlledModelTasks(swapped, source),
    )

    assert positive.final_outcome == "PASS_EQUIVALENT_NUMERIC_EXPRESSION"
    assert negative.final_outcome == "REVIEW_VALUE_DIFFERENCE"


def test_unit_result_preserves_differing_ol_reference_from_bound_row():
    """Western lookup never replaces the row's distinct original-language coordinate."""
    ref = VerseRef("MAT", 1, 1)
    row = ReferenceRow(
        ref, "MRK 9:44", "GRK", "3 men", (Fraction(3),),
        "3 men", (Fraction(3),), {"SOURCE_IDS": "SRC-1"},
    )
    bundle = ReferenceBundle(
        "fixture", "b" * 64, {ref: row}, {}, {}, {},
        {"SRC-1": {"SOURCE_ID": "SRC-1"}}, "QUALIFIED",
    )

    result = evaluate_unit(
        projected(ref, "3 men"), bundle=bundle, language="en", language_profile={},
        style_profile=style_profile(), check_policy=check_policy(), model_tasks=ol_tasks("3 men"),
    )

    assert result.ol_references == ("MRK 9:44",)

    review = evaluate_run(
        (projected(ref, "4 men"),), bundle=bundle, language="en", language_profile={},
        style_profile=style_profile(), check_policy=check_policy(presentation=False, footnotes=False),
        run_id="RUN-DIFFERING-OL", expected_unit_ids=("unit-1",),
        model_tasks=ControlledModelTasks(
            Extraction((expression("4 men", 4),), "COMPLETE"),
            (expression("3 men", 3, expression_id="ol-1", stream_id="ol"),),
        ),
    )
    assert review.findings[0]["ol_reference"] == "MRK 9:44"
    assert review.findings[0]["western_references"] == ("MAT 1:1",)


def test_registered_alternate_requires_adequate_note_for_acceptable_outcome():
    """A complete candidate correspondence plus disclosure permits the registered outcome."""
    ref = VerseRef("MAT", 1, 1)
    note = TargetNote("note-1", "f", "Other witnesses read four.", (ref,), ({"kind": "CONTENT", "start": 0, "end": 26, "text": "Other witnesses read four."},))
    bundle = reference_bundle(ref, ol=3, niv=4, registered=True)
    target = Extraction((expression("4 men", 4),), "COMPLETE")
    source = (expression("3 men", 3, expression_id="ol-1", stream_id="ol"),)
    candidate = (expression("4 men", 4, expression_id="alt-1", stream_id="registered"),)
    tasks = ControlledModelTasks(target, source, registered=candidate,
                                 footnote=FootnoteDecision("REQUIRE", "ADEQUATE", "NONE", ((0, 26),)))

    result = evaluate_unit(
        projected(ref, "4 men", notes=(note,)), bundle=bundle, language="en",
        language_profile={"id": "fixture"}, style_profile=style_profile(),
        check_policy=check_policy(), model_tasks=tasks,
    )

    assert result.reading.selected == "ALT"
    assert result.footnote.status == "ADEQUATE"
    assert result.final_outcome == "ACCEPTABLE_VARIANT_WITH_FOOTNOTE"
    assert tasks.reading_contexts[0]["values"] == ["4"]


def test_registered_alternate_with_missing_note_requires_review():
    """A supported alternate without required target disclosure remains actionable."""
    ref = VerseRef("MAT", 1, 1)
    bundle = reference_bundle(ref, ol=3, niv=4, registered=True)
    tasks = ControlledModelTasks(
        Extraction((expression("4 men", 4),), "COMPLETE"),
        (expression("3 men", 3, expression_id="ol-1", stream_id="ol"),),
        registered=(expression("4 men", 4, expression_id="alt-1", stream_id="registered"),),
    )

    result = evaluate_unit(
        projected(ref, "4 men"), bundle=bundle, language="en",
        language_profile={"id": "fixture"}, style_profile=style_profile(),
        check_policy=check_policy(), model_tasks=tasks,
    )

    assert result.final_outcome == "REVIEW_MISSING_FOOTNOTE"


def test_unindexed_target_number_is_visible_reference_gap():
    """A target number outside the authoritative index cannot be silently skipped."""
    ref = VerseRef("MAT", 1, 2)
    bundle = ReferenceBundle("fixture", "b" * 64, {}, {}, {}, {}, {}, "QUALIFIED")
    tasks = ol_tasks("7 men", value=7)

    result = evaluate_unit(
        projected(ref, "7 men"), bundle=bundle, language="en",
        language_profile={}, style_profile=style_profile(),
        check_policy=check_policy(), model_tasks=tasks,
    )

    assert result.final_outcome == "REFERENCE_NOT_INDEXED"
    assert tasks.correspond_calls == 0


def test_unindexed_empty_unit_is_screened_without_an_accuracy_finding():
    """A complete number-free unit needs no registry row and keeps complete coverage."""
    ref = VerseRef("MAT", 1, 2)
    bundle = ReferenceBundle("fixture", "b" * 64, {}, {}, {}, {}, {}, "QUALIFIED")
    tasks = ControlledModelTasks(Extraction((), "COMPLETE"), ())

    run = evaluate_run(
        (projected(ref, "ordinary prose"),), bundle=bundle, language="en",
        language_profile={}, style_profile=style_profile(),
        check_policy=check_policy(presentation=False, footnotes=False),
        run_id="RUN-SCREENED", expected_unit_ids=("unit-1",), model_tasks=tasks,
    )

    assert run.units[0].reading.semantic.outcome == "NOT_ASSESSED"
    assert run.findings == ()
    assert run.coverage["coverage"] == "COMPLETE_WITH_RESTRICTIONS"
    assert run.coverage["result"] == "NO_FINDINGS"


def test_unsupported_language_and_absent_target_number_never_pass():
    """Unsupported interpretation and an empty known target remain distinct limitations."""
    ref = VerseRef("MAT", 1, 1)
    bundle = reference_bundle(ref)
    unsupported = ol_tasks("text 3", extraction_status="UNSUPPORTED")
    unsupported_result = evaluate_unit(
        projected(ref, "text 3"), bundle=bundle, language="und",
        language_profile={}, style_profile=style_profile(),
        check_policy=check_policy(), model_tasks=unsupported,
    )
    empty_tasks = ControlledModelTasks(
        Extraction((), "COMPLETE"),
        (expression("3 men", 3, expression_id="ol-1", stream_id="ol"),),
    )
    empty_result = evaluate_unit(
        projected(ref, ""), bundle=bundle, language="en",
        language_profile={}, style_profile=style_profile(),
        check_policy=check_policy(), model_tasks=empty_tasks,
    )

    assert unsupported_result.final_outcome == "INSUFFICIENT_EVIDENCE"
    assert empty_result.final_outcome == "REVIEW_NUMBER_MISSING"


def test_bridge_and_multirow_groups_are_evaluated_once():
    """One merged stream is never compared independently against every row."""
    first = VerseRef("MAT", 1, 1)
    second = VerseRef("MAT", 1, 2)
    single_bundle = reference_bundle(first)
    tasks = ol_tasks("3 men")
    run = evaluate_run(
        (projected(first, "3 men", end=2),), bundle=single_bundle, language="en",
        language_profile={}, style_profile=style_profile(), check_policy=check_policy(),
        run_id="RUN-1", expected_unit_ids=("unit-1",), model_tasks=tasks,
    )
    multi_rows = ReferenceBundle(
        "fixture", "b" * 64,
        {**single_bundle.rows, second: ReferenceRow(second, second.label(), "GRK", "4 men", (Fraction(4),), "4 men", (Fraction(4),), {})},
        {}, {}, {}, {}, "QUALIFIED",
    )
    ambiguous_tasks = ol_tasks("3 men")
    ambiguous = evaluate_unit(
        projected(first, "3 men", end=2, western=(first, second)),
        bundle=multi_rows, language="en", language_profile={},
        style_profile=style_profile(), check_policy=check_policy(), model_tasks=ambiguous_tasks,
    )

    assert run.summary["units"] == 1
    assert tasks.extract_calls == tasks.correspond_calls == 1
    assert ambiguous.final_outcome == "INSUFFICIENT_EVIDENCE"
    assert ambiguous_tasks.extract_calls == 1
    assert ambiguous_tasks.correspond_calls == 0


def test_disabled_checks_are_not_assessed_and_emit_no_cross_check_claims():
    """Each enabled-check combination runs prerequisites without claiming disabled checks."""
    ref = VerseRef("MAT", 1, 1)
    bundle = reference_bundle(ref, ol=3, niv=4, registered=True)
    target = Extraction((expression("4 men", 4),), "COMPLETE")
    source = (expression("3 men", 3, expression_id="ol-1", stream_id="ol"),)
    candidate = (expression("4 men", 4, expression_id="alt-1", stream_id="registered"),)

    accuracy_tasks = ControlledModelTasks(target, source, registered=candidate)
    accuracy_run = evaluate_run(
        (projected(ref, "4 men"),), bundle=bundle, language="en", language_profile={},
        style_profile=style_profile(words=True),
        check_policy=check_policy(presentation=False, footnotes=False),
        run_id="RUN-ACCURACY", expected_unit_ids=("unit-1",), model_tasks=accuracy_tasks,
    )
    accuracy_only = accuracy_run.units[0]
    footnote_tasks = ControlledModelTasks(target, source, registered=candidate)
    footnote_only = evaluate_run(
        (projected(ref, "4 men"),), bundle=bundle, language="en", language_profile={},
        style_profile=style_profile(words=True), check_policy=check_policy(accuracy=False, presentation=False),
        run_id="RUN-2", expected_unit_ids=("unit-1",), model_tasks=footnote_tasks,
    )
    presentation_tasks = ControlledModelTasks(target, source, registered=candidate)
    presentation_only = evaluate_run(
        (projected(ref, "4 men"),), bundle=bundle, language="en", language_profile={"grammar_issue": "ignore"},
        style_profile=style_profile(words=True), check_policy=check_policy(accuracy=False, footnotes=False),
        run_id="RUN-3", expected_unit_ids=("unit-1",), model_tasks=presentation_tasks,
    )

    assert accuracy_only.final_outcome == "REGISTERED_ALTERNATE"
    assert accuracy_only.footnote.status == "NOT_ASSESSED"
    assert accuracy_only.style_findings == ()
    assert not any(item["category"] == "ACCURACY" for item in footnote_only.findings)
    assert any(item["category"] == "FOOTNOTE" for item in footnote_only.findings)
    assert presentation_only.units[0].final_outcome == "NOT_ASSESSED"
    assert {item["category"] for item in presentation_only.findings} == {"STYLE"}

    document = numbers_result_document(
        accuracy_run,
        provenance={
            "run_id": "RUN-ACCURACY", "job_id": "JOB-1",
            "style_profile": {"selector": "fixture-en/1", "sha256": "f" * 64},
            "reference_package": {"package_id": "fixture", "sha256": "b" * 64},
            "wip": {"identity": "WIP", "sha256": "a" * 64},
        },
        check_policy=check_policy(presentation=False, footnotes=False),
        model_receipts={
            "EXTRACTION": [phase_receipt("EXTRACTION")],
            "CORRESPONDENCE": [phase_receipt("CORRESPONDENCE")],
            "FOOTNOTE": [],
        },
    )
    validated = validate_numbers_result(
        document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
    )
    assert validated["units"][0]["footnote"] == {
        "action": "NONE", "status": "NOT_ASSESSED", "outcome": "NONE",
        "evidence_spans": [], "evidence_note_ids": [],
    }


def test_registered_unit_conversion_requires_candidate_correspondence_and_residual_check():
    """A registered unit pair passes only with whole-verse candidate evidence."""
    ref = VerseRef("LUK", 13, 21)
    record = {"OL_QUANTITY": "3 sata", "NIV_QUANTITY": "60 gallons", "SOURCE_IDS": "SRC-1"}
    bundle = reference_bundle(ref, ol=3, niv=60, unit_record=record)
    target = Extraction((expression("60 gallons", 60, unit="gallon"),), "COMPLETE")
    source = (expression("3 sata", 3, expression_id="ol-1", stream_id="ol", unit="saton"),)
    candidate = (expression("60 gallons", 60, expression_id="unit-1", stream_id="registered", unit="gallon"),)
    tasks = ControlledModelTasks(target, source, registered=candidate)

    result = evaluate_unit(
        projected(ref, "60 gallons"), bundle=bundle, language="en", language_profile={},
        style_profile=style_profile(), check_policy=check_policy(), model_tasks=tasks,
    )

    assert result.final_outcome == "PASS_UNIT_CONVERSION"
    assert result.reading.selected == "OL"
    assert tasks.reading_contexts[0]["text"] == "60 gallons"
    assert tasks.reading_contexts[0]["values"] == ["60"]


def test_registered_unit_preserves_typed_ol_residuals_independently_of_niv():
    """A conversion authorizes its pair while every unrelated OL meaning remains binding."""
    ref = VerseRef("LUK", 16, 7)
    row = ReferenceRow(
        ref, ref.label(), "GRK", "3 sata and 2 debts", (Fraction(3), Fraction(2)),
        "60 gallons and 7 debts", (Fraction(60), Fraction(7)), {"SOURCE_IDS": "SRC-1"},
    )
    record = {"OL_QUANTITY": "3 sata", "NIV_QUANTITY": "60 gallons", "SOURCE_IDS": "SRC-1"}
    bundle = ReferenceBundle(
        "fixture", "b" * 64, {ref: row}, {}, {}, {ref: record},
        {"SRC-1": {"SOURCE_ID": "SRC-1"}}, "QUALIFIED",
    )
    source = (
        expression("3 sata", 3, role="measure", expression_id="ol-1", stream_id="ol", unit="saton"),
        expression("2 debts", 2, role="debts", expression_id="ol-2", stream_id="ol"),
    )
    candidate = (
        expression("60 gallons", 60, role="measure", expression_id="unit-1", stream_id="registered", unit="gallon"),
    )

    def result_for(role: str):
        """Evaluate the same registered conversion with one residual referent."""
        target = Extraction((
            expression("60 gallons", 60, role="measure", unit="gallon"),
            expression("2 debts", 2, role=role, expression_id="target-2"),
        ), "COMPLETE")
        return evaluate_unit(
            projected(ref, "60 gallons and 2 debts"), bundle=bundle, language="en",
            language_profile={}, style_profile=style_profile(), check_policy=check_policy(),
            model_tasks=ControlledModelTasks(target, source, registered=candidate),
        )

    assert result_for("debts").final_outcome == "PASS_UNIT_CONVERSION"
    assert result_for("years").final_outcome == "REVIEW_VALUE_DIFFERENCE"


def test_registered_unit_allows_role_preserving_residual_reordering():
    """A unit conversion preserves typed OL residuals even when their order changes."""
    ref = VerseRef("LUK", 16, 7)
    source_text = "3 sata and 2 debts and 5 years"
    target_text = "60 gallons and 5 years and 2 debts"
    row = ReferenceRow(
        ref, ref.label(), "GRK", source_text,
        (Fraction(3), Fraction(2), Fraction(5)), target_text,
        (Fraction(60), Fraction(5), Fraction(2)), {"SOURCE_IDS": "SRC-1"},
    )
    record = {"OL_QUANTITY": "3 sata", "NIV_QUANTITY": "60 gallons", "SOURCE_IDS": "SRC-1"}
    bundle = ReferenceBundle(
        "fixture", "b" * 64, {ref: row}, {}, {}, {ref: record},
        {"SRC-1": {"SOURCE_ID": "SRC-1"}}, "QUALIFIED",
    )
    source = (
        expression_at(source_text, "3", 3, role="sata", expression_id="ol-1", stream_id="ol"),
        expression_at(source_text, "2", 2, role="debts", expression_id="ol-2", stream_id="ol"),
        expression_at(source_text, "5", 5, role="years", expression_id="ol-3", stream_id="ol"),
    )
    target = Extraction(
        (
            expression_at(target_text, "60", 60, role="gallons", expression_id="target-1", stream_id="main"),
            expression_at(target_text, "5", 5, role="years", expression_id="target-2", stream_id="main"),
            expression_at(target_text, "2", 2, role="debts", expression_id="target-3", stream_id="main"),
        ),
        "COMPLETE",
    )
    source = (
        replace(source[0], unit="saton", role="measure"), source[1], source[2],
    )
    target = Extraction(
        (replace(target.expressions[0], unit="gallon", role="measure"),) + target.expressions[1:],
        "COMPLETE",
    )
    registered = (
        replace(target.expressions[0], expression_id="unit-1", stream_id="registered"),
    )

    result = evaluate_unit(
        projected(ref, target_text), bundle=bundle, language="en", language_profile={},
        style_profile=style_profile(), check_policy=check_policy(),
        model_tasks=ControlledModelTasks(target, source, registered=registered),
    )

    assert result.final_outcome == "PASS_UNIT_CONVERSION"


def test_model_tasks_are_required_for_interpretation():
    """The engine cannot synthesize typed correspondence when no model adapter is supplied."""
    ref = VerseRef("MAT", 1, 1)
    result = evaluate_unit(
        projected(ref, "3 men"), bundle=reference_bundle(ref), language="en",
        language_profile={}, style_profile=style_profile(), check_policy=check_policy(),
    )

    assert result.final_outcome == "INSUFFICIENT_EVIDENCE"
    assert result.extraction.status == "UNSUPPORTED"


def test_registered_absence_reaches_its_explicit_reference_policy():
    """A registered absent target unit is assessed through its nullable-OL authority row."""
    ref = VerseRef("NEH", 7, 68)
    row = ReferenceRow(ref, None, "", "", (), "550 singers", (Fraction(550),), {"SOURCE_IDS": "SRC-1"})
    guidance = {
        "OL_VALUES": "",
        "ALT_NIV_VALUES": "550",
        "SOURCE_IDS": "SRC-1",
        "CLASS": "ATTESTED_VERSE_OMISSION_ADDITION",
        "SCHOLARSHIP_STATUS": "DIVIDED",
        "FOOTNOTE_IF_TARGET_FOLLOWS_OL": "REQUIRE",
        "FOOTNOTE_IF_TARGET_FOLLOWS_ALT": "REQUIRE",
        "VALIDATION_IF_TARGET_FOLLOWS_OL": "NO_CONFIGURED_OL_READING",
        "VALIDATION_IF_TARGET_FOLLOWS_ALT": "ACCEPTABLE_VARIANT_WITH_FOOTNOTE",
    }
    bundle = ReferenceBundle(
        "fixture", "b" * 64, {ref: row},
        {ref: {"NIV_VALUE_RESEARCHED": "550"}}, {ref: guidance}, {},
        {"SRC-1": {"SOURCE_ID": "SRC-1"}}, "QUALIFIED",
    )
    target = TargetUnit("absent-1", (), "", (), "a" * 64, {"line_start": 1, "line_end": 1})
    unit = ProjectedUnit(target, (ref,), (), "REGISTERED", "REGISTERED_ABSENCE")
    tasks = ControlledModelTasks(Extraction((), "COMPLETE"), ())

    result = evaluate_unit(
        unit, bundle=bundle, language="en", language_profile={},
        style_profile=style_profile(),
        check_policy=check_policy(presentation=False, footnotes=False),
        model_tasks=tasks,
    )

    assert result.reading.selected == "OL"
    assert result.final_outcome == "NO_CONFIGURED_OL_READING"
    assert result.ol_references == (None,)


def test_presentation_assesses_body_and_note_as_separate_streams():
    """Target note numbers use footnote rules and retain note-local span identity."""
    ref = VerseRef("MAT", 1, 1)
    note = TargetNote(
        "note-1", "f", "4 witnesses", (ref,),
        ({"kind": "CONTENT", "start": 0, "end": 11, "text": "4 witnesses"},),
    )

    class StreamTasks:
        """Extract one controlled expression from each body or note stream."""

        def extract(self, unit, *, language, style_profile):
            """Return an expression bound to the supplied stream's own text."""
            value = 4 if unit.unit_id.endswith("note-1") else 3
            return SimpleNamespace(value=Extraction((expression(unit.main_text, value),), "COMPLETE"))

    result = evaluate_unit(
        projected(ref, "3 men", notes=(note,)), bundle=reference_bundle(ref),
        language="en", language_profile={}, style_profile=style_profile(words=True),
        check_policy=check_policy(accuracy=False, footnotes=False), model_tasks=StreamTasks(),
    )

    assert {finding["location"] for finding in result.style_findings} == {"body", "footnote"}
    note_findings = [finding for finding in result.style_findings if finding["location"] == "footnote"]
    assert {finding["note_id"] for finding in note_findings} == {"note-1"}


def test_run_assesses_supplied_headings_once_with_heading_rules():
    """Task 2 heading streams remain distinct expected units in run coverage."""
    ref = VerseRef("MAT", 1, 1)
    heading = TargetUnit(
        "heading-1", (ref,), "4 witnesses", (), "a" * 64,
        {"heading": 1, "content_index": 2, "chapter": 1},
    )

    class HeadingTasks:
        """Extract one controlled digit from body and heading streams."""

        def extract(self, unit, *, language, style_profile):
            """Return the value already visible in the supplied exact text."""
            value = 4 if unit.unit_id == "heading-1" else 3
            return SimpleNamespace(value=Extraction((expression(unit.main_text, value),), "COMPLETE"))

    run = evaluate_run(
        (projected(ref, "3 men"),), style_units=(heading,),
        bundle=reference_bundle(ref), language="en", language_profile={},
        style_profile=style_profile(words=True),
        check_policy=check_policy(accuracy=False, footnotes=False),
        run_id="RUN-HEADINGS", expected_unit_ids=("unit-1", "heading-1"),
        model_tasks=HeadingTasks(),
    )

    assert run.summary["units"] == 2
    assert run.summary["expressions"] == 2
    heading_result = next(item for item in run.units if item.projected.target.unit_id == "heading-1")
    assert {item["location"] for item in heading_result.style_findings} == {"heading"}

    disabled_tasks = ol_tasks("3 men")
    disabled = evaluate_run(
        (projected(ref, "3 men"),), style_units=(heading,),
        bundle=reference_bundle(ref), language="en", language_profile={},
        style_profile=style_profile(words=True),
        check_policy=check_policy(presentation=False, footnotes=False),
        run_id="RUN-HEADINGS-OFF", expected_unit_ids=("unit-1", "heading-1"),
        model_tasks=disabled_tasks,
    )
    disabled_heading = next(item for item in disabled.units if item.projected.target.unit_id == "heading-1")
    assert disabled_tasks.extract_calls == 1
    assert disabled_heading.final_outcome == "NOT_ASSESSED"
    assert disabled_heading.style_findings == ()
    assert disabled.summary["insufficient_evidence"] == 0

    combined = evaluate_run(
        (projected(ref, "3 men"),), style_units=(heading,),
        bundle=reference_bundle(ref), language="en", language_profile={},
        style_profile=style_profile(words=True),
        check_policy=check_policy(footnotes=False), run_id="RUN-HEADINGS-COMBINED",
        expected_unit_ids=("unit-1", "heading-1"), model_tasks=ol_tasks("3 men"),
    )
    heading_findings = [item for item in combined.findings if item["work_unit_id"] == "heading-1"]
    assert {item["category"] for item in heading_findings} == {"STYLE"}


def test_footnote_only_unsupported_interpretation_is_visible_as_insufficient():
    """Footnote review cannot claim no requirement when no reading was identified."""
    ref = VerseRef("MAT", 1, 1)
    run = evaluate_run(
        (projected(ref, "text 3"),), bundle=reference_bundle(ref), language="und",
        language_profile={}, style_profile=style_profile(),
        check_policy=check_policy(accuracy=False, presentation=False),
        run_id="RUN-FOOTNOTE", expected_unit_ids=("unit-1",),
        model_tasks=ol_tasks("text 3", extraction_status="UNSUPPORTED"),
    )

    result = run.units[0]
    assert (result.footnote.status, result.footnote.outcome) == (
        "NOT_ASSESSED", "INSUFFICIENT_EVIDENCE",
    )
    assert run.coverage["result"] == "INSUFFICIENT_DATA"
    assert {finding["category"] for finding in run.findings} == {"FOOTNOTE"}
    assert run.summary["extraction_unsupported"] == 1
    assert run.summary["extraction_complete"] == 0


def test_adequate_note_cannot_upgrade_failed_registered_correspondence():
    """Disclosure adequacy never converts a candidate meaning difference into acceptance."""
    ref = VerseRef("MAT", 1, 1)
    note = TargetNote(
        "note-1", "f", "Other witnesses read four.", (ref,),
        ({"kind": "CONTENT", "start": 0, "end": 26, "text": "Other witnesses read four."},),
    )
    tasks = ControlledModelTasks(
        Extraction((expression("4 men", 4),), "COMPLETE"),
        (expression("3 men", 3, expression_id="ol-1", stream_id="ol"),),
        registered=(expression("5 men", 5, expression_id="alt-1", stream_id="registered"),),
        footnote=FootnoteDecision("REQUIRE", "ADEQUATE", "NONE", ((0, 26),)),
    )

    result = evaluate_unit(
        projected(ref, "4 men", notes=(note,)),
        bundle=reference_bundle(ref, ol=3, niv=4, registered=True), language="en",
        language_profile={}, style_profile=style_profile(), check_policy=check_policy(),
        model_tasks=tasks,
    )

    assert result.reading.semantic.outcome == "REVIEW_VALUE_DIFFERENCE"
    assert result.footnote.status == "ADEQUATE"
    assert result.final_outcome == "REVIEW_VALUE_DIFFERENCE"


def test_incomplete_footnote_evidence_restricts_coverage_and_summary():
    """An unresolved eligible note keeps the run from claiming complete evidence."""
    ref = VerseRef("MAT", 1, 1)
    note = TargetNote(
        "note-1", "f", "4 witnesses", (ref,),
        ({"kind": "CONTENT", "start": 0, "end": 11, "text": "4 witnesses"},),
    )
    tasks = ControlledModelTasks(
        Extraction((expression("4 men", 4),), "COMPLETE"),
        (expression("3 men", 3, expression_id="ol-1", stream_id="ol"),),
        registered=(expression("4 men", 4, expression_id="alt-1", stream_id="registered"),),
    )

    run = evaluate_run(
        (projected(ref, "4 men", notes=(note,)),),
        bundle=reference_bundle(ref, ol=3, niv=4, registered=True), language="en",
        language_profile={}, style_profile=style_profile(),
        check_policy=check_policy(presentation=False), run_id="RUN-INCOMPLETE-NOTE",
        expected_unit_ids=("unit-1",), model_tasks=tasks,
    )

    assert run.units[0].footnote.outcome == "INSUFFICIENT_EVIDENCE"
    assert run.coverage["result"] == "INSUFFICIENT_DATA"
    assert run.coverage["coverage"] == "PARTIAL"
    assert run.summary["insufficient_evidence"] == 1
