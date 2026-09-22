from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from sage_sqs.db import Database
from sage_sqs.publisher import Publisher
from sage_sqs.repository import Repository
from test_ingest import _submission
from test_publication_boundary import _seed


def test_published_bundle_validates_against_frozen_schema(tmp_path: Path):
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    _seed(repo)
    bundle = Publisher(repo, authority_id="biblica-sqs-production", publication_epoch=1, output_paths=()).publish(actor="ADMIN")
    schema = json.loads(Path("contracts/sqs-bundle.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(bundle, schema)


def test_discovery_contract_matches_wire_vocabulary():
    schema = json.loads(Path("contracts/discovery.schema.json").read_text(encoding="utf-8"))
    model = {
        "kind": "MODEL",
        "sage_version": "0.02a1",
        "observed": {
            "provider_family": "openai",
            "model_id": "gpt-new",
            "reasoning_levels": ["low", "medium", "high"],
            "capability_fingerprint": "a" * 64,
        },
    }
    language = {
        "kind": "LANGUAGE_PROFILE",
        "sage_version": "0.02a1",
        "observed": {"profile_id": "sw-CD", "language_code": "sw", "script": "Latn", "region": "CD"},
    }
    jsonschema.validate(model, schema)
    jsonschema.validate(language, schema)


def test_qualification_submission_contract_matches_wire_vocabulary():
    schema = json.loads(Path("contracts/qualification-submission-1.0.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(_submission("run-1"), schema)
