"""Capture mutable imported WIP data and seal immutable Run evidence."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .errors import ValidationError
from .generations import project_validation_fingerprint
from .registry import load_ecosystem
from .scripture import compile_project

READY_PROJECT_STATES = frozenset({"READY", "READY_WITH_WARNINGS"})


def _normalized_import_time(imported_at: datetime | None) -> datetime:
    """Return an aware timestamp for one imported WIP snapshot."""
    value = imported_at or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(
            "WIP import timestamp must include a timezone.",
            code="INVALID_WIP_IMPORT_TIME",
        )
    return value


def _require_new_destination(destination: Path) -> Path:
    """Resolve and validate an unused snapshot destination."""
    value = destination.resolve()
    if value.exists():
        raise ValidationError(
            f"Snapshot destination already exists: {value}",
            code="SNAPSHOT_DESTINATION_EXISTS",
        )
    return value


def capture_wip_snapshot(
    sage_root: Path,
    *,
    settings_path: Path,
    project_id: str,
    destination: Path,
    imported_at: datetime | None = None,
) -> dict[str, Any]:
    """Compile and copy one registered WIP Project into Job-owned USJ evidence."""
    root = sage_root.resolve()
    output = _require_new_destination(destination)
    imported = _normalized_import_time(imported_at)
    imported_utc = imported.astimezone(timezone.utc).replace(microsecond=0)
    config = load_ecosystem(settings_path.resolve())
    if config.root != root:
        raise ValidationError(
            f"Snapshot settings resolve to {config.root}, not requested SAGE root {root}.",
            code="SNAPSHOT_WORKSPACE_MISMATCH",
        )
    project = config.project(project_id)
    compiled = compile_project(config, project)
    status = str(compiled.get("status", ""))
    if status not in READY_PROJECT_STATES:
        raise ValidationError(
            f"WIP Project {project_id} cannot be snapshotted: {status or 'UNKNOWN'}",
            code="WIP_SNAPSHOT_IMPORT_FAILED",
            affected_scope=project_id,
            next_action="Correct the reported Project resource issues, then refresh the Job snapshot.",
            details={"issues": list(compiled.get("issues", []))},
        )

    file_entries = list(compiled.get("files", []))
    books = sorted(str(item.get("book", "")).strip().upper() for item in file_entries)
    if not books or any(not book for book in books):
        raise ValidationError(
            f"WIP Project {project_id} produced no complete Book cache set.",
            code="WIP_SNAPSHOT_EMPTY",
            affected_scope=project_id,
        )

    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "project_id": project_id,
        "snapshot_date": imported.astimezone().strftime("%Y%m%d"),
        "imported_utc": imported_utc.isoformat(),
        "content_fingerprint": project_validation_fingerprint(compiled),
        "resource_sha256": str(compiled.get("resource_sha256", "")),
        "compiled_files_sha256": str(compiled.get("compiled_files_sha256", "")),
        "books": books,
        "atomic_coordinates": int(compiled.get("summary", {}).get("atomic_coordinates", 0)),
        "source_location": str(project.path),
        "project_status": status,
        "warnings": list(compiled.get("warnings", [])),
    }

    try:
        usj_root = output / "usj"
        usj_root.mkdir(parents=True)
        for entry in file_entries:
            book = str(entry["book"]).strip().upper()
            cache = Path(str(entry["cache"])).resolve()
            if not cache.is_file():
                raise ValidationError(
                    f"Compiled USJ cache is missing for WIP Project {project_id}: {cache}",
                    code="WIP_SNAPSHOT_CACHE_MISSING",
                    affected_scope=book,
                )
            shutil.copy2(cache, usj_root / f"{book}.json")
        atomic_write_json(output / "SNAPSHOT.json", receipt)
    except Exception:
        if output.exists():
            shutil.rmtree(output)
        raise
    return receipt


def seal_run_snapshot(
    job_snapshot_root: Path,
    destination: Path,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Copy a Job's current WIP snapshot into Run-owned immutable evidence."""
    source = job_snapshot_root.resolve()
    output = _require_new_destination(destination)
    receipt_path = source / "SNAPSHOT.json"
    usj_root = source / "usj"
    if not receipt_path.is_file() or not usj_root.is_dir():
        raise ValidationError(
            f"Job WIP snapshot is incomplete: {source}",
            code="JOB_SNAPSHOT_INCOMPLETE",
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(
            f"Job WIP snapshot receipt is invalid: {receipt_path}",
            code="JOB_SNAPSHOT_RECEIPT_INVALID",
        ) from exc
    if not isinstance(receipt, dict):
        raise ValidationError(
            f"Job WIP snapshot receipt must be a mapping: {receipt_path}",
            code="JOB_SNAPSHOT_RECEIPT_INVALID",
        )

    sealed = dict(receipt)
    sealed["run_id"] = str(run_id)
    sealed["sealed_from_snapshot_date"] = str(receipt.get("snapshot_date", ""))
    sealed["sealed_utc"] = datetime.now(timezone.utc).isoformat()
    try:
        shutil.copytree(usj_root, output / "usj")
        atomic_write_json(output / "SNAPSHOT.json", sealed)
    except Exception:
        if output.exists():
            shutil.rmtree(output)
        raise
    return sealed
