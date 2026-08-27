"""Provider-neutral SAGE LLM harness, local transport, and resource-mount contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sage.storage import storage_layout
from sage.atomic import atomic_write_json
from sage.errors import ConfigurationError, ValidationError
from sage.evidence_policy import AUTHORIZED_CONTENT_EVIDENCE, task_evidence_policy
from sage.executors.base import ModelCapability, ProviderRequest, ProviderResponse, ProviderStatus, ReasoningEffortOption
from sage.executors.codex_cli import CodexCLIExecutor
from sage.executors.http import validate_local_endpoint
from sage.hashing import sha256_file
from sage.llm_tasks import (
    _materialize_saw_findings,
    _model_read_content,
    _output_schema,
    _parse_response,
    _read_projection_measurement,
    execute_task,
)
from sage.llm_settings import update_llm_selection
from sage.model_policy import recommend_model, validate_explicit_selection
from sage.registry import load_ecosystem
from sage.resource_mounts import mounts_path, set_resource_mount


def _synthetic_task(root: Path, *, conditional: bool = False) -> Path:
    """Create a minimal immutable task for sealed-execution regression tests."""
    evidence = root / "evidence.txt"
    evidence.write_text("bounded evidence\n", encoding="utf-8")
    conditional_evidence = root / "greek.txt"
    conditional_evidence.write_text("conditional OL evidence\n", encoding="utf-8")
    task = storage_layout(root, create=True).system_root / "synthetic-task"
    task.mkdir(parents=True, exist_ok=True)
    (task / "ACT.md").write_text("# Governed task\nReturn the required outputs.\n", encoding="utf-8")
    writes = ["output/result.txt"]
    if conditional:
        writes = ["output/rewrite.usfm", "output/translation-challenges.json"]
    manifest = {
        "task_id": "synthetic-task-1",
        "execution_mode": "SAGE_GOVERNED_TASK_V1",
        "workflow": "bic",
        "operation": "rewrite" if conditional else "inspect",
        "scope": "MAT 1:1",
        "evidence_policy": task_evidence_policy("bic"),
        "allowed_reads": [
            {
                "path": "evidence.txt",
                "sha256": sha256_file(evidence),
                "evidence_class": AUTHORIZED_CONTENT_EVIDENCE,
            }
        ],
        "conditional_reads": (
            [
                {
                    "path": "greek.txt",
                    "sha256": sha256_file(conditional_evidence),
                    "evidence_class": AUTHORIZED_CONTENT_EVIDENCE,
                }
            ]
            if conditional
            else []
        ),
        "allowed_writes": writes,
    }
    path = task / "task-manifest.json"
    atomic_write_json(path, manifest)
    return path


def _fake_codex_status() -> ProviderStatus:
    """Return a live-looking ChatGPT catalog covering SAGE baseline routing tests."""
    sol = ModelCapability(
        id="gpt-5.6-sol",
        model="gpt-5.6-sol",
        display_name="GPT-5.6 Sol",
        supported_reasoning_efforts=tuple(
            ReasoningEffortOption(value) for value in ("low", "medium", "high", "xhigh")
        ),
        default_reasoning_effort="medium",
        is_default=True,
    )
    terra = ModelCapability(
        id="gpt-5.6-terra",
        model="gpt-5.6-terra",
        display_name="GPT-5.6 Terra",
        supported_reasoning_efforts=tuple(
            ReasoningEffortOption(value) for value in ("low", "medium", "high")
        ),
        default_reasoning_effort="medium",
    )
    return ProviderStatus(
        provider="codex",
        available=True,
        ready=True,
        auth_mode="CHATGPT",
        selected_model="gpt-5.6-sol",
        models=("gpt-5.6-sol", "gpt-5.6-terra"),
        model_capabilities=(sol, terra),
        account_plan_type="business",
        diagnostic="verified",
    )


def test_codex_catalog_uses_chatgpt_account_and_applies_xhigh_ceiling(monkeypatch) -> None:
    """Verify live discovery preserves supported order while removing efforts above XHigh."""
    executor = CodexCLIExecutor(command="codex")

    def fake_roundtrip(requests, *, timeout=20):
        """Return deterministic App Server JSON-RPC responses for catalog discovery."""
        result = {0: {"id": 0, "result": {}}}
        for request_id, method, _params in requests:
            if method == "account/read":
                result[request_id] = {
                    "id": request_id,
                    "result": {"account": {"type": "chatgpt", "planType": "business"}},
                }
            elif method == "model/list":
                result[request_id] = {
                    "id": request_id,
                    "result": {
                        "data": [
                            {
                                "id": "gpt-5.6-sol",
                                "model": "gpt-5.6-sol",
                                "displayName": "GPT-5.6 Sol",
                                "isDefault": True,
                                "defaultReasoningEffort": "high",
                                "supportedReasoningEfforts": [
                                    {"reasoningEffort": "medium"},
                                    {"reasoningEffort": "high"},
                                    {"reasoningEffort": "xhigh"},
                                    {"reasoningEffort": "max"},
                                    {"reasoningEffort": "ultra"},
                                    {"reasoningEffort": "future-super-effort"},
                                ],
                            }
                        ],
                        "nextCursor": None,
                    },
                }
        return result

    monkeypatch.setattr(executor, "_app_server_roundtrip", fake_roundtrip)
    auth, plan, models = executor.query_catalog()
    assert auth == "CHATGPT"
    assert plan == "business"
    assert models[0].reasoning_efforts == ("medium", "high", "xhigh")
    assert models[0].default_reasoning_effort == "high"


def test_codex_catalog_drops_provider_default_above_xhigh(monkeypatch) -> None:
    """Verify a provider default above SAGE's hard ceiling is not surfaced as a SAGE default."""
    executor = CodexCLIExecutor(command="codex")

    def fake_roundtrip(requests, *, timeout=20):
        """Return a live-looking model whose provider default exceeds SAGE's ceiling."""
        result = {0: {"id": 0, "result": {}}}
        for request_id, method, _params in requests:
            if method == "account/read":
                result[request_id] = {
                    "id": request_id,
                    "result": {"account": {"type": "chatgpt", "planType": "business"}},
                }
            else:
                result[request_id] = {
                    "id": request_id,
                    "result": {
                        "data": [{
                            "id": "future-model",
                            "model": "future-model",
                            "defaultReasoningEffort": "max",
                            "supportedReasoningEfforts": [
                                {"reasoningEffort": "high"},
                                {"reasoningEffort": "xhigh"},
                                {"reasoningEffort": "max"},
                            ],
                        }],
                        "nextCursor": None,
                    },
                }
        return result

    monkeypatch.setattr(executor, "_app_server_roundtrip", fake_roundtrip)
    _auth, _plan, models = executor.query_catalog()
    assert models[0].reasoning_efforts == ("high", "xhigh")
    assert models[0].default_reasoning_effort is None


def test_codex_prevalidated_execution_reuses_verified_catalog_without_status_probe(monkeypatch) -> None:
    """A task-scoped Codex readiness snapshot may execute multiple phases without re-querying status."""
    import subprocess

    executor = CodexCLIExecutor(command="codex")
    status = _fake_codex_status()
    monkeypatch.setattr(
        executor,
        "status",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("status must not be re-queried")),
    )

    def fake_run(args, **_kwargs):
        """Materialize the schema-constrained response and assert the sealed Codex execution contract."""
        assert args[0] == "--config"
        assert 'model_reasoning_effort="xhigh"' in args
        for token in ("exec", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--color", "never",
                      "--sandbox", "read-only", "--skip-git-repo-check", "--output-schema",
                      "--output-last-message", "--model", "gpt-5.6-sol", "-"):
            assert token in args
        output = Path(args[args.index("--output-last-message") + 1])
        output.write_text('{"result":"ok"}', encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(executor, "_run_governed", fake_run)
    response = executor.execute_prevalidated(
        ProviderRequest(
            prompt="bounded prompt",
            schema={"type": "object"},
            model="gpt-5.6-sol",
            reasoning_effort="xhigh",
        ),
        status,
    )

    assert response.model == "gpt-5.6-sol"
    assert response.reasoning_effort == "xhigh"
    assert response.content == '{"result":"ok"}'


def test_codex_environment_prohibits_api_key(monkeypatch) -> None:
    """Verify Codex subprocesses receive only OS essentials and never API credentials/secrets."""
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-pass")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-pass")
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    env = CodexCLIExecutor._environment()
    assert "OPENAI_API_KEY" not in env
    assert "UNRELATED_SECRET" not in env
    assert env.get("SystemRoot") == "C:/Windows"


def test_codex_catalog_rejects_api_key_account(monkeypatch) -> None:
    """Verify SAGE fails closed when Codex App Server reports non-ChatGPT authentication."""
    executor = CodexCLIExecutor(command="codex")

    def fake_roundtrip(requests, *, timeout=20):
        """Return an API-key account even though a model list exists."""
        result = {0: {"id": 0, "result": {}}}
        for request_id, method, _params in requests:
            if method == "account/read":
                result[request_id] = {"id": request_id, "result": {"account": {"type": "apiKey"}}}
            else:
                result[request_id] = {"id": request_id, "result": {"data": [], "nextCursor": None}}
        return result

    monkeypatch.setattr(executor, "_app_server_roundtrip", fake_roundtrip)
    with pytest.raises(ValidationError, match="requires ChatGPT-managed authentication"):
        executor.query_catalog()

def test_local_provider_endpoint_is_loopback_only() -> None:
    """Verify the Ollama transport cannot be redirected to a remote or credentialed URL."""
    assert validate_local_endpoint("http://127.0.0.1:11434", provider="Ollama") == "http://127.0.0.1:11434"
    with pytest.raises(ValidationError, match="localhost/loopback"):
        validate_local_endpoint("http://192.168.1.50:11434", provider="Ollama")
    with pytest.raises(ValidationError, match="credentials"):
        validate_local_endpoint("http://user:pass@localhost:11434", provider="Ollama")


def test_scripture_usj_model_projection_removes_duplicate_internal_records() -> None:
    """Verify model-facing Scripture keeps exact USJ content while dropping duplicated parser internals."""
    document = {
        "type": "USJ",
        "version": "3.1",
        "content": [
            {"type": "book", "marker": "id", "code": "MAT", "content": ["Fixture"]},
            {"type": "chapter", "marker": "c", "number": "1", "sid": "MAT 1"},
            {
                "type": "para",
                "marker": "p",
                "content": [
                    {"type": "verse", "marker": "v", "number": "1", "sid": "MAT 1:1"},
                    "Exact supplied wording",
                ],
            },
        ],
        "sage": {
            "book_code": "MAT",
            "scope": "MAT 1:1",
            "source_sha256": "a" * 64,
            "verse_records": [
                {
                    "chapter": 1,
                    "verse_start": 1,
                    "verse_end": 1,
                    "body_text_exact": "Exact supplied wording",
                    "content": ["Exact supplied wording"],
                    "lines": ["\\v 1 Exact supplied wording"],
                    "line_start": 99,
                    "paragraph_id": "P0001",
                }
            ],
            "errors": [],
        },
    }
    raw = json.dumps(document, ensure_ascii=False, indent=2)

    projected, recipe = _model_read_content(
        "workspace_data/task/packet/source.usj.json",
        raw,
        AUTHORIZED_CONTENT_EVIDENCE,
    )
    value = json.loads(projected)

    assert recipe == "SAGE_SCRIPTURE_SLICE_V1"
    assert value["projection"] == "SAGE_SCRIPTURE_SLICE_V1"
    assert value["source_sha256"] == "a" * 64
    assert value["scope"] == "MAT 1:1"
    assert "Exact supplied wording" in projected
    assert "verse_records" not in projected
    assert "line_start" not in projected
    assert len(projected.encode("utf-8")) < len(raw.encode("utf-8"))


def test_projection_telemetry_quantifies_scripture_token_savings() -> None:
    """Verify receipts can quantify raw Scripture packets versus deterministic model projections."""
    document = {
        "type": "USJ",
        "version": "3.1",
        "content": [{"type": "verse", "marker": "v", "number": "1", "content": ["Exact wording"]}],
        "sage": {
            "book_code": "MAT",
            "scope": "MAT 1:1",
            "source_sha256": "b" * 64,
            "verse_records": [{"chapter": 1, "verse_start": 1, "content": ["Exact wording"]} for _ in range(40)],
        },
    }
    raw = json.dumps(document, ensure_ascii=False, indent=2)
    measured = _read_projection_measurement(
        [("packet/source.usj.json", raw, AUTHORIZED_CONTENT_EVIDENCE)]
    )
    assert measured["projected_read_count"] == 1
    assert measured["saved_estimated_tokens"] > 0
    assert measured["model_estimated_tokens"] < measured["raw_estimated_tokens"]
    assert measured["estimated_token_reduction_percent"] > 50


def test_task_dry_run_rehashes_and_seals_authorised_reads(make_workspace) -> None:
    """Verify dry-run execution re-hashes immutable reads before assembling a sealed request."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    manifest = _synthetic_task(root)
    config = load_ecosystem(root / "ecosystem.yml")
    result = execute_task(config, task_manifest=manifest, dry_run=True)
    assert result["status"] == "READY_TO_EXECUTE"
    assert result["normal_reads"] == 1
    assert result["conditional_reads"] == 0
    assert result["allowed_writes"] == ["output/result.txt"]
    assert result["handoff_measurement"]["measurement_scope"] == "provider_prompt_plus_output_schema"
    assert result["handoff_measurement"]["total_estimated_tokens"] > 0
    assert result["handoff_measurement"]["evidence_projection"]["read_count"] == 1
    (root / "evidence.txt").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="changed after task creation"):
        execute_task(config, task_manifest=manifest, dry_run=True)


def test_task_executor_materializes_only_exact_allowlist(make_workspace, monkeypatch) -> None:
    """Verify model content is materialised only through the exact task write allowlist."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    manifest = _synthetic_task(root)
    config = load_ecosystem(root / "ecosystem.yml")

    class FakeExecutor:
        """Return one deterministic provider envelope for allowlist materialisation."""

        def status(self, **_kwargs):
            """Expose a deterministic live catalog for policy routing."""
            return _fake_codex_status()

        def execute(self, request):
            """Return the exact synthetic response required by this regression test."""
            payload = {
                "schema_version": "1.0",
                "task_id": "synthetic-task-1",
                "files": {"output/result.txt": "accepted\n"},
            }
            return ProviderResponse(
                "codex", request.model, json.dumps(payload), {"fake": True}, request.reasoning_effort
            )

    monkeypatch.setattr("sage.llm_tasks.make_executor", lambda provider, settings: FakeExecutor())
    result = execute_task(config, task_manifest=manifest, provider="codex")
    assert result["status"] == "EXECUTED"
    assert (manifest.parent / "output" / "result.txt").read_text(encoding="utf-8") == "accepted\n"
    assert (manifest.parent / "validation" / "llm-execution-receipt.json").is_file()
    files = [p.relative_to(manifest.parent).as_posix() for p in manifest.parent.rglob("*") if p.is_file()]
    assert "output/result.txt" in files
    assert not any(path.startswith("output/") and path != "output/result.txt" for path in files)


def test_saw_provider_schema_requests_only_stage_semantics() -> None:
    """SAW provider schema omits deterministic identity, coverage, and receipt boilerplate."""
    manifest = {
        "task_id": "saw-qa-mat-example",
        "task_fingerprint": "fingerprint",
        "workflow": "saw",
        "operation": "qa",
        "qa_stage": "TRANSLATION_AND_MEANING_QA",
        "scope": "MAT 1:1",
        "focus": None,
        "check_type": None,
        "expected_references": ["MAT 1:1"],
        "review_requirements": {
            "expected_work_unit_ids": ["SAW-QA-U001"],
            "required_checks": ["MEANING_EQUIVALENCE", "GRAMMAR"],
        },
        "allowed_writes": ["output/findings.json"],
    }

    schema = _output_schema(manifest)
    findings_schema = schema["properties"]["files"]["properties"]["output/findings.json"]

    assert findings_schema["type"] == "object"
    assert set(findings_schema["required"]) == {"review_summary", "findings", "ol_review_requests"}
    assert "coverage" not in findings_schema["properties"]
    assert "review_receipts" not in findings_schema["properties"]
    assert "task_id" not in findings_schema["properties"]
    assert "operation" not in findings_schema["properties"]
    assert "scope" not in findings_schema["properties"]
    assert "structural_adjudications" not in findings_schema["properties"]
    assert "ol_resolutions" not in findings_schema["properties"]
    finding_properties = findings_schema["properties"]["findings"]["items"]["properties"]
    assert "target_reference" in finding_properties
    assert "reference" not in finding_properties
    assert "required_action" in finding_properties
    assert "recommended_action" not in finding_properties


def test_saw_semantic_result_materializes_identity_coverage_and_receipt_locally() -> None:
    """SAGE expands compact SAW semantics to the canonical findings document before submission."""
    manifest = {
        "task_id": "saw-qa-mat-example",
        "task_fingerprint": "fingerprint",
        "operation": "qa",
        "qa_stage": "TRANSLATION_AND_MEANING_QA",
        "scope": "MAT 1:1-2",
        "focus": None,
        "check_type": None,
        "expected_references": ["MAT 1:1", "MAT 1:2"],
        "review_requirements": {
            "expected_work_unit_ids": ["SAW-QA-U001"],
            "required_checks": ["MEANING_EQUIVALENCE", "GRAMMAR"],
        },
    }
    semantic = {
        "review_summary": "Compared the bounded WIP against the routed REFERENCE and grammar evidence.",
        "findings": [],
        "ol_review_requests": [],
    }

    document = _materialize_saw_findings(manifest, semantic)

    assert document["schema_version"] == "2.0"
    assert document["task_id"] == manifest["task_id"]
    assert document["stage"] == "TRANSLATION_AND_MEANING_QA"
    assert document["coverage"] == {
        "status": "COMPLETE",
        "reviewed_references": ["MAT 1:1", "MAT 1:2"],
    }
    assert document["review_receipts"][0]["work_unit_id"] == "SAW-QA-U001"
    assert document["review_receipts"][0]["task_fingerprint"] == "fingerprint"
    assert document["review_receipts"][0]["checks_performed"] == [
        "MEANING_EQUIVALENCE",
        "GRAMMAR",
    ]
    assert document["review_receipts"][0]["evidence_summary"] == semantic["review_summary"]
    assert document["structural_adjudications"] == []
    assert document["resolved_ol_request_ids"] == []
    assert "review_summary" not in document


def test_selective_ol_schema_materializes_role_specific_finding_evidence() -> None:
    """Option 11 returns resolutions while SAGE owns finding evidence identity."""
    manifest = {
        "task_id": "saw-qa-exo-selective",
        "task_fingerprint": "fingerprint",
        "workflow": "saw",
        "operation": "qa",
        "qa_stage": "SELECTIVE_OL_ADJUDICATION",
        "scope": "EXO 1:10",
        "expected_references": ["EXO 1:10"],
        "allowed_evidence_ids": [
            "WIP", "REFERENCE", "PROJECT-GRAMMAR", "ORIGINAL_LANGUAGE_HEBREW"
        ],
        "original_language_sources": [{
            "role": "ORIGINAL_LANGUAGE_HEBREW", "project": "HEB", "routing": "DIRECT"
        }],
        "review_requirements": {
            "expected_work_unit_ids": ["SAW-QA-EXO-U001"],
            "required_checks": ["WIP_REFERENCE_SOURCE_ADJUDICATION"],
        },
        "allowed_writes": ["output/findings.json"],
    }
    schema = _output_schema(manifest)["properties"]["files"]["properties"]["output/findings.json"]
    assert set(schema["required"]) == {"review_summary", "ol_resolutions"}
    assert "findings" not in schema["properties"]
    semantic = {
        "review_summary": "Adjudicated the exact inherited variance against routed Hebrew.",
        "ol_resolutions": [{
            "request_id": "OLR-1",
            "target_reference": "EXO 1:10",
            "outcome": "FINDING",
            "finding_id": "OL-F-001",
            "decision": "REFERENCE_CLOSER_TO_SOURCE",
            "original_language_evidence": "The routed Hebrew supports the Reference rendering.",
            "rationale": "The WIP introduces a source-dependent distinction not supported here.",
            "issue": "The WIP rendering is not supported by the routed Hebrew evidence.",
            "required_action": "Revise toward the supported source meaning.",
            "action_level": "CHANGE",
            "confidence": "HIGH",
        }],
    }

    document = _materialize_saw_findings(manifest, semantic)

    assert document["findings"][0]["evidence_ids"] == [
        "WIP", "REFERENCE", "ORIGINAL_LANGUAGE_HEBREW"
    ]
    assert document["findings"][0]["finding_id"] == "OL-F-001"


def test_saw_provider_object_is_materialised_as_canonical_json_text() -> None:
    """The sealed transport serializes a schema-constrained SAW object deterministically."""
    manifest = {
        "task_id": "saw-qa-mat-example",
        "allowed_writes": ["output/findings.json"],
    }
    document = {"schema_version": "2.0", "task_id": manifest["task_id"]}
    response = json.dumps({
        "schema_version": "1.0",
        "task_id": manifest["task_id"],
        "files": {"output/findings.json": document},
    })

    materialised = _parse_response(response, manifest)

    assert json.loads(materialised["output/findings.json"]) == document
    assert materialised["output/findings.json"].endswith("\n")


def test_conditional_ol_evidence_is_released_only_after_material_trigger(make_workspace, monkeypatch) -> None:
    """Verify conditional OL evidence stays sealed until the first pass establishes material risk."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    manifest = _synthetic_task(root, conditional=True)
    config = load_ecosystem(root / "ecosystem.yml")
    prompts: list[str] = []
    efforts: list[str | None] = []
    status_calls: list[int] = []
    prevalidated_calls: list[int] = []

    class FakeExecutor:
        """Capture both rewrite phases while returning deterministic challenge evidence."""

        def status(self, **_kwargs):
            """Expose a deterministic live catalog for policy routing."""
            status_calls.append(1)
            return _fake_codex_status()

        def execute_prevalidated(self, request, status):
            """Reuse the task-scoped readiness snapshot for every provider phase."""
            assert status.ready is True
            prevalidated_calls.append(1)
            return self.execute(request)

        def execute(self, request):
            """Return a risk-triggering full pass followed by one narrow OL micro-decision."""
            prompts.append(request.prompt)
            efforts.append(request.reasoning_effort)
            first = len(prompts) == 1
            if not first:
                payload = {
                    "schema_version": "1.0",
                    "challenge_id": "CH-1",
                    "scripture_reference": "MAT 1:1",
                    "ol_evidence_summary": "The governed OL packet supports candidate C2.",
                    "recommended_candidate_id": "C2",
                    "after_ol_risk": 1,
                    "replacement_usfm": "\\c 1\n\\v 1 phase2\n",
                    "recommended_action": "Use candidate C2.",
                    "grammar_issues": [],
                    "grammar_unresolved_additions": [],
                }
                return ProviderResponse(
                    "codex", request.model, json.dumps(payload), {"phase": len(prompts)}, request.reasoning_effort
                )
            challenge = {
                "challenges": [
                    {
                        "challenge_id": "CH-1",
                        "scripture_reference": "MAT 1:1",
                        "category": "VERB_CHOICE",
                        "summary": "Resolve the disputed verb",
                        "risk": {"before_ol": 2, "material_triggers": ["semantic ambiguity"]},
                        "candidates": [
                            {"candidate_id": "C1", "rendering": "phase1"},
                            {"candidate_id": "C2", "rendering": "phase2"},
                        ],
                        "recommended_candidate_id": "C1",
                        "ol_referral": {"performed": False},
                    }
                ]
            }
            payload = {
                "schema_version": "1.0",
                "task_id": "synthetic-task-1",
                "files": {
                    "output/rewrite.usfm": "\\id MAT Fixture\n\\c 1\n\\v 1 phase1\n",
                    "output/translation-challenges.json": json.dumps(challenge),
                },
            }
            return ProviderResponse(
                "codex", request.model, json.dumps(payload), {"phase": len(prompts)}, request.reasoning_effort
            )

    monkeypatch.setattr("sage.llm_tasks.make_executor", lambda provider, settings: FakeExecutor())
    result = execute_task(config, task_manifest=manifest, provider="codex")
    assert result["phase_count"] == 2
    assert result["conditional_evidence_used"] is True
    assert "conditional OL evidence" not in prompts[0]
    assert "conditional OL evidence" in prompts[1]
    assert "PHASE 1 DRAFT OUTPUTS" not in prompts[1]
    assert "SAGE BIC CONDITIONAL OL MICRO-ADJUDICATION" in prompts[1]
    assert "LOCAL EVIDENCE BOUNDARY: CONTENT EVIDENCE IS SAGE-LOCAL ONLY." in prompts[0]
    assert "READ CLASS: AUTHORIZED_CONTENT_EVIDENCE" in prompts[0]
    assert efforts == ["high", "xhigh"]
    assert result["phase_reasoning_efforts"] == ["high", "xhigh"]
    assert result["selection_mode"] == "AUTO_RECOMMENDED"
    assert len(status_calls) == 1
    assert len(prevalidated_calls) == 2
    rewrite = (manifest.parent / "output" / "rewrite.usfm").read_text(encoding="utf-8")
    assert "\\v 1 phase2" in rewrite
    ledger = json.loads((manifest.parent / "output" / "translation-challenges.json").read_text(encoding="utf-8"))
    assert ledger["challenges"][0]["recommended_candidate_id"] == "C2"
    assert ledger["challenges"][0]["ol_referral"]["performed"] is True



def test_model_policy_recommends_task_specific_model_and_reasoning(make_workspace) -> None:
    """Verify live availability is filtered through SAGE qualification and task policy."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    status = _fake_codex_status()
    inspect = recommend_model(root=root, status=status, workflow="bic", operation="inspect")
    rewrite = recommend_model(root=root, status=status, workflow="bic", operation="rewrite")
    self_check = recommend_model(root=root, status=status, workflow="bic", operation="self_check")
    assert (inspect.model, inspect.reasoning_effort) == ("gpt-5.6-terra", "medium")
    assert (rewrite.model, rewrite.reasoning_effort) == ("gpt-5.6-sol", "high")
    assert rewrite.conditional_second_pass_reasoning_effort == "xhigh"
    assert (self_check.model, self_check.reasoning_effort) == ("gpt-5.6-sol", "xhigh")


@pytest.mark.parametrize("effort", ["max", "ultra", "future-super-effort"])
def test_explicit_effort_above_xhigh_is_rejected_even_with_operator_override(make_workspace, effort: str) -> None:
    """Verify the hard reasoning ceiling cannot be bypassed by Operator policy override."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    status = _fake_codex_status()
    sol = status.model_capabilities[0]
    status = ProviderStatus(
        **{
            **status.__dict__,
            "model_capabilities": (
                ModelCapability(
                    **{
                        **sol.__dict__,
                        "supported_reasoning_efforts": sol.supported_reasoning_efforts + (ReasoningEffortOption(effort),),
                    }
                ),
                status.model_capabilities[1],
            ),
        }
    )
    with pytest.raises(ValidationError, match="highest supported reasoning level is xhigh"):
        validate_explicit_selection(
            root=root,
            status=status,
            workflow="bic",
            operation="rewrite",
            model="gpt-5.6-sol",
            reasoning_effort=effort,
            allow_unqualified=True,
        )


@pytest.mark.parametrize("effort", ["max", "ultra", "future-super-effort"])
def test_settings_cannot_persist_reasoning_above_xhigh(make_workspace, effort: str) -> None:
    """Verify unsupported reasoning cannot survive as a persisted Codex selection."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    with pytest.raises(ConfigurationError, match="highest supported level is xhigh"):
        update_llm_selection(
            root,
            provider="codex",
            model="gpt-5.6-sol",
            reasoning_effort=effort,
        )

def test_external_resource_mount_supports_role_specific_scripture_access(make_workspace, tmp_path: Path) -> None:
    """Verify locked and under-review Scripture resources may use explicit external read-only mappings."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    source_external = tmp_path / "paratext-idKKHv0"
    source_external.mkdir()
    (source_external / "41MAT.SFM").write_text("\\id MAT\n\\c 1\n\\v 1 Test\n", encoding="utf-8")
    target_external = tmp_path / "paratext-usBOLx1"
    target_external.mkdir()

    set_resource_mount(root, project_id="idKKHv0", external_path=source_external)
    set_resource_mount(root, project_id="usBOLx1", external_path=target_external)
    config = load_ecosystem(root / "ecosystem.yml")
    assert config.project("idKKHv0").path == source_external.resolve()
    assert config.project("idKKHv0").external_readonly is True
    assert config.project("usBOLx1").path == target_external.resolve()
    assert config.project("usBOLx1").external_readonly is True


def test_codex_chatgpt_connect_requires_cli_without_desktop_app() -> None:
    """Verify missing Codex CLI produces actionable install guidance and no desktop-app dependency."""
    executor = CodexCLIExecutor(command="")
    executor.command = None
    with pytest.raises(ValidationError) as caught:
        executor.connect_chatgpt()
    assert caught.value.code == "CODEX_CLI_NOT_FOUND"
    assert "desktop app" in caught.value.message.casefold()
    assert caught.value.next_action
    assert "codex" in caught.value.next_action.casefold()


def test_codex_chatgpt_connect_runs_interactive_login_and_verifies_chatgpt(monkeypatch) -> None:
    """Verify SAGE invokes Codex ChatGPT login directly and validates the resulting account mode."""
    import subprocess

    executor = CodexCLIExecutor(command="codex")
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        """Capture the interactive login command and return success without starting Codex."""
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(executor, "status", _fake_codex_status)
    status = executor.connect_chatgpt(device_auth=False)
    assert calls == [["codex", "login"]]
    assert status.ready is True
    assert status.auth_mode == "CHATGPT"


def test_codex_chatgpt_connect_supports_device_code(monkeypatch) -> None:
    """Verify the alternative device-code sign-in remains available through SAGE."""
    import subprocess

    executor = CodexCLIExecutor(command="codex")
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        """Capture the device-code login command and return success without starting Codex."""
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(executor, "status", _fake_codex_status)
    executor.connect_chatgpt(device_auth=True)
    assert calls == [["codex", "login", "--device-auth"]]


def test_codex_environment_preserves_proxy_and_custom_ca_paths(monkeypatch) -> None:
    """Codex must inherit operator network transport configuration while still excluding API credentials."""
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("CURL_CA_BUNDLE", "C:/corp/ca.pem")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "C:/corp/ca.pem")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-pass")
    env = CodexCLIExecutor._environment()
    assert env["ALL_PROXY"] == "http://proxy.example:8080"
    assert env["CURL_CA_BUNDLE"] == "C:/corp/ca.pem"
    assert env["REQUESTS_CA_BUNDLE"] == "C:/corp/ca.pem"
    assert "OPENAI_API_KEY" not in env
