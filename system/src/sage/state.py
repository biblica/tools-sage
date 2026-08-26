"""Governed ecosystem state and append-only event helpers."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .standard import SageStandard


def utc_now() -> str:
    """Return a stable UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_state(path: Path) -> dict[str, Any]:
    """Read one state document or return an empty mapping."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(path: Path, value: dict[str, Any]) -> None:
    """Write one state document atomically."""
    atomic_write_json(path, value)


def append_event(path: Path, event: dict[str, Any]) -> None:
    """Append one durable JSONL event while the caller holds its operation lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def ecosystem_state_path(runtime_state_root: Path) -> Path:
    """Return the ecosystem state document under the configured data root."""
    return runtime_state_root / "state" / "ecosystem.json"


def ecosystem_event_path(runtime_state_root: Path) -> Path:
    """Return the ecosystem event log under the configured data root."""
    return runtime_state_root / "transactions" / "events.jsonl"


def write_ecosystem_state(
    runtime_state_root: Path,
    standard: SageStandard,
    state: str,
    payload: dict[str, Any],
) -> None:
    """Validate and write the ecosystem state plus an append-only event."""
    normalized = state.upper()
    if normalized not in standard.operation_states:
        raise ValueError(f"Uncontrolled ecosystem state: {state}")
    document = {
        "schema_version": "1.0",
        "ecosystem": "sage",
        "version": standard.version,
        "state": normalized,
        "updated_utc": utc_now(),
        **payload,
    }
    write_state(ecosystem_state_path(runtime_state_root), document)
    append_event(
        ecosystem_event_path(runtime_state_root),
        {
            "event": "ECOSYSTEM_STATE",
            "state": normalized,
            "version": standard.version,
            "time_utc": document["updated_utc"],
        },
    )
