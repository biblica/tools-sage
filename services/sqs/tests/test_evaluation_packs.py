import json
from pathlib import Path

import pytest

from sage_sqs.evaluation.packs import EvaluationCase, EvaluationPack, load_pack
from sage_sqs.evaluation.scoring import (
    AttemptScore,
    reasoning_level_can_still_pass,
    run_pack_cases,
    score_attempt,
)


def case(case_id="scope", *, critical=True, priority=100):
    return EvaluationCase(
        case_id=case_id,
        diagnostic_class="negation_scope",
        critical=critical,
        priority=priority,
        prompt="Analyze the controlled text and return JSON.",
        expected={"finding.material": True, "finding.relation": "negation_scope"},
        expected_constraints=("material finding required", "scope relation must be negation_scope"),
        estimated_input_tokens=100,
        estimated_output_tokens=40,
    )


def pack():
    return EvaluationPack(
        pack_id="uk-UA-grammar-analysis-r1",
        profile_id="uk-UA",
        capability="GRAMMAR_ANALYSIS",
        revision=1,
        cases=(case(),),
    )


def test_pack_requires_critical_case():
    with pytest.raises(ValueError, match="critical"):
        EvaluationPack(
            pack_id="bad", profile_id="uk-UA", capability="GRAMMAR_ANALYSIS", revision=1,
            cases=(case(critical=False),),
        )


def test_hidden_expected_values_are_not_in_provider_prompt():
    c = case()
    assert "negation_scope" not in c.provider_prompt()
    assert "material finding required" not in c.provider_prompt()


def test_score_attempt_uses_structured_hidden_expected_values():
    result = json.dumps({"finding": {"material": True, "relation": "negation_scope"}})
    score = score_attempt(case(), result)
    assert score.passed is True
    assert score.quality == 1.0
    assert score.contract_failure is False


def test_invalid_json_is_contract_failure():
    score = score_attempt(case(), "not-json")
    assert score.passed is False
    assert score.contract_failure is True


def test_critical_failure_can_fail_fast():
    scores = [AttemptScore(case_id="scope", passed=False, quality=0.0, critical=True)]
    assert reasoning_level_can_still_pass(pack(), scores) is False


def test_fail_fast_does_not_execute_lower_priority_case():
    p = EvaluationPack(
        pack_id="p", profile_id="uk-UA", capability="GRAMMAR_ANALYSIS", revision=1,
        cases=(case("critical", critical=True, priority=100), case("later", critical=False, priority=1)),
    )
    called = []

    def execute(c):
        called.append(c.case_id)
        if c.case_id == "critical":
            return json.dumps({"finding": {"material": False, "relation": "other"}})
        return json.dumps({"finding": {"material": True, "relation": "negation_scope"}})

    scores = run_pack_cases(p, execute)
    assert [s.case_id for s in scores] == ["critical"]
    assert called == ["critical"]


def test_seed_packs_load_and_have_critical_cases():
    root = Path(__file__).resolve().parents[1] / "config" / "evaluation-packs"
    for name in ["en-US-grammar-analysis-r1.yml", "uk-UA-grammar-analysis-r1.yml"]:
        loaded = load_pack(root / name)
        assert loaded.capability == "GRAMMAR_ANALYSIS"
        assert any(c.critical for c in loaded.cases)
