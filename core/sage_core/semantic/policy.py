"""Forward-only semantic evidence-state and export policy for SAGE."""

from __future__ import annotations

from typing import Final

from ..errors import ValidationError

EVIDENCE_STATES: Final[tuple[str, ...]] = (
    "SEED",
    "OBSERVED",
    "TEAM_CONFIRMED",
    "ESTABLISHED",
    "APPROVED",
)
REVIEW_STATES: Final[tuple[str, ...]] = (
    "OBSERVED",
    "TEAM_CONFIRMED",
    "ESTABLISHED",
    "APPROVED",
)
IMPORT_LIFT_STATUS: Final[str] = "OBSERVED"

EXPORT_VIEWS: Final[dict[str, tuple[str, ...]]] = {
    "starter": EVIDENCE_STATES,
    "reviewed": ("TEAM_CONFIRMED", "ESTABLISHED", "APPROVED"),
    "established": ("ESTABLISHED", "APPROVED"),
    "approved": ("APPROVED",),
}


def normalise_evidence_status(value: str, *, allow_reference: bool = False) -> str:
    """Validate one semantic evidence status against the forward-only policy."""
    status = str(value).strip().upper()
    if allow_reference and status == "REFERENCE":
        return status
    if status not in EVIDENCE_STATES:
        raise ValidationError(
            "Semantic evidence status must be one of " + ", ".join(EVIDENCE_STATES)
        )
    return status


def export_statuses(view: str) -> tuple[str, ...]:
    """Return the statuses permitted by one explicit LIFT export view."""
    normalized = str(view).strip().casefold()
    if normalized not in EXPORT_VIEWS:
        raise ValidationError(
            "Semantic export view must be one of " + ", ".join(EXPORT_VIEWS)
        )
    return EXPORT_VIEWS[normalized]
