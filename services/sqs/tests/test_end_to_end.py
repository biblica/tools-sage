import json
from pathlib import Path

from fastapi.testclient import TestClient

from sage_sqs.admin import AdminApp
from sage_sqs.api import create_app
from sage_sqs.bootstrap import bootstrap_from_config
from sage_sqs.db import Database
from sage_sqs.publisher import Publisher
from sage_sqs.providers.base import ProviderResult
from sage_sqs.repository import Repository
from sage_sqs.worker import Worker


class PassingProvider:
    def execute(self, *, model_id, reasoning, prompt):
        # Medium is production-capable; Low deliberately fails the first critical case.
        passed = reasoning != "low"
        if "rewrite.changed" in prompt:
            no_change = "no_change" in prompt
            payload = {"rewrite": {
                "changed": False if (passed and no_change) else bool(passed),
                "preserved": bool(passed),
                "authorized_only": bool(passed),
            }}
        else:
            diagnostics = [
                "meaning_preservation", "negation_scope", "participant_reference",
                "morphology_syntax_agreement", "clause_relationship_ambiguity", "zero_finding",
            ]
            diagnostic = next((value for value in diagnostics if value in prompt), "other")
            if passed and diagnostic == "zero_finding":
                finding = {"material": False, "relation": "none"}
            elif passed:
                finding = {"material": True, "relation": diagnostic}
            else:
                finding = {"material": False, "relation": "other"}
            payload = {"finding": finding}
        return ProviderResult(text=json.dumps(payload), input_tokens=100, output_tokens=20, usage_raw={})


def test_discovery_to_published_qualification(tmp_path):
    root = Path(__file__).resolve().parents[1]
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    bootstrap_from_config(repo, root / "config")
    publisher = Publisher(repo, authority_id="biblica-sqs-production", publication_epoch=1, output_paths=())
    admin = AdminApp(repo, publisher=publisher)
    client = TestClient(create_app(repo))

    model = repo.latest_model("openai", "gpt-5.6-terra")
    response = client.post("/discoveries", json={
        "kind": "MODEL", "sage_version": "0.02a1",
        "observed": {
            "provider_family": "openai", "model_id": model.model_id,
            "reasoning_levels": list(model.reasoning_levels),
            "capability_fingerprint": model.capability_fingerprint,
        },
    })
    assert response.status_code == 202

    admin.approve_profile("en-US")
    admin.approve_tier_mapping("gpt-5.6-terra")
    admin.approve_model("gpt-5.6-terra")
    admin.queue_evaluation(model_id="gpt-5.6-terra", profile_id="en-US", capability="GRAMMAR_ANALYSIS")
    Worker(repo, provider=PassingProvider(), pack_dir=root / "config" / "evaluation-packs", execution_channel="codex_workspace").drain(max_items=4)
    admin.publish_bundle()

    rows = client.get("/qualifications?profile_id=en-US&capability=GRAMMAR_ANALYSIS&model_id=gpt-5.6-terra").json()
    assert len(rows) == 1
    assert rows[0]["status"] == "QUALIFIED"
    assert rows[0]["minimum_reasoning"] == "medium"
    assert rows[0]["confidence"] == "HIGH"
    assert rows[0]["model_capability_fingerprint"] == model.capability_fingerprint


def test_public_bundle_contains_no_private_host_fields(tmp_path):
    root = Path(__file__).resolve().parents[1]
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    bootstrap_from_config(repo, root / "config")
    Publisher(repo, authority_id="biblica-sqs-production", publication_epoch=1, output_paths=()).publish(actor="ADMIN")
    bundle = TestClient(create_app(repo)).get("/bundle").json()
    text = json.dumps(bundle).casefold()
    forbidden = {"scripture", "usfm", "usj", "job_id", "project_id", "api_key", "authorization", "prompt"}
    assert all(word not in text for word in forbidden)
