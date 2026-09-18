"""Deterministic cost-aware SQS evaluation planner.

Planner output is scheduling metadata only. It can never create qualification
or negative evidence; only executed evaluations may do that.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain import PlannerDisposition

BENEFIT = {
    "UNSUPPORTED_COVERAGE": 5,
    "CHEAPER_MODEL_POSSIBLE": 3,
    "LOWER_REASONING_POSSIBLE": 2,
    "NEW_OR_CHANGED_MODEL_BOUNDARY": 2,
    "LOW_CONFIDENCE_ROUTE": 2,
    "FALLBACK_DIVERSITY": 1,
    "ADEQUATE_CHEAPER_ROUTE_EXISTS": -3,
    "STRONGER_MODEL_FAILED_HIGH": -3,
    "REDUNDANT_CLUSTER_RESULT": -2,
}


@dataclass(frozen=True)
class PlannedTest:
    candidate_id: str
    profile_id: str = ""
    model_id: str = ""
    capability: str = ""
    reasoning: str = "medium"
    scope: str = "FULL"
    disposition: PlannerDisposition = PlannerDisposition.TEST
    reason_code: str = "ROUTING_VALUE"
    benefit_points: int = 0
    estimated_cost_usd: float = 0.0
    qualification: None = None
    evidence_basis: None = None

    @property
    def benefit_per_cost(self) -> float:
        return self.benefit_points / max(self.estimated_cost_usd, 1e-9)


def next_reasoning_levels(medium_passed: bool) -> tuple[str, ...]:
    return ("low",) if medium_passed else ("high",)


def _start_reasoning(candidate: dict[str, Any]) -> str:
    predecessor = candidate.get("predecessor_reasoning")
    return predecessor if predecessor in {"low", "medium", "high"} else "medium"


def _benefit(candidate: dict[str, Any]) -> int:
    points = 0
    if candidate.get("unsupported_coverage"):
        points += BENEFIT["UNSUPPORTED_COVERAGE"]
    if candidate.get("cheaper_model_possible"):
        points += BENEFIT["CHEAPER_MODEL_POSSIBLE"]
    if candidate.get("lower_reasoning_possible"):
        points += BENEFIT["LOWER_REASONING_POSSIBLE"]
    if candidate.get("generation_sentinel") or candidate.get("new_or_changed_model"):
        points += BENEFIT["NEW_OR_CHANGED_MODEL_BOUNDARY"]
    if candidate.get("low_confidence_route"):
        points += BENEFIT["LOW_CONFIDENCE_ROUTE"]
    if candidate.get("fallback_diversity"):
        points += BENEFIT["FALLBACK_DIVERSITY"]
    if candidate.get("redundant_cluster_result"):
        points += BENEFIT["REDUNDANT_CLUSTER_RESULT"]
    return points or 1


def _can_cluster_confirm(candidate: dict[str, Any]) -> bool:
    if not (candidate.get("cluster_anchor_consistent") and candidate.get("exact_confirmation_available")):
        return False
    if candidate.get("cluster") == "punjabi":
        script = candidate.get("script")
        anchor_script = candidate.get("anchor_script")
        if script and anchor_script and script != anchor_script:
            return False
    return True


def _plan_candidate(candidate: dict[str, Any]) -> PlannedTest:
    common = {
        "candidate_id": str(candidate.get("candidate_id") or f"{candidate.get('model_id','')}:{candidate.get('profile_id','')}:{candidate.get('capability','')}"),
        "profile_id": str(candidate.get("profile_id", "")),
        "model_id": str(candidate.get("model_id", "")),
        "capability": str(candidate.get("capability", "")),
        "reasoning": _start_reasoning(candidate),
        "estimated_cost_usd": float(candidate.get("estimated_cost_usd", 0.0)),
    }

    # New-generation sentinels must execute before economic DEFER priors; otherwise
    # the planner can never detect a successor regression or improvement.
    if candidate.get("generation_sentinel"):
        return PlannedTest(
            **common,
            disposition=PlannerDisposition.TEST,
            reason_code="GENERATION_SENTINEL",
            benefit_points=_benefit(candidate),
            scope="FULL",
        )

    if candidate.get("stronger_high_failed"):
        return PlannedTest(
            **common,
            disposition=PlannerDisposition.PRUNE,
            reason_code="STRONGER_MODEL_FAILED_HIGH",
            benefit_points=BENEFIT["STRONGER_MODEL_FAILED_HIGH"],
            scope="FULL",
        )

    if candidate.get("adequate_cheaper_route_exists"):
        return PlannedTest(
            **common,
            disposition=PlannerDisposition.DEFER,
            reason_code="ADEQUATE_CHEAPER_ROUTE_EXISTS",
            benefit_points=BENEFIT["ADEQUATE_CHEAPER_ROUTE_EXISTS"],
            scope="FULL",
        )

    if _can_cluster_confirm(candidate):
        return PlannedTest(
            **common,
            disposition=PlannerDisposition.TEST,
            reason_code="CLUSTER_EXACT_CONFIRMATION",
            benefit_points=_benefit(candidate),
            scope="CONFIRMATION",
        )

    if candidate.get("unsupported_coverage"):
        reason = "UNSUPPORTED_COVERAGE"
    elif candidate.get("new_or_changed_model"):
        reason = "NEW_OR_CHANGED_MODEL_BOUNDARY"
    elif candidate.get("low_confidence_route"):
        reason = "LOW_CONFIDENCE_ROUTE"
    elif candidate.get("cheaper_model_possible"):
        reason = "CHEAPER_MODEL_POSSIBLE"
    elif candidate.get("lower_reasoning_possible"):
        reason = "LOWER_REASONING_POSSIBLE"
    else:
        reason = "ROUTING_VALUE"
    return PlannedTest(
        **common,
        disposition=PlannerDisposition.TEST,
        reason_code=reason,
        benefit_points=_benefit(candidate),
        scope="FULL",
    )


def plan_next_tests(snapshot: dict[str, Any]) -> list[PlannedTest]:
    rows = [_plan_candidate(dict(candidate)) for candidate in snapshot.get("candidates") or []]
    disposition_rank = {
        PlannerDisposition.TEST: 0,
        PlannerDisposition.DEFER: 1,
        PlannerDisposition.PRUNE: 2,
        PlannerDisposition.MEASURED: 3,
        PlannerDisposition.CONFIRMED: 4,
    }
    return sorted(
        rows,
        key=lambda row: (
            disposition_rank[row.disposition],
            -row.benefit_per_cost if row.disposition == PlannerDisposition.TEST else 0.0,
            row.candidate_id,
        ),
    )


class EvaluationPlanner:
    """Small object facade retained for ADMIN/worker integration."""

    def first_test(self, *, predecessor_reasoning: str | None = None) -> PlannedTest:
        return _plan_candidate({
            "candidate_id": "first",
            "predecessor_reasoning": predecessor_reasoning,
            "estimated_cost_usd": 1.0,
        })

    def plan_weaker_candidate(self, *, stronger_high_failed: bool) -> PlannedTest:
        return _plan_candidate({
            "candidate_id": "weaker",
            "stronger_high_failed": stronger_high_failed,
            "estimated_cost_usd": 1.0,
        })
