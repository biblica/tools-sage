"""Canonical in-process SAGE runtime and AI status for all interactive surfaces."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    """Return one stable UTC timestamp for runtime status checks."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class AIStatus:
    """Hold the one canonical workflow-AI prerequisite result used by all UI surfaces."""
    connection: str = "NOT CHECKED"
    provider_id: str | None = None
    provider: str | None = None
    model: str | None = None
    reasoning_level: str | None = None
    prerequisite_status: str = "BLOCKED"
    last_checked: str | None = None
    reason_code: str | None = None
    diagnostic: str | None = None
    available: bool = False
    ready: bool = False
    auth_mode: str | None = None
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly copy for setup state and report rendering."""
        return asdict(self)


@dataclass
class RuntimeStatus:
    """Hold current in-process task, resource, language, and AI status."""
    state: str = "IDLE"
    active_task: str | None = None
    stage: str | None = None
    progress: str | None = None
    current_job: str | None = None
    current_project: str | None = None
    current_run: str | None = None
    interface_language: str = "en-US"
    ai: AIStatus = field(default_factory=AIStatus)
    resource_change_count: int = 0
    resource_status: str = "NOT CHECKED"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly snapshot suitable for diagnostics or future UIs."""
        value = asdict(self)
        return value
