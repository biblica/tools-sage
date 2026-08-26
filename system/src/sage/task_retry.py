"""Evidence-preserving retry preparation for rejected provider task outputs."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .hashing import sha256_file


def _utc_stamp() -> str:
    """Return a path-safe UTC timestamp for one task attempt archive."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _next_attempt(task_root: Path) -> int:
    """Return the next monotonically increasing rejected-attempt number."""
    root = task_root / "attempts"
    numbers: list[int] = []
    if root.is_dir():
        for path in root.iterdir():
            if not path.is_dir() or not path.name.startswith("attempt-"):
                continue
            try:
                numbers.append(int(path.name.split("-", 2)[1]))
            except (ValueError, IndexError):
                continue
    return max(numbers, default=0) + 1


def archive_rejected_task_output(
    manifest_path: Path,
    *,
    reason_code: str,
    message: str,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Archive rejected outputs/validation evidence and reset the sealed task for a same-task retry."""
    task_root = manifest_path.parent.resolve()
    attempt = _next_attempt(task_root)
    attempt_root = task_root / "attempts" / f"attempt-{attempt:03d}-rejected-{_utc_stamp()}"
    attempt_root.mkdir(parents=True, exist_ok=False)
    archived: list[dict[str, Any]] = []

    output_root = task_root / "output"
    if output_root.is_dir():
        archived_output = attempt_root / "output"
        shutil.move(str(output_root), str(archived_output))
        output_root.mkdir(parents=True, exist_ok=True)
        for path in sorted(archived_output.rglob("*")):
            if path.is_file():
                archived.append(
                    {
                        "path": path.relative_to(attempt_root).as_posix(),
                        "sha256": sha256_file(path),
                    }
                )

    validation_root = task_root / "validation"
    archived_validation = attempt_root / "validation"
    if validation_root.is_dir():
        archived_validation.mkdir(parents=True, exist_ok=True)
        for name in (
            "llm-execution-receipt.json",
            "normalized-findings.json",
            "actions.json",
            "ACTION-REPORT.md",
            "OPERATOR-NOTE-TEXT.txt",
            "normalized-translation-challenges.json",
            "translation-challenge-ledger.json",
            "TRANSLATION-CHALLENGES.md",
        ):
            source = validation_root / name
            if source.is_file():
                destination = archived_validation / name
                shutil.move(str(source), str(destination))
                archived.append(
                    {
                        "path": destination.relative_to(attempt_root).as_posix(),
                        "sha256": sha256_file(destination),
                    }
                )

    receipt = {
        "schema_version": "1.0",
        "attempt": attempt,
        "status": "TASK_OUTPUT_REJECTED",
        "reason_code": str(reason_code).strip().upper(),
        "message": str(message),
        "event_id": event_id,
        "task_manifest": str(manifest_path),
        "archived_files": archived,
    }
    atomic_write_json(attempt_root / "attempt-receipt.json", receipt)
    return {**receipt, "attempt_path": str(attempt_root)}
