"""Job/run-scoped runtime path helpers for governed SAGE tasks."""

from __future__ import annotations

import re
from pathlib import Path

from .errors import ValidationError
from .registry import EcosystemConfig, WorkflowSpec

_SAFE_CONTEXT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")


def validate_context_id(value: str | None, label: str) -> str | None:
    """Validate one optional Job/Run identifier used in governed paths."""
    if value in (None, ""):
        return None
    normalized = str(value).strip()
    if not _SAFE_CONTEXT_ID.fullmatch(normalized):
        raise ValidationError(
            f"{label} must start with an alphanumeric character and use only letters, "
            "digits, dot, underscore, or hyphen"
        )
    return normalized


def task_container(workflow: WorkflowSpec, run_id: str | None = None) -> Path:
    """Return the directory that owns immutable tasks for one optional Run."""
    run = validate_context_id(run_id, "run_id")
    if run is None:
        return workflow.output_root / "active"
    return workflow.output_root / "runs" / run / "tasks"


def plan_container(workflow: WorkflowSpec, run_id: str | None = None) -> Path:
    """Return the directory that owns work-unit plans for one optional Run."""
    run = validate_context_id(run_id, "run_id")
    if run is None:
        return workflow.output_root / "plans"
    return workflow.output_root / "runs" / run / "plans"


def run_root(workflow: WorkflowSpec, run_id: str) -> Path:
    """Return the governed root for one Job-scoped Run."""
    run = validate_context_id(run_id, "run_id")
    assert run is not None
    return workflow.output_root / "runs" / run


def _scoped_tree_is_governed(root: Path, leaf: str, value: Path) -> bool:
    """Return whether a path belongs to one governed Run subtree of the requested kind."""
    try:
        relative = value.relative_to((root / "runs").resolve())
    except ValueError:
        return False
    return len(relative.parts) >= 3 and relative.parts[1] == leaf


def task_is_governed(workflow: WorkflowSpec, task_root: Path) -> bool:
    """Return whether a task is in the governed active or Run task tree."""
    resolved = task_root.resolve()
    try:
        resolved.relative_to((workflow.output_root / "active").resolve())
        return True
    except ValueError:
        return _scoped_tree_is_governed(workflow.output_root, "tasks", resolved)


def plan_is_governed(workflow: WorkflowSpec, plan_path: Path) -> bool:
    """Return whether a plan is in the governed global or Run plan tree."""
    resolved = plan_path.resolve()
    try:
        resolved.relative_to((workflow.output_root / "plans").resolve())
        return True
    except ValueError:
        return _scoped_tree_is_governed(workflow.output_root, "plans", resolved)


def infer_run_id(workflow: WorkflowSpec, path: Path) -> str | None:
    """Return a Run ID from a Run path, when present."""
    try:
        relative = path.resolve().relative_to((workflow.output_root / "runs").resolve())
    except ValueError:
        return None
    if len(relative.parts) >= 2:
        return validate_context_id(relative.parts[0], "run_id")
    return None


def workflow_for_task(config: EcosystemConfig, task_root: Path) -> str:
    """Resolve exactly one workflow owner for a governed task."""
    matches = [
        workflow_id
        for workflow_id, workflow in config.workflows.items()
        if task_is_governed(workflow, task_root)
    ]
    if len(matches) != 1:
        raise ValidationError("ACT task is not inside exactly one governed workflow task directory")
    return matches[0]


def workflow_memory_root(workflow: WorkflowSpec) -> Path:
    """Return the explicit BIC memory root or the default governed location."""
    return workflow.memory_root or (workflow.state_root.parent / "memory")
