"""Deterministic admission primitives for selective original-language referrals."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sage.errors import ValidationError
from sage.hashing import sha256_bytes


OL_REFERRAL_CONTRACT_V1 = "SAW_OL_REFERRAL_ADMISSION_V1"
OL_REFERRAL_CONFLICT_CLASSES = frozenset(
    {
        "NEGATION_OR_POLARITY_CONFLICT",
        "PARTICIPANT_IDENTITY_OR_ROLE_CONFLICT",
        "CORE_EVENT_OR_STATE_CONFLICT",
        "CORE_PROPOSITION_OMISSION_OR_ADDITION",
    }
)
OL_REFERRAL_SOURCE_DEPENDENCY = "UNRESOLVED_REQUIRES_ORIGINAL_LANGUAGE"

_ADMISSION_FIELDS = (
    "conflict_class",
    "wip_proposition",
    "reference_proposition",
    "fundamental_impact",
    "source_dependency",
)


def _normalized_text(value: str) -> str:
    """Normalize narrative text for deterministic semantic identity comparison."""
    return " ".join(value.casefold().split())


def normalize_referral_admission(
    request: Mapping[str, Any],
    *,
    index: int,
) -> dict[str, str]:
    """Validate and normalize one closed-contract referral admission."""
    missing = [
        field
        for field in _ADMISSION_FIELDS
        if not isinstance(request.get(field), str) or not request[field].strip()
    ]
    if missing:
        raise ValidationError(
            f"OL review request {index} is missing admission fields: {', '.join(missing)}",
            code="SAW_OL_REFERRAL_FIELDS_MISSING",
        )

    normalized = {field: request[field].strip() for field in _ADMISSION_FIELDS}
    normalized["conflict_class"] = normalized["conflict_class"].upper()
    normalized["source_dependency"] = normalized["source_dependency"].upper()

    if normalized["conflict_class"] not in OL_REFERRAL_CONFLICT_CLASSES:
        raise ValidationError(
            f"OL review request {index} uses an unsupported conflict class",
            code="SAW_OL_REFERRAL_CLASS_INVALID",
        )
    if normalized["source_dependency"] != OL_REFERRAL_SOURCE_DEPENDENCY:
        raise ValidationError(
            f"OL review request {index} is not unresolved without original-language evidence",
            code="SAW_OL_REFERRAL_ADMISSION_INVALID",
        )
    if _normalized_text(normalized["wip_proposition"]) == _normalized_text(
        normalized["reference_proposition"]
    ):
        raise ValidationError(
            f"OL review request {index} states equivalent WIP and REFERENCE propositions",
            code="SAW_OL_REFERRAL_ADMISSION_INVALID",
        )
    return normalized


def referral_conflict_key(
    *,
    target_reference: str,
    conflict_class: str,
    wip_proposition: str,
    reference_proposition: str,
) -> str:
    """Return the stable semantic identity for an admitted conflict."""
    payload = {
        "target_reference": " ".join(target_reference.upper().split()),
        "conflict_class": " ".join(conflict_class.upper().split()),
        "wip_proposition": _normalized_text(wip_proposition),
        "reference_proposition": _normalized_text(reference_proposition),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(serialized)
