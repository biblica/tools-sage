from pathlib import Path

from sage_sqs.domain import (
    Capability, Confidence, EvidenceBasis, PlannerDisposition,
    QualificationStatus, RouteValue,
)
from sage_sqs.profile_builder import load_seed_profiles
from sage_sqs.providers.openai_provider import load_openai_catalog, routine_reasoning


def test_public_vocabulary_is_stable():
    assert [x.value for x in Capability] == ["GRAMMAR_ANALYSIS", "SEMANTIC_REWRITE"]
    assert [x.value for x in QualificationStatus] == ["QUALIFIED", "NOT_QUALIFIED", "UNASSESSED"]
    assert [x.value for x in Confidence] == ["HIGH", "MEDIUM", "LOW"]
    assert [x.value for x in RouteValue] == ["HIGH", "MEDIUM", "LOW"]
    assert [x.value for x in EvidenceBasis] == ["MEASURED", "CONFIRMED"]
    assert [x.value for x in PlannerDisposition] == ["TEST", "DEFER", "PRUNE", "MEASURED", "CONFIRMED"]


def test_seed_catalog_is_exact_and_review_required():
    root = Path(__file__).resolve().parents[1]
    rows = load_seed_profiles(root / "seed" / "languages")
    assert len(rows) == 20
    assert sum(p.tier == 1 for p in rows) == 9
    assert sum(p.tier == 2 for p in rows) == 6
    assert sum(p.tier == 3 for p in rows) == 5
    assert {p.status for p in rows} == {"REVIEW_REQUIRED"}
    assert len({p.evaluation_identity_sha256 for p in rows}) == 20


def test_openai_registry_filters_premium_reasoning_and_has_stable_fingerprints():
    root = Path(__file__).resolve().parents[1]
    rows = load_openai_catalog(root / "seed" / "openai-provider.yml")
    by_id = {m.model_id: m for m in rows}
    assert routine_reasoning(by_id["gpt-5.6-terra"]) == ("low", "medium", "high")
    assert [by_id[x].capability_rank for x in ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]] == [1, 2, 3]
    assert all(len(model.capability_fingerprint) == 64 for model in rows)
