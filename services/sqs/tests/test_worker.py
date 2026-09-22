import json
from pathlib import Path

from sage_sqs.db import Database
from sage_sqs.domain import LanguageProfile, ModelRecord
from sage_sqs.providers.base import ProviderResult
from sage_sqs.repository import Repository
from sage_sqs.worker import Worker, claim_next_planned_test


class FakeProvider:
    def __init__(self, pass_map=None, *, error=None):
        self.pass_map = pass_map or {"medium": True, "low": False, "high": True}
        self.error = error
        self.calls = []

    def execute(self, *, model_id, reasoning, prompt):
        self.calls.append(reasoning)
        if self.error:
            raise self.error
        passed = self.pass_map.get(reasoning, False)
        if "rewrite.changed" in prompt:
            no_change = "no_change" in prompt
            rewrite = {
                "changed": False if (passed and no_change) else bool(passed),
                "preserved": bool(passed),
                "authorized_only": bool(passed),
            }
            return ProviderResult(text=json.dumps({"rewrite": rewrite}), input_tokens=100, output_tokens=20, usage_raw={})
        diagnostics = [
            "meaning_preservation", "negation_scope", "participant_reference",
            "morphology_syntax_agreement", "clause_relationship_ambiguity", "zero_finding",
        ]
        diagnostic = next((name for name in diagnostics if name in prompt), "other")
        if passed and diagnostic == "zero_finding":
            finding = {"material": False, "relation": "none"}
        elif passed:
            finding = {"material": True, "relation": diagnostic}
        else:
            finding = {"material": False, "relation": "other"}
        return ProviderResult(text=json.dumps({"finding": finding}), input_tokens=100, output_tokens=20, usage_raw={})



def setup_repo(tmp_path):
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    profile = LanguageProfile("en-US", "English", "ACTIVE", 1, 1, "english", "en", "eng", "Latn", "US")
    model = ModelRecord("openai", "gpt-x", "APPROVED", 1, ("low", "medium", "high"), "a" * 64, 2.0, 12.0, 2, 2)
    repo.save_profile(profile)
    repo.save_model(model)
    return repo


def pack_dir():
    return Path(__file__).resolve().parents[1] / "config" / "evaluation-packs"


def test_claim_is_transactional_and_marks_running(tmp_path):
    repo = setup_repo(tmp_path)
    item = repo.queue_test({"profile_id": "en-US", "model_id": "gpt-x", "capability": "GRAMMAR_ANALYSIS", "reasoning": "medium"})
    claimed = claim_next_planned_test(repo)
    assert claimed["id"] == item["id"]
    assert repo.evaluation_status(item["id"]) == "RUNNING"
    assert claim_next_planned_test(repo) is None


def test_list_pending_evaluations_is_read_only(tmp_path):
    repo = setup_repo(tmp_path)
    item = repo.queue_test({"profile_id": "en-US", "model_id": "gpt-x", "capability": "GRAMMAR_ANALYSIS", "reasoning": "medium"})
    pending = repo.list_pending_evaluations()
    assert pending == [{
        "id": item["id"], "provider_family": "openai", "profile_id": "en-US",
        "model_id": "gpt-x", "capability": "GRAMMAR_ANALYSIS", "reasoning": "medium", "scope": "FULL",
    }]
    assert repo.evaluation_status(item["id"]) == "PENDING"
    assert repo.list_pending_evaluations() == pending  # calling it again does not claim or mutate


def test_list_pending_evaluations_excludes_running_and_completed(tmp_path):
    repo = setup_repo(tmp_path)
    repo.queue_test({"profile_id": "en-US", "model_id": "gpt-x", "capability": "GRAMMAR_ANALYSIS", "reasoning": "medium"})
    claim_next_planned_test(repo)
    assert repo.list_pending_evaluations() == []


def test_worker_does_not_reexecute_completed_test(tmp_path):
    repo = setup_repo(tmp_path)
    item = repo.queue_test({"profile_id": "en-US", "model_id": "gpt-x", "capability": "GRAMMAR_ANALYSIS", "reasoning": "medium"})
    worker = Worker(repo, provider=FakeProvider(), pack_dir=pack_dir(), execution_channel="codex_workspace")
    assert worker.run_once() is True
    worker.run_once()  # may process newly replanned work, but never this completed row again
    assert repo.attempt_count(item["id"]) == 1
    assert repo.evaluation_status(item["id"]) == "COMPLETED"
    rows = repo.publishable_qualifications()
    assert rows[0].minimum_reasoning == "medium"


def test_worker_honors_queued_predecessor_start(tmp_path):
    repo = setup_repo(tmp_path)
    repo.queue_test({"profile_id": "en-US", "model_id": "gpt-x", "capability": "GRAMMAR_ANALYSIS", "reasoning": "high"})
    provider = FakeProvider({"high": True, "medium": False, "low": False})
    Worker(repo, provider=provider, pack_dir=pack_dir(), execution_channel="codex_workspace").run_once()
    assert provider.calls[0] == "high"


def test_worker_failure_creates_attention_and_preserves_prior_evidence(tmp_path):
    repo = setup_repo(tmp_path)
    repo.queue_test({"profile_id": "en-US", "model_id": "gpt-x", "capability": "GRAMMAR_ANALYSIS", "reasoning": "medium"})
    worker = Worker(repo, provider=FakeProvider(error=RuntimeError("provider down")), pack_dir=pack_dir(), execution_channel="codex_workspace")
    assert worker.run_once() is True
    assert repo.list_attention()[0]["category"] == "EVALUATION_FAILURE"
    assert repo.publishable_qualifications() == []


def test_successful_worker_replans_remaining_exact_candidate(tmp_path):
    repo = setup_repo(tmp_path)
    first = repo.latest_model("openai", "gpt-x")
    second = ModelRecord("openai", "gpt-y", "APPROVED", 1, ("low", "medium", "high"), "e" * 64, 3.0, 15.0, 3, 3)
    repo.save_model(second)
    repo.queue_test({"provider_family": "openai", "profile_id": "en-US", "model_id": first.model_id, "capability": "GRAMMAR_ANALYSIS", "reasoning": "medium", "scope": "FULL"})
    worker = Worker(repo, provider=FakeProvider(), pack_dir=pack_dir(), execution_channel="codex_workspace")
    assert worker.run_once() is True
    pending = repo.db.connection.execute("SELECT payload_json FROM evaluation_runs WHERE status='PENDING'").fetchall()
    assert len(pending) == 1
    next_payload = json.loads(pending[0][0])
    assert (next_payload["model_id"], next_payload["capability"]) != ("gpt-x", "GRAMMAR_ANALYSIS")
