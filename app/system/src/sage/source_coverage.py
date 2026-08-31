"""Deterministic report-only issues for comparison-source coordinate gaps."""

from __future__ import annotations

from typing import Any, Iterable

from .vrs import VerseRef


SOURCE_PRIMARY_COVERAGE_MISMATCH = "SOURCE_PRIMARY_COVERAGE_MISMATCH"
COMPLETE_WITH_SOURCE_TEXT_ISSUES = "COMPLETE_WITH_SOURCE_TEXT_ISSUES"


def source_text_issues(
    expected_refs: Iterable[VerseRef],
    covered_refs: Iterable[VerseRef],
    *,
    workflow: str,
    source_stream: str,
    source_project_id: str = "",
    scope: str,
) -> tuple[dict[str, Any], ...]:
    """Describe missing source coordinates without changing WIP coverage."""
    missing = sorted(frozenset(expected_refs) - frozenset(covered_refs))
    return tuple(
        {
            "status": "REPORT_ONLY",
            "code": SOURCE_PRIMARY_COVERAGE_MISMATCH,
            "workflow": str(workflow).strip().upper(),
            "source_stream": str(source_stream).strip().upper(),
            "source_project_id": str(source_project_id).strip(),
            "scope": str(scope).strip(),
            "reference": ref.label(),
            "message": (
                f"{str(source_stream).strip().upper()} has no source text at {ref.label()}; "
                "the run continued without inventing comparison evidence."
            ),
        }
        for ref in missing
    )


def unique_source_text_issues(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return deterministic source-text issues without duplicate coordinates."""
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for value in rows:
        row = dict(value)
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
    return COMPLETE_WITH_SOURCE_TEXT_ISSUES if any(True for _ in rows) else "COMPLETE"
