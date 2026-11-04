"""Operator verdicts on SAGE's core lists, kept as a local overlay (never edits a shipped package).

Core lists are immutable pinned packages or evidence (BSB phrase index, MACULA original-language senses,
Paratext Biblical Terms). The Operator reviews entries and the verdicts are appended here, newest wins,
and applied on top when a terms list is built. Lists and keys:

* ``OL_SENSE``    key ``<normalized wording>|<lemma>``: ACCEPT confirms the sense; REJECT hides it.
* ``KEY_TERM``    key ``<lemma>``: REJECT stops treating the lemma as a key term.
* ``INDEX_ENTRY`` key ``<normalized wording>``: REJECT stops a curated index entry seeding a Run.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..errors import ValidationError
from ..state import append_event

LISTS = ("OL_SENSE", "KEY_TERM", "INDEX_ENTRY")
VERDICTS = ("ACCEPT", "REJECT", "CLEAR")
OVERLAY_FILE = "core-overlay.jsonl"


def overlay_path(folder: Path) -> Path:
    """Return the overlay file inside ``folder`` (the Operator's local PCC data folder)."""
    return folder / OVERLAY_FILE


def record_verdict(folder: Path, list_name: str, key: str, verdict: str, note: str = "", actor: str = "operator") -> None:
    """Append one verdict; ``CLEAR`` withdraws an earlier one."""
    if list_name not in LISTS or verdict not in VERDICTS or not key:
        raise ValidationError(f"Unknown overlay verdict {list_name}/{verdict}", code="PCC_OVERLAY_INVALID")
    append_event(overlay_path(folder), {
        "time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "actor": actor,
        "list": list_name, "key": key, "verdict": verdict, "note": note})


def current_verdicts(folder: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Return the standing verdict per (list, key); unreadable lines are skipped, never fatal."""
    path = overlay_path(folder)
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.is_file():
        return latest
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
            latest[(event["list"], event["key"])] = event
        except (ValueError, KeyError, TypeError):
            continue
    return {k: v for k, v in latest.items() if v["verdict"] != "CLEAR"}


def verdict_map(folder: Path) -> Mapping[tuple[str, str], str]:
    """Return {(list, key): ACCEPT|REJECT}."""
    return {k: v["verdict"] for k, v in current_verdicts(folder).items()}
