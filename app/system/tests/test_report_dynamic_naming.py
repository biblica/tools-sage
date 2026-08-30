"""Regression coverage for Scripture-aware report naming and execution provenance."""

import json
from pathlib import Path

import pytest

from sage.act_outputs import (
    aggregate_execution_routes,
    execution_route_from_receipt,
    render_execution_section,
)
from sage.errors import ValidationError
from sage.hashing import sha256_file
from sage.plan_continuation import _append_parts, _report_book_code, _report_scope_parts, _report_scope_slug


@pytest.mark.parametrize(
    "book",
    (
        "1SA", "2SA", "1KI", "2KI", "1CH", "2CH", "1CO", "2CO",
        "1TH", "2TH", "1TI", "2TI", "1PE", "2PE", "1JN", "2JN", "3JN",
    ),
)
def test_numbered_book_code_is_never_zero_padded_or_split(book: str) -> None:
    """Numbered canonical book codes remain intact while coordinates receive padding."""
    assert _report_book_code(book) == book
    assert _report_scope_slug(book) == book
    assert _report_scope_slug(f"{book} 1") == f"{book}-001"


def test_numbered_book_alias_is_canonicalized_before_report_naming() -> None:
    """Book-name aliases canonicalize before report folder and scope names are composed."""
    assert _report_book_code("2 John 1") == "2JN"
    assert _report_scope_slug("2 John 1") == "2JN-001"
    assert _report_scope_slug("2JN 1:7-13") == "2JN-001-007-013"


def test_report_scope_slug_preserves_existing_coordinate_padding() -> None:
    """Ordinary book/chapter/verse scopes retain the established three-digit coordinate grammar."""
    assert _report_scope_slug("GEN 1") == "GEN-001"
    assert _report_scope_slug("MAT 1:1") == "MAT-001-001"
    assert _report_scope_slug("MAT 1:1-3") == "MAT-001-001-003"
    assert _report_scope_slug("MAT 1:1-2:3") == "MAT-001-001-002-003"
    assert _report_scope_slug("MAT 1-2") == "MAT-001-002"


def test_whole_book_report_scope_does_not_repeat_book_directory() -> None:
    """Whole-book output uses one Book directory rather than BOOK/BOOK duplication."""
    assert _report_scope_parts("1JN") == ("1JN",)
    assert _report_scope_parts("ZEC") == ("ZEC",)


def test_report_scope_directories_use_book_only() -> None:
    """Operator report directories stop at Book; scope detail belongs in filenames."""
    assert _report_scope_parts("1JN 1") == ("1JN",)
    assert _report_scope_parts("ZEC 3:2-9") == ("ZEC",)


def test_generated_path_builder_removes_adjacent_duplicate_segments(tmp_path) -> None:
    """Generated directory paths never append the same adjacent segment twice."""
    root = tmp_path / "reports" / "SAW_example" / "1JN"
    assert _append_parts(root, ("1JN",)) == root
    assert _append_parts(root, ("1JN", "1JN-001")) == root / "1JN-001"


def _execution_receipt(task_root: Path, *, task_id: str = "saw-rtc-mat-001") -> dict:
    """Return one complete exact-route receipt fixture for report projection tests."""
    output = task_root / "output" / "findings.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('{"findings": []}\n', encoding="utf-8")
    return {
        "schema_version": "2.0",
        "task_id": task_id,
        "skill_id": "saw-rtc",
        "route_id": "a" * 64,
        "routing_mode": "AUTOMATIC",
        "qualification_status": "RECOMMENDED",
        "qualification_evidence_sha256": "b" * 64,
        "routing_policy_version": "alpha1-1",
        "provider_runtime_version": "1.2.3",
        "model_identity_strength": "ALIASED",
        "capability_fingerprint": "c" * 64,
        "provider": "codex",
        "model": "gpt-test",
        "reasoning_effort": "medium",
        "selection_mode": "AUTOMATIC",
        "operator_policy_override": False,
        "phase_reasoning_efforts": ["medium"],
        "started_utc": "2026-08-29T10:00:00Z",
        "completed_utc": "2026-08-29T10:00:01Z",
        "output_sha256": {"output/findings.json": sha256_file(output)},
    }


def test_execution_route_projection_verifies_task_and_output_hashes(tmp_path: Path) -> None:
    """Only the sibling receipt for the exact task outputs can prove report route identity."""
    task_root = tmp_path / "task"
    receipt = _execution_receipt(task_root)
    validation = task_root / "validation"
    validation.mkdir()
    receipt_path = validation / "llm-execution-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    route = execution_route_from_receipt(
        task_root,
        task_id="saw-rtc-mat-001",
        output_hashes=receipt["output_sha256"],
    )
    assert route["status"] == "PROVED"
    assert route["route_id"] == "a" * 64
    assert route["skill_id"] == "saw-rtc"
    assert route["model"] == "gpt-test"
    assert route["receipt_sha256"] == sha256_file(receipt_path)

    with pytest.raises(ValidationError) as caught:
        execution_route_from_receipt(
            task_root,
            task_id="another-task",
            output_hashes=receipt["output_sha256"],
        )
    assert caught.value.code == "EXECUTION_RECEIPT_IDENTITY_MISMATCH"

    with pytest.raises(ValidationError) as caught:
        execution_route_from_receipt(
            task_root,
            task_id="saw-rtc-mat-001",
            output_hashes={"output/findings.json": "d" * 64},
        )
    assert caught.value.code == "EXECUTION_RECEIPT_OUTPUT_MISMATCH"


def test_execution_route_projection_accepts_provisional_policy_provenance(tmp_path: Path) -> None:
    """Requiring qualification evidence for an Alpha fallback must reject its truthful receipt."""
    task_root = tmp_path / "task"
    receipt = _execution_receipt(task_root)
    receipt.update(
        {
            "qualification_status": "PROVISIONAL_UNQUALIFIED",
            "qualification_evidence_sha256": None,
            "routing_basis_sha256": "e" * 64,
            "selection_mode": "PROVISIONAL_PROVIDER_DEFAULT",
        }
    )
    validation = task_root / "validation"
    validation.mkdir()
    (validation / "llm-execution-receipt.json").write_text(
        json.dumps(receipt),
        encoding="utf-8",
    )

    route = execution_route_from_receipt(
        task_root,
        task_id=receipt["task_id"],
        output_hashes=receipt["output_sha256"],
    )

    assert route["status"] == "PROVED"
    assert route["qualification_status"] == "PROVISIONAL_UNQUALIFIED"
    assert route["qualification_evidence_sha256"] is None
    assert route["routing_basis_sha256"] == "e" * 64


def test_execution_route_aggregation_and_rendering_preserve_distinct_routes() -> None:
    """Route summaries count tasks without collapsing distinct provider identities."""
    first = {
        "status": "PROVED",
        "task_id": "T-1",
        "skill_id": "saw-rtc",
        "route_id": "a" * 64,
        "provider": "codex",
        "model": "gpt-a",
        "reasoning_effort": "medium",
        "routing_mode": "AUTOMATIC",
        "qualification_status": "RECOMMENDED",
    }
    second = {
        **first,
        "task_id": "T-2",
        "route_id": "b" * 64,
        "model": "gpt-b",
        "reasoning_effort": "high",
        "qualification_status": "QUALIFIED",
    }
    routes = aggregate_execution_routes(
        [{"execution_route": first}, {"execution_route": first}, {"execution_route": second}]
    )
    assert [row["task_count"] for row in routes] == [1, 1]
    assert routes[0]["task_ids"] == ["T-1"]
    assert routes[1]["task_ids"] == ["T-2"]
    lines = render_execution_section(routes)
    assert "SKILL | PROVIDER | MODEL | REASONING | MODE | TASKS" in lines
    assert "saw-rtc | codex | gpt-a | medium | AUTOMATIC | 1" in lines
    assert "saw-rtc | codex | gpt-b | high | AUTOMATIC | 1" in lines
