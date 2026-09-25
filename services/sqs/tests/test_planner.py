import pytest

from sage_sqs.domain import PlannerDisposition
from sage_sqs.evaluation.planner import EvaluationPlanner, next_reasoning_levels, plan_next_tests


@pytest.mark.parametrize(("medium_passed", "next_levels"), [(True, ("low",)), (False, ("high",))])
def test_medium_first_boundary(medium_passed, next_levels):
    assert next_reasoning_levels(medium_passed) == next_levels


def test_predecessor_medium_starts_successor_at_medium():
    planned = EvaluationPlanner().first_test(predecessor_reasoning="medium")
    assert planned.reasoning == "medium"
    assert planned.evidence_basis is None
    assert planned.qualification is None


def test_stronger_high_failure_prunes_weaker_without_evidence():
    row = EvaluationPlanner().plan_weaker_candidate(stronger_high_failed=True)
    assert row.disposition == PlannerDisposition.PRUNE
    assert row.reason_code == "STRONGER_MODEL_FAILED_HIGH"
    assert row.qualification is None


def test_plan_orders_tests_by_benefit_per_cost():
    rows = plan_next_tests({"candidates": [
        {"candidate_id": "expensive", "profile_id": "uk-UA", "model_id": "m2", "capability": "GRAMMAR_ANALYSIS", "estimated_cost_usd": 2.0, "unsupported_coverage": True},
        {"candidate_id": "cheap", "profile_id": "uk-UA", "model_id": "m1", "capability": "GRAMMAR_ANALYSIS", "estimated_cost_usd": 0.5, "unsupported_coverage": True},
    ]})
    assert [r.candidate_id for r in rows] == ["cheap", "expensive"]
    assert all(r.disposition == PlannerDisposition.TEST for r in rows)


def test_adequate_cheaper_route_defers_redundant_candidate():
    [row] = plan_next_tests({"candidates": [{
        "candidate_id": "expensive", "profile_id": "uk-UA", "model_id": "m2", "capability": "GRAMMAR_ANALYSIS",
        "estimated_cost_usd": 2.0, "adequate_cheaper_route_exists": True,
    }]})
    assert row.disposition == PlannerDisposition.DEFER
    assert row.reason_code == "ADEQUATE_CHEAPER_ROUTE_EXISTS"
    assert row.qualification is None


def test_generation_sentinel_is_not_deferred_by_cheaper_route_prior():
    [row] = plan_next_tests({"candidates": [{
        "candidate_id": "sentinel", "profile_id": "en-US", "model_id": "new", "capability": "GRAMMAR_ANALYSIS",
        "estimated_cost_usd": 1.0, "generation_sentinel": True, "adequate_cheaper_route_exists": True,
        "predecessor_reasoning": "medium",
    }]})
    assert row.disposition == PlannerDisposition.TEST
    assert row.reason_code == "GENERATION_SENTINEL"
    assert row.reasoning == "medium"


def test_consistent_cluster_can_use_exact_confirmation():
    [row] = plan_next_tests({"candidates": [{
        "candidate_id": "fr-011", "profile_id": "fr-011", "model_id": "m1", "capability": "GRAMMAR_ANALYSIS",
        "estimated_cost_usd": 0.5, "cluster": "french", "cluster_anchor_consistent": True,
        "exact_confirmation_available": True,
    }]})
    assert row.disposition == PlannerDisposition.TEST
    assert row.scope == "CONFIRMATION"
    assert row.reason_code == "CLUSTER_EXACT_CONFIRMATION"


def test_punjabi_never_uses_cross_script_cluster_confirmation():
    [row] = plan_next_tests({"candidates": [{
        "candidate_id": "pa-Arab-PK", "profile_id": "pa-Arab-PK", "model_id": "m1", "capability": "GRAMMAR_ANALYSIS",
        "estimated_cost_usd": 0.5, "cluster": "punjabi", "script": "Arab", "anchor_script": "Guru",
        "cluster_anchor_consistent": True, "exact_confirmation_available": True,
    }]})
    assert row.scope == "FULL"
    assert row.reason_code != "CLUSTER_EXACT_CONFIRMATION"


def test_planner_dispositions_never_carry_qualification_evidence():
    rows = plan_next_tests({"candidates": [
        {"candidate_id": "test", "profile_id": "en-US", "model_id": "m", "capability": "GRAMMAR_ANALYSIS", "estimated_cost_usd": 1.0},
        {"candidate_id": "defer", "profile_id": "en-US", "model_id": "m2", "capability": "GRAMMAR_ANALYSIS", "estimated_cost_usd": 1.0, "adequate_cheaper_route_exists": True},
        {"candidate_id": "prune", "profile_id": "en-US", "model_id": "m3", "capability": "GRAMMAR_ANALYSIS", "estimated_cost_usd": 1.0, "stronger_high_failed": True},
    ]})
    assert all(r.qualification is None and r.evidence_basis is None for r in rows)
