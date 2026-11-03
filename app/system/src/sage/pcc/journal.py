"""Append-only PCC decision journal (handover doc 04, plan §5 A5).

The journal is the only place Operator and team decisions live: rendering choices from the terms
list, sense reclassifications, and later finding decisions. Events are never edited or removed; a
reversal is a new event. Each event names the event before it (``previous_event_id``), so a
truncated, reordered or edited journal fails closed on read. The materialized view is rebuilt from
events and never stored as the source of truth.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..errors import ValidationError
from ..locking import WorkspaceLock
from ..state import append_event
from .contracts import SCHEMA_VERSION, validate_record
from .ids import full_digest, make_id
from .jsonl import read_jsonl

JOURNAL_DIRECTORY = "glossary"
JOURNAL_FILE = "review-journal.jsonl"
POLICY_VERSION = "pcc-decisions-1"


def journal_path(job_root: Path) -> Path:
    """Return the Job's decision journal path."""
    return job_root / JOURNAL_DIRECTORY / JOURNAL_FILE


def read_journal(job_root: Path) -> list[dict[str, Any]]:
    """Read and verify the whole journal; an absent journal is an empty one."""
    path = journal_path(job_root)
    if not path.is_file():
        return []
    events = read_jsonl(path, kind="review_event")
    previous: str | None = None
    seen: set[str] = set()
    for index, event in enumerate(events, 1):
        if event["previous_event_id"] != previous:
            raise ValidationError(
                f"PCC decision journal chain is broken at event {index}",
                code="PCC_JOURNAL_CHAIN_BROKEN",
                details={"path": str(path), "event": index, "event_id": event["event_id"]},
            )
        if event["event_id"] in seen or event["event_id"] != _event_id(event):
            raise ValidationError(
                f"PCC decision journal event {index} has an invalid identity",
                code="PCC_JOURNAL_EVENT_INVALID",
                details={"path": str(path), "event": index, "event_id": event["event_id"]},
            )
        seen.add(event["event_id"])
        previous = event["event_id"]
    return events


def _event_id(event: Mapping[str, Any]) -> str:
    """Return the deterministic ID of one event from every field except the ID itself."""
    return make_id("event", {key: value for key, value in event.items() if key != "event_id"})


def append_review_event(
    job_root: Path,
    *,
    lock_path: Path,
    actor_id: str,
    operation: str,
    subject_type: str,
    subject_id: str,
    rationale: str,
    scope: Mapping[str, str],
    job_id: str,
    source_corpus_sha256: str,
    target_language: str,
    evidence_refs: Iterable[str] = (),
    before_hash: str | None = None,
    after_hash: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate, chain and durably append one decision event; return the stored event."""
    with WorkspaceLock(lock_path, "PCC_JOURNAL_APPEND"):
        events = read_journal(job_root)
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        event: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "time_utc": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "actor_id": actor_id,
            "operation": operation,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "rationale": rationale,
            "before_hash": before_hash,
            "after_hash": after_hash,
            "evidence_refs": sorted(set(evidence_refs)),
            "job_id": job_id,
            "source_corpus_sha256": source_corpus_sha256,
            "target_language": target_language,
            "policy_version": POLICY_VERSION,
            "scope": dict(scope),
            "previous_event_id": events[-1]["event_id"] if events else None,
        }
        event["event_id"] = _event_id(event)
        validate_record("review_event", event, where="new decision event")
        append_event(journal_path(job_root), event)
        return event


def decision_snapshot_sha256(events: Iterable[Mapping[str, Any]]) -> str:
    """Return the fingerprint of the decision history a Run was sealed against."""
    return full_digest([event["event_id"] for event in events])


def materialize(events: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Return the latest event per decision subject, keyed by ``(subject_type, subject_id)``.

    This is a view only. Rule precedence, scope specificity, ``STALE`` and conflicts are applied by
    the rule resolver (plan P7), which reads the full history rather than this view.
    """
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        latest[(event["subject_type"], event["subject_id"])] = dict(event)
    return latest
