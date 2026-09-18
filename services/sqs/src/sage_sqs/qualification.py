"""Synthesize publishable measured qualification and relative route value."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from .domain import (
    Confidence,
    EvidenceBasis,
    LanguageProfile,
    ModelRecord,
    Qualification,
    QualificationStatus,
    canonical_sha256,
)
from .evaluation.runner import PlannedRunResult


@dataclass(frozen=True)
class CandidateRoute:
    model_id: str
    cost: float
    quality: float
    reliability: float
    confidence: str


def derive_confidence(*, scope: str, repeatability: float, required_repeats_met: bool,
                      decisive_critical_failure: bool = False) -> Confidence:
    if decisive_critical_failure and scope == "FULL":
        return Confidence.HIGH
    if not required_repeats_met or repeatability < 0.95:
        return Confidence.LOW
    if scope == "FULL":
        return Confidence.HIGH
    if scope == "CONFIRMATION":
        return Confidence.MEDIUM
    return Confidence.LOW


def _confidence_rank(value: str) -> int:
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(str(value), -1)


def _dominates(left: CandidateRoute, right: CandidateRoute) -> bool:
    not_worse = (
        left.cost <= right.cost
        and left.quality >= right.quality
        and left.reliability >= right.reliability
        and _confidence_rank(left.confidence) >= _confidence_rank(right.confidence)
    )
    strictly_better = (
        left.cost < right.cost
        or left.quality > right.quality
        or left.reliability > right.reliability
        or _confidence_rank(left.confidence) > _confidence_rank(right.confidence)
    )
    return not_worse and strictly_better


def recompute_route_values(routes: Iterable[CandidateRoute]) -> dict[str, str]:
    rows = list(routes)
    values: dict[str, str] = {}
    non_dominated: list[CandidateRoute] = []
    for route in rows:
        if any(other.model_id != route.model_id and _dominates(other, route) for other in rows):
            values[route.model_id] = "LOW"
        else:
            non_dominated.append(route)
    if non_dominated:
        best_cost = min(route.cost for route in non_dominated)
        for route in non_dominated:
            values[route.model_id] = "HIGH" if route.cost == best_cost else "MEDIUM"
    return values


def synthesize_qualification(*, model: ModelRecord, profile: LanguageProfile, capability: str,
                             run: PlannedRunResult, evidence_basis: EvidenceBasis | str,
                             route_value: str, execution_channel: str) -> Qualification:
    status = QualificationStatus.QUALIFIED if run.minimum_reasoning is not None else QualificationStatus.NOT_QUALIFIED
    confidence = derive_confidence(
        scope=run.scope,
        repeatability=run.reliability_score,
        required_repeats_met=run.required_repeats_met,
        decisive_critical_failure=run.decisive_critical_failure,
    )
    evaluated_at = datetime.now(timezone.utc).isoformat()
    basis = evidence_basis.value if isinstance(evidence_basis, EvidenceBasis) else str(evidence_basis)
    evidence = {
        "provider_family": model.provider_family,
        "execution_channel": execution_channel,
        "model_id": model.model_id,
        "model_capability_fingerprint": model.capability_fingerprint,
        "profile_id": profile.profile_id,
        "profile_identity_sha256": profile.evaluation_identity_sha256,
        "capability": capability,
        "status": status.value,
        "minimum_reasoning": run.minimum_reasoning,
        "quality_score": run.quality_score,
        "reliability_score": run.reliability_score,
        "confidence": confidence.value,
        "evidence_basis": basis,
        "estimated_unit_cost_usd": run.estimated_unit_cost_usd,
    }
    return Qualification(
        provider_family=model.provider_family,
        execution_channel=execution_channel,
        model_id=model.model_id,
        model_capability_fingerprint=model.capability_fingerprint,
        profile_id=profile.profile_id,
        profile_identity_sha256=profile.evaluation_identity_sha256,
        capability=capability,
        status=status.value,
        minimum_reasoning=run.minimum_reasoning or "",
        quality_score=run.quality_score,
        reliability_score=run.reliability_score,
        confidence=confidence.value,
        value=route_value,
        evidence_basis=basis,
        estimated_unit_cost_usd=run.estimated_unit_cost_usd,
        evaluated_at=evaluated_at,
        evidence_sha256=canonical_sha256(evidence),
    )
