from pathlib import Path

from sage_sqs.admin import AdminApp
from sage_sqs.db import Database
from sage_sqs.domain import LanguageProfile, ModelRecord
from sage_sqs.publisher import Publisher
from sage_sqs.repository import Repository


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
