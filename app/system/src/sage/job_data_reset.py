"""Bounded removal of operator-created Job, Run, report, and history data."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .errors import ValidationError
from .storage import storage_layout


def _bounded_target(path: Path, data_root: Path) -> Path:
    """Validate a lexical target below localdata without following its final symlink."""
    root = data_root.resolve()
    target = Path(os.path.abspath(path))
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValidationError(f"Job-data wipe target is outside localdata: {path}") from exc
    if target == root:
        raise ValidationError("Job-data wipe cannot target the localdata root")
    return target


def _remove(path: Path, data_root: Path, removed: list[str]) -> None:
    """Remove one validated Job-data target and record its localdata-relative path."""
    target = _bounded_target(path, data_root)
    if not target.exists() and not target.is_symlink():
        return
    label = target.relative_to(data_root.resolve()).as_posix()
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    else:
        target.unlink(missing_ok=True)
    removed.append(label)


def wipe_all_job_data(sage_root: Path) -> dict[str, Any]:
    """Remove all workflow work while preserving environment and resource configuration."""
    root = sage_root.expanduser().resolve()
    if not (root / "ecosystem.yml").is_file():
        raise ValidationError(f"Not a complete SAGE installation: {root}")
    layout = storage_layout(root, create=True)
    removed: list[str] = []
    targets = (
        layout.jobs_root,
        layout.reports_root,
        layout.exports_root,
        layout.system_root / "jobs",
        layout.workflow_root,
        layout.locks_root,
        layout.transactions_root,
        layout.state_root / "active-jobs.json",
        layout.state_root / "last-run.json",
        layout.state_root / "operator-cues.jsonl",
        layout.state_root / "setup-state.json",
    )
    for target in targets:
        _remove(target, layout.data_root, removed)

    # Recreate only the empty ownership roots. Tool-specific folders are created
    # by the next Job, leaving an unambiguous empty post-wipe state.
    for path in (
        layout.jobs_root,
        layout.reports_root,
        layout.exports_root,
        layout.system_root / "jobs",
        layout.workflow_root,
        layout.locks_root,
        layout.transactions_root,
        layout.state_root,
    ):
        path.mkdir(parents=True, exist_ok=True)

    receipt_path = layout.state_root / "job-data-wipe.json"
    receipt = {
        "schema_version": "1.0",
        "status": "JOB_DATA_WIPED",
        "completed_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "root": str(root),
        "data_root": str(layout.data_root),
        "removed": sorted(set(removed)),
        "preserved": [
            "SAGE Core",
            "managed runtime and virtual environment",
            "Project Inventory and external Project locations",
            "resource mappings and original-language selections",
            "operator, language, grammar, and AI configuration",
            "bundled resources and indexes",
        ],
        "next_action": "Create or select a new BIC, RTC, or STC Job.",
    }
    atomic_write_json(receipt_path, receipt)
    return {**receipt, "receipt_path": str(receipt_path)}
