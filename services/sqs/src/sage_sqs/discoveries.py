"""Metadata-only discovery intake and deduplicated ADMIN attention."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .discovery import validate_discovery as _validate_wire
from .repository import Repository


class DiscoveryValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DiscoveryReceipt:
    discovery_id: str
    status: str = "ACCEPTED"


def validate_discovery(payload: Any) -> dict[str, Any]:
    try:
        return _validate_wire(payload)
    except ValueError as exc:
        raise DiscoveryValidationError("INVALID_DISCOVERY") from exc


def accept_discovery(repo: Repository, payload: Any) -> DiscoveryReceipt:
    value = validate_discovery(payload)
    discovery_id = repo.record_discovery(value)
    kind = value["kind"]
    observed = value["observed"]
    if kind == "LANGUAGE_VALIDATION_REQUEST":
        category = "LANGUAGE_VALIDATION_REQUEST"
        severity = "MEDIUM"
        summary = f"Requested {observed['capability']} validation for {observed['profile_id']}"
    else:
        category = "DISCOVERY"
        severity = "INFO"
        summary = f"Unresolved {kind} discovery"
    repo.upsert_attention(
        attention_key=f"{category}:{discovery_id}",
        category=category,
        severity=severity,
        summary=summary,
        payload={"discovery_id": discovery_id, "kind": kind, "observed": observed},
    )
    return DiscoveryReceipt(discovery_id=discovery_id)
