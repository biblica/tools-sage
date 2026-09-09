"""NCA machine results preserve exact evidence and reject invented state."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest
import yaml

from sage.errors import ValidationError
from sage.numbers.models import (
    Extraction,
    FootnoteDecision,
    NumericExpression,
    ProjectedUnit,
    ReadingDecision,
    RunResult,
    SemanticDecision,
    TargetUnit,
    UnitResult,
)
from sage.numbers.results import (
    NCA_CAPABILITY_LIMITATION,
    numbers_result_document,
    validate_numbers_result,
)
from sage.vrs import VerseRef


def complete_run_result() -> RunResult:
    """Build one complete typed result without using the serializer under test."""
    reference = VerseRef("MAT", 1, 1)
    target = TargetUnit(
        "unit-1",
        (reference,),
        "three men",
        (),
        "a" * 64,
        {"line_start": 3, "line_end": 3},
    )
    projected = ProjectedUnit(
        target,
        (reference,),
        (reference,),
        "COORDINATE",
        "READY",
    )
    expression = NumericExpression(
        (Fraction(3),),
        "CARDINAL",
        "three",
        (0, 5),
        role="men",
        expression_id="target-1",
        role_spans=((6, 9),),
    )
    source_expression = replace(expression, expression_id="ol-1", stream_id="ol")
    semantic = SemanticDecision("REVIEW_VALUE_DIFFERENCE")
    unit = UnitResult(
        projected,
        Extraction((expression,), "COMPLETE"),
        ReadingDecision("UNSUPPORTED", semantic, "NONE", None, ()),
        FootnoteDecision("NONE", "NOT_REQUIRED", "NONE"),
        "REVIEW_VALUE_DIFFERENCE",
        ol_references=("MRK 9:44",),
        source_expressions=(source_expression,),
        reference_context={
            "language": "GRK",
            "ol_text": "three men",
            "ol_values": (Fraction(3),),
            "variant_class": None,
            "scholarship_status": None,
        },
        reference_index=({
            "western_reference": "MAT 1:1",
            "status": "INDEXED",
            "ol_reference": "MRK 9:44",
        },),
    )
    finding = {
        "finding_id": "NUMBERS_RUN-1_UNIT-1_0001",
        "work_unit_id": "unit-1",
        "category": "ACCURACY",
        "code": "NCA_REVIEW_VALUE_DIFFERENCE",
        "severity": "REVIEW",
        "target_reference": "MAT 1:1",
        "target_references": ["MAT 1:1"],
        "western_references": ["MAT 1:1"],
        "ol_reference": "MRK 9:44",
        "ol_references": ["MRK 9:44"],
        "selected_reading": "UNSUPPORTED",
        "source_ids": [],
        "evidence_ids": [],
        "message": "Review numeric meaning.",
    }
    coverage = {
        "result": "FINDINGS",
        "coverage": "COMPLETE",
        "confidence_basis": "FULL",
        "restrictions": [],
        "skipped_checks": [],
        "expected_unit_ids": ["unit-1"],
        "assessed_unit_ids": ["unit-1"],
    }
    summary = {
        "units": 1,
        "expressions": 1,
        "target_expressions": 1,
        "ol_expressions_checked": 1,
        "passes": 0,
        "unit_conversions": 0,
        "value_differences": 1,
        "missing_numbers": 0,
        "added_numbers": 0,
        "known_variants": 0,
        "style_findings": 0,
        "indexed_coordinates": 1,
        "unindexed_coordinates": 0,
        "findings": 1,
        "insufficient_evidence": 0,
        "reference_not_indexed": 0,
        "not_assessed": 0,
        "extraction_complete": 1,
        "extraction_partial": 0,
        "extraction_unsupported": 0,
    }
    return RunResult((unit,), (finding,), coverage, summary)


@pytest.mark.parametrize(
    "build",
    [
        lambda: NumericExpression(
            (Fraction(3),), "CARDINAL", "three", (0, 5),
            representations=({"invented": True},),
        ),
        lambda: NumericExpression((Fraction(3),), "CARDINAL", "", (0, 0)),
        lambda: NumericExpression((Fraction(3),), "CARDINAL", "x", (False, 1)),
        lambda: NumericExpression(
            (Fraction(3),), "CARDINAL", "three (3)", (0, 9),
            representations=({"surface": "xxxxx", "span": (0, 5), "value": "3"},),
        ),
        lambda: NumericExpression(
            (Fraction(3),), "CARDINAL", "three", (0, 5), role_spans=((2, 2),)
        ),
        lambda: FootnoteDecision("REQUIRE", "ADEQUATE", "NONE", ((1, 1),)),
    ],
)
def test_shared_evidence_models_reject_malformed_or_empty_nested_spans(build):
    """Immutable evidence records reject invented representation fields and empty spans."""
    with pytest.raises(ValidationError) as exc:
        build()

    assert exc.value.code == "NCA_MODEL_INVALID"


def test_unit_result_rejects_a_contradictory_reference_index_aggregate():
    """Typed results keep each Western reference aligned to its exact index state."""
    with pytest.raises(ValidationError) as exc:
        replace(
            complete_run_result().units[0],
            reference_index=({
                "western_reference": "MAT 1:2",
                "status": "UNINDEXED",
                "ol_reference": None,
            },),
        )

    assert exc.value.code == "NCA_MODEL_INVALID"


def test_footnote_model_scopes_duplicate_offsets_by_note_identity():
    """Equal note-local offsets are valid across notes but cannot repeat in one note."""
    decision = FootnoteDecision(
        "REQUIRE", "ADEQUATE", "NONE", ((0, 1), (0, 1)), ("note-1", "note-2")
    )
    assert decision.evidence_spans == ((0, 1), (0, 1))

    with pytest.raises(ValidationError):
        FootnoteDecision(
            "REQUIRE", "ADEQUATE", "NONE", ((0, 1), (0, 1)), ("note-1", "note-1")
        )


def provenance() -> dict[str, object]:
    """Return the immutable identity fields Task 9 supplies at finalization."""
    return {
        "run_id": "RUN-1",
        "job_id": "JOB-1",
        "style_profile": {"selector": "fixture-en/1", "sha256": "b" * 64},
        "reference_package": {"package_id": "fixture", "sha256": "c" * 64},
        "wip": {"identity": "WIP", "sha256": "a" * 64},
        "report_language": "en",
    }


def policy() -> dict[str, object]:
    """Return the exact three-check policy shape consumed by Task 8."""
    return {
        "checks": {
            "number_accuracy": True,
            "presentation_consistency": True,
            "footnote_review": True,
        }
    }


def receipts() -> dict[str, list[dict[str, object]]]:
    """Return one exact model-phase receipt without synthesizing confidence."""
    def receipt(phase: str) -> dict[str, object]:
        """Build one complete exact receipt for a phase that actually ran."""
        return {
            "phase": phase,
            "task_version": f"nca-{phase.casefold()}-1.0",
            "provider": "fixture-provider",
            "model": "fixture-model",
            "reasoning_effort": "medium",
            "route_id": "nca-numbers",
            "routing_mode": "AUTOMATIC",
            "qualification_status": "PROVISIONAL_UNQUALIFIED",
            "prompt_sha256": "d" * 64,
            "input_sha256": "e" * 64,
            "response_sha256": "f" * 64,
            "provider_metadata": {},
        }

    return {
        "EXTRACTION": [receipt("EXTRACTION")],
        "CORRESPONDENCE": [receipt("CORRESPONDENCE")],
        "FOOTNOTE": [],
    }


def complete_document() -> dict[str, object]:
    """Serialize one known-good result for independent mutation checks."""
    return numbers_result_document(
        complete_run_result(),
        provenance=provenance(),
        check_policy=policy(),
        model_receipts=receipts(),
    )


def test_result_document_serializes_exact_fractions_and_mandatory_limitations():
    """Machine output carries rational strings plus the LLM and SQS limitation."""
    document = complete_document()

    validated = validate_numbers_result(
        document,
        expected_unit_ids=("unit-1",),
        allowed_evidence_ids=("SRC-1",),
    )

    expression = validated["units"][0]["extraction"]["expressions"][0]
    assert expression["values"] == ["3"]
    assert validated["limitations"]["capability"] == NCA_CAPABILITY_LIMITATION
    assert validated["limitations"]["sqs_confidence_checks_applied"] is False
    assert validated["provenance"]["style_profile"]["sha256"] == "b" * 64
    assert validated["units"][0]["projection"]["ol_references"] == ["MRK 9:44"]
    assert validated["units"][0]["projection"]["target_text"] == "three men"
    assert validated["units"][0]["source_evidence"]["expressions"][0]["values"] == ["3"]
    assert validated["units"][0]["source_evidence"]["context"]["ol_text"] == "three men"
    assert validated["units"][0]["source_evidence"]["context"]["ol_values"] == ["3"]


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda value: value["units"][0].__setitem__("final_outcome", "APPROVED"), "NCA_RESULT_ENUM_INVALID"),
        (lambda value: value["units"][0]["reading"]["semantic"].__setitem__("evidence_ids", ["INVENTED"]), "NCA_RESULT_EVIDENCE_INVALID"),
        (lambda value: value["coverage"].__setitem__("assessed_unit_ids", []), "NCA_RESULT_COVERAGE_INVALID"),
        (lambda value: value["provenance"]["style_profile"].__setitem__("sha256", "bad"), "NCA_RESULT_PROVENANCE_INVALID"),
        (lambda value: value["units"][0]["extraction"]["expressions"][0]["values"].__setitem__(0, 3.0), "NCA_RESULT_FRACTION_INVALID"),
        (lambda value: value["summary"].__setitem__("extraction_complete", 0), "NCA_RESULT_SUMMARY_INVALID"),
        (lambda value: value["units"][0]["projection"].__setitem__("ol_references", [None]), "NCA_RESULT_REFERENCE_INVALID"),
    ],
)
def test_result_validation_rejects_independent_contract_mutations(mutation, code):
    """Each governed machine field rejects a plausible independent corruption."""
    document = deepcopy(complete_document())
    mutation(document)

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document,
            expected_unit_ids=("unit-1",),
            allowed_evidence_ids=("SRC-1",),
        )

    assert exc.value.code == code


def test_result_validation_reconciles_each_expected_unit_exactly_once():
    """Duplicate or omitted expected units cannot produce a complete machine result."""
    document = complete_document()

    for expected in (("unit-1", "unit-1"), ("unit-1", "unit-2"), ()):
        with pytest.raises(ValidationError) as exc:
            validate_numbers_result(
                document,
                expected_unit_ids=expected,
                allowed_evidence_ids=("SRC-1",),
            )
        assert exc.value.code == "NCA_RESULT_COVERAGE_INVALID"


def test_result_validation_rejects_missing_limitation_even_with_zero_findings():
    """A zero-finding export cannot omit the mandatory capability statement."""
    document = complete_document()
    document["findings"] = []
    document["summary"]["findings"] = 0
    document["coverage"]["result"] = "NO_FINDINGS"
    document["limitations"]["capability"] = ""

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document,
            expected_unit_ids=("unit-1",),
            allowed_evidence_ids=("SRC-1",),
        )

    assert exc.value.code == "NCA_RESULT_LIMITATION_REQUIRED"


def test_numbers_result_schema_declares_exact_scope_and_evidence_controls():
    """The governed schema records the canonical result owner and fail-closed controls."""
    root = Path(__file__).resolve().parents[2]
    schema = yaml.safe_load(
        (root / "config/schemas/numbers-result.schema.yml").read_text(encoding="utf-8")
    )

    assert schema["schema_id"] == "sage-numbers-result-1.0"
    assert schema["controls"]["owner"] == "system/src/sage/numbers/results.py"
    assert schema["controls"]["expected_unit_reconciliation"] == "exactly_once"
    assert schema["controls"]["numeric_encoding"] == "reduced_rational_strings"
    assert schema["controls"]["sqs_confidence_checks"] == "not_applied"
    assert schema["controls"]["ol_reference_state"] == "ordered_nullable_resolved_rows"
    assert schema["controls"]["target_span_binding"] == "exact_serialized_target_stream"
    assert schema["controls"]["ol_expression_evidence"] == "exact_serialized_source_stream"
    assert schema["controls"]["handover_summary_counters"] == "derived_from_assessments"
    assert schema["required"] == [
        "schema_version", "workflow", "check_id", "provenance", "check_policy",
        "model_receipts", "limitations", "units", "findings", "coverage", "summary",
    ]


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda value: value["units"][0]["extraction"].__setitem__("status", "DONE"), "NCA_RESULT_ENUM_INVALID"),
        (lambda value: value["units"][0]["reading"].__setitem__("source_ids", ["INVENTED"]), "NCA_RESULT_EVIDENCE_INVALID"),
        (lambda value: value["coverage"].update(result="NO_FINDINGS", coverage="PARTIAL", confidence_basis="LIMITED", restrictions=["Missing evidence"]), "NCA_RESULT_COVERAGE_INVALID"),
    ],
)
def test_result_validation_rejects_hidden_evidence_and_false_all_clear(mutation, code):
    """Reading provenance and incomplete coverage cannot bypass canonical validation."""
    document = complete_document()
    mutation(document)

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )

    assert exc.value.code == code


def test_incomplete_result_accepts_an_exact_empty_receipt_ledger():
    """A failed model dependency remains reportable without inventing a phase receipt."""
    document = complete_document()
    unit = document["units"][0]
    unit["extraction"].update(status="UNSUPPORTED", limitations=["Model unavailable"], expressions=[])
    unit["source_evidence"] = {"expressions": [], "context": {}}
    unit["reading"].update(selected="UNSUPPORTED", source_ids=[])
    unit["reading"]["semantic"].update(outcome="INSUFFICIENT_EVIDENCE", evidence_ids=[])
    unit["final_outcome"] = "INSUFFICIENT_EVIDENCE"
    document["findings"][0].update(
        category="EVIDENCE",
        code="NCA_INSUFFICIENT_EVIDENCE",
        selected_reading="UNSUPPORTED",
        source_ids=[],
        evidence_ids=[],
    )
    document["model_receipts"]["EXTRACTION"] = []
    document["model_receipts"]["CORRESPONDENCE"] = []
    document["coverage"].update(
        result="INSUFFICIENT_DATA", coverage="PARTIAL", confidence_basis="LIMITED",
        restrictions=["Model unavailable"],
    )
    document["summary"].update(
        expressions=0, target_expressions=0, ol_expressions_checked=0,
        value_differences=0, insufficient_evidence=1,
        extraction_complete=0, extraction_unsupported=1,
    )

    validated = validate_numbers_result(
        document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
    )

    assert validated["model_receipts"] == {"EXTRACTION": [], "CORRESPONDENCE": [], "FOOTNOTE": []}


def test_registered_absence_serializes_null_ol_reference_distinct_from_unknown():
    """A resolved nullable row uses null while an unresolved lookup uses an empty list."""
    document = complete_document()
    unit = document["units"][0]
    unit["projection"]["status"] = "REGISTERED_ABSENCE"
    unit["projection"]["ol_references"] = [None]
    unit["projection"]["reference_index"][0].update(
        status="REGISTERED_ABSENCE", ol_reference=None
    )
    document["findings"][0].update(ol_reference=None, ol_references=[None])

    validated = validate_numbers_result(
        document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
    )

    assert validated["units"][0]["projection"]["ol_references"] == [None]

    with pytest.raises(ValidationError):
        replace(complete_run_result().units[0], ol_references=(None,))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda expression: expression.__setitem__("expression_id", ""),
        lambda expression: expression.__setitem__("expression_id", " "),
        lambda expression: expression.__setitem__("stream_id", ""),
        lambda expression: expression.__setitem__("stream_id", "forged"),
        lambda expression: expression.__setitem__("surface", ""),
        lambda expression: expression.__setitem__("span", [-1, 5]),
        lambda expression: expression.__setitem__("span", [0, 99]),
        lambda expression: expression.__setitem__("kind", "NUMBER"),
        lambda expression: expression.__setitem__("qualifier", "MAYBE"),
        lambda expression: expression.__setitem__("role", ""),
        lambda expression: expression.__setitem__("role", " "),
        lambda expression: expression.__setitem__("unit", " "),
        lambda expression: expression.__setitem__("role_spans", [[-1, 3]]),
        lambda expression: expression.__setitem__("role_spans", [[6, 9], [6, 9]]),
        lambda expression: expression.__setitem__(
            "representations", [{"surface": "three", "span": [0, 5], "value": "4"}]
        ),
        lambda expression: expression.__setitem__(
            "representations", [
                {"surface": "three", "span": [0, 5], "value": "3"},
                {"surface": "three", "span": [0, 5], "value": "3"},
            ]
        ),
        lambda expression: expression.__setitem__(
            "representations", [{"surface": "three", "span": [9, 14], "value": "3"}]
        ),
    ],
)
def test_result_validation_rejects_malformed_nested_expression_evidence(mutation):
    """Serialized target evidence retains bounded IDs, spans, roles, and numeric enums."""
    document = complete_document()
    mutation(document["units"][0]["extraction"]["expressions"][0])

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )

    assert exc.value.code == "NCA_RESULT_EXPRESSION_INVALID"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda unit: unit["extraction"]["expressions"][0].update(
            surface="xxxxx", span=[0, 5]
        ),
        lambda unit: unit["extraction"]["expressions"][0].update(
            role_spans=[[6, 99]]
        ),
        lambda unit: unit["extraction"]["expressions"][0].update(
            representations=[{"surface": "xxxxx", "span": [0, 5], "value": "3"}]
        ),
    ],
)
def test_result_validation_binds_nested_evidence_to_the_serialized_target_stream(mutation):
    """Expression, role, and representation spans stay inside the immutable target text."""
    document = complete_document()
    mutation(document["units"][0])

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )

    assert exc.value.code == "NCA_RESULT_EXPRESSION_INVALID"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda unit: unit["reading"].__setitem__("invented", True),
        lambda unit: unit["reading"]["semantic"].__setitem__("invented", True),
        lambda unit: unit["footnote"].__setitem__("invented", True),
        lambda unit: unit.__setitem__("final_outcome", "PASS_AUTHORITY1"),
        lambda unit: unit["footnote"].update(
            action="NONE", status="NOT_REQUIRED", outcome="ADVISORY"
        ),
    ],
)
def test_result_validation_rejects_invented_or_contradictory_decision_state(mutation):
    """Closed reading, footnote, and final decisions cannot be changed after serialization."""
    document = complete_document()
    mutation(document["units"][0])

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )

    assert exc.value.code in {"NCA_RESULT_SCHEMA_INVALID", "NCA_RESULT_DECISION_INVALID"}


@pytest.mark.parametrize(("field", "value"), [("location", "forged"), ("area", "forged")])
def test_result_validation_rejects_unknown_style_context(field, value):
    """Style decisions retain only closed rule areas and exact target stream locations."""
    document = complete_document()
    style = {
        "rule_id": "NCA-DIGITS",
        "area": "digits",
        "code": "NCA_STYLE_RULE_UNSPECIFIED",
        "status": "NOT_ASSESSED",
        "location": "body",
    }
    style[field] = value
    document["units"][0]["style_findings"] = [style]

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )

    assert exc.value.code == "NCA_RESULT_DECISION_INVALID"


def test_result_validation_binds_findings_to_their_owning_unit():
    """A finding cannot replace its unit references, selection, or evidence context."""
    document = complete_document()
    document["findings"][0].update(
        target_reference="REV 22:21",
        target_references=["REV 22:21"],
        western_references=["REV 22:21"],
        ol_reference="REV 22:21",
        ol_references=["REV 22:21"],
    )

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )

    assert exc.value.code == "NCA_RESULT_FINDING_INVALID"


def test_result_validation_rejects_cross_reading_authority_promotion():
    """An alternate cannot borrow the OL pass policy or another reading's authority."""
    document = complete_document()
    reading = document["units"][0]["reading"]
    reading.update(
        selected="ALT",
        registry_id="MAT 1:1",
        source_ids=["SRC-1"],
        source_validation_outcome="PASS_AUTHORITY1",
    )
    reading["semantic"].update(
        outcome="REGISTERED_ALTERNATE", evidence_ids=["SRC-1"], reason_codes=[]
    )
    document["units"][0]["final_outcome"] = "REGISTERED_ALTERNATE"

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )

    assert exc.value.code == "NCA_RESULT_DECISION_INVALID"


def test_review_outcome_from_complete_correspondence_requires_its_receipt():
    """A correspondence-derived mismatch cannot retain only extraction provenance."""
    document = complete_document()
    document["model_receipts"]["CORRESPONDENCE"] = []

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )

    assert exc.value.code == "NCA_RESULT_RECEIPT_INVALID"


def test_correspondence_outcome_requires_exact_indexed_ol_values():
    """A semantic comparison cannot drop or replace its bound OL expression sequence."""
    document = complete_document()
    document["units"][0]["source_evidence"]["expressions"] = []
    document["summary"]["ol_expressions_checked"] = 0

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )

    assert exc.value.code == "NCA_RESULT_EXPRESSION_INVALID"


def test_partial_ol_evidence_must_be_an_authority_ordered_subsequence():
    """An insufficient result may retain partial OL evidence only in indexed order."""
    document = complete_document()
    unit = document["units"][0]
    unit["reading"].update(selected="UNSUPPORTED", source_ids=[])
    unit["reading"]["semantic"].update(
        outcome="INSUFFICIENT_EVIDENCE", evidence_ids=[], reason_codes=["ROLE_UNRESOLVED"]
    )
    unit["final_outcome"] = "INSUFFICIENT_EVIDENCE"
    source = unit["source_evidence"]
    source["context"].update(ol_text="four men", ol_values=["3"])
    source["expressions"][0].update(surface="four", span=[0, 4], values=["4"], role_spans=[[5, 8]])
    document["findings"][0].update(
        category="EVIDENCE", code="NCA_INSUFFICIENT_EVIDENCE",
        selected_reading="UNSUPPORTED", source_ids=[], evidence_ids=[],
    )
    document["coverage"].update(
        result="INSUFFICIENT_DATA", coverage="PARTIAL", confidence_basis="LIMITED",
        restrictions=["ROLE_UNRESOLVED"],
    )
    document["summary"].update(
        insufficient_evidence=1, value_differences=0,
    )

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )

    assert exc.value.code == "NCA_RESULT_EXPRESSION_INVALID"


def test_dual_form_result_requires_both_serialized_representations():
    """Words plus parenthesized digits cannot lose either exact representation span."""
    document = complete_document()
    unit = document["units"][0]
    unit["projection"]["target_text"] = "three (3) men"
    expression = unit["extraction"]["expressions"][0]
    expression.update(surface="three (3)", span=[0, 9], role_spans=[[10, 13]], representations=[])

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )

    assert exc.value.code == "NCA_RESULT_EXPRESSION_INVALID"


def test_result_rejects_duplicate_footnote_evidence_within_one_note():
    """Canonical footnote evidence keys spans by both note identity and local offset."""
    document = complete_document()
    unit = document["units"][0]
    unit["projection"]["target_note_streams"] = [{"note_id": "note-1", "text": "x"}]
    unit["reading"].update(
        selected="OL", footnote_action="REQUIRE", registry_id="MAT 1:1",
        source_ids=["SRC-1"], source_validation_outcome="PASS_AUTHORITY1",
    )
    unit["reading"]["semantic"].update(outcome="PASS_AUTHORITY1", reason_codes=[])
    unit["footnote"] = {
        "action": "REQUIRE", "status": "ADEQUATE", "outcome": "NONE",
        "evidence_spans": [[0, 1], [0, 1]], "evidence_note_ids": ["note-1", "note-1"],
    }
    unit["final_outcome"] = "PASS_AUTHORITY1"
    document["findings"] = []
    document["coverage"]["result"] = "NO_FINDINGS"
    document["summary"].update(findings=0, passes=1, value_differences=0)

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )

    assert exc.value.code == "NCA_RESULT_EXPRESSION_INVALID"


def test_partial_extraction_cannot_validate_as_complete_no_findings():
    """Incomplete extraction forces insufficient-data coverage even with no findings."""
    document = complete_document()
    document["units"][0]["extraction"].update(status="PARTIAL", limitations=["One token unresolved"])
    document["summary"].update(extraction_complete=0, extraction_partial=1, insufficient_evidence=1)
    document["coverage"].update(result="NO_FINDINGS", coverage="COMPLETE", confidence_basis="FULL")

    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )

    assert exc.value.code == "NCA_RESULT_COVERAGE_INVALID"


def test_resolved_accuracy_requires_complete_correspondence_receipt_identity():
    """A semantic OL decision cannot rely only on an extraction receipt."""
    missing = complete_document()
    missing["model_receipts"]["CORRESPONDENCE"] = []
    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            missing, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )
    assert exc.value.code == "NCA_RESULT_RECEIPT_INVALID"

    malformed = complete_document()
    malformed["model_receipts"]["EXTRACTION"][0]["invented"] = True
    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(
            malformed, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
        )
    assert exc.value.code == "NCA_RESULT_RECEIPT_INVALID"
