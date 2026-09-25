from dataclasses import asdict
from pathlib import Path

import pytest

import yaml

from sage_sqs.admin import AdminApp
from sage_sqs.db import Database
from sage_sqs.domain import LanguageProfile, ModelRecord, Qualification
from sage_sqs.ingest import stage_submission
from sage_sqs.profile_validation import validate_profile
from sage_sqs.publisher import Publisher
from sage_sqs.repository import Repository
from test_ingest import _submission


def setup(tmp_path):
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    repo.save_profile(LanguageProfile("en-US", "English", "REVIEW_REQUIRED", 1, 1, "english", "en", "eng", "Latn", "US"))
    repo.save_model(ModelRecord("openai", "gpt-x", "CANDIDATE", 1, ("low", "medium", "high"), "a"*64, 2.0, 12.0, 2, 2))
    publisher = Publisher(repo, authority_id="biblica-sqs-production", publication_epoch=1, output_paths=())
    return repo, AdminApp(repo, publisher=publisher)


def test_admin_starts_with_status_and_attention(tmp_path, capsys):
    _, app = setup(tmp_path)
    app.render_home()
    text = capsys.readouterr().out
    assert "SAGE Qualification Service (SQS) 0.02a1" in text
    assert "Attention required" in text
    assert "Tests pruned" in text


def test_admin_menu_is_locked_one_to_nine(tmp_path):
    _, app = setup(tmp_path)
    text = app.menu_text()
    for item in [
        "1. Review attention items", "2. Language profiles", "3. OpenAI models",
        "4. Qualifications", "5. Run / review evaluations", "6. Host discoveries",
        "7. Publish bundle", "8. Logs / audit", "9. Service status", "0. Exit",
    ]:
        assert item in text


def test_admin_cannot_set_qualified_directly(tmp_path):
    _, app = setup(tmp_path)
    assert not hasattr(app, "set_qualification_status")


def test_admin_can_approve_profile_and_model_then_queue_evaluation(tmp_path):
    repo, app = setup(tmp_path)
    app.approve_profile("en-US")
    app.approve_model("gpt-x")
    item = app.queue_evaluation(model_id="gpt-x", profile_id="en-US", capability="GRAMMAR_ANALYSIS")
    assert repo.latest_profile("en-US").status == "ACTIVE"
    assert repo.latest_model("openai", "gpt-x").status == "APPROVED"
    assert repo.evaluation_status(item["id"]) == "PENDING"


def test_admin_publish_is_explicit_and_audited(tmp_path):
    repo, app = setup(tmp_path)
    app.approve_profile("en-US")
    app.approve_model("gpt-x")
    bundle = app.publish_bundle()
    assert bundle["bundle_revision"] == 1
    row = repo.db.connection.execute("SELECT action FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
    assert row[0] == "PUBLISH_BUNDLE"


def test_admin_cannot_manually_construct_qualifications(tmp_path):
    _, app = setup(tmp_path)
    assert not hasattr(app, "set_qualification_status")
    assert not hasattr(app, "enter_qualification")


def test_admin_approving_a_submission_publishes_the_measured_result(tmp_path):
    repo, app = setup(tmp_path)
    app.approve_profile("en-US")
    app.approve_model("gpt-x")
    item = app.queue_evaluation(model_id="gpt-x", profile_id="en-US", capability="GRAMMAR_ANALYSIS")
    identity = repo.latest_profile("en-US").evaluation_identity_sha256
    receipt = stage_submission(repo, _submission(item["id"], profile_identity_sha256=identity))

    app.review_qualification_submission(receipt.attention_key, decision="APPROVE")

    assert repo.evaluation_status(item["id"]) == "COMPLETED"
    assert repo.attempt_count(item["id"]) == 1
    assert repo.list_attention() == []
    published = repo.publishable_qualifications()
    assert len(published) == 1
    assert published[0].model_id == "gpt-x"
    assert published[0].status == "QUALIFIED"
    row = repo.db.connection.execute("SELECT action FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
    assert row[0] == "APPROVE_QUALIFICATION_SUBMISSION"


def test_admin_rejecting_a_submission_fails_the_run_and_never_publishes(tmp_path):
    repo, app = setup(tmp_path)
    app.approve_profile("en-US")
    app.approve_model("gpt-x")
    item = app.queue_evaluation(model_id="gpt-x", profile_id="en-US", capability="GRAMMAR_ANALYSIS")
    receipt = stage_submission(repo, _submission(item["id"]))

    app.review_qualification_submission(receipt.attention_key, decision="REJECT")

    assert repo.evaluation_status(item["id"]) == "FAILED"
    assert repo.list_attention() == []
    assert repo.publishable_qualifications() == []


def test_review_qualification_submission_rejects_an_unknown_attention_key(tmp_path):
    _, app = setup(tmp_path)
    with pytest.raises(ValueError):
        app.review_qualification_submission("QUALIFICATION_SUBMISSION:missing", decision="APPROVE")


def test_admin_provider_refresh_invalidates_changed_fingerprint(tmp_path):
    import yaml
    repo, app = setup(tmp_path)
    source = Path(__file__).resolve().parents[1] / "seed" / "openai-provider.yml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["models"] = [row for row in payload["models"] if row["model_id"] == "gpt-x"] or [{
        "model_id": "gpt-x", "capability_rank": 2, "cost_rank": 2,
        "reasoning_levels": ["low", "medium", "high"], "input_usd_per_mtok": 2.1,
        "output_usd_per_mtok": 12.0, "status": "CANDIDATE",
    }]
    # The seed has different IDs; force one exact current model entry with changed price.
    payload["models"] = [{
        "model_id": "gpt-x", "capability_rank": 2, "cost_rank": 2,
        "reasoning_levels": ["low", "medium", "high"], "input_usd_per_mtok": 2.1,
        "output_usd_per_mtok": 12.0, "status": "CANDIDATE",
    }]
    path = tmp_path / "provider.yml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    app.approve_model("gpt-x")
    rows = app.refresh_provider_metadata(path)
    assert rows[0].changed is True
    assert repo.latest_model("openai", "gpt-x").revision == 2
    assert repo.latest_model("openai", "gpt-x").status == "REVIEW_REQUIRED"


def test_draft_language_profile_seed_writes_an_identity_stub(tmp_path):
    repo, app = setup(tmp_path)
    seed_dir = tmp_path / "seed" / "languages"
    path = app.draft_language_profile_seed(
        profile_id="sw-CD", language_code="sw", script="Latn", region="CD",
        requested_capability="GRAMMAR_ANALYSIS", seed_dir=seed_dir,
    )
    assert path == seed_dir / "sw-CD.yml"
    stub = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert stub["profile_id"] == "sw-CD"
    assert stub["identity"] == {"iso_639_1": "sw", "iso_639_3": "", "script": "Latn", "region": "CD"}
    assert stub["capabilities"] == ["GRAMMAR_ANALYSIS", "SEMANTIC_REWRITE"]
    assert stub["profile_build"]["evaluation_pack_state"] == "BUILD_REQUIRED"
    row = repo.db.connection.execute("SELECT action FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
    assert row[0] == "DRAFT_LANGUAGE_PROFILE_SEED"


def test_draft_language_profile_seed_refuses_to_overwrite_an_existing_file(tmp_path):
    _, app = setup(tmp_path)
    seed_dir = tmp_path / "seed" / "languages"
    app.draft_language_profile_seed(
        profile_id="sw-CD", language_code="sw", script="Latn", region="CD",
        requested_capability="GRAMMAR_ANALYSIS", seed_dir=seed_dir,
    )
    with pytest.raises(ValueError):
        app.draft_language_profile_seed(
            profile_id="sw-CD", language_code="sw", script="Latn", region="CD",
            requested_capability="SEMANTIC_REWRITE", seed_dir=seed_dir,
        )


def test_draft_language_profile_seed_still_requires_admin_judgment_to_pass_validation(tmp_path):
    """The scaffolded stub fails validate_profile() until ADMIN sets tier/cluster/iso_639_3 -- it never fabricates those."""
    _, app = setup(tmp_path)
    seed_dir = tmp_path / "seed" / "languages"
    path = app.draft_language_profile_seed(
        profile_id="sw-CD", language_code="sw", script="Latn", region="CD",
        requested_capability="GRAMMAR_ANALYSIS", seed_dir=seed_dir,
    )
    stub = yaml.safe_load(path.read_text(encoding="utf-8"))
    issues = {issue.code for issue in validate_profile(stub)}
    assert "INVALID_TIER" in issues
    assert "MISSING_CLUSTER" in issues
