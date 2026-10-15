"""Governed task sealing: write the manifest, ACT.md, and controller record, then make them read-only.

Split from act_tasks.py; the generic and STC task builders both seal through seal_task.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .act_common import _relative
from .atomic import atomic_write_json, atomic_write_text
from .hashing import sha256_file
from .registry import EcosystemConfig
from .state import utc_now


def seal_task(
    config: EcosystemConfig,
    *,
    workflow: str,
    operation: str,
    job_id: str | None,
    run_id: str | None,
    task_root: Path,
    manifest_path: Path,
    manifest: Mapping[str, Any],
    act_path: Path,
    act_text: str,
    allowed_writes: Sequence[str],
) -> dict[str, Any]:
    """Write one task's sealed files and its CREATED control record; return the manifest with their paths."""
    task_id = str(manifest["task_id"])
    atomic_write_json(manifest_path, dict(manifest))
    atomic_write_text(act_path, act_text)
    manifest_sha256 = sha256_file(manifest_path)
    act_sha256 = sha256_file(act_path)
    control_path = config.workflow(workflow).state_root / "act-tasks" / f"{task_id}.json"
    control = {
        "schema_version": "2.0",
        "task_id": task_id,
        "workflow": workflow,
        "operation": operation,
        "job_id": job_id,
        "run_id": run_id,
        "task_root": _relative(config.root, task_root),
        "manifest_path": _relative(config.root, manifest_path),
        "manifest_sha256": manifest_sha256,
        "act_path": _relative(config.root, act_path),
        "act_sha256": act_sha256,
        "task_fingerprint": manifest["task_fingerprint"],
        "settings_sha256": sha256_file(config.settings_path),
        "allowed_writes": list(allowed_writes),
        "status": "CREATED",
        "created_utc": utc_now(),
    }
    atomic_write_json(control_path, control)
    for immutable in (manifest_path, act_path, control_path):
        try:
            os.chmod(immutable, 0o444)
        except OSError:
            pass
    return {
        **manifest,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "control_path": str(control_path),
        "act_path": str(act_path),
        "act_sha256": act_sha256,
    }
