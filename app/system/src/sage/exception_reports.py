"""Shared exception reports: content problems become reported exceptions, only integrity guards stop a Run.

One structured record, one integrity-code list, one retry-then-NOT_ASSESSED policy, and one report
section serve BIC, RTC, STC, and NCA. This module sits on top of ``execution_events``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .atomic import atomic_write_json
from .coverage import assess_coverage
from .execution_events import (
    _BINDING_CODES,
    _COMMIT_CODES,
    _FINALIZATION_CODES,
    _STALE_CODES,
    _scrub,
    load_events,
    utc_now,
)
from .human_output import catalogue_text
from .state import append_event

NOT_ASSESSED = "NOT_ASSESSED"
# Failed attempts allowed per work unit before its coordinates are reported as not assessed.
MAX_UNIT_ATTEMPTS = 3
EXCEPTION_REPORT_FILE = "EXCEPTION-REPORTS.jsonl"
NOT_ASSESSED_RESULT_FILE = "not-assessed.json"
SEVERITIES = ("INFORMATION", "WARNING", "ERROR")
EFFECTS = ("RETRY", NOT_ASSESSED, "FLAGGED", "CORRECTED", "STOP")

# Detected data-integrity breaches in a sealed NCA task: a soft, resumable framing would misrepresent them.
NCA_INTEGRITY_FAILURE_CODES = frozenset(
    {
        "LLM_TASK_OUTPUT_NOT_EMPTY",
        "NCA_PHASE_CHECKPOINT_INVALID",
        "EXECUTION_RECEIPT_OUTPUT_MISMATCH",
    }
)
# Path safety, sealed task identity, pinned contracts, and routing guards.
_PATH_AND_CONTRACT_CODES = frozenset(
    {
        "EXTERNAL_PATH_ESCAPE",
        "LLM_TASK_PATH_INVALID",
        "LLM_TASK_READ_INVALID",
        "LLM_TASK_GOVERNANCE_INPUT_INVALID",
        "LLM_TASK_EVIDENCE_POLICY_INVALID",
        "LLM_TASK_SKILL_IDENTITY_INVALID",
        "LLM_TASK_INVALID",
        "LLM_TASK_NOT_FOUND",
        "TASK_ROUTE_BYPASS_PROHIBITED",
        "BIC_PROTECTED_CONTRACT_MISSING",
        "BIC_PROTECTED_CONTRACT_STALE",
        "BIC_PROTECTED_CONTRACT_HASH_MISMATCH",
        "RESULT_COVERAGE_DRIFT",
        "DUPLICATE_WORK_UNIT_RESULT",
        "MISSING_WORK_UNIT_RESULT",
        "RTC_TASK_CONTRACT_INVALID",
        "STC_TASK_CONTRACT_INVALID",
        "STC_OL_AUTHORITY_MISMATCH",
        "LLM_RESPONSE_ROUTE_MISMATCH",
        "TASK_SUBMISSION_TAMPERED",
        "EXECUTION_RECEIPT_MISSING",
        "LLM_ANALYSIS_WORK_UNIT_LAYOUT_INVALID",
        "LLM_SAW_WORK_UNIT_LAYOUT_INVALID",
    }
)
INTEGRITY_CODES = frozenset(
    {
        *NCA_INTEGRITY_FAILURE_CODES,
        *_STALE_CODES,
        *_BINDING_CODES,
        *_COMMIT_CODES,
        *_FINALIZATION_CODES,
        *_PATH_AND_CONTRACT_CODES,
    }
)
_INTEGRITY_FRAGMENTS = ("STALE", "FINGERPRINT_MISMATCH", "BINDING_MISMATCH", "HASH_MISMATCH", "PATH_ESCAPE")
# Environment conditions (login, provider outage) say nothing about content, so they pause the Run.
_ENVIRONMENT_DISPOSITIONS = frozenset({"INPUT_REQUIRED", "TASK_PAUSED"})
# Provider, configuration, and controller failures: retrying them only seals good work NOT_ASSESSED.
RUN_STOP_CODES = frozenset(
    {
        "CODEX_EXECUTION_NOT_READY",
        "PROVIDER_EXECUTION_NOT_READY",
        "MENU_CONTROLLER_COMMAND_FAILED",
        "CONFIGURATION_ERROR",
        "PROVIDER_ROUTE_UNAVAILABLE",
    }
)
# A non-content code that already cost this many units is systemic: the next one stops the Run.
CIRCUIT_BREAKER_UNITS = 2


def is_integrity_code(code: str) -> bool:
    """Return whether one error code is an integrity guard that must stop a Run."""
    value = str(code or "").strip().upper()
    return value in INTEGRITY_CODES or any(fragment in value for fragment in _INTEGRITY_FRAGMENTS)


@dataclass(frozen=True)
class ExceptionRecord:
    """One reported exception: what was not assessed or corrected, where, why, and with what effect."""

    tool: str
    code: str
    message: str
    effect: str
    run_id: str | None = None
    job_id: str | None = None
    task_id: str | None = None
    work_unit: str | None = None
    stage: str | None = None
    coordinates: tuple[str, ...] = ()
    severity: str = "WARNING"
    attempts: int = 0
    evidence_path: str | None = None
    recorded_utc: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        """Reject uncontrolled severity and effect values."""
        if self.severity not in SEVERITIES:
            raise ValueError(f"Unsupported exception severity: {self.severity}")
        if self.effect not in EFFECTS:
            raise ValueError(f"Unsupported exception effect: {self.effect}")

    def to_dict(self) -> dict[str, Any]:
        """Return the scrubbed JSON form persisted and rendered everywhere."""
        row = asdict(self)
        row["coordinates"] = list(self.coordinates)
        row["message"] = _scrub(self.message)
        return row


def unit_failure_action(
    code: str,
    disposition: str,
    attempts: int,
    *,
    cap: int = MAX_UNIT_ATTEMPTS,
    prior_not_assessed_codes: Sequence[str] = (),
) -> str:
    """Decide what the plan runner does after one failed work-unit attempt.

    ``attempts`` counts failures so far, including this one: integrity codes, environment conditions,
    and provider/configuration/controller failures STOP; anything else RETRYs until ``cap`` failures,
    then the unit is NOT_ASSESSED. ``prior_not_assessed_codes`` are the codes of units this Run already
    sealed NOT_ASSESSED: a non-content code that recurs that often trips the circuit breaker and STOPs.
    """
    value = str(code or "").strip().upper()
    if is_integrity_code(value) or value in RUN_STOP_CODES:
        return "STOP"
    if str(disposition or "").upper() in _ENVIRONMENT_DISPOSITIONS:
        return "STOP"
    content = str(disposition or "").upper() == "TASK_OUTPUT_REJECTED"
    if not content and sum(1 for item in prior_not_assessed_codes if str(item).upper() == value) >= CIRCUIT_BREAKER_UNITS:
        return "STOP"
    return "RETRY" if attempts < cap else NOT_ASSESSED


def _report_path(run_root: Path) -> Path:
    """Return the Run's append-only exception-report file."""
    return run_root / "diagnostics" / EXCEPTION_REPORT_FILE


def record_exception(run_root: Path, record: ExceptionRecord) -> dict[str, Any]:
    """Append one exception record to its Run's diagnostics and return its persisted form."""
    row = record.to_dict()
    append_event(_report_path(run_root), row)
    return row


def exceptions_for_run(run_root: Path) -> list[dict[str, Any]]:
    """Return every exception recorded for one Run, oldest first."""
    return load_events(_report_path(run_root))


def failed_attempts(run_root: Path, task_id: str) -> int:
    """Count the failed attempts already recorded for one task."""
    return sum(
        1
        for row in exceptions_for_run(run_root)
        if row.get("task_id") == task_id and row.get("effect") in {"RETRY", NOT_ASSESSED}
    )


def write_not_assessed_result(manifest_path: Path, record: ExceptionRecord) -> dict[str, Any]:
    """Seal one work unit as terminal NOT_ASSESSED so plan continuation and aggregation can proceed."""
    validation_root = manifest_path.parent / "validation"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evidence = {
        "schema_version": "1.0",
        "status": NOT_ASSESSED,
        "task_id": manifest.get("task_id"),
        "operation": manifest.get("operation"),
        "scope": manifest.get("scope"),
        "expected_references": list(manifest.get("expected_references") or []),
        "exception": record.to_dict(),
    }
    atomic_write_json(validation_root / NOT_ASSESSED_RESULT_FILE, evidence)
    submission = {
        "schema_version": "1.0",
        "status": NOT_ASSESSED,
        "task_id": manifest.get("task_id"),
        "operation": manifest.get("operation"),
        "scope": manifest.get("scope"),
        "reason_code": record.code,
        "not_assessed_path": f"validation/{NOT_ASSESSED_RESULT_FILE}",
    }
    atomic_write_json(validation_root / "submission.json", submission)
    return evidence


def load_not_assessed_result(manifest_path: Path) -> dict[str, Any]:
    """Load the evidence of a NOT_ASSESSED work unit."""
    path = manifest_path.parent / "validation" / NOT_ASSESSED_RESULT_FILE
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"NOT_ASSESSED evidence is missing or invalid: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"NOT_ASSESSED evidence must be an object: {path}")
    return value


def coverage_document(
    reviewed: Sequence[str],
    not_assessed: Sequence[str],
    *,
    findings_present: bool,
    restrictions: Iterable[str] = (),
) -> dict[str, Any]:
    """Derive one coverage record through ``assess_coverage``; extras appear only when something was not assessed."""
    reviewed_list = list(reviewed)
    missing = list(not_assessed)
    assessment = assess_coverage(
        findings_present=findings_present,
        required_evidence_complete=not missing,
        restrictions=restrictions,
        assessed=bool(reviewed_list) or not missing,
    )
    document: dict[str, Any] = {"status": assessment.coverage, "reviewed_references": reviewed_list}
    if missing:
        document.update(
            {
                "result": assessment.result,
                "confidence_basis": assessment.confidence_basis,
                "not_assessed_references": missing,
                "restrictions": list(assessment.restrictions),
            }
        )
    return document


def write_run_exception_report(run_root: Path, *, language: str = "en") -> Path | None:
    """Write the Run's standalone "Exceptions — not assessed" report; None when nothing was lost."""
    section = render_exceptions_section(exceptions_for_run(run_root), language=language)
    if not section:
        return None
    path = run_root / "diagnostics" / "EXCEPTIONS-NOT-ASSESSED.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(["# SAGE Exception Report", "", *section]).rstrip() + "\n", encoding="utf-8")
    return path


def not_assessed_rows(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep the records whose effect is that coordinates were not assessed."""
    return [dict(row) for row in records if row.get("effect") == NOT_ASSESSED]


def render_exceptions_section(records: Iterable[Mapping[str, Any]], *, language: str = "en") -> list[str]:
    """Render the shared "Exceptions — not assessed" Markdown section, or nothing when there are none."""
    rows = not_assessed_rows(records)
    if not rows:
        return []
    lines = [
        f"## {catalogue_text(language, 'report.exceptions_not_assessed')}",
        "",
        catalogue_text(language, "report.exceptions_not_assessed_note"),
        "",
    ]
    for row in rows:
        coordinates = ", ".join(str(value) for value in row.get("coordinates") or []) or str(row.get("work_unit") or "")
        lines.extend(
            [
                f"### {coordinates or row.get('code', '')}",
                "",
                f"- Code: `{row.get('code', '')}`; attempts: `{row.get('attempts', 0)}`; severity: `{row.get('severity', '')}`",
                f"- Stage: `{row.get('stage') or ''}`; work unit: `{row.get('work_unit') or ''}`",
                f"- {row.get('message', '')}",
            ]
        )
        if row.get("evidence_path"):
            lines.append(f"- Evidence: `{row['evidence_path']}`")
        lines.append("")
    return lines


def apply_unit_failure(
    run_root: Path,
    manifest_path: Path,
    *,
    tool: str,
    code: str,
    message: str,
    disposition: str,
    run_id: str | None = None,
    job_id: str | None = None,
    work_unit: str | None = None,
    stage: str | None = None,
    evidence_path: str | None = None,
) -> tuple[str, int]:
    """Apply the one work-unit failure policy shared by the menu and the CLI.

    Records the failed attempt and seals the unit NOT_ASSESSED once the cap is reached; returns the action
    (``STOP``, ``RETRY``, or ``NOT_ASSESSED``) and the attempt number. ``STOP`` records nothing, so the Run
    stays resumable exactly where it stopped.
    """
    from .references import atomic_reference_labels

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    task_id = str(manifest.get("task_id") or "")
    attempts = failed_attempts(run_root, task_id) + 1
    action = unit_failure_action(
        code,
        disposition,
        attempts,
        prior_not_assessed_codes=[str(row.get("code") or "") for row in not_assessed_rows(exceptions_for_run(run_root))],
    )
    if action == "STOP":
        return action, attempts
    record = ExceptionRecord(
        tool=tool,
        code=code,
        message=message,
        effect="RETRY" if action == "RETRY" else NOT_ASSESSED,
        run_id=run_id,
        job_id=job_id,
        task_id=task_id,
        work_unit=work_unit,
        stage=stage,
        coordinates=tuple(atomic_reference_labels(str(value) for value in manifest.get("expected_references") or [])),
        attempts=attempts,
        evidence_path=evidence_path,
    )
    record_exception(run_root, record)
    if action == NOT_ASSESSED:
        write_not_assessed_result(Path(manifest_path), record)
    return action, attempts
