"""Read-only lookup over a validated SqsCache, mapping one governed route to
a status SAGE's existing model-policy vocabulary already understands.

This module makes no routing decisions itself -- it only answers "what does
SQS say about this route," using the same three-way vocabulary
(`QUALIFIED`/`NOT_QUALIFIED`/`UNASSESSED`) `model-policy.yml`'s
`unknown_route_status` already anticipates. Task 5 layers this in as
`model_policy.py`'s evidence source; this module is deliberately independent
of that policy engine until then.
"""
from __future__ import annotations

from dataclasses import dataclass

from .sqs_cache import SqsCache


@dataclass(frozen=True)
class QualificationLookup:
    """One route's SQS-reported status, or UNASSESSED if SQS has no opinion."""

    status: str
    minimum_reasoning: str | None
    execution_channel: str | None
    evaluated_at: str | None


_UNASSESSED = QualificationLookup(status="UNASSESSED", minimum_reasoning=None, execution_channel=None, evaluated_at=None)


def lookup_qualification(cache: SqsCache, *, provider_family: str, model_id: str, profile_id: str, capability: str) -> QualificationLookup:
    """Return the SQS-reported status for one (provider_family, model_id, profile_id, capability) route.

    Checks the durable negative tombstone first: by construction (see
    sqs_cache.SqsCache._commit_tombstones), it already reflects any explicit
    newer positive re-qualification from the current bundle, so this is safe
    and never masks a real requalification.
    """
    if cache.is_denied(provider_family=provider_family, model_id=model_id, profile_id=profile_id, capability=capability):
        return QualificationLookup(status="NOT_QUALIFIED", minimum_reasoning=None, execution_channel=None, evaluated_at=None)

    bundle = cache.load_current()
    if bundle is None:
        return _UNASSESSED

    for qualification in bundle.get("qualifications", []):
        matches = (
            qualification.get("provider_family") == provider_family
            and qualification.get("model_id") == model_id
            and qualification.get("profile_id") == profile_id
            and qualification.get("capability") == capability
        )
        if matches:
            return QualificationLookup(
                status=str(qualification.get("status")),
                minimum_reasoning=qualification.get("minimum_reasoning"),
                execution_channel=qualification.get("execution_channel"),
                evaluated_at=qualification.get("evaluated_at"),
            )

    return _UNASSESSED
