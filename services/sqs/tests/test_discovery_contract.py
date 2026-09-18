from __future__ import annotations

from fastapi.testclient import TestClient

from sage_sqs.api import create_app
from sage_sqs.db import Database
from sage_sqs.repository import Repository


def _client(tmp_path):
    return TestClient(create_app(Repository(Database.open(tmp_path / "sqs.db"))))


def test_model_discovery_requires_exact_capability_fingerprint(tmp_path):
    client = _client(tmp_path)
    payload = {
        "kind": "MODEL",
        "sage_version": "0.02a1",
        "observed": {
            "provider_family": "openai",
            "model_id": "gpt-new",
            "reasoning_levels": ["low", "medium", "high"],
            "capability_fingerprint": "a" * 64,
        },
    }
    assert client.post("/discoveries", json=payload).status_code == 202


def test_discovery_rejects_extra_content_or_credentials(tmp_path):
    client = _client(tmp_path)
    base = {
        "kind": "MODEL",
        "sage_version": "0.02a1",
        "observed": {
            "provider_family": "openai",
            "model_id": "gpt-new",
            "reasoning_levels": ["medium"],
            "capability_fingerprint": "a" * 64,
        },
    }
    with_content = {**base, "scripture": "text"}
    assert client.post("/discoveries", json=with_content).status_code == 400
    with_secret = {**base, "observed": {**base["observed"], "token": "secret"}}
    assert client.post("/discoveries", json=with_secret).status_code == 400


def test_language_discovery_is_exact_metadata_only(tmp_path):
    client = _client(tmp_path)
    payload = {
        "kind": "LANGUAGE_PROFILE",
        "sage_version": "0.02a1",
        "observed": {
            "profile_id": "sw-CD",
            "language_code": "sw",
            "script": "Latn",
            "region": "CD",
        },
    }
    assert client.post("/discoveries", json=payload).status_code == 202
