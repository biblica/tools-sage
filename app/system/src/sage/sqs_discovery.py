"""Outbox-first SQS discovery: SAGE queues metadata locally and never blocks
governed task execution on delivery; an explicit sync flushes the queue.

Uses the actually tested/enforced discovery contract (uppercase `kind`,
`{kind, sage_version, observed}` exactly, no `execution_provider` field) --
`services/sqs/contracts/openapi.yaml` is stale relative to this and must not
be used as a reference (see the architecture evaluation spec, section 3).

Discovery is metadata-only: it must never carry project text, Scripture
text, prompts, or secrets -- only the fixed field sets below.

capability_fingerprint here is deliberately NOT the same computation as
SQS's own `ModelRecord.catalog_fingerprint` (domain.py), which additionally
hashes `capability_rank`/`cost_rank`/per-token pricing -- catalog metadata
SAGE has no way to know for a model it is merely observing in use. SQS's
`accept_discovery` stores this value as opaque metadata for ADMIN review
(confirmed: no server-side formula validation), so a SAGE-only identity
fingerprint over the fields SAGE can truthfully know is correct, not a
stand-in for the vendor's full catalog fingerprint.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .atomic import atomic_write_json
from .sqs_client import post_discovery


def discovery_capability_fingerprint(*, model_id: str, reasoning_levels: Iterable[str]) -> str:
    """Return SAGE's own observed-identity fingerprint for a model discovery."""
    payload = {"provider_family": "openai", "model_id": model_id, "reasoning_levels": sorted(set(reasoning_levels))}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_model_discovery(*, model_id: str, reasoning_levels: Iterable[str], sage_version: str) -> dict[str, Any]:
    """Build one MODEL discovery payload in the exact tested wire shape."""
    levels = sorted(set(reasoning_levels))
    return {
        "kind": "MODEL",
        "sage_version": sage_version,
        "observed": {
            "provider_family": "openai",
            "model_id": model_id,
            "capability_fingerprint": discovery_capability_fingerprint(model_id=model_id, reasoning_levels=levels),
            "reasoning_levels": levels,
        },
    }


def build_language_profile_discovery(*, profile_id: str, language_code: str, script: str, region: str,
                                     sage_version: str) -> dict[str, Any]:
    """Build one LANGUAGE_PROFILE discovery payload in the exact tested wire shape."""
    return {
        "kind": "LANGUAGE_PROFILE",
        "sage_version": sage_version,
        "observed": {
            "profile_id": profile_id,
            "language_code": language_code,
            "script": script,
            "region": region,
        },
    }


def build_language_validation_request(*, profile_id: str, language_code: str, script: str, region: str,
                                      capability: str, sage_version: str) -> dict[str, Any]:
    """Build one LANGUAGE_VALIDATION_REQUEST discovery payload in the exact tested wire shape.

    Distinct from build_language_profile_discovery: this is a deliberate
    operator action ("a real project needs this now"), not passive
    telemetry, and it names the one exact capability that project needs --
    never the whole profile -- so ADMIN is never implicitly committed to
    authoring evaluation-pack content nobody has asked for yet.
    """
    return {
        "kind": "LANGUAGE_VALIDATION_REQUEST",
        "sage_version": sage_version,
        "observed": {
            "profile_id": profile_id,
            "language_code": language_code,
            "script": script,
            "region": region,
            "capability": capability,
        },
    }


def queue_discovery(outbox_path: Path, discovery: dict[str, Any]) -> None:
    """Append one discovery to the local outbox; never makes a network call."""
    entries = load_outbox(outbox_path)
    entries.append(discovery)
    atomic_write_json(outbox_path, entries)


def load_outbox(outbox_path: Path) -> list[dict[str, Any]]:
    """Return the currently queued, not-yet-delivered discoveries."""
    if not outbox_path.is_file():
        return []
    try:
        payload = json.loads(outbox_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return list(payload) if isinstance(payload, list) else []


@dataclass(frozen=True)
class FlushResult:
    """Outcome of one outbox flush attempt."""

    sent: int
    remaining: int
    last_error: str | None


def flush_outbox(outbox_path: Path, endpoints: list[str], *, timeout: int = 10) -> FlushResult:
    """Send every queued discovery, removing each only once its send succeeds.

    Continues past a failed item rather than aborting the whole flush, so one
    bad entry never blocks delivery of the rest. A crash mid-flush leaves
    whatever has not yet been successfully removed still queued -- at most a
    harmless duplicate resend, which the server already deduplicates.
    """
    entries = load_outbox(outbox_path)
    remaining: list[dict[str, Any]] = []
    sent = 0
    last_error: str | None = None
    for entry in entries:
        try:
            post_discovery(endpoints, entry, timeout=timeout)
            sent += 1
        except Exception as exc:  # any failure keeps this entry queued, never drops it
            remaining.append(entry)
            last_error = str(exc)
    if len(remaining) != len(entries):
        atomic_write_json(outbox_path, remaining)
    return FlushResult(sent=sent, remaining=len(remaining), last_error=last_error)
