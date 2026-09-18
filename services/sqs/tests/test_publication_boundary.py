from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from sage_sqs.api import create_app
from sage_sqs.db import Database
from sage_sqs.domain import LanguageProfile, ModelRecord, Qualification
from sage_sqs.publisher import Publisher
from sage_sqs.repository import Repository


def _repo(tmp_path: Path) -> Repository:
    return Repository(Database.open(tmp_path / "sqs.db"))


def _seed(repo: Repository) -> None:
    profile = LanguageProfile(
        profile_id="uk-UA",
        display_name="Ukrainian (Ukraine)",
        status="ACTIVE",
        revision=1,
        tier=2,
        cluster="slavic-east",
        iso_639_1="uk",
        iso_639_3="ukr",
        script="Cyrl",
        region="UA",
    )
    model = ModelRecord(
        provider_family="openai",
        model_id="gpt-5.6-terra",
        status="APPROVED",
        revision=1,
        reasoning_levels=("low", "medium", "high"),
        capability_fingerprint="a" * 64,
        input_usd_per_mtok=2.0,
        output_usd_per_mtok=12.0,
    )
    repo.save_profile(profile)
    repo.save_model(model)
    repo.save_qualification(Qualification(
        provider_family="openai",
        execution_channel="codex_workspace",
        model_id=model.model_id,
        model_capability_fingerprint=model.capability_fingerprint,
        profile_id=profile.profile_id,
        profile_identity_sha256=profile.evaluation_identity_sha256,
        capability="GRAMMAR_ANALYSIS",
        status="QUALIFIED",
        minimum_reasoning="medium",
        quality_score=0.96,
        reliability_score=0.98,
        confidence="HIGH",
        value="HIGH",
        evidence_basis="MEASURED",
        estimated_unit_cost_usd=0.0042,
        evaluated_at="2026-08-31T10:00:00Z",
        evidence_sha256="b" * 64,
    ))


def test_unpublished_db_state_is_not_public(tmp_path: Path):
    repo = _repo(tmp_path)
    _seed(repo)
    assert repo.current_published_bundle() is None
    client = TestClient(create_app(repo))
    response = client.get("/bundle")
    assert response.status_code == 503
    assert response.json()["detail"] == "NO_PUBLISHED_BUNDLE"


def test_publish_creates_explicit_authority_identity_and_exact_replicas(tmp_path: Path):
    repo = _repo(tmp_path)
    _seed(repo)
    primary = tmp_path / "primary" / "bundle.json"
    replica = tmp_path / "replica" / "bundle.json"
    publisher = Publisher(
        repo,
        authority_id="biblica-sqs-production",
        publication_epoch=1,
        output_paths=(primary, replica),
    )

    bundle = publisher.publish(actor="ADMIN")

    assert bundle["authority_id"] == "biblica-sqs-production"
    assert bundle["publication_epoch"] == 1
    assert bundle["bundle_revision"] == 1
    assert bundle["profiles"][0]["evaluation_identity_sha256"]
    assert bundle["qualifications"][0]["profile_identity_sha256"] == bundle["profiles"][0]["evaluation_identity_sha256"]
    assert primary.read_bytes() == replica.read_bytes()
    assert json.loads(primary.read_text(encoding="utf-8"))["bundle_sha256"] == bundle["bundle_sha256"]
    assert repo.current_published_bundle() == bundle


def test_public_api_serves_only_stored_publication(tmp_path: Path):
    repo = _repo(tmp_path)
    _seed(repo)
    Publisher(repo, authority_id="biblica-sqs-production", publication_epoch=1, output_paths=()).publish(actor="ADMIN")
    client = TestClient(create_app(repo))
    response = client.get("/bundle")
    assert response.status_code == 200
    assert response.json()["bundle_revision"] == 1
    assert response.headers["etag"] == f'"{response.json()["bundle_sha256"]}"'


def test_next_publication_revision_is_monotonic(tmp_path: Path):
    repo = _repo(tmp_path)
    _seed(repo)
    publisher = Publisher(repo, authority_id="biblica-sqs-production", publication_epoch=1, output_paths=())
    assert publisher.publish(actor="ADMIN")["bundle_revision"] == 1
    assert publisher.publish(actor="ADMIN")["bundle_revision"] == 2
