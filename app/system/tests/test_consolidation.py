"""Governed chapter-report consolidation contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sage.consolidation import consolidate_result_documents
from sage.errors import ValidationError


def _document(*, job_id: str, task_id: str, issue: str, finding_id: str) -> dict[str, object]:
    """Return one compact finalized SAW result fixture."""
    return {
        "schema_version": "2.0",
        "task_id": task_id,
        "job_id": job_id,
        "run_id": task_id,
        "operation": "qa",
        "stage": "COMPOSITE_FINALIZED",
        "scope": "GEN 1",
        "coverage": {"status": "COMPLETE", "reviewed_references": ["GEN 1:1"]},
        "review_receipts": [],
        "structural_adjudications": [],
        "ol_review_requests": [],
        "ol_resolutions": [],
        "findings": [
            {
                "finding_id": finding_id,
                "target_reference": "GEN 1:1",
                "category": "MEANING",
                "issue": issue,
                "required_action": "Review with the Team.",
                "action_level": "REVIEW",
                "confidence": "MEDIUM",
                "evidence_ids": [f"WIP:{task_id}"],
                "grammar_rule_ids": [],
                "original_language_evidence": "",
            }
        ],
    }


def _source(tmp_path: Path, name: str, document: dict[str, object]) -> Path:
    """Persist one immutable source fixture for provenance hashing."""
    path = tmp_path / name
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    return path


def test_equivalent_findings_are_deduplicated_with_both_sources(tmp_path: Path) -> None:
    """Merge equivalent records while retaining every contributing Run identity."""
    first = _document(job_id="SAW_example", task_id="RUN-1", issue="Check the subject.", finding_id="F-1")
    second = _document(job_id="SAW_example", task_id="RUN-2", issue="Check the subject.", finding_id="F-2")
    paths = [_source(tmp_path, "one.json", first), _source(tmp_path, "two.json", second)]

    result = consolidate_result_documents([first, second], source_paths=paths)

    assert result["finding_count"] == 1
    assert result["consolidation"]["status"] == "COMPLETE"
    assert len(result["consolidation"]["duplicate_groups"][0]["contributors"]) == 2
    assert all(row["sha256"] for row in result["consolidation"]["provenance"])


def test_distinct_findings_at_one_coordinate_are_not_guessed_to_conflict(tmp_path: Path) -> None:
    """Retain separate issues without treating shared verse/category as contradiction evidence."""
    first = _document(job_id="SAW_example", task_id="RUN-1", issue="Subject is Peter.", finding_id="F-1")
    second = _document(job_id="SAW_example", task_id="RUN-2", issue="Subject is John.", finding_id="F-2")

    result = consolidate_result_documents([first, second])

    assert result["finding_count"] == 2
    assert result["consolidation"]["status"] == "COMPLETE"
    assert result["consolidation"]["conflicts"] == []
    assert result["consolidation"]["conflict_policy"] == "EXPLICIT_LINEAGE_ONLY"


def test_explicit_conflict_lineage_requires_human_review() -> None:
    """Surface competing versions only when an upstream validator supplies shared lineage."""
    first = _document(job_id="SAW_example", task_id="RUN-1", issue="Subject is Peter.", finding_id="F-1")
    second = _document(job_id="SAW_example", task_id="RUN-2", issue="Subject is John.", finding_id="F-2")
    first["findings"][0]["conflict_group_id"] = "SUBJECT-ADJUDICATION-1"
    second["findings"][0]["conflict_group_id"] = "SUBJECT-ADJUDICATION-1"

    result = consolidate_result_documents([first, second])

    assert result["consolidation"]["status"] == "HUMAN_REVIEW_REQUIRED"
    assert result["consolidation"]["conflicts"][0]["finding_ids"] == ["F-1", "F-2"]


def test_cross_job_consolidation_is_rejected() -> None:
    """Keep report consolidation inside one owning Job."""
    first = _document(job_id="SAW_one", task_id="RUN-1", issue="One", finding_id="F-1")
    second = _document(job_id="SAW_two", task_id="RUN-2", issue="One", finding_id="F-2")

    with pytest.raises(ValidationError, match="one Job"):
        consolidate_result_documents([first, second])


def test_chapter_projection_excludes_other_chapter_findings_and_ol_ledgers() -> None:
    """Chapter report input is bounded before consolidation, including OL and receipt ledgers."""
    from sage.plan_continuation import _chapter_document

    document = {
        "scope": "DAN 1-2",
        "coverage": {"status": "COMPLETE", "reviewed_references": ["DAN 1:1", "DAN 2:1"]},
        "findings": [
            {"finding_id": "F1", "target_reference": "DAN 1:1"},
            {"finding_id": "F2", "target_reference": "DAN 2:1"},
        ],
        "review_receipts": [
            {"receipt_id": "R", "reviewed_references": ["DAN 1:1", "DAN 2:1"]},
        ],
        "structural_adjudications": [
            {"candidate_id": "C1", "finding_id": "F1"},
            {"candidate_id": "C2", "finding_id": "F2"},
        ],
        "ol_review_requests": [
            {"request_id": "OL1", "target_reference": "DAN 1:1"},
            {"request_id": "OL2", "target_reference": "DAN 2:1"},
        ],
        "ol_resolutions": [
            {"request_id": "OL1", "target_reference": "DAN 1:1"},
            {"request_id": "OL2", "target_reference": "DAN 2:1"},
        ],
        "work_units": [{"scope": "DAN 1:1"}, {"scope": "DAN 2:1"}],
        "versification_advisories": [],
        "execution_events": [],
    }
    chapter = _chapter_document(document, book="DAN", chapter=1)
    assert chapter["scope"] == "DAN 1"
    assert [row["finding_id"] for row in chapter["findings"]] == ["F1"]
    assert chapter["coverage"]["reviewed_references"] == ["DAN 1:1"]
    assert chapter["review_receipts"][0]["reviewed_references"] == ["DAN 1:1"]
    assert [row["request_id"] for row in chapter["ol_review_requests"]] == ["OL1"]
    assert [row["request_id"] for row in chapter["ol_resolutions"]] == ["OL1"]
    assert [row["candidate_id"] for row in chapter["structural_adjudications"]] == ["C1"]
    assert [row["scope"] for row in chapter["work_units"]] == ["DAN 1:1"]


def test_chapter_catalog_accumulates_finalized_scopes_from_same_book(tmp_path: Path) -> None:
    """A later partial-scope Run does not replace earlier findings in the same chapter catalog."""
    from sage.plan_continuation import _chapter_result_documents

    job_root = tmp_path / "jobs" / "saw" / "SAW_example"
    first_plan = job_root / "runs" / "RUN-1" / "plans" / "plan.json"
    current_plan = job_root / "runs" / "RUN-2" / "plans" / "plan.json"
    first_plan.parent.mkdir(parents=True)
    current_plan.parent.mkdir(parents=True)
    first = _document(job_id="SAW_example", task_id="RUN-1", issue="First", finding_id="F-1")
    first["scope"] = "GEN 1:1"
    first_raw = _source(tmp_path, "first-final.json", first)
    first_plan.write_text(
        json.dumps(
            {
                "plan_type": "SAW_QA_COMPOSITE",
                "status": "FINALIZED",
                "requested_scope": "GEN 1:1",
                "aggregate_path": str(first_raw),
            }
        ),
        encoding="utf-8",
    )
    current = _document(job_id="SAW_example", task_id="RUN-2", issue="Second", finding_id="F-2")
    current["scope"] = "GEN 1:2"
    current_raw = _source(tmp_path, "current-final.json", current)

    documents, paths = _chapter_result_documents(
        current_plan,
        "GEN 1:2",
        current_path=current_raw,
        current_document=current,
    )

    assert [document["task_id"] for document in documents] == ["RUN-1", "RUN-2"]
    assert paths == [first_raw.resolve(), current_raw.resolve()]
