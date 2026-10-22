"""Capture mutable imported WIP data and seal immutable Run evidence."""

from __future__ import annotations

import json
import hashlib
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .errors import ValidationError
from .generations import project_validation_fingerprint
from .registry import load_ecosystem
from .scripture import compile_project, issue_chapters

READY_PROJECT_STATES = frozenset({"READY", "READY_WITH_WARNINGS"})
SNAPSHOT_WITH_EXCEPTIONS = "READY_WITH_EXCEPTIONS"
BOOK_LEFT_OUT = "BOOK_LEFT_OUT"
CHAPTER_NOT_ASSESSED = "CHAPTER_NOT_ASSESSED"


def _snapshot_exceptions(compiled: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    """Turn compile issues into snapshot exception rows and the set of books to leave out.

    A defect located in chapters stays in the snapshot: each Run leaves those chapters out and reports them
    not assessed. A defect no chapter owns (book header, missing book ID, duplicate book, undecodable file)
    leaves the whole book out of the snapshot.
    """
    book_by_file = {
        str(entry.get("source", "")): str(entry.get("book", "")).strip().upper()
        for entry in compiled.get("files", [])
    }
    rows: list[dict[str, Any]] = []
    left_out: set[str] = set()
    for issue in compiled.get("issues", []):
        file_value = str(issue.get("file", ""))
        book = book_by_file.get(file_value) or str(issue.get("reference", "")).split(" ")[0].strip().upper()
        chapters = issue_chapters(issue, book) if book else None
        if not chapters:
            left_out.add(book)
        rows.append(
            {
                "code": str(issue.get("code") or "UNKNOWN"),
                "reference": str(issue.get("reference") or book),
                "message": str(issue.get("message") or ""),
                "file": Path(file_value).name if file_value else "",
                "book": book,
                "effect": CHAPTER_NOT_ASSESSED if chapters else BOOK_LEFT_OUT,
                "chapters": sorted(chapters or ()),
            }
        )
    # A book left out for one defect takes its located defects with it.
    for row in rows:
        if row["book"] in left_out:
            row["effect"] = BOOK_LEFT_OUT
    return rows, left_out


def _snapshot_inventory(snapshot_root: Path) -> tuple[dict[str, str], str]:
    """Hash every regular USJ file and return one canonical inventory identity."""
    root = snapshot_root.resolve()
    usj_root = root / "usj"
    if not usj_root.is_dir() or usj_root.is_symlink():
        raise ValidationError("WIP snapshot USJ evidence is missing", code="NCA_WIP_SNAPSHOT_STALE")
    files: dict[str, str] = {}
    for path in sorted(usj_root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            raise ValidationError("WIP snapshot contains an unsafe entry", code="NCA_WIP_SNAPSHOT_STALE")
        relative = path.relative_to(root).as_posix()
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not files:
        raise ValidationError("WIP snapshot contains no USJ evidence", code="NCA_WIP_SNAPSHOT_STALE")
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return files, hashlib.sha256(payload).hexdigest()


def verify_wip_snapshot(
    snapshot_root: Path,
    *,
    require_file_inventory: bool = False,
) -> dict[str, Any]:
    """Verify receipt identity and every sealed USJ byte in one WIP snapshot."""
    root = snapshot_root.resolve()
    receipt_path = root / "SNAPSHOT.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("WIP snapshot receipt is invalid", code="NCA_WIP_SNAPSHOT_STALE") from exc
    if not isinstance(receipt, dict):
        raise ValidationError("WIP snapshot receipt must be a mapping", code="NCA_WIP_SNAPSHOT_STALE")
    files, inventory_sha256 = _snapshot_inventory(root)
    recorded_files = receipt.get("files")
    recorded_inventory = receipt.get("inventory_sha256")
    if recorded_files is None and recorded_inventory is None and not require_file_inventory:
        return receipt
    if recorded_files != files or recorded_inventory != inventory_sha256:
        raise ValidationError(
            "WIP snapshot byte inventory differs from its sealed receipt",
            code="NCA_WIP_SNAPSHOT_STALE",
            details={"snapshot_root": str(root)},
        )
    return receipt


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
    # Inventory records remain role-neutral and disabled until a Job binds them.
    # Snapshot capture is itself that governed WIP binding, so compile an enabled
    # view without rewriting the operator-owned Project record.
    project = replace(config.project(project_id), enabled=True)
    compiled = compile_project(config, project)
    status = str(compiled.get("status", ""))
    file_entries = list(compiled.get("files", []))
    if status not in READY_PROJECT_STATES and not file_entries:
        # Nothing compiled at all (missing root, no Scripture files, filename settings): a configuration
        # problem the Operator must fix, not a content defect a Run can report around.
        raise ValidationError(
            f"WIP Project {project_id} cannot be snapshotted: {status or 'UNKNOWN'}",
            code="WIP_SNAPSHOT_IMPORT_FAILED",
            affected_scope=project_id,
            next_action="Correct the reported Project resource issues, then refresh the Job snapshot.",
            details={
                "issues": list(compiled.get("issues", [])),
                "filename_validation": dict(compiled.get("filename_validation", {})),
            },
        )

    exceptions, left_out = _snapshot_exceptions(compiled)
    file_entries = [
        entry for entry in file_entries if str(entry.get("book", "")).strip().upper() not in left_out
    ]
    books = sorted(str(item.get("book", "")).strip().upper() for item in file_entries)
    if not books or any(not book for book in books):
        raise ValidationError(
            f"WIP Project {project_id} produced no complete Book cache set.",
            code="WIP_SNAPSHOT_EMPTY",
            affected_scope=project_id,
            next_action="Correct the reported book defects, then refresh the Job snapshot.",
            details={"exceptions": exceptions},
        )

    receipt: dict[str, Any] = {
        "schema_version": "1.0",
        "project_id": project_id,
        "snapshot_date": imported.astimezone(timezone.utc).strftime("%Y%m%d"),
        "imported_utc": imported_utc.isoformat(),
        "content_fingerprint": project_validation_fingerprint(compiled),
        "resource_sha256": str(compiled.get("resource_sha256", "")),
        "compiled_files_sha256": str(compiled.get("compiled_files_sha256", "")),
        "books": books,
        "atomic_coordinates": sum(int(entry.get("atomic_coordinates", 0)) for entry in file_entries),
        "source_location": str(project.path),
        "project_status": SNAPSHOT_WITH_EXCEPTIONS if exceptions else status,
        "warnings": list(compiled.get("warnings", [])),
        "filename_validation": dict(compiled.get("filename_validation", {})),
        "exceptions": exceptions,
        "left_out_books": sorted(left_out),
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
        files, inventory_sha256 = _snapshot_inventory(output)
        receipt["files"] = files
        receipt["inventory_sha256"] = inventory_sha256
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
    require_file_inventory: bool = False,
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
    receipt = verify_wip_snapshot(source, require_file_inventory=require_file_inventory)

    sealed = dict(receipt)
    sealed["run_id"] = str(run_id)
    sealed["sealed_from_snapshot_date"] = str(receipt.get("snapshot_date", ""))
    sealed["sealed_utc"] = datetime.now(timezone.utc).isoformat()
    try:
        shutil.copytree(usj_root, output / "usj")
        atomic_write_json(output / "SNAPSHOT.json", sealed)
        verify_wip_snapshot(output, require_file_inventory=require_file_inventory)
    except Exception:
        if output.exists():
            shutil.rmtree(output)
        raise
    return sealed
