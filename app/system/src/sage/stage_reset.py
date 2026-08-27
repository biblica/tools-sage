"""Governed stage-specific runtime reset without cross-workflow deletion."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .bic_memory import eligible_memory_records
from .errors import ValidationError
from .locking import WorkspaceLock
from .registry import EcosystemConfig
from .runtime_paths import workflow_memory_root
from .state import utc_now
from .transactions import FileTransaction, incomplete_transactions

STAGES: dict[str, tuple[str, ...]] = {
    "bic": ("inspect", "rewrite", "self_check"),
    "saw": ("qa", "focused", "ol"),
}
_BIC_DOWNSTREAM = {
    "inspect": {"rewrite", "self_check"},
    "rewrite": {"self_check"},
    "self_check": set(),
}


def _read_json(path: Path) -> dict[str, Any]:
    """Read one JSON object and reject malformed governed state."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid governed JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"Governed JSON must contain one object: {path}")
    return dict(value)


def _read_list(path: Path) -> list[dict[str, Any]]:
    """Read one governed JSON list, returning an empty list only when absent."""
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid governed JSON list {path}: {exc}") from exc
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValidationError(f"Governed JSON must contain a list of objects: {path}")
    return [dict(row) for row in value]


def _inside(path: Path, root: Path, label: str) -> Path:
    """Resolve one deletion target and require it to remain in its governed root."""
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValidationError(
            f"Stage reset target escapes the governed {label} root: {resolved}",
            code="STAGE_RESET_BOUNDARY_VIOLATION",
        ) from exc
    return resolved


def _task_controls(config: EcosystemConfig, workflow_id: str) -> list[tuple[Path, dict[str, Any]]]:
    """Load all task controls owned by one workflow only."""
    workflow = config.workflow(workflow_id)
    controls_root = workflow.state_root / "act-tasks"
    rows: list[tuple[Path, dict[str, Any]]] = []
    if not controls_root.exists():
        return rows
    for path in sorted(controls_root.glob("*.json")):
        control = _read_json(path)
        if str(control.get("workflow", "")).lower() != workflow_id:
            raise ValidationError(
                f"Task control in {workflow_id} state root claims another workflow: {path}",
                code="STAGE_RESET_BOUNDARY_VIOLATION",
            )
        rows.append((path, control))
    return rows


def _remove(path: Path, removed: list[str], root: Path) -> None:
    """Remove one prevalidated generated path and record its localdata-relative name."""
    if not path.exists() and not path.is_symlink():
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    removed.append(path.resolve().relative_to(root.resolve()).as_posix())


def _reset_inspect_memory(
    config: EcosystemConfig,
    task_ids: set[str],
) -> dict[str, Any]:
    """Remove only unapproved INSPECT governance rows belonging to reset task IDs."""
    if not task_ids:
        return {"operations": 0, "proposals": 0, "challenges": 0, "reviews": 0}
    workflow = config.workflow("bic")
    memory_root = workflow_memory_root(workflow)
    proposals_path = memory_root / "inspect-proposals.json"
    challenges_path = memory_root / "translation-challenges.json"
    operations_path = memory_root / "inspect-operations.json"
    reviews_path = memory_root / "human-review-receipts.json"
    approved_path = memory_root / "approved-memory.json"
    proposals = _read_list(proposals_path)
    challenges = _read_list(challenges_path)
    operations = _read_list(operations_path)
    reviews = _read_list(reviews_path)

    selected = [row for row in proposals if str(row.get("operation_id")) in task_ids]
    protected = [
        row
        for row in selected
        if str(row.get("memory_state", "PROPOSED")).upper() not in {"PROPOSED", "INACTIVE"}
    ]
    if protected:
        identities = sorted(
            str(row.get("proposal_id") or row.get("record_id") or "UNKNOWN")
            for row in protected
        )
        raise ValidationError(
            "INSPECT stage reset cannot delete reviewed or approved memory records: "
            + ", ".join(identities),
            code="STAGE_RESET_GOVERNANCE_BLOCKED",
            next_action=(
                "Use governed memory transitions to deactivate protected records, then retry the "
                "INSPECT reset."
            ),
        )

    remaining_proposals = [row for row in proposals if str(row.get("operation_id")) not in task_ids]
    remaining_challenges = [row for row in challenges if str(row.get("operation_id")) not in task_ids]
    remaining_operations = [row for row in operations if str(row.get("operation_id")) not in task_ids]
    remaining_reviews = [row for row in reviews if str(row.get("operation_id")) not in task_ids]
    approved = [
        row
        for row in eligible_memory_records(remaining_proposals)
        if str((row.get("provenance") or {}).get("submission_source", "")).upper() == "BIC_INSPECT"
    ]
    transaction = FileTransaction(
        workflow.transaction_root,
        operation="BIC_INSPECT_STAGE_RESET",
        allowed_roots=(memory_root,),
    )
    transaction.stage_json(proposals_path, remaining_proposals)
    transaction.stage_json(challenges_path, remaining_challenges)
    transaction.stage_json(operations_path, remaining_operations)
    transaction.stage_json(reviews_path, remaining_reviews)
    transaction.stage_json(approved_path, sorted(approved, key=lambda row: str(row.get("proposal_id", ""))))
    transaction.commit()
    return {
        "operations": len(operations) - len(remaining_operations),
        "proposals": len(proposals) - len(remaining_proposals),
        "challenges": len(challenges) - len(remaining_challenges),
        "reviews": len(reviews) - len(remaining_reviews),
        "transaction_id": transaction.transaction_id,
    }


def reset_workflow_stage(
    config: EcosystemConfig,
    *,
    workflow_id: str,
    stage: str,
    operator: str,
    decision_id: str,
    notes: str = "",
) -> dict[str, Any]:
    """Reset generated state for exactly one workflow stage and no other boundary."""
    workflow_key = workflow_id.strip().lower()
    stage_key = stage.strip().lower().replace("-", "_")
    if workflow_key not in STAGES:
        raise ValidationError(f"Unsupported workflow for stage reset: {workflow_id}")
    if stage_key not in STAGES[workflow_key]:
        allowed = ", ".join(value.replace("_", "-") for value in STAGES[workflow_key])
        raise ValidationError(
            f"Unsupported {workflow_key.upper()} reset stage {stage!r}; expected one of: {allowed}"
        )
    operator_id = operator.strip()
    decision = decision_id.strip()
    if not operator_id or not decision:
        raise ValidationError("Stage reset requires nonempty operator and decision ID")
    workflow = config.workflow(workflow_key)
    pending = incomplete_transactions(workflow.transaction_root)
    if pending:
        raise ValidationError(
            f"{workflow_key.upper()} has incomplete transactions; stage reset is blocked",
            code="STAGE_RESET_PENDING_TRANSACTION",
            next_action="Recover or resolve listed workflow transactions before resetting a stage.",
            details={"transactions": [str(path) for path in pending]},
        )

    lock_path = workflow.lock_root / "stage-reset.lock"
    with WorkspaceLock(lock_path, f"{workflow_key.upper()}_STAGE_RESET"):
        receipt_path = workflow.state_root / "stage-resets" / f"{decision}.json"
        if receipt_path.exists():
            raise ValidationError(
                f"Stage reset decision ID is already recorded: {decision}",
                code="STAGE_RESET_DECISION_ALREADY_RECORDED",
            )
        controls = _task_controls(config, workflow_key)
        if workflow_key == "bic":
            downstream = _BIC_DOWNSTREAM[stage_key]
            blockers = [
                str(control.get("task_id"))
                for _, control in controls
                if str(control.get("operation", "")).lower() in downstream
            ]
            if blockers:
                raise ValidationError(
                    f"BIC {stage_key.replace('_', '-')} reset is blocked by downstream tasks",
                    code="STAGE_RESET_DOWNSTREAM_EXISTS",
                    next_action="Reset downstream BIC stages first.",
                    details={"blocking_task_ids": sorted(blockers)},
                )

        selected = [
            (path, control)
            for path, control in controls
            if str(control.get("operation", "")).lower() == stage_key
        ]
        task_ids = {str(control.get("task_id")) for _, control in selected}
        task_roots = [
            _inside(Path(str(control.get("task_root", ""))), workflow.output_root / "active", "task output")
            for _, control in selected
        ]
        control_paths = [
            _inside(path, workflow.state_root / "act-tasks", "task-control")
            for path, _ in selected
        ]

        plan_paths: list[Path] = []
        plans_root = workflow.output_root / "plans"
        if plans_root.exists():
            for plan_path in sorted(plans_root.glob("*.json")):
                if plan_path.name.endswith("-aggregate.json"):
                    continue
                plan = _read_json(plan_path)
                if (
                    str(plan.get("workflow", "")).lower() == workflow_key
                    and str(plan.get("operation", "")).lower() == stage_key
                ):
                    plan_paths.append(_inside(plan_path, plans_root, "plan"))
                    aggregate_path = plan_path.with_name(f"{plan.get('plan_id')}-aggregate.json")
                    report_path = plan_path.with_name(f"{plan.get('plan_id')}-aggregate.md")
                    for related in (aggregate_path, report_path):
                        if related.exists():
                            plan_paths.append(_inside(related, plans_root, "plan"))

        memory_reset: dict[str, Any] | None = None
        if workflow_key == "bic" and stage_key == "inspect":
            memory_reset = _reset_inspect_memory(config, task_ids)

        removed: list[str] = []
        for path in task_roots + control_paths + plan_paths:
            _remove(path, removed, config.data_root)
        receipt = {
            "schema_version": "1.0",
            "status": "RESET",
            "workflow": workflow_key,
            "stage": stage_key,
            "operator": operator_id,
            "decision_id": decision,
            "notes": notes.strip(),
            "task_ids": sorted(task_ids),
            "removed": sorted(set(removed)),
            "memory_reset": memory_reset,
            "recorded_utc": utc_now(),
        }
        atomic_write_json(receipt_path, receipt)
    return {**receipt, "receipt_path": str(receipt_path)}
