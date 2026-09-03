"""Canonical operator workflow and persisted Job identity helpers."""

from __future__ import annotations

import re

from .errors import ValidationError

OPERATOR_WORKFLOWS = ("bic", "rtc", "stc")
ANALYSIS_WORKFLOWS = frozenset({"rtc", "stc"})
LEGACY_ANALYSIS_WORKFLOW = "saw"
SUPPORTED_JOB_TOOLS = ("bic", "rtc", "stc", "saw")

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SNAPSHOT_DATE_RE = re.compile(r"^[0-9]{8}$")


def validate_project_code(project_id: str) -> str:
    """Return one path-safe Project code suitable for canonical Job identity."""
    value = str(project_id).strip()
    if not _PROJECT_ID_RE.fullmatch(value):
        raise ValidationError(
            f"Invalid Project code for Job identity: {project_id!r}",
            code="INVALID_JOB_PROJECT_ID",
            next_action="Use the exact registered Project code without path separators.",
        )
    return value


def runtime_workflow_id(tool: str) -> str:
    """Return the canonical runtime workflow for new work or one legacy Job."""
    value = str(tool).strip().lower()
    if value in ANALYSIS_WORKFLOWS:
        return value
    if value in {"bic", LEGACY_ANALYSIS_WORKFLOW}:
        return value
    raise ValidationError(
        f"Unsupported Job workflow: {tool!r}",
        code="UNSUPPORTED_JOB_WORKFLOW",
    )


def legacy_saw_workflow(workflow: str) -> bool:
    """Return whether a stored workflow uses the retired analysis identity."""
    return str(workflow).strip().lower() == LEGACY_ANALYSIS_WORKFLOW


def is_analysis_workflow(workflow: str) -> bool:
    """Return whether a value identifies current or legacy analysis execution."""
    value = str(workflow).strip().lower()
    return value in ANALYSIS_WORKFLOWS or legacy_saw_workflow(value)


def canonical_analysis_workflow(
    workflow: str,
    operation: str | None = None,
) -> str:
    """Normalize one canonical or explicitly identified legacy analysis workflow."""
    value = str(workflow).strip().lower()
    if value in ANALYSIS_WORKFLOWS:
        return value
    normalized_operation = str(operation or "").strip().lower()
    if legacy_saw_workflow(value) and normalized_operation in ANALYSIS_WORKFLOWS:
        return normalized_operation
    if legacy_saw_workflow(value):
        raise ValidationError(
            "The legacy analysis workflow requires an RTC or STC operation",
            code="LEGACY_ANALYSIS_OPERATION_REQUIRED",
        )
    raise ValidationError(
        f"Unsupported analysis workflow: {workflow!r}",
        code="UNSUPPORTED_ANALYSIS_WORKFLOW",
    )


def analysis_operation_label(operation: str) -> str:
    """Return the canonical current-facing label for one analysis operation."""
    normalized = str(operation).strip().lower()
    labels = {
        "rtc": "Reference Text Comparison (RTC)",
        "stc": "Source Text Correspondence (STC)",
        "focused": "Targeted Check",
        "ol": "Original-Language Review",
    }
    try:
        return labels[normalized]
    except KeyError as exc:
        raise ValidationError(
            f"Unsupported analysis operation: {operation!r}",
            code="UNSUPPORTED_ANALYSIS_OPERATION",
        ) from exc


def analysis_reason_code(code: str, operation: str) -> str:
    """Convert one legacy-shaped code into a canonical new-operation code."""
    canonical = canonical_analysis_workflow(operation)
    value = str(code).strip().upper()
    for prefix in (f"SAW_{canonical.upper()}_", "SAW_"):
        if value.startswith(prefix):
            return f"{canonical.upper()}_{value[len(prefix):]}"
    return value


def canonical_analysis_job_id(tool: str, project_id: str, snapshot_date: str) -> str:
    """Build ``RTC/STC-<Project>_<YYYYMMDD>`` from the WIP import snapshot."""
    workflow = str(tool).strip().lower()
    if workflow not in ANALYSIS_WORKFLOWS:
        raise ValidationError(
            f"Analysis Job identity requires RTC or STC, not {tool!r}",
            code="UNSUPPORTED_ANALYSIS_WORKFLOW",
        )
    project = validate_project_code(project_id)
    date = str(snapshot_date).strip()
    if not _SNAPSHOT_DATE_RE.fullmatch(date):
        raise ValidationError(
            f"Invalid WIP snapshot date for Job identity: {snapshot_date!r}",
            code="INVALID_WIP_SNAPSHOT_DATE",
            next_action="Use the WIP import date in YYYYMMDD form.",
        )
    return f"{workflow.upper()}-{project}_{date}"
