"""Restore localdata to an explicit, bounded first-run state without modifying Core."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .errors import ValidationError
from .hashing import sha256_file
from .storage import storage_layout


def _remove(path: Path, data_root: Path, removed: list[str]) -> None:
    """Remove one path only when it is governed by this localdata root."""
    if not path.exists() and not path.is_symlink():
        return
    try:
        label = path.resolve().relative_to(data_root.resolve()).as_posix()
    except ValueError as exc:
        raise ValidationError(f"Out-of-box reset target is outside localdata: {path}") from exc
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    removed.append(label)


def reset_to_out_of_box(sage_root: Path) -> dict[str, Any]:
    """Delete explicit local operating data, preserve managed Python, and leave Core byte-identical."""
    root = sage_root.expanduser().resolve()
    settings = root / "ecosystem.yml"
    if not (root / "system" / "config").is_dir() or not settings.is_file():
        raise ValidationError(f"Not a complete SAGE installation: {root}")
    layout = storage_layout(root, create=True)
    before_hash = sha256_file(settings)
    removed: list[str] = []

    # The managed venv is expensive but contains no operator work. Preserve only it;
    # all other installation/operator state is explicitly reset by this command.
    venv = layout.venv_root
    preserved_venv: Path | None = None
    if venv.exists():
        preserved_venv = venv

    for path in (
        layout.inputs_root,
        layout.work_root,
        layout.plugins_root,
        layout.reports_root,
        layout.exports_root,
        layout.config_root,
        layout.state_root,
        layout.indexes_root,
        layout.cache_root,
        layout.locks_root,
        layout.transactions_root,
        layout.logs_root,
        layout.diagnostics_root,
        layout.temp_root,
        layout.workflow_root,
        layout.system_root / "jobs",
    ):
        _remove(path, layout.data_root, removed)

    layout.ensure()
    after_hash = sha256_file(settings)
    if after_hash != before_hash:
        raise ValidationError("Core ecosystem.yml changed during localdata reset", code="CORE_MUTATION_DETECTED")

    receipt_path = layout.state_root / "out-of-box-reset.json"
    receipt = {
        "schema_version": "2.0",
        "status": "OUT_OF_BOX_RESET",
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "data_root": str(layout.data_root),
        "settings_sha256_before": before_hash,
        "settings_sha256_after": after_hash,
        "removed": sorted(set(removed)),
        "preserved": [
            "SAGE Core",
            "localdata/.system/runtime/venv" if preserved_venv is not None else "managed runtime not yet created",
        ],
        "next_action": "Relaunch SAGE to begin first-use Setup.",
    }
    atomic_write_json(receipt_path, receipt)
    return {**receipt, "receipt_path": str(receipt_path)}
