"""NCA human reports retain authority evidence while localizing visible labels."""

from copy import deepcopy

import pytest

from sage.errors import ValidationError
from sage.nca_reporting import render_nca_report
from sage.numbers.results import NCA_CAPABILITY_LIMITATION


def report_document() -> dict[str, object]:
    """Build a complete rendering input with differing coordinate identities."""
    finding = {
        "finding_id": "NUMBERS_RUN-1_UNIT-1_0001",
        "work_unit_id": "unit-1",
        "category": "FOOTNOTE",
        "code": "NCA_FOOTNOTE_REVIEW_MISSING_FOOTNOTE",
        "severity": "REVIEW",
        "target_reference": "MAT 1:2",
        "target_references": ["MAT 1:2"],
        "western_references": ["MAT 1:1"],
        "ol_reference": "MRK 9:44",
        "selected_reading": "ALT",
        "source_ids": ["SRC-1", "SRC-2"],
        "evidence_ids": ["SRC-1"],
        "footnote_action": "REQUIRE",
        "footnote_status": "MISSING",
        "suggested_note": "Other witnesses read four.",
        "message": "Review the reading-specific target footnote.",
    }
    unit = {
        "unit_id": "unit-1",
        "projection": {
            "target_references": ["MAT 1:2"],
            "western_references": ["MAT 1:1"],
            "canonical_references": ["MAT 1:1"],
            "ol_references": ["MRK 9:44"],
            "precision": "COORDINATE",
            "status": "READY",
            "source_sha256": "a" * 64,
            "source_locator": {"line_start": 14, "line_end": 14},
        },
        "extraction": {"status": "COMPLETE", "limitations": [], "expressions": []},
        "source_evidence": {
            "expressions": [{
                "expression_id": "ol-1", "stream_id": "ol", "surface": "three",
                "span": [0, 5], "values": ["3"], "kind": "CARDINAL", "unit": None,
                "qualifier": "EXACT", "role": "men", "role_spans": [[6, 9]],
                "representations": [],
            }],
            "context": {
                "language": "GRK", "ol_text": "three men",
                "ol_values": ["3"],
                "variant_class": "TEXTUAL_VARIANT", "scholarship_status": "SUPPORTED",
            },
        },
        "reading": {
            "selected": "ALT",
            "footnote_action": "REQUIRE",
            "registry_id": "MAT 1:1",
            "source_ids": ["SRC-1", "SRC-2"],
            "source_validation_outcome": "ACCEPTABLE_VARIANT_WITH_FOOTNOTE",
            "semantic": {"outcome": "REGISTERED_ALTERNATE", "evidence_ids": ["SRC-1"], "reason_codes": []},
        },
        "footnote": {"action": "REQUIRE", "status": "MISSING", "outcome": "REVIEW_MISSING_FOOTNOTE", "evidence_spans": [], "evidence_note_ids": []},
        "final_outcome": "REVIEW_MISSING_FOOTNOTE",
        "style_findings": [],
        "limitations": [],
    }
    return {
        "schema_version": "1.0",
        "workflow": "nca",
        "check_id": "NUMBERS",
        "provenance": {
            "run_id": "RUN-1",
            "job_id": "JOB-1",
            "style_profile": {"selector": "fixture-en/1", "sha256": "b" * 64},
            "reference_package": {"package_id": "fixture", "sha256": "c" * 64},
            "wip": {"identity": "WIP", "sha256": "d" * 64},
            "language_profile": {"grammar_issue": "Never report this."},
        },
        "check_policy": {"checks": {"number_accuracy": True, "presentation_consistency": True, "footnote_review": True}},
        "model_receipts": {
            "EXTRACTION": [{
                "phase": "EXTRACTION", "provider": "fixture-provider", "model": "fixture-model",
                "prompt_sha256": "e" * 64, "input_sha256": "f" * 64, "response_sha256": "0" * 64,
            }],
            "CORRESPONDENCE": [], "FOOTNOTE": [],
        },
        "limitations": {"capability": NCA_CAPABILITY_LIMITATION, "sqs_confidence_checks_applied": False},
        "units": [unit],
        "findings": [finding],
        "coverage": {
            "result": "FINDINGS",
            "coverage": "COMPLETE",
            "confidence_basis": "FULL",
            "restrictions": [],
            "skipped_checks": [],
            "expected_unit_ids": ["unit-1"],
            "assessed_unit_ids": ["unit-1"],
        },
        "summary": {
            "units": 1, "expressions": 0, "findings": 1,
            "target_expressions": 0, "ol_expressions_checked": 1, "passes": 0,
            "unit_conversions": 0, "value_differences": 0, "missing_numbers": 0,
            "added_numbers": 0, "known_variants": 1, "style_findings": 0,
            "indexed_coordinates": 1, "unindexed_coordinates": 0,
            "insufficient_evidence": 0, "reference_not_indexed": 0, "not_assessed": 0,
            "extraction_complete": 1, "extraction_partial": 0, "extraction_unsupported": 0,
        },
    }


def test_report_exposes_navigation_authority_and_registered_note_evidence():
    """The report distinguishes target, Western, and OL coordinates with note policy."""
    report = render_nca_report(report_document())

    for expected in (
        "JOB-1", "RUN-1", "WIP", "fixture-en/1", "fixture",
        "MAT 1:2", "MAT 1:1", "MRK 9:44", "line_start=14",
        "SRC-1, SRC-2", "ALT", "REQUIRE", "MISSING",
        "EXTRACTION: fixture-provider/fixture-model",
        "Other witnesses read four.", "NCA_FOOTNOTE_REVIEW_MISSING_FOOTNOTE",
        "three = 3 [CARDINAL ; role=men ; qualifier=EXACT]",
        "TEXTUAL_VARIANT", "SUPPORTED",
        NCA_CAPABILITY_LIMITATION,
    ):
        assert expected in report
    assert "Never report this." not in report


def test_zero_finding_and_incomplete_reports_still_show_capability_limitations():
    """Neither an all-clear nor incomplete evidence may hide the mandatory limitation."""
    document = report_document()
    document["findings"] = []
    document["summary"]["findings"] = 0
    document["coverage"].update(
        result="INSUFFICIENT_DATA",
        coverage="PARTIAL",
        confidence_basis="LIMITED",
        restrictions=["Required evidence is incomplete."],
    )

    report = render_nca_report(document)

    assert NCA_CAPABILITY_LIMITATION in report
    assert "INSUFFICIENT_DATA" in report
    assert "No NCA findings were recorded." not in report


def test_localized_report_changes_human_labels_but_retains_machine_evidence():
    """A bound report localizer changes prose without altering codes or identifiers."""
    localized_text = {
        "report.nca.title": "Laporan NCA",
        "report.nca.limitations": "Batasan",
        "report.nca.capability_limitation": "Temuan dibatasi oleh pemahaman bahasa dan kemampuan interpretasi angka LLM yang dipilih. Pemeriksaan keyakinan SQS belum diterapkan.",
        "report.nca.findings": "Temuan",
    }

    report = render_nca_report(
        report_document(), language="id", localize=lambda key: localized_text.get(key, key)
    )

    assert "# Laporan NCA" in report
    assert localized_text["report.nca.capability_limitation"] in report
    assert "NCA_FOOTNOTE_REVIEW_MISSING_FOOTNOTE" in report
    assert "SRC-1, SRC-2" in report
    assert "MRK 9:44" in report
    assert NCA_CAPABILITY_LIMITATION not in report


def test_report_rejects_missing_limitation_and_unknown_language_rendering():
    """Reports fail closed when capability prose or requested localization is unavailable."""
    missing = deepcopy(report_document())
    missing["limitations"]["capability"] = ""
    with pytest.raises(ValidationError) as exc:
        render_nca_report(missing)
    assert exc.value.code == "NCA_RESULT_LIMITATION_REQUIRED"

    with pytest.raises(ValidationError) as exc:
        render_nca_report(report_document(), language="sw")
    assert exc.value.code == "NCA_REPORT_TRANSLATION_REQUIRED"


def test_report_rejects_missing_model_identity_for_assessed_units():
    """A completed extraction cannot be rendered under an invented anonymous model."""
    document = report_document()
    document["model_receipts"]["EXTRACTION"] = []

    with pytest.raises(ValidationError) as exc:
        render_nca_report(document)

    assert exc.value.code == "NCA_RESULT_RECEIPT_INVALID"
