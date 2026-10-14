"""Evidence-preserving retry preparation for rejected provider task outputs."""

from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from .atomic import atomic_write_json, atomic_write_text
from .errors import SageError, ValidationError
from .hashing import sha256_file

# Validators raise these codes for any malformed field; only the call site knows the cause is provider output.
GENERIC_VALIDATION_CODES = frozenset({"VALIDATION_ERROR", "MEMORY_GOVERNANCE_ERROR"})
PROVIDER_RESPONSES_DIRECTORY = "provider-responses"


@contextmanager
def provider_output_contract(code: str, *, affected_scope: str | None = None) -> Iterator[None]:
    """Re-code generic validator failures so rejected provider output is archived and retried, not resubmitted."""
    try:
        yield
    except SageError as exc:
        if exc.code not in GENERIC_VALIDATION_CODES:
            raise
        raise ValidationError(
            exc.message,
            code=code,
            affected_scope=exc.affected_scope or affected_scope,
            next_action="Retry the same sealed task with corrected provider output.",
            details=exc.details,
        ) from exc


def write_provider_responses(directory: Path, responses: Sequence[str]) -> list[dict[str, Any]]:
    """Persist raw provider responses verbatim, in phase order, replacing any earlier set, and return their hashes."""
    if directory.is_dir():
        shutil.rmtree(directory)
    written: list[dict[str, Any]] = []
    for index, content in enumerate(responses, start=1):
        path = directory / f"response-{index:02d}.txt"
        atomic_write_text(path, content)
        written.append({"phase": index, "path": path.name, "sha256": sha256_file(path)})
    return written


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
        responses_root = validation_root / PROVIDER_RESPONSES_DIRECTORY
        if responses_root.is_dir():
            archived_responses = archived_validation / PROVIDER_RESPONSES_DIRECTORY
            shutil.move(str(responses_root), str(archived_responses))
            for path in sorted(archived_responses.rglob("*")):
                if path.is_file():
                    archived.append(
                        {
                            "path": path.relative_to(attempt_root).as_posix(),
                            "sha256": sha256_file(path),
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


def preserve_failed_provider_responses(
    manifest_path: Path,
    responses: Sequence[str],
    *,
    reason_code: str,
    message: str,
    status: str,
) -> dict[str, Any]:
    """Archive raw provider responses from one failed execution; nothing was materialized, so the task stays open."""
    task_root = manifest_path.parent.resolve()
    attempt = _next_attempt(task_root)
    label = "rejected" if status == "TASK_OUTPUT_REJECTED" else "failed"
    attempt_root = task_root / "attempts" / f"attempt-{attempt:03d}-{label}-{_utc_stamp()}"
    attempt_root.mkdir(parents=True, exist_ok=False)
    written = write_provider_responses(attempt_root / PROVIDER_RESPONSES_DIRECTORY, responses)
    receipt = {
        "schema_version": "1.0",
        "attempt": attempt,
        "status": status,
        "stage": "PROVIDER_EXECUTION",
        "reason_code": str(reason_code).strip().upper(),
        "message": str(message),
        "event_id": None,
        "task_manifest": str(manifest_path),
        "archived_files": [
            {"path": f"{PROVIDER_RESPONSES_DIRECTORY}/{row['path']}", "sha256": row["sha256"]}
            for row in written
        ],
    }
    atomic_write_json(attempt_root / "attempt-receipt.json", receipt)
    return {**receipt, "attempt_path": str(attempt_root)}
