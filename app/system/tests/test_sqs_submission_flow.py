"""End-to-end preparation of one SQS qualification-submission file (Codex-workspace provider plan)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sage.sqs_submission_flow import (
    PlannedEvaluationNotRunnable,
    SqsSubmissionUploadError,
    prepare_submission,
    upload_submission_file,
    write_submission_file,
)

_APP_ROOT = Path(__file__).resolve().parents[2]
_PACK_DIR = _APP_ROOT.parent / "services" / "sqs" / "config" / "evaluation-packs"


class FakeProvider:
    """Deterministic in-process provider matching the exact case shape the real packs use."""

    def __init__(self, pass_map: dict[str, bool] | None = None):
        """Store which reasoning levels should pass every case."""
        self.pass_map = pass_map or {"medium": True, "low": False, "high": True}
        self.calls: list[str] = []

    def execute(self, *, model_id: str, reasoning: str, prompt: str):
        """Return a scripted finding matching this fixture pack's diagnostic_class convention."""
        from sage_sqs.providers.base import ProviderResult

        self.calls.append(reasoning)
        passed = self.pass_map.get(reasoning, False)
        diagnostics = (
            "meaning_preservation", "negation_scope", "participant_reference",
            "morphology_syntax_agreement", "clause_relationship_ambiguity", "zero_finding",
        )
        diagnostic = next((name for name in diagnostics if name in prompt), "other")
        if passed and diagnostic == "zero_finding":
            finding = {"material": False, "relation": "none"}
        elif passed:
            finding = {"material": True, "relation": diagnostic}
        else:
            finding = {"material": False, "relation": "other"}
        return ProviderResult(text=json.dumps({"finding": finding}), input_tokens=100, output_tokens=20, usage_raw={})


def _bundle(*, profile_id: str = "en-US", model_id: str = "gpt-x") -> dict:
    """Build a minimal bundle-shaped dict carrying just the fields prepare_submission reads."""
    return {
        "profiles": [{"profile_id": profile_id, "evaluation_identity_sha256": "c" * 64}],
        "models": [{
            "provider_family": "openai", "model_id": model_id, "capability_fingerprint": "a" * 64,
            "input_usd_per_mtok": 2.0, "output_usd_per_mtok": 12.0,
        }],
    }


def _planned_evaluation(**overrides) -> dict:
    """Build one GET /planned-evaluations row, as the server would return it."""
    base = {
        "id": "run-abc123", "provider_family": "openai", "profile_id": "en-US",
        "model_id": "gpt-x", "capability": "GRAMMAR_ANALYSIS", "reasoning": "medium", "scope": "FULL",
    }
    return {**base, **overrides}


def test_prepare_submission_runs_a_real_pack_and_builds_a_valid_submission():
    """Running against a real evaluation-pack fixture produces a complete, correctly shaped submission."""
    submission = prepare_submission(
        planned_evaluation=_planned_evaluation(),
        bundle=_bundle(),
        pack_dir=_PACK_DIR,
        sage_root=_APP_ROOT,
        submitted_by="pieter.traut@biblica.com",
        provider=FakeProvider(),
    )
    assert submission["schema"] == "sage-sqs-qualification-submission-1.0"
    assert submission["run_id"] == "run-abc123"
    assert submission["qualification"]["model_id"] == "gpt-x"
    assert submission["qualification"]["profile_id"] == "en-US"
    assert submission["qualification"]["status"] == "QUALIFIED"
    assert submission["attempt"]["minimum_reasoning"] == "medium"
    assert submission["attempt"]["total_input_tokens"] > 0


def test_prepare_submission_raises_for_an_unknown_profile():
    """A planned evaluation naming a profile absent from the local bundle fails closed."""
    with pytest.raises(PlannedEvaluationNotRunnable):
        prepare_submission(
            planned_evaluation=_planned_evaluation(profile_id="zz-ZZ"),
            bundle=_bundle(), pack_dir=_PACK_DIR, sage_root=_APP_ROOT,
            submitted_by="op", provider=FakeProvider(),
        )


def test_prepare_submission_raises_for_an_unknown_model():
    """A planned evaluation naming a model absent from the local bundle fails closed."""
    with pytest.raises(PlannedEvaluationNotRunnable):
        prepare_submission(
            planned_evaluation=_planned_evaluation(model_id="gpt-unknown"),
            bundle=_bundle(), pack_dir=_PACK_DIR, sage_root=_APP_ROOT,
            submitted_by="op", provider=FakeProvider(),
        )


def test_prepare_submission_raises_when_no_pack_exists_for_the_profile_capability():
    """A profile/capability pair with no evaluation pack on disk fails closed, not silently."""
    with pytest.raises(PlannedEvaluationNotRunnable):
        prepare_submission(
            planned_evaluation=_planned_evaluation(capability="SEMANTIC_REWRITE", profile_id="ceb-PH"),
            bundle=_bundle(profile_id="ceb-PH"), pack_dir=_PACK_DIR, sage_root=_APP_ROOT,
            submitted_by="op", provider=FakeProvider(),
        )


def test_write_submission_file_writes_valid_json_named_by_run_id(tmp_path):
    """The written file is named after the run id and round-trips as identical JSON."""
    submission = prepare_submission(
        planned_evaluation=_planned_evaluation(),
        bundle=_bundle(), pack_dir=_PACK_DIR, sage_root=_APP_ROOT,
        submitted_by="op", provider=FakeProvider(),
    )
    path = write_submission_file(submission, tmp_path)
    assert path.name == "run-abc123.json"
    assert json.loads(path.read_text(encoding="utf-8")) == submission


def test_upload_submission_file_raises_when_ssh_host_is_not_configured(tmp_path):
    """An empty ssh_host (the fresh-install default) fails with its own distinct error code."""
    local = tmp_path / "run-abc123.json"
    local.write_text("{}", encoding="utf-8")
    with pytest.raises(SqsSubmissionUploadError) as excinfo:
        upload_submission_file(
            local, ssh_host="", ssh_port=22, ssh_user="sqs-uploader",
            remote_incoming_dir="/var/lib/sage-sqs/incoming", private_key_path=tmp_path / "key",
        )
    assert excinfo.value.code == "SQS_SUBMISSION_NOT_CONFIGURED"


def test_upload_submission_file_raises_a_distinct_error_on_scp_failure(tmp_path):
    """A non-zero scp exit is surfaced as a distinct upload error carrying scp's own stderr."""
    local = tmp_path / "run-abc123.json"
    local.write_text("{}", encoding="utf-8")

    def fake_runner(args, **_kwargs):
        """Simulate a failed scp invocation, e.g. an untrusted host key under BatchMode=yes."""
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="Host key verification failed.")

    with pytest.raises(SqsSubmissionUploadError) as excinfo:
        upload_submission_file(
            local, ssh_host="sqs.example.org", ssh_port=22, ssh_user="sqs-uploader",
            remote_incoming_dir="/var/lib/sage-sqs/incoming", private_key_path=tmp_path / "key",
            runner=fake_runner,
        )
    assert excinfo.value.code == "SQS_SUBMISSION_UPLOAD_FAILED"
    assert "Host key verification failed" in str(excinfo.value)


def test_upload_submission_file_succeeds_and_builds_the_expected_scp_destination(tmp_path):
    """A successful scp call is built with BatchMode=yes and the correct user@host:path destination."""
    local = tmp_path / "run-abc123.json"
    local.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_runner(args, **_kwargs):
        """Capture the constructed scp argv and simulate success."""
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    upload_submission_file(
        local, ssh_host="sqs.example.org", ssh_port=2222, ssh_user="sqs-uploader",
        remote_incoming_dir="/var/lib/sage-sqs/incoming/", private_key_path=tmp_path / "key",
        runner=fake_runner,
    )
    args = captured["args"]
    assert args[0] == "scp"
    assert "-o" in args and "BatchMode=yes" in args
    assert args[-1] == "sqs-uploader@sqs.example.org:/var/lib/sage-sqs/incoming/run-abc123.json"
    assert "2222" in args
