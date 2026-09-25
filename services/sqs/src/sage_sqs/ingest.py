"""Qualification-submission intake: stage admin-run results for explicit ADMIN review.

Submissions arrive as files dropped into the incoming/ directory over SSH/SCP by a
trusted, SSH-key-authenticated operator machine (a SAGE host run by an ADMIN).
Ingest never writes into qualifications directly -- it only stages a
QUALIFICATION_SUBMISSION attention item; publishing a submitted result requires a
separate, explicit ADMIN review decision (see admin.py's review_qualification_submission).
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from .db import Database
from .domain import Qualification
from .repository import Repository

_SCHEMA_ID = "sage-sqs-qualification-submission-1.0"
_TOP_LEVEL_FIELDS = {"schema", "run_id", "submitted_by", "submitted_at", "qualification", "attempt"}
_QUALIFICATION_FIELDS = {field.name for field in fields(Qualification)}
_ATTEMPT_FIELDS = {
    "minimum_reasoning", "quality_score", "reliability_score",
    "total_input_tokens", "total_output_tokens", "estimated_unit_cost_usd", "reasoning_runs",
}


class SubmissionValidationError(ValueError):
    pass


def validate_submission(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_FIELDS:
        raise SubmissionValidationError("INVALID_SUBMISSION")
    if payload.get("schema") != _SCHEMA_ID:
        raise SubmissionValidationError("INVALID_SUBMISSION")
    if not str(payload.get("run_id") or ""):
        raise SubmissionValidationError("INVALID_SUBMISSION")
    if not str(payload.get("submitted_by") or ""):
        raise SubmissionValidationError("INVALID_SUBMISSION")
    if not str(payload.get("submitted_at") or ""):
        raise SubmissionValidationError("INVALID_SUBMISSION")
    qualification = payload.get("qualification")
    if not isinstance(qualification, dict) or set(qualification) != _QUALIFICATION_FIELDS:
        raise SubmissionValidationError("INVALID_SUBMISSION")
    attempt = payload.get("attempt")
    if not isinstance(attempt, dict) or set(attempt) != _ATTEMPT_FIELDS:
        raise SubmissionValidationError("INVALID_SUBMISSION")
    return dict(payload)


@dataclass(frozen=True)
class SubmissionReceipt:
    run_id: str
    attention_key: str
    status: str = "STAGED_FOR_REVIEW"


def stage_submission(repo: Repository, payload: Any) -> SubmissionReceipt:
    value = validate_submission(payload)
    run_id = str(value["run_id"])
    run = repo.evaluation_run(run_id)
    if run is None:
        raise SubmissionValidationError("UNKNOWN_RUN")
    if run["status"] != "PENDING":
        raise SubmissionValidationError("RUN_NOT_PENDING")
    qualification = value["qualification"]
    expected = (run.get("profile_id"), run.get("model_id"), run.get("capability"))
    submitted = (qualification["profile_id"], qualification["model_id"], qualification["capability"])
    if submitted != expected:
        raise SubmissionValidationError("SUBMISSION_DOES_NOT_MATCH_RUN")
    attention_key = f"QUALIFICATION_SUBMISSION:{run_id}"
    repo.upsert_attention(
        attention_key=attention_key,
        category="QUALIFICATION_SUBMISSION",
        severity="INFO",
        summary=(
            f"Submitted {qualification['status']} result for "
            f"{qualification['model_id']} / {qualification['profile_id']} / {qualification['capability']}"
        ),
        payload=value,
    )
    return SubmissionReceipt(run_id=run_id, attention_key=attention_key)


def ingest_incoming_directory(repo: Repository, *, incoming_dir: Path, processed_dir: Path, rejected_dir: Path) -> list[dict[str, Any]]:
    incoming_dir = Path(incoming_dir)
    processed_dir = Path(processed_dir)
    rejected_dir = Path(rejected_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)
    outcomes: list[dict[str, Any]] = []
    for path in sorted(incoming_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            receipt = stage_submission(repo, payload)
            os.replace(path, processed_dir / path.name)
            outcomes.append({
                "file": path.name, "status": "STAGED",
                "run_id": receipt.run_id, "attention_key": receipt.attention_key,
            })
        except (SubmissionValidationError, json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            # OSError included deliberately: this is an unattended, timer-driven batch
            # (see the module docstring) -- one unreadable or mid-transfer file (a
            # permission mismatch after SCP, or a concurrent scan racing a delete)
            # must never abort the whole run and lose every outcome already recorded.
            try:
                os.replace(path, rejected_dir / path.name)
            except OSError:
                pass
            outcomes.append({"file": path.name, "status": "REJECTED", "reason": str(exc)})
    return outcomes


def drain(repo: Repository, *, incoming_dir: Path | None = None, processed_dir: Path | None = None, rejected_dir: Path | None = None) -> int:
    base = Path(os.environ.get("SQS_INCOMING_DIR", "/var/lib/sage-sqs/incoming"))
    incoming_dir = incoming_dir if incoming_dir is not None else base
    processed_dir = processed_dir if processed_dir is not None else base.parent / "incoming-processed"
    rejected_dir = rejected_dir if rejected_dir is not None else base.parent / "incoming-rejected"
    ingest_incoming_directory(repo, incoming_dir=incoming_dir, processed_dir=processed_dir, rejected_dir=rejected_dir)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drain", action="store_true", required=True)
    parser.parse_args()
    repo = Repository(Database.open(Path(os.environ.get("SQS_DB_PATH", "/var/lib/sage-sqs/sqs.db"))))
    return drain(repo)
