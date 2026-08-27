"""Persistent execution-event classification and deterministic interruption reporting."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .atomic import atomic_write_text
from .errors import InputRequiredError, SageError
from .hashing import sha256_bytes
from .state import append_event
from .storage import storage_layout

SCHEMA_VERSION = "1.0"
DISPOSITIONS = (
    "INPUT_REQUIRED",
    "READY_WITH_ACTIONS",
    "TASK_PAUSED",
    "TASK_OUTPUT_REJECTED",
    "STALE",
    "BLOCKED",
    "ERROR",
)
BOUNDARIES = (
    "SETUP",
    "JOB_CREATION",
    "RUN_CREATION",
    "WORK_UNIT",
    "TASK_ATTEMPT",
    "STAGE",
    "TARGET_COMMIT",
    "RUN_FINALIZATION",
    "NONE",
)

_PROVIDER_INPUT_CODES = {
    "CODEX_CLI_NOT_FOUND",
    "CODEX_CHATGPT_AUTH_REQUIRED",
    "CODEX_CHATGPT_LOGIN_FAILED",
    "CODEX_INSTALL_PREREQUISITE_MISSING",
    "CODEX_INSTALL_FAILED",
    "CODEX_INSTALL_PATH_REFRESH_REQUIRED",
    "CODEX_INSTALL_START_FAILED",
    "CODEX_LOGIN_START_FAILED",
    "CODEX_MODEL_OR_AUTH_NOT_READY",
    "INTERACTIVE_LOGIN_REQUIRED",
    "LLM_PROVIDER_NOT_READY",
    "MODEL_SELECTION_REQUIRED",
    "NO_QUALIFIED_MODEL_AVAILABLE",
    "REASONING_SELECTION_NOT_AVAILABLE",
}
_PROVIDER_PAUSE_CODES = {
    "CODEX_EXECUTION_CONNECTION_FAILED",
    "CODEX_APP_SERVER_TIMEOUT",
    "CODEX_APP_SERVER_UNAVAILABLE",
    "LLM_PROVIDER_TIMEOUT",
    "LLM_PROVIDER_EXECUTION_FAILED",
}
_STALE_CODES = {
    "ACT_INPUT_STALE",
    "BIC_EVIDENCE_COHORT_CHANGED",
    "BIC_PREDECESSOR_OL_EVIDENCE_CHANGED",
    "SAW_PREDECESSOR_FINGERPRINT_MISMATCH",
    "OPERATOR_OVERRIDE_STALE",
    "SAW_APPROVED_PLAN_STALE",
    "SAW_TASK_CONTRACT_INVALID",
}
_FINALIZATION_CODES = {
    "AGGREGATE_COVERAGE_MISMATCH",
    "WORK_UNIT_NOT_FINALIZED",
    "SAW_SEQUENTIAL_ORDER_VIOLATION",
}
_COMMIT_CODES = {
    "EXTERNAL_TARGET_WRITE_PROHIBITED",
    "INCOMPLETE_TRANSACTION",
    "TARGET_REVERT_CONFLICT",
    "TARGET_REVERT_POST_MERGE_MISMATCH",
    "TARGET_SCOPE_OUTSIDE_CONTENT_CHANGED",
    "TARGET_SCOPE_POST_MERGE_MISMATCH",
    "TRANSACTION_ERROR",
}
_COMMIT_PREFLIGHT_CODES = {
    "TARGET_SCOPE_BRIDGE_CROSSES_BOUNDARY",
    "TARGET_SCOPE_CHAPTER_MISSING",
    "TARGET_SCOPE_COMPLEX_VERSE_UNSUPPORTED",
    "TARGET_SCOPE_INSERT_BRIDGE_UNSUPPORTED",
    "TARGET_SCOPE_VERSE_SHAPE_MISMATCH",
}
_BINDING_CODES = {
    "BIC_DONOR_TARGET_LANGUAGE_MISMATCH",
    "JOB_ID_MISMATCH",
    "LANGUAGE_PROFILE_ROLE_NOT_CONFIGURED",
    "PROJECT_BINDING_MISMATCH",
    "RESOURCE_WRITE_ROLE_PROHIBITED",
    "WORKFLOW_QUALIFICATION_NOT_VALIDATED",
}
_OUTPUT_CODE_FRAGMENTS = (
    "PROVIDER_RESPONSE_INVALID",
    "REVIEW_EVIDENCE",
    "FINDING",
    "OUTPUT_INVALID",
    "OUTPUT_SCHEMA",
    "GRAMMAR_ASSESSMENT",
    "TRANSLATION_CHALLENGE",
    "OL_MICRO_CHALLENGE_INVALID",
    "OL_MICRO_MERGE_INVALID",
    "OL_MICRO_REPLACEMENT_REQUIRED",
)
_HARD_RESOURCE_FRAGMENTS = (
    "PARSER_ERROR",
    "SCRIPTURE_NOT_FOUND",
    "DUPLICATE",
    "OVERLAP",
    "RESOURCE_MOUNT_NOT_FOUND",
    "PROJECT_FOLDER_NOT_FOUND",
    "PROJECT_NOT_MAPPED",
)
_SECRET_KEY = re.compile(r"(authorization|api[_-]?key|token|secret|password|cookie|credential|environment|env)", re.I)


def utc_now() -> str:
    """Return the canonical event timestamp."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def classify_exception(
    exc: SageError,
    *,
    boundary_hint: str | None = None,
) -> tuple[str, str, str]:
    """Return disposition, blocking boundary, and retryability for one expected failure."""
    code = str(exc.code or "SAGE_ERROR").strip().upper()
    if isinstance(exc, InputRequiredError) or code in _PROVIDER_INPUT_CODES or code.endswith("_INPUT_REQUIRED"):
        disposition, boundary, retry = "INPUT_REQUIRED", "TASK_ATTEMPT", "AFTER_INPUT"
    elif code in _PROVIDER_PAUSE_CODES or code.startswith("CODEX_APP_SERVER_"):
        disposition, boundary, retry = "TASK_PAUSED", "TASK_ATTEMPT", "RETRY_SAME_TASK"
    elif code in _STALE_CODES or "STALE" in code or "FINGERPRINT_MISMATCH" in code:
        disposition, boundary, retry = "STALE", "STAGE", "REBUILD_AFFECTED_STAGE"
    elif code in _FINALIZATION_CODES or "COVERAGE_MISMATCH" in code:
        disposition, boundary, retry = "BLOCKED", "RUN_FINALIZATION", "AFTER_CORRECTION"
    elif code in _COMMIT_PREFLIGHT_CODES:
        disposition, boundary, retry = "BLOCKED", "TARGET_COMMIT", "AFTER_CORRECTION"
    elif code in _COMMIT_CODES or code.startswith("TARGET_REVERT_"):
        disposition, boundary, retry = "BLOCKED", "TARGET_COMMIT", "AFTER_CORRECTION"
    elif code in _BINDING_CODES or "BINDING_MISMATCH" in code:
        disposition, boundary, retry = "BLOCKED", "JOB_CREATION", "AFTER_CORRECTION"
    elif any(fragment in code for fragment in _OUTPUT_CODE_FRAGMENTS) or code in {
        "RTC_REVIEW_EVIDENCE_INCOMPLETE",
        "RTC_REVIEW_EVIDENCE_MISSING",
        "SAW_TASK_RESULT_INVALID",
    }:
        disposition, boundary, retry = "TASK_OUTPUT_REJECTED", "TASK_ATTEMPT", "RETRY_SAME_TASK"
    elif code in {"REQUESTED_SCOPE_BLOCKED", "WORKSPACE_INITIALIZATION_BLOCKED"} or any(
        fragment in code for fragment in _HARD_RESOURCE_FRAGMENTS
    ):
        disposition, boundary, retry = "BLOCKED", "WORK_UNIT", "AFTER_CORRECTION"
    elif code.endswith("_REQUIRED") or code.endswith("_NOT_CONFIGURED") or code.endswith("_SELECTION_REQUIRED"):
        disposition, boundary, retry = "INPUT_REQUIRED", "TASK_ATTEMPT", "AFTER_INPUT"
    else:
        disposition, boundary, retry = "ERROR", "STAGE", "DEVELOPER_REVIEW"
    if boundary_hint and disposition != "STALE":
        normalized = str(boundary_hint).strip().upper()
        if normalized in BOUNDARIES:
            boundary = normalized
    return disposition, boundary, retry


def terminal_heading(disposition: str) -> str:
    """Return the concise terminal heading for one persisted disposition."""
    return {
        "INPUT_REQUIRED": "SAGE INPUT REQUIRED",
        "READY_WITH_ACTIONS": "SAGE ACTION / ADVISORY",
        "TASK_PAUSED": "SAGE TASK PAUSED",
        "TASK_OUTPUT_REJECTED": "SAGE TASK OUTPUT REJECTED",
        "STALE": "SAGE STATE STALE",
        "BLOCKED": "SAGE OPERATION BLOCKED",
        "ERROR": "SAGE ERROR",
    }.get(str(disposition).upper(), "SAGE ERROR")


def _scrub(value: Any, *, depth: int = 0) -> Any:
    """Bound and sanitize event details so reports cannot persist credentials accidentally."""
    if depth > 5:
        return "[detail depth omitted]"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            label = str(key)
            if _SECRET_KEY.search(label):
                result[label] = "[redacted]"
            else:
                result[label] = _scrub(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_scrub(item, depth=depth + 1) for item in list(value)[:100]]
    if isinstance(value, str):
        text = value.replace("\x00", "")
        return text if len(text) <= 4000 else text[:4000] + "... [truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _scrub(str(value), depth=depth + 1)


def _event_paths(
    sage_root: Path,
    *,
    job_root: Path | None = None,
    run_root: Path | None = None,
) -> tuple[Path, Path]:
    """Resolve the governed JSONL evidence and deterministic Markdown projection paths."""
    if run_root is not None:
        root = run_root / "diagnostics"
        return root / "EXECUTION-EVENTS.jsonl", root / "BLOCK-REPORT.md"
    if job_root is not None:
        root = job_root / "diagnostics"
        return root / "EXECUTION-EVENTS.jsonl", root / "BLOCK-REPORT.md"
    root = storage_layout(sage_root).diagnostics_root
    return root / "SETUP-EVENTS.jsonl", root / "SETUP-BLOCK-REPORT.md"


def load_events(path: Path) -> list[dict[str, Any]]:
    """Load valid event rows from one append-only JSONL file."""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def render_event_report(events: Iterable[Mapping[str, Any]]) -> str:
    """Render a deterministic execution interruption/block/advisory report."""
    rows = [dict(item) for item in events]
    lines = ["# SAGE Execution Interruptions, Blocks, and Advisories", ""]
    if not rows:
        return "\n".join(lines + ["No execution-affecting events have been recorded.", ""])
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("disposition") or "ERROR").upper()].append(row)
    order = ["BLOCKED", "STALE", "TASK_OUTPUT_REJECTED", "TASK_PAUSED", "INPUT_REQUIRED", "READY_WITH_ACTIONS", "ERROR"]
    for disposition in order:
        items = groups.get(disposition, [])
        if not items:
            continue
        lines.extend([f"## {disposition.replace('_', ' ').title()}", ""])
        for row in items:
            scope = str(row.get("work_unit_scope") or row.get("requested_scope") or "").strip()
            title = f"{row.get('reason_code', 'SAGE_ERROR')}"
            if scope:
                title += f" - {scope}"
            lines.extend(
                [
                    f"### {title}",
                    "",
                    f"- Event: `{row.get('event_id', '')}`",
                    f"- Time: `{row.get('timestamp_utc', '')}`",
                    f"- Effect: `{row.get('blocks', 'NONE')}`",
                    f"- Retryability: `{row.get('retryability', 'UNKNOWN')}`",
                    f"- Message: {row.get('message', '')}",
                ]
            )
            if row.get("next_action"):
                lines.append(f"- Next action: {row['next_action']}")
            resource = row.get("resource")
            if isinstance(resource, Mapping) and any(resource.values()):
                summary = ", ".join(f"{key}={value}" for key, value in resource.items() if value not in (None, ""))
                if summary:
                    lines.append(f"- Resource: {summary}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def record_execution_event(
    sage_root: Path,
    *,
    disposition: str,
    reason_code: str,
    message: str,
    blocks: str,
    retryability: str,
    workflow: str | None = None,
    job_id: str | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
    operation: str | None = None,
    stage: str | None = None,
    requested_scope: str | None = None,
    work_unit_scope: str | None = None,
    next_action: str | None = None,
    details: Mapping[str, Any] | None = None,
    resource: Mapping[str, Any] | None = None,
    source_module: str | None = None,
    exception_class: str | None = None,
    job_root: Path | None = None,
    run_root: Path | None = None,
) -> dict[str, Any]:
    """Append one governed event and regenerate its deterministic Markdown projection."""
    normalized_disposition = str(disposition).strip().upper()
    normalized_blocks = str(blocks).strip().upper()
    if normalized_disposition not in DISPOSITIONS:
        raise ValueError(f"Unsupported SAGE execution-event disposition: {disposition}")
    if normalized_blocks not in BOUNDARIES:
        raise ValueError(f"Unsupported SAGE execution-event boundary: {blocks}")
    event_path, report_path = _event_paths(sage_root, job_root=job_root, run_root=run_root)
    timestamp = utc_now()
    existing = load_events(event_path)
    seed = json.dumps(
        {
            "timestamp": timestamp,
            "sequence": len(existing) + 1,
            "reason": reason_code,
            "job": job_id,
            "run": run_id,
            "task": task_id,
            "scope": work_unit_scope or requested_scope,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    event_id = f"EVT-{sha256_bytes(seed.encode('utf-8'))[:16].upper()}"
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "timestamp_utc": timestamp,
        "disposition": normalized_disposition,
        "reason_code": str(reason_code or "SAGE_ERROR").strip().upper(),
        "message": _scrub(str(message)),
        "workflow": str(workflow or "").strip().lower() or None,
        "job_id": job_id,
        "run_id": run_id,
        "task_id": task_id,
        "operation": operation,
        "stage": stage,
        "requested_scope": requested_scope,
        "work_unit_scope": work_unit_scope,
        "blocks": normalized_blocks,
        "retryability": retryability,
        "resource": _scrub(dict(resource or {})),
        "next_action": _scrub(next_action) if next_action else None,
        "details": _scrub(dict(details or {})),
        "source": {
            "module": source_module,
            "exception_class": exception_class,
        },
    }
    append_event(event_path, event)
    atomic_write_text(report_path, render_event_report([*existing, event]))
    return {**event, "event_path": str(event_path), "report_path": str(report_path)}


def record_exception_event(
    sage_root: Path,
    exc: SageError,
    *,
    boundary_hint: str | None = None,
    workflow: str | None = None,
    job_id: str | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
    operation: str | None = None,
    stage: str | None = None,
    requested_scope: str | None = None,
    work_unit_scope: str | None = None,
    job_root: Path | None = None,
    run_root: Path | None = None,
    source_module: str | None = None,
) -> dict[str, Any]:
    """Classify one SAGE exception and persist it at the narrowest known boundary."""
    disposition, boundary, retryability = classify_exception(exc, boundary_hint=boundary_hint)
    return record_execution_event(
        sage_root,
        disposition=disposition,
        reason_code=exc.code,
        message=exc.message,
        blocks=boundary,
        retryability=retryability,
        workflow=workflow,
        job_id=job_id,
        run_id=run_id,
        task_id=task_id,
        operation=operation,
        stage=stage,
        requested_scope=requested_scope or exc.affected_scope,
        work_unit_scope=work_unit_scope,
        next_action=exc.next_action,
        details=exc.details,
        source_module=source_module,
        exception_class=type(exc).__name__,
        job_root=job_root,
        run_root=run_root,
    )


def events_for_run(run_root: Path) -> list[dict[str, Any]]:
    """Return the canonical execution events for one Run."""
    return load_events(run_root / "diagnostics" / "EXECUTION-EVENTS.jsonl")


def events_for_job(job_root: Path) -> list[dict[str, Any]]:
    """Return the canonical pre-Run execution events for one Job."""
    return load_events(job_root / "diagnostics" / "EXECUTION-EVENTS.jsonl")


def report_section(events: Iterable[Mapping[str, Any]]) -> str:
    """Render the final-report section body without a top-level document title."""
    rows = [dict(item) for item in events]
    if not rows:
        return ""
    rendered = render_event_report(rows).splitlines()
    if rendered and rendered[0].startswith("# "):
        rendered = rendered[2:] if len(rendered) > 1 and rendered[1] == "" else rendered[1:]
    return "\n".join(rendered).rstrip() + "\n"
