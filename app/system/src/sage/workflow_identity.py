"""Canonical operator workflow and persisted Job identity helpers."""

from __future__ import annotations

import re

from .errors import ValidationError

OPERATOR_WORKFLOWS = ("bic", "rtc", "stc")
ANALYSIS_WORKFLOWS = frozenset({"rtc", "stc"})
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
    """Map an operator-facing workflow to its current internal runtime adapter."""
    value = str(tool).strip().lower()
    if value in ANALYSIS_WORKFLOWS:
        return "saw"
    if value in {"bic", "saw"}:
        return value
    raise ValidationError(
        f"Unsupported Job workflow: {tool!r}",
        code="UNSUPPORTED_JOB_WORKFLOW",
    )


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
