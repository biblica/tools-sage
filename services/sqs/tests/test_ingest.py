import json
from dataclasses import asdict
from pathlib import Path

import pytest

from sage_sqs.db import Database
from sage_sqs.domain import LanguageProfile, ModelRecord, Qualification
from sage_sqs.ingest import SubmissionValidationError, ingest_incoming_directory, stage_submission, validate_submission
from sage_sqs.repository import Repository


def setup_repo(tmp_path):
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    repo.save_profile(LanguageProfile("en-US", "English", "ACTIVE", 1, 1, "english", "en", "eng", "Latn", "US"))
    repo.save_model(ModelRecord("openai", "gpt-x", "APPROVED", 1, ("low", "medium", "high"), "a" * 64, 2.0, 12.0, 2, 2))
    return repo


def _qualification_dict(**overrides) -> dict:
    base = Qualification(
        provider_family="openai", execution_channel="codex_workspace", model_id="gpt-x",
        model_capability_fingerprint="a" * 64, profile_id="en-US", profile_identity_sha256="c" * 64,
        capability="GRAMMAR_ANALYSIS", status="QUALIFIED", minimum_reasoning="medium",
        quality_score=.96, reliability_score=.98, confidence="HIGH", value="HIGH", evidence_basis="MEASURED",
        estimated_unit_cost_usd=.004, evaluated_at="2026-09-22T10:00:00Z", evidence_sha256="b" * 64,
    )
    return {**asdict(base), **overrides}


def _submission(run_id: str, **qualification_overrides) -> dict:
    return {
        "schema": "sage-sqs-qualification-submission-1.0",
        "run_id": run_id,
        "submitted_by": "pieter.traut@biblica.com",
        "submitted_at": "2026-09-22T10:05:00Z",
        "qualification": _qualification_dict(**qualification_overrides),
        "attempt": {
            "minimum_reasoning": "medium", "quality_score": .96, "reliability_score": .98,
            "total_input_tokens": 1000, "total_output_tokens": 200, "estimated_unit_cost_usd": .004,
            "reasoning_runs": ["medium"],
        },
    }


def test_validate_submission_rejects_unknown_shape():
    with pytest.raises(SubmissionValidationError):
        validate_submission({"schema": "sage-sqs-qualification-submission-1.0"})


def test_validate_submission_rejects_wrong_schema_id():
    payload = _submission("run-1")
    payload["schema"] = "not-a-real-schema"
    with pytest.raises(SubmissionValidationError):
        validate_submission(payload)


def test_stage_submission_creates_a_review_attention_item(tmp_path):
    repo = setup_repo(tmp_path)
    item = repo.queue_test({"profile_id": "en-US", "model_id": "gpt-x", "capability": "GRAMMAR_ANALYSIS", "reasoning": "medium"})
    receipt = stage_submission(repo, _submission(item["id"]))
    assert receipt.attention_key == f"QUALIFICATION_SUBMISSION:{item['id']}"
    attention = repo.list_attention()
    assert len(attention) == 1
    assert attention[0]["category"] == "QUALIFICATION_SUBMISSION"
    # Staging never writes the qualification or completes the run -- that is ADMIN's call.
    assert repo.evaluation_status(item["id"]) == "PENDING"
    assert repo.publishable_qualifications() == []


def test_stage_submission_rejects_a_run_that_does_not_exist(tmp_path):
    repo = setup_repo(tmp_path)
    with pytest.raises(SubmissionValidationError):
        stage_submission(repo, _submission("unknown-run-id"))


def test_stage_submission_rejects_a_run_that_is_not_pending(tmp_path):
    repo = setup_repo(tmp_path)
    item = repo.queue_test({"profile_id": "en-US", "model_id": "gpt-x", "capability": "GRAMMAR_ANALYSIS", "reasoning": "medium"})
    repo.complete_evaluation(item["id"])
    with pytest.raises(SubmissionValidationError):
        stage_submission(repo, _submission(item["id"]))


def test_stage_submission_rejects_a_submission_for_a_different_model_than_the_run(tmp_path):
    repo = setup_repo(tmp_path)
    item = repo.queue_test({"profile_id": "en-US", "model_id": "gpt-x", "capability": "GRAMMAR_ANALYSIS", "reasoning": "medium"})
    with pytest.raises(SubmissionValidationError):
        stage_submission(repo, _submission(item["id"], model_id="gpt-mismatched"))


def test_ingest_incoming_directory_stages_valid_files_and_moves_them_to_processed(tmp_path):
    repo = setup_repo(tmp_path)
    item = repo.queue_test({"profile_id": "en-US", "model_id": "gpt-x", "capability": "GRAMMAR_ANALYSIS", "reasoning": "medium"})
    incoming, processed, rejected = tmp_path / "incoming", tmp_path / "processed", tmp_path / "rejected"
    incoming.mkdir()
    (incoming / "result-1.json").write_text(json.dumps(_submission(item["id"])), encoding="utf-8")

    outcomes = ingest_incoming_directory(repo, incoming_dir=incoming, processed_dir=processed, rejected_dir=rejected)

    assert outcomes == [{
        "file": "result-1.json", "status": "STAGED",
        "run_id": item["id"], "attention_key": f"QUALIFICATION_SUBMISSION:{item['id']}",
    }]
    assert not (incoming / "result-1.json").exists()
    assert (processed / "result-1.json").exists()
    assert not (rejected / "result-1.json").exists()


def test_ingest_incoming_directory_moves_invalid_files_to_rejected_without_touching_the_repo(tmp_path):
    repo = setup_repo(tmp_path)
    incoming, processed, rejected = tmp_path / "incoming", tmp_path / "processed", tmp_path / "rejected"
    incoming.mkdir()
    (incoming / "garbage.json").write_text("not json", encoding="utf-8")

    outcomes = ingest_incoming_directory(repo, incoming_dir=incoming, processed_dir=processed, rejected_dir=rejected)

    assert outcomes[0]["status"] == "REJECTED"
    assert (rejected / "garbage.json").exists()
    assert repo.list_attention() == []
