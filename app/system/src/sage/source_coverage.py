"""Deterministic report-only issues for comparison-source coordinate gaps."""

from __future__ import annotations

from typing import Any, Iterable

from .structural_issues import (
    COMPLETE_WITH_STRUCTURE_PROBLEMS,
    classify_text_relation,
    completion_status,
    normalize_structure_problem,
)
from .vrs import VerseRef


SOURCE_PRIMARY_COVERAGE_MISMATCH = "SOURCE_PRIMARY_COVERAGE_MISMATCH"
COMPLETE_WITH_SOURCE_TEXT_ISSUES = COMPLETE_WITH_STRUCTURE_PROBLEMS


def source_text_issues(
    expected_refs: Iterable[VerseRef],
    covered_refs: Iterable[VerseRef],
    *,
    workflow: str,
    source_stream: str,
    source_project_id: str = "",
    wip_project_id: str = "",
    scope: str,
) -> tuple[dict[str, Any], ...]:
    """Describe missing source coordinates without changing WIP coverage."""
    missing = sorted(frozenset(expected_refs) - frozenset(covered_refs))
    authority = str(source_project_id).strip() or str(source_stream).split(":", 1)[0].upper()
    wip = str(wip_project_id).strip()
    relation = classify_text_relation(wip_has_text=True, authority_has_text=False)
    return tuple(
        normalize_structure_problem({
            "code": SOURCE_PRIMARY_COVERAGE_MISMATCH,
            "workflow": str(workflow).strip().upper(),
            "source_stream": str(source_stream).strip().upper(),
            "source_project_id": str(source_project_id).strip(),
            "wip_project_id": wip,
            "scope": str(scope).strip(),
            "reference": ref.label(),
            "message": (
                f"{'Project ' + wip if wip else 'The WIP Project'} contains an {relation} "
                f"at {ref.label()} relative to {authority}; the Run continued and reported "
                "the structural deficiency."
            ),
        }, versification=True, relation=relation)
        for ref in missing
    )


def unique_source_text_issues(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return deterministic source-text issues without duplicate coordinates."""
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for value in rows:
        row = normalize_structure_problem(value)
        key = (
            str(row.get("workflow") or "").upper(),
            str(row.get("source_stream") or "").upper(),
            str(row.get("source_project_id") or ""),
            str(row.get("reference") or ""),
        )
        unique.setdefault(key, row)
    return [unique[key] for key in sorted(unique)]


def source_comparison_status(rows: Iterable[dict[str, Any]]) -> str:
    """Describe comparison completion independently from exact WIP coverage."""
    return completion_status(rows)
