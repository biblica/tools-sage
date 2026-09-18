from fastapi.testclient import TestClient

from sage_sqs.api import create_app
from sage_sqs.db import Database
from sage_sqs.domain import LanguageProfile, ModelRecord, Qualification
from sage_sqs.publisher import Publisher
from sage_sqs.repository import Repository


def seeded_client(tmp_path):
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    profile = LanguageProfile("uk-UA", "Ukrainian", "ACTIVE", 1, 2, "east-slavic", "uk", "ukr", "Cyrl", "UA")
    model = ModelRecord("openai", "gpt-x", "APPROVED", 1, ("low", "medium", "high"), "a" * 64, 2.0, 12.0, 2, 2)
    repo.save_profile(profile)
    repo.save_model(model)
    repo.save_qualification(Qualification(
        provider_family="openai", execution_channel="codex_workspace", model_id="gpt-x", model_capability_fingerprint="a" * 64,
        profile_id="uk-UA", profile_identity_sha256=profile.evaluation_identity_sha256,
        capability="GRAMMAR_ANALYSIS", status="QUALIFIED", minimum_reasoning="medium",
        quality_score=.96, reliability_score=.98, confidence="HIGH", value="HIGH", evidence_basis="MEASURED",
        estimated_unit_cost_usd=.004, evaluated_at="2026-08-31T10:00:00Z", evidence_sha256="b" * 64,
    ))
    Publisher(repo, authority_id="biblica-sqs-production", publication_epoch=1, output_paths=()).publish(actor="ADMIN")
    return TestClient(create_app(repo))


def test_health_reports_published_revision(tmp_path):
    client = seeded_client(tmp_path)
    assert client.get("/health").json() == {"status": "OK", "service_version": "0.02a1", "bundle_revision": 1}


def test_public_catalog_endpoints_are_views_of_stored_publication(tmp_path):
    client = seeded_client(tmp_path)
    assert client.get("/profiles").json()[0]["profile_id"] == "uk-UA"
    assert client.get("/profiles/uk-UA").status_code == 200
    assert client.get("/profiles/missing").status_code == 404
    assert client.get("/models").json()[0]["model_id"] == "gpt-x"
    assert client.get("/qualifications?profile_id=uk-UA&capability=GRAMMAR_ANALYSIS").json()[0]["model_id"] == "gpt-x"


def test_bundle_etag_supports_not_modified(tmp_path):
    client = seeded_client(tmp_path)
    first = client.get("/bundle")
    assert first.status_code == 200
    etag = first.headers["etag"]
    second = client.get("/bundle", headers={"If-None-Match": etag})
    assert second.status_code == 304


def test_no_v1_route_exists(tmp_path):
    client = seeded_client(tmp_path)
    assert client.get("/v1/bundle").status_code == 404
