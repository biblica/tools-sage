"""NCA machine results preserve exact evidence and reject invented state."""

from copy import deepcopy
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
    semantic = SemanticDecision("PASS_AUTHORITY1", ("SRC-1",))
    unit = UnitResult(
        projected,
        Extraction((expression,), "COMPLETE"),
        ReadingDecision("OL", semantic, "NONE", None, ("SRC-1",)),
        FootnoteDecision("NONE", "NOT_REQUIRED", "NONE"),
        "PASS_AUTHORITY1",
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
        "ol_reference": "MAT 1:1",
        "selected_reading": "OL",
        "source_ids": ["SRC-1"],
        "evidence_ids": ["SRC-1"],
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
        "findings": 1,
        "insufficient_evidence": 0,
        "reference_not_indexed": 0,
        "not_assessed": 0,
        "extraction_complete": 1,
        "extraction_partial": 0,
        "extraction_unsupported": 0,
    }
    return RunResult((unit,), (finding,), coverage, summary)


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
    return {
        "EXTRACTION": [{
            "phase": "EXTRACTION",
            "task_version": "nca-extraction-v1",
            "provider": "fixture-provider",
            "model": "fixture-model",
            "reasoning_effort": "medium",
            "route_id": "nca-numbers",
            "routing_mode": "PINNED",
            "qualification_status": "QUALIFIED",
            "prompt_sha256": "d" * 64,
            "input_sha256": "e" * 64,
            "response_sha256": "f" * 64,
            "provider_metadata": {},
        }],
        "CORRESPONDENCE": [],
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


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda value: value["units"][0].__setitem__("final_outcome", "APPROVED"), "NCA_RESULT_ENUM_INVALID"),
        (lambda value: value["units"][0]["reading"]["semantic"].__setitem__("evidence_ids", ["INVENTED"]), "NCA_RESULT_EVIDENCE_INVALID"),
        (lambda value: value["coverage"].__setitem__("assessed_unit_ids", []), "NCA_RESULT_COVERAGE_INVALID"),
        (lambda value: value["provenance"]["style_profile"].__setitem__("sha256", "bad"), "NCA_RESULT_PROVENANCE_INVALID"),
        (lambda value: value["units"][0]["extraction"]["expressions"][0]["values"].__setitem__(0, 3.0), "NCA_RESULT_FRACTION_INVALID"),
        (lambda value: value["summary"].__setitem__("extraction_complete", 0), "NCA_RESULT_SUMMARY_INVALID"),
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
    unit["reading"].update(selected="UNSUPPORTED", source_ids=[])
    unit["reading"]["semantic"].update(outcome="INSUFFICIENT_EVIDENCE", evidence_ids=[])
    unit["final_outcome"] = "INSUFFICIENT_EVIDENCE"
    document["findings"] = []
    document["model_receipts"]["EXTRACTION"] = []
    document["coverage"].update(
        result="INSUFFICIENT_DATA", coverage="PARTIAL", confidence_basis="LIMITED",
        restrictions=["Model unavailable"],
    )
    document["summary"].update(
        expressions=0, findings=0, insufficient_evidence=1,
        extraction_complete=0, extraction_unsupported=1,
    )

    validated = validate_numbers_result(
        document, expected_unit_ids=("unit-1",), allowed_evidence_ids=("SRC-1",)
    )

    assert validated["model_receipts"] == {"EXTRACTION": [], "CORRESPONDENCE": [], "FOOTNOTE": []}
