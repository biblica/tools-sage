import json

from sage_sqs.domain import Confidence, EvidenceBasis, LanguageProfile, ModelRecord, QualificationStatus
from sage_sqs.evaluation.packs import EvaluationCase, EvaluationPack
from sage_sqs.evaluation.runner import evaluate_boundary, estimated_cost_usd, run_planned_test
from sage_sqs.providers.base import ProviderResult
from sage_sqs.qualification import CandidateRoute, derive_confidence, recompute_route_values, synthesize_qualification


class FakeProvider:
    def __init__(self, pass_map):
        self.pass_map = dict(pass_map)
        self.calls = []

    def execute(self, *, model_id, reasoning, prompt):
        self.calls.append((model_id, reasoning))
        passed = self.pass_map[reasoning]
        text = json.dumps({"finding": {"material": True if passed else False, "relation": "negation_scope" if passed else "other"}})
        return ProviderResult(text=text, input_tokens=100, output_tokens=20, usage_raw={"input_tokens": 100, "output_tokens": 20})


def sample_pack():
    return EvaluationPack(
        pack_id="en-US-grammar-analysis-r1", profile_id="en-US", capability="GRAMMAR_ANALYSIS", revision=1,
        repeat_confirmation_cases=1,
        cases=(EvaluationCase(
            case_id="scope", diagnostic_class="negation_scope", critical=True, priority=100,
            prompt="Return JSON for the controlled fixture.",
            expected={"finding.material": True, "finding.relation": "negation_scope"},
            expected_constraints=("hidden",), estimated_input_tokens=100, estimated_output_tokens=20,
            confirmation=True,
        ),),
    )


def sample_model():
    return ModelRecord(
        provider_family="openai", model_id="gpt-x", status="APPROVED", revision=1,
        reasoning_levels=("low", "medium", "high"), capability_fingerprint="a" * 64,
        input_usd_per_mtok=2.0, output_usd_per_mtok=12.0, capability_rank=2, cost_rank=2,
    )


def sample_profile():
    return LanguageProfile(
        profile_id="en-US", display_name="English", status="ACTIVE", revision=1, tier=1, cluster="english",
        iso_639_1="en", iso_639_3="eng", script="Latn", region="US",
    )


def test_reasoning_boundary_truth_table():
    assert evaluate_boundary(medium_pass=True, branch_pass=True).minimum_reasoning == "low"
    assert evaluate_boundary(medium_pass=True, branch_pass=False).minimum_reasoning == "medium"
    assert evaluate_boundary(medium_pass=False, branch_pass=True).minimum_reasoning == "high"
    assert evaluate_boundary(medium_pass=False, branch_pass=False).minimum_reasoning is None


def test_runner_executes_only_medium_then_needed_branch():
    provider = FakeProvider({"medium": True, "low": False, "high": True})
    result = run_planned_test(pack=sample_pack(), provider=provider, model=sample_model(), starting_reasoning="medium")
    assert result.minimum_reasoning == "medium"
    assert [reasoning for _, reasoning in provider.calls][:2] == ["medium", "low"]
    assert "high" not in [reasoning for _, reasoning in provider.calls]


def test_measured_cost_uses_observed_tokens():
    assert estimated_cost_usd(1_000_000, 500_000, 2.0, 12.0) == 8.0


def test_confidence_distinguishes_full_measured_from_confirmation():
    assert derive_confidence(scope="FULL", repeatability=1.0, required_repeats_met=True) == Confidence.HIGH
    assert derive_confidence(scope="CONFIRMATION", repeatability=1.0, required_repeats_met=True) == Confidence.MEDIUM
    assert derive_confidence(scope="FULL", repeatability=0.5, required_repeats_met=False) == Confidence.LOW


def test_cheapest_adequate_route_is_high_and_dominated_route_low():
    values = recompute_route_values([
        CandidateRoute("luna", 1.0, .95, .97, "HIGH"),
        CandidateRoute("terra", 4.0, .95, .97, "HIGH"),
    ])
    assert values["luna"] == "HIGH"
    assert values["terra"] == "LOW"


def test_more_expensive_better_route_remains_useful_medium():
    values = recompute_route_values([
        CandidateRoute("luna", 1.0, .92, .94, "HIGH"),
        CandidateRoute("terra", 4.0, .99, .99, "HIGH"),
    ])
    assert values["luna"] == "HIGH"
    assert values["terra"] == "MEDIUM"


def test_synthesize_qualification_keeps_metrics_distinct():
    provider = FakeProvider({"medium": True, "low": False, "high": True})
    result = run_planned_test(pack=sample_pack(), provider=provider, model=sample_model(), starting_reasoning="medium")
    q = synthesize_qualification(
        model=sample_model(), profile=sample_profile(), capability="GRAMMAR_ANALYSIS", run=result,
        evidence_basis=EvidenceBasis.MEASURED, route_value="HIGH",
    )
    assert q.status == QualificationStatus.QUALIFIED
    assert q.minimum_reasoning == "medium"
    assert 0 <= q.quality_score <= 1
    assert 0 <= q.reliability_score <= 1
    assert q.confidence in {"HIGH", "MEDIUM", "LOW"}
    assert q.value == "HIGH"
    assert q.estimated_unit_cost_usd > 0
