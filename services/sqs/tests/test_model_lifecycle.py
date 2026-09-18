from dataclasses import replace
from pathlib import Path

from sage_sqs.db import Database
from sage_sqs.domain import LanguageProfile, ModelRecord, Qualification
from sage_sqs.evaluation.lifecycle import build_planner_snapshot, replan_repository
from sage_sqs.providers.openai_provider import sync_provider_catalog
from sage_sqs.repository import Repository


def setup_repo(tmp_path):
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    profile = LanguageProfile("en-US", "English", "ACTIVE", 1, 1, "english", "en", "eng", "Latn", "US")
    model = ModelRecord("openai", "gpt-x", "APPROVED", 1, ("low", "medium", "high"), "a"*64, 2.0, 12.0, 2, 2)
    repo.save_profile(profile)
    repo.save_model(model)
    return repo, profile, model


def qualification(profile, model, reasoning="medium"):
    return Qualification(
        provider_family="openai", model_id=model.model_id, model_capability_fingerprint=model.capability_fingerprint,
        profile_id=profile.profile_id, profile_identity_sha256=profile.evaluation_identity_sha256,
        capability="GRAMMAR_ANALYSIS", status="QUALIFIED", minimum_reasoning=reasoning,
        quality_score=.96, reliability_score=.98, confidence="HIGH", value="HIGH", evidence_basis="MEASURED",
        estimated_unit_cost_usd=.004, evaluated_at="2026-08-31T10:00:00Z", evidence_sha256="b"*64,
    )


def test_changed_model_fingerprint_creates_review_revision_and_suppresses_old_evidence(tmp_path):
    repo, profile, model = setup_repo(tmp_path)
    repo.save_qualification(qualification(profile, model))
    assert len(repo.publishable_qualifications()) == 1

    changed = replace(model, capability_fingerprint="c"*64, input_usd_per_mtok=2.1)
    result = sync_provider_catalog(repo, [changed])

    latest = repo.latest_model("openai", "gpt-x")
    assert result[0].changed is True
    assert latest.revision == 2
    assert latest.status == "REVIEW_REQUIRED"
    assert repo.publishable_qualifications() == []
    assert repo.list_attention()[0]["category"] == "MODEL_REVISION"


def test_unchanged_model_keeps_approved_revision(tmp_path):
    repo, _, model = setup_repo(tmp_path)
    result = sync_provider_catalog(repo, [model])
    assert result[0].changed is False
    assert repo.latest_model("openai", "gpt-x").revision == 1
    assert repo.latest_model("openai", "gpt-x").status == "APPROVED"


def test_successor_uses_predecessor_boundary_in_planner_snapshot(tmp_path):
    repo, profile, old = setup_repo(tmp_path)
    repo.save_qualification(qualification(profile, old, "medium"))
    new = replace(old, model_id="gpt-new", capability_fingerprint="d"*64, revision=1)
    repo.save_model(new)
    repo.link_predecessor("gpt-new", "gpt-x")

    snapshot = build_planner_snapshot(repo, Path(__file__).resolve().parents[1] / "config" / "evaluation-packs")
    candidate = next(row for row in snapshot["candidates"] if row["model_id"] == "gpt-new" and row["profile_id"] == "en-US")
    assert candidate["predecessor_reasoning"] == "medium"


def test_replan_queues_only_uncovered_exact_candidates(tmp_path):
    repo, profile, first = setup_repo(tmp_path)
    second = replace(first, model_id="gpt-y", capability_fingerprint="e"*64, cost_rank=3)
    repo.save_model(second)
    repo.save_qualification(qualification(profile, first))

    rows = replan_repository(repo, Path(__file__).resolve().parents[1] / "config" / "evaluation-packs")
    queued = [row for row in rows if row.disposition.value == "TEST"]
    assert any(row.model_id == "gpt-y" for row in queued)
    assert repo.pending_evaluation_count() == 1

def test_price_only_change_preserves_approval_and_linguistic_evidence(tmp_path):
    repo, profile, model = setup_repo(tmp_path)
    repo.save_qualification(qualification(profile, model))
    repriced = replace(model, input_usd_per_mtok=model.input_usd_per_mtok + 0.5)
    result = sync_provider_catalog(repo, [repriced])
    latest = repo.latest_model('openai','gpt-x')
    assert result[0].changed is True
    assert latest.revision == 2
    assert latest.status == 'APPROVED'
    assert latest.capability_fingerprint == model.capability_fingerprint
    assert len(repo.publishable_qualifications()) == 1
