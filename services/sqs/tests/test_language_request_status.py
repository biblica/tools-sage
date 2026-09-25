from sage_sqs.db import Database
from sage_sqs.discoveries import accept_discovery
from sage_sqs.domain import LanguageProfile, ModelRecord, Qualification
from sage_sqs.publisher import Publisher
from sage_sqs.repository import Repository


def _repo(tmp_path):
    return Repository(Database.open(tmp_path / "sqs.db"))


def _request_payload(**overrides):
    observed = {
        "profile_id": "sw-CD", "language_code": "sw", "script": "Latn", "region": "CD",
        "capability": "GRAMMAR_ANALYSIS",
    }
    return {"kind": "LANGUAGE_VALIDATION_REQUEST", "sage_version": "0.02a1", "observed": {**observed, **overrides}}


def test_status_is_not_requested_with_no_evidence_at_all(tmp_path):
    repo = _repo(tmp_path)
    assert repo.language_request_status(profile_id="sw-CD", capability="GRAMMAR_ANALYSIS") == "NOT_REQUESTED"


def test_status_is_requested_once_a_validation_request_is_staged(tmp_path):
    repo = _repo(tmp_path)
    accept_discovery(repo, _request_payload())
    assert repo.language_request_status(profile_id="sw-CD", capability="GRAMMAR_ANALYSIS") == "REQUESTED"
    assert repo.language_request_status(profile_id="sw-CD", capability="SEMANTIC_REWRITE") == "NOT_REQUESTED"


def test_status_is_profile_in_progress_once_a_profile_row_exists(tmp_path):
    repo = _repo(tmp_path)
    accept_discovery(repo, _request_payload())
    repo.save_profile(LanguageProfile("sw-CD", "Swahili (DR Congo)", "REVIEW_REQUIRED", 1, 2, "bantu", "sw", "swc", "Latn", "CD"))
    assert repo.language_request_status(profile_id="sw-CD", capability="GRAMMAR_ANALYSIS") == "PROFILE_IN_PROGRESS"


def test_status_is_testing_in_progress_once_a_run_is_queued(tmp_path):
    repo = _repo(tmp_path)
    repo.save_profile(LanguageProfile("sw-CD", "Swahili (DR Congo)", "ACTIVE", 1, 2, "bantu", "sw", "swc", "Latn", "CD"))
    repo.queue_test({"profile_id": "sw-CD", "model_id": "gpt-x", "capability": "GRAMMAR_ANALYSIS", "reasoning": "medium"})
    assert repo.language_request_status(profile_id="sw-CD", capability="GRAMMAR_ANALYSIS") == "TESTING_IN_PROGRESS"
    assert repo.language_request_status(profile_id="sw-CD", capability="SEMANTIC_REWRITE") == "PROFILE_IN_PROGRESS"


def test_status_is_qualified_once_published(tmp_path):
    repo = _repo(tmp_path)
    profile = LanguageProfile("sw-CD", "Swahili (DR Congo)", "ACTIVE", 1, 2, "bantu", "sw", "swc", "Latn", "CD")
    model = ModelRecord("openai", "gpt-x", "APPROVED", 1, ("low", "medium", "high"), "a" * 64, 2.0, 12.0, 2, 2)
    repo.save_profile(profile)
    repo.save_model(model)
    repo.save_qualification(Qualification(
        provider_family="openai", execution_channel="codex_workspace", model_id="gpt-x",
        model_capability_fingerprint=model.capability_fingerprint, profile_id="sw-CD",
        profile_identity_sha256=profile.evaluation_identity_sha256, capability="GRAMMAR_ANALYSIS",
        status="QUALIFIED", minimum_reasoning="medium", quality_score=.96, reliability_score=.98,
        confidence="HIGH", value="HIGH", evidence_basis="MEASURED", estimated_unit_cost_usd=.004,
        evaluated_at="2026-09-25T00:00:00Z", evidence_sha256="b" * 64,
    ))
    Publisher(repo, authority_id="biblica-sqs-production", publication_epoch=1, output_paths=()).publish(actor="ADMIN")
    assert repo.language_request_status(profile_id="sw-CD", capability="GRAMMAR_ANALYSIS") == "QUALIFIED"


def test_status_is_not_qualified_once_published_with_a_negative_result(tmp_path):
    repo = _repo(tmp_path)
    profile = LanguageProfile("sw-CD", "Swahili (DR Congo)", "ACTIVE", 1, 2, "bantu", "sw", "swc", "Latn", "CD")
    model = ModelRecord("openai", "gpt-x", "APPROVED", 1, ("low", "medium", "high"), "a" * 64, 2.0, 12.0, 2, 2)
    repo.save_profile(profile)
    repo.save_model(model)
    repo.save_qualification(Qualification(
        provider_family="openai", execution_channel="codex_workspace", model_id="gpt-x",
        model_capability_fingerprint=model.capability_fingerprint, profile_id="sw-CD",
        profile_identity_sha256=profile.evaluation_identity_sha256, capability="GRAMMAR_ANALYSIS",
        status="NOT_QUALIFIED", minimum_reasoning=None, quality_score=.4, reliability_score=.5,
        confidence="HIGH", value="LOW", evidence_basis="MEASURED", estimated_unit_cost_usd=.004,
        evaluated_at="2026-09-25T00:00:00Z", evidence_sha256="c" * 64,
    ))
    Publisher(repo, authority_id="biblica-sqs-production", publication_epoch=1, output_paths=()).publish(actor="ADMIN")
    assert repo.language_request_status(profile_id="sw-CD", capability="GRAMMAR_ANALYSIS") == "NOT_QUALIFIED"
