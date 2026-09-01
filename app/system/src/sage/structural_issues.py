"""Normalize report-only text-structure deficiencies across RTC and STC."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

STRUCTURE_PROBLEM = "STRUCTURE_PROBLEM"
VERSIFICATION_MISMATCH = "VERSIFICATION_MISMATCH"
READY_WITH_STRUCTURE_PROBLEMS = "READY_WITH_STRUCTURE_PROBLEMS"
COMPLETE_WITH_STRUCTURE_PROBLEMS = "COMPLETE_WITH_STRUCTURE_PROBLEMS"


def classify_text_relation(
    *,
    wip_has_text: bool,
    authority_has_text: bool,
    wording_matches: bool | None = None,
) -> str:
    """Classify a coordinate relative to what the WIP Project contains."""
    if authority_has_text and not wip_has_text:
        return "OMISSION"
    if wip_has_text and not authority_has_text:
        return "ADDITION"
    if wip_has_text and authority_has_text:
        return "MATCH" if wording_matches is not False else "VARIATION"
    return "ABSENT_IN_BOTH"


def normalize_structure_problem(
    row: Mapping[str, Any],
    *,
    versification: bool | None = None,
    relation: str | None = None,
) -> dict[str, Any]:
    """Return one stable, report-only structural issue projection."""
    value = dict(row)
    code = str(value.get("code") or STRUCTURE_PROBLEM).strip().upper()
    is_versification = (
        bool(versification)
        if versification is not None
        else (
            str(value.get("structure_status") or "").strip().upper()
            == VERSIFICATION_MISMATCH
            or "VRS" in code
            or "VERSIFICATION" in code
        )
    )
    value.update(
        {
            "code": code,
            "classification": STRUCTURE_PROBLEM,
            "status": "REPORT_ONLY",
            "structure_status": (
                VERSIFICATION_MISMATCH if is_versification else STRUCTURE_PROBLEM
            ),
        }
    )
    if relation is not None:
        value["text_relation"] = str(relation).strip().upper()
    return value


def readiness_status(
    issues: Iterable[Mapping[str, Any]],
    *,
    evidence_loaded: bool = True,
) -> str:
    """Return readiness without treating loaded structural defects as a failure."""
    if not evidence_loaded:
        return "ACTION_NEEDED"
    return READY_WITH_STRUCTURE_PROBLEMS if any(True for _ in issues) else "READY"


def completion_status(
    issues: Iterable[Mapping[str, Any]],
    *,
    analysis_complete: bool = True,
) -> str:
    """Return completed analysis status while preserving structural deficiencies."""
    if not analysis_complete:
        return "IN_PROGRESS"
    return COMPLETE_WITH_STRUCTURE_PROBLEMS if any(True for _ in issues) else "COMPLETE"
