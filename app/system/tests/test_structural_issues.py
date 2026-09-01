"""Report-only structural classification and status contracts."""

from __future__ import annotations

from sage.structural_issues import (
    classify_text_relation,
    completion_status,
    normalize_structure_problem,
    readiness_status,
)


def test_text_relation_is_relative_to_wip() -> None:
    """Addition and omission labels always describe the WIP Project."""
    assert classify_text_relation(wip_has_text=False, authority_has_text=True) == "OMISSION"
    assert classify_text_relation(wip_has_text=True, authority_has_text=False) == "ADDITION"
    assert (
        classify_text_relation(
            wip_has_text=True,
            authority_has_text=True,
            wording_matches=False,
        )
        == "VARIATION"
    )


def test_structural_issue_completes_without_failure() -> None:
    """A comparison deficiency changes status but does not fail completed analysis."""
    issues = [{"classification": "STRUCTURE_PROBLEM", "code": "VERSIFICATION_MISMATCH"}]
    assert readiness_status(issues) == "READY_WITH_STRUCTURE_PROBLEMS"
    assert completion_status(issues) == "COMPLETE_WITH_STRUCTURE_PROBLEMS"


def test_normalization_marks_vrs_rows_report_only() -> None:
    """Versification findings have one stable structural projection."""
    row = normalize_structure_problem(
        {"code": "SFM_ROUTE_PRIMARY_COVERAGE_MISMATCH", "reference": "JHN 5:4"},
        versification=True,
        relation="ADDITION",
    )
    assert row["classification"] == "STRUCTURE_PROBLEM"
    assert row["status"] == "REPORT_ONLY"
    assert row["structure_status"] == "VERSIFICATION_MISMATCH"
    assert row["text_relation"] == "ADDITION"
