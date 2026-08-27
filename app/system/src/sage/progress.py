"""Canonical sequential Job/Run progress quantification and compact TUI rendering."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

PROGRESS_BASIS_PROJECTED_HANDOFF_ESTIMATED_TOKENS = "PROJECTED_HANDOFF_ESTIMATED_TOKENS"
PROGRESS_BASIS_ACT_ESTIMATED_TOKENS = "ACT_ESTIMATED_TOKENS"
PROGRESS_ADVANCEMENT_FINALIZED_TASKS = "FINALIZED_TASKS_ONLY"
PROGRESS_VISUAL_CELLS = 10
TERMINAL_RESULTS = {"DONE", "FAILED", "BLOCKED", "CANCELLED"}
ACTIVE_PHASES = {"PREPARING", "RUNNING", "VALIDATING", "WRITING"}
FINAL_TASK_STATUSES = {
    "FINALIZED",
    "COMMITTED",
    "STAGED_VALIDATED",
    "STAGED_VALIDATED_WITH_CHALLENGES",
}


@dataclass(frozen=True)
class JobProgressPolicy:
    """Describe how one sequential Job quantifies progress without exposing token detail in the TUI."""

    basis: str = PROGRESS_BASIS_PROJECTED_HANDOFF_ESTIMATED_TOKENS
    advancement: str = PROGRESS_ADVANCEMENT_FINALIZED_TASKS
    visual_cells: int = PROGRESS_VISUAL_CELLS

    def to_dict(self) -> dict[str, Any]:
        """Return the additive Job-manifest contract for progress quantification."""
        return {
            "basis": self.basis,
            "advancement": self.advancement,
            "visual_cells": self.visual_cells,
        }


DEFAULT_JOB_PROGRESS_POLICY = JobProgressPolicy()


@dataclass(frozen=True)
class RunProgress:
    """Quantified progress for one sequential Run derived from its governed ACT tasks."""

    basis: str
    completed: int
    total: int
    task_completed: int
    task_total: int
    active_task_id: str | None = None
    active_operation: str | None = None
    active_skill_id: str | None = None
    phase: str | None = None
    result: str | None = None
    reason_code: str | None = None

    @property
    def percent(self) -> int | None:
        """Return conservative integer progress without overstating incomplete work."""
        if self.total <= 0:
            return None
        if self.completed >= self.total:
            return 100
        return max(0, min(99, (self.completed * 100) // self.total))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly progress snapshot for menus, TUI and diagnostics."""
        return {
            "basis": self.basis,
            "completed": self.completed,
            "total": self.total,
            "percent": self.percent,
            "task_completed": self.task_completed,
            "task_total": self.task_total,
            "active_task_id": self.active_task_id,
            "active_operation": self.active_operation,
            "active_skill_id": self.active_skill_id,
            "phase": self.phase,
            "result": self.result,
            "reason_code": self.reason_code,
        }


def validate_job_progress_policy(raw: Mapping[str, Any] | None) -> JobProgressPolicy:
    """Validate an additive Job progress policy or return the canonical default."""
    if not raw:
        return DEFAULT_JOB_PROGRESS_POLICY
    basis = str(raw.get("basis") or PROGRESS_BASIS_PROJECTED_HANDOFF_ESTIMATED_TOKENS).upper()
    advancement = str(raw.get("advancement") or PROGRESS_ADVANCEMENT_FINALIZED_TASKS).upper()
    try:
        visual_cells = int(raw.get("visual_cells", PROGRESS_VISUAL_CELLS))
    except (TypeError, ValueError) as exc:
        raise ValueError("Job progress visual_cells must be an integer") from exc
    if basis not in {
        PROGRESS_BASIS_PROJECTED_HANDOFF_ESTIMATED_TOKENS,
        PROGRESS_BASIS_ACT_ESTIMATED_TOKENS,
    }:
        raise ValueError(f"Unsupported Job progress basis: {basis}")
    if advancement != PROGRESS_ADVANCEMENT_FINALIZED_TASKS:
        raise ValueError(f"Unsupported Job progress advancement: {advancement}")
    if visual_cells != PROGRESS_VISUAL_CELLS:
        raise ValueError(f"Job progress visual_cells must be {PROGRESS_VISUAL_CELLS}")
    return JobProgressPolicy(basis=basis, advancement=advancement, visual_cells=visual_cells)


def _load_json(path: Path) -> dict[str, Any]:
    """Return a JSON object or an empty mapping when a progress source is absent or malformed."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _resolve_task_path(root: Path, value: str) -> Path:
    """Resolve a Run task-manifest path without assuming absolute storage."""
    path = Path(value)
    return path if path.is_absolute() else (root / path)


def _task_weight(manifest: Mapping[str, Any], basis: str) -> int:
    """Return the workload weight for the requested progress basis with legacy compatibility."""
    budget = manifest.get("context_budget")
    if not isinstance(budget, Mapping):
        return 1
    if basis == PROGRESS_BASIS_ACT_ESTIMATED_TOKENS:
        governance = budget.get("governance_context")
        if isinstance(governance, Mapping):
            raw = governance.get("final_estimated_tokens", governance.get("estimated_tokens"))
        else:
            raw = None
        # Historical manifests may carry a controller-context token estimate. New
        # manifests intentionally do not tokenize controller-only data, so this
        # legacy display basis falls back to the actual provider handoff weight.
        if raw is None:
            handoff = budget.get("provider_handoff")
            raw = (
                handoff.get("total_estimated_tokens")
                if isinstance(handoff, Mapping)
                else budget.get("final_estimated_tokens", budget.get("estimated_tokens", 1))
            )
    else:
        handoff = budget.get("provider_handoff")
        if isinstance(handoff, Mapping):
            raw = handoff.get(
                "total_estimated_tokens", budget.get("final_estimated_tokens", 1)
            )
        else:
            raw = budget.get("final_estimated_tokens", budget.get("estimated_tokens", 1))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(1, value)


def _task_status(manifest_path: Path, manifest: Mapping[str, Any]) -> str:
    """Return the durable task state used for progress advancement and active-phase reporting."""
    submission = _load_json(manifest_path.parent / "validation" / "submission.json")
    if submission:
        return str(submission.get("status") or "SUBMITTED").upper()
    allowed = manifest.get("allowed_writes")
    if isinstance(allowed, list) and allowed and all(
        isinstance(value, str) and (manifest_path.parent / value).is_file() for value in allowed
    ):
        return "OUTPUT_READY"
    return "CREATED"


def _task_identity(manifest: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Return task ID, operation and Skill ID from one governed ACT manifest."""
    task_id = str(manifest.get("task_id") or "").strip() or None
    operation = str(manifest.get("operation") or "").strip().upper() or None
    skill = manifest.get("skill")
    skill_id = None
    if isinstance(skill, Mapping):
        skill_id = str(skill.get("id") or "").strip() or None
    return task_id, operation, skill_id


def quantify_run(
    *,
    root: Path,
    task_manifests: Iterable[str],
    run_status: str,
    current_stage: str,
    basis: str = PROGRESS_BASIS_PROJECTED_HANDOFF_ESTIMATED_TOKENS,
    result: str | None = None,
    reason_code: str | None = None,
) -> RunProgress:
    """Derive one conservative sequential Run quantifier from sealed task manifests and submissions."""
    rows: list[tuple[int, str, str | None, str | None, str | None]] = []
    for value in task_manifests:
        path = _resolve_task_path(root, str(value)).resolve()
        manifest = _load_json(path)
        if not manifest:
            continue
        task_id, operation, skill_id = _task_identity(manifest)
        rows.append((_task_weight(manifest, basis), _task_status(path, manifest), task_id, operation, skill_id))

    total = sum(weight for weight, *_rest in rows)
    completed = sum(weight for weight, status, *_rest in rows if status in FINAL_TASK_STATUSES)
    task_completed = sum(1 for _weight, status, *_rest in rows if status in FINAL_TASK_STATUSES)

    active_row = next((row for row in rows if row[1] not in FINAL_TASK_STATUSES), None)
    active_task_id = active_row[2] if active_row else None
    active_operation = active_row[3] if active_row else None
    active_skill_id = active_row[4] if active_row else None

    normalized_status = str(run_status or "").upper()
    normalized_stage = str(current_stage or "").upper()
    normalized_result = str(result or "").upper() or None
    if normalized_result not in TERMINAL_RESULTS:
        if normalized_status == "COMPLETE":
            normalized_result = "DONE"
        elif normalized_status == "ABANDONED":
            normalized_result = "CANCELLED"
        elif normalized_status == "FAILED":
            normalized_result = "FAILED"
        elif normalized_status == "BLOCKED":
            normalized_result = "BLOCKED"
        else:
            normalized_result = None

    phase = None
    if normalized_result is None:
        if not rows:
            phase = "PREPARING"
        elif active_row is not None:
            phase = "VALIDATING" if active_row[1] == "OUTPUT_READY" else "RUNNING"
        elif normalized_stage not in {"COMPLETE", "ABANDONED", "ARCHIVED"}:
            phase = "WRITING"

    if normalized_result == "DONE" and total > 0:
        completed = total
        task_completed = len(rows)

    return RunProgress(
        basis=basis,
        completed=completed,
        total=total,
        task_completed=task_completed,
        task_total=len(rows),
        active_task_id=active_task_id,
        active_operation=active_operation,
        active_skill_id=active_skill_id,
        phase=phase,
        result=normalized_result,
        reason_code=(str(reason_code).upper() if reason_code else None),
    )


def render_progress_bar(percent: int | None, *, cells: int = PROGRESS_VISUAL_CELLS) -> str:
    """Render the canonical low-resolution bar while preserving integer-percent precision separately."""
    if cells <= 0:
        raise ValueError("Progress bar cells must be positive")
    if percent is None:
        filled = 0
    else:
        bounded = max(0, min(100, int(percent)))
        filled = cells if bounded == 100 else (bounded * cells) // 100
    return f"[{'█' * filled}{'░' * (cells - filled)}]"


def format_progress_line(job_id: str, progress: Mapping[str, Any], *, label_width: int = 24) -> str:
    """Render one compact aligned sequential Job progress line for the TUI dashboard."""
    percent_raw = progress.get("percent")
    percent = int(percent_raw) if isinstance(percent_raw, int) else None
    bar = render_progress_bar(percent)
    percent_cell = f"{percent:>3}%" if percent is not None else " --%"
    label = str(job_id or "IDLE")
    if len(label) > label_width:
        label = label[: max(1, label_width - 1)] + "…"
    label = f"{label:<{label_width}}"
    return f"{label} {bar} {percent_cell}"


def format_activity_label(progress: Mapping[str, Any]) -> str:
    """Return the compact ACT/SKILL activity or terminal-result label shown below the progress bar."""
    result = str(progress.get("result") or "").upper()
    reason = str(progress.get("reason_code") or "").upper()
    if result:
        return f"{result}: {reason}" if result == "BLOCKED" and reason else result
    operation = str(progress.get("active_operation") or "").strip().upper()
    skill_id = str(progress.get("active_skill_id") or "").strip()
    phase = str(progress.get("phase") or "RUNNING").upper()
    parts = [value for value in (operation, skill_id, phase) if value]
    return " / ".join(parts) if parts else phase
