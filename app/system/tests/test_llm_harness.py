"""Provider-neutral SAGE LLM harness, local transport, and resource-mount contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from sage.storage import storage_layout
from sage.atomic import atomic_write_json
from sage.errors import ValidationError
from sage.evidence_policy import AUTHORIZED_CONTENT_EVIDENCE, task_evidence_policy
from sage.execution_events import classify_exception
from sage.executors.base import ModelCapability, ProviderRequest, ProviderResponse, ProviderStatus, ReasoningEffortOption
from sage.executors.codex_cli import CodexCLIExecutor
from sage.executors.http import validate_local_endpoint
from sage.hashing import sha256_file
from sage.llm_tasks import (
    _materialize_saw_findings,
    _materialize_provider_files,
    _model_read_content,
    _output_schema,
    _parse_response,
    _read_projection_measurement,
    execute_task,
)
from sage.model_policy import recommend_model
from sage.routing_override import set_global_override
from sage.skill_routing import capability_fingerprint, skill_contract_sha256
from sage.skill_routing import resolve_skill_route
from sage.registry import load_ecosystem
from sage.resource_mounts import mounts_path, set_resource_mount


def _synthetic_task(
    root: Path,
    *,
    conditional: bool = False,
    qualified: bool = True,
) -> Path:
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
        writes = [
            "output/rewrite.usfm",
            "output/grammar-assessment.json",
            "output/translation-challenges.json",
        ]
    manifest = {
        "task_id": "synthetic-task-1",
        "skill_id": "bic-rewrite" if conditional else "bic-inspect",
        "execution_mode": "SAGE_GOVERNED_TASK_V1",
        "workflow": "bic",
        "operation": "rewrite" if conditional else "inspect",
        "scope": "MAT 1:1",
        "narrative_language": {
            "tag": "en",
            "authority": "CANONICAL_REPORT_NARRATIVE",
        },
        "interface_language": "fr",
        "human_output": {
            "logs_and_reports": {
                "primary_language": "en",
                "secondary_language": "uk",
                "bilingual": True,
            }
        },
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
    if conditional:
        manifest.update(
            {
                "contemporary_source": "idKKHv0",
                "output_project": "usBOLx1",
                "marker_policy": "SEMANTIC_STRUCTURE_V1",
                "resource_fingerprints": {"settings": "b" * 64},
                "project_grammar": {
                    "profile_id": "GRAMMAR-1",
                    "profile_sha256": "a" * 64,
                    "rule_ids": ["R1", "R2"],
                },
            }
        )
        from sage.act_tasks import (
            _load_bic_protected_rewrite_contract,
            _load_bic_protected_verb_selection_contract,
        )

        pinned = load_ecosystem(root / "ecosystem.yml")
        manifest["protected_rewrite_contract"] = _load_bic_protected_rewrite_contract(pinned)
        manifest["protected_verb_selection_contract"] = _load_bic_protected_verb_selection_contract(pinned)
    path = task / "task-manifest.json"
    atomic_write_json(path, manifest)
    if qualified:
        _qualify_test_route(
            root,
            skill_id=str(manifest["skill_id"]),
            model="gpt-5.6-sol" if conditional else "gpt-5.6-terra",
            reasoning_id="high" if conditional else "medium",
        )
    return path


def _assert_strict_object_schema(schema: dict) -> None:
    """Every provider-facing (sub)schema is typed; objects are closed and fully required."""
    assert "type" in schema or "anyOf" in schema, schema
    if schema.get("type") == "object":
        assert schema.get("additionalProperties") is False
        assert set(schema.get("required", ())) == set(schema["properties"])
        for child in schema["properties"].values():
            _assert_strict_object_schema(child)
    if schema.get("type") == "array":
        _assert_strict_object_schema(schema["items"])


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


def _qualify_test_route(root: Path, *, skill_id: str, model: str, reasoning_id: str) -> None:
    """Install one exact synthetic qualification seed in a disposable test workspace."""
    status = _fake_codex_status()
    capability = next(item for item in status.model_capabilities if item.model == model)
    policy_path = root / "system/config/model-policy.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    suite_sha256 = (skill_id.encode("utf-8").hex() + "0" * 64)[:64]
    policy["skill_routes"][skill_id]["suite_sha256"] = suite_sha256
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    skills = json.loads((root / "system/config/skills.json").read_text(encoding="utf-8"))
    seed_path = root / "system/config/model-qualification-seeds.json"
    seeds = json.loads(seed_path.read_text(encoding="utf-8")) if seed_path.is_file() else {
        "schema_version": "1.0",
        "routes": [],
    }
    seeds["routes"] = [
        row for row in seeds["routes"] if str(row.get("skill_id") or "") != skill_id
    ]
    seeds["routes"].append(
        {
            "provider": "codex",
            "model_id": model,
            "capability_fingerprint": capability_fingerprint(capability),
            "reasoning_id": reasoning_id,
            "skill_id": skill_id,
            "skill_sha256": skill_contract_sha256(skills["skills"][skill_id]),
            "suite_id": f"alpha1-{skill_id}",
            "suite_sha256": suite_sha256,
            "policy_version": "alpha1-1",
            "qualification_status": "QUALIFIED",
            "evidence_sha256": "d" * 64,
            "cost_class": capability.cost_class,
            "semantic_score": 1.0,
            "semantic_score_material": False,
        }
    )
    seed_path.write_text(json.dumps(seeds, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_codex_catalog_preserves_every_provider_native_reasoning_identifier(monkeypatch) -> None:
    """Live discovery must preserve provider order without applying a universal reasoning scale."""
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
    assert models[0].reasoning_efforts == (
        "medium", "high", "xhigh", "max", "ultra", "future-super-effort"
    )
    assert models[0].default_reasoning_effort == "high"


def test_codex_catalog_preserves_provider_native_default(monkeypatch) -> None:
    """A provider-native default remains visible even when its identifier is new to SAGE."""
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
    assert models[0].reasoning_efforts == ("high", "xhigh", "max")
    assert models[0].default_reasoning_effort == "max"


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


def test_projection_telemetry_never_counts_non_sfm_reads_as_sizing_tokens() -> None:
    """Non-SFM model projections remain transport telemetry and contribute zero sizing tokens."""
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
    assert measured["routed_sfm_estimated_tokens"] == 0
    assert measured["routed_sfm_bytes"] == 0
    assert measured["model_bytes"] < measured["raw_bytes"]


def test_task_dry_run_resolves_exact_route_without_provider_execution(
    make_workspace, monkeypatch
) -> None:
    """Verify dry-run execution re-hashes immutable reads before assembling a sealed request."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    manifest = _synthetic_task(root)
    config = load_ecosystem(root / "ecosystem.yml")

    class FakeExecutor:
        """Expose capability metadata while prohibiting task evidence execution."""

        def status(self):
            """Return the exact live capability snapshot used by route resolution."""
            return _fake_codex_status()

        def execute(self, _request):
            """Fail if dry-run transmits the assembled task prompt."""
            raise AssertionError("dry-run must not execute provider evidence")

    monkeypatch.setattr("sage.llm_tasks.make_executor", lambda provider, settings: FakeExecutor())
    result = execute_task(config, task_manifest=manifest, dry_run=True)
    assert result["status"] == "READY_TO_EXECUTE"
    assert result["skill_id"] == "bic-inspect"
    assert result["routing_mode"] == "AUTOMATIC"
    assert result["qualification_status"] == "RECOMMENDED"
    assert result["selection_mode"] == "EXACT_SKILL_QUALIFICATION"
    assert len(result["route_id"]) == 64
    assert result["provider"] == "codex"
    assert result["model"] == "gpt-5.6-terra"
    assert result["reasoning_effort"] == "medium"
    assert result["normal_reads"] == 1
    assert result["conditional_reads"] == 0
    assert result["allowed_writes"] == ["output/result.txt"]
    assert result["handoff_measurement"]["measurement_scope"] == "routed_reads_bytes_and_sfm_tokens"
    assert result["handoff_measurement"]["total_estimated_tokens"] == 0
    assert result["handoff_measurement"]["transport_bytes"] > 0
    assert result["handoff_measurement"]["evidence_projection"]["read_count"] == 1
    (root / "evidence.txt").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="changed after task creation"):
        execute_task(config, task_manifest=manifest, dry_run=True)


def test_task_dry_run_exposes_truthful_provisional_route_without_execution(
    make_workspace,
    monkeypatch,
) -> None:
    """Replacing the route selection mode with AUTOMATIC must hide the no-data basis."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    manifest = _synthetic_task(root, qualified=False)
    config = load_ecosystem(root / "ecosystem.yml")

    class FakeExecutor:
        """Expose a live catalog while proving dry-run never calls the provider."""

        def status(self):
            """Return the live-looking no-data capability snapshot."""
            return _fake_codex_status()

        def execute(self, _request):
            """Fail if a dry-run sends the sealed request."""
            raise AssertionError("dry-run must not execute provider evidence")

    monkeypatch.setattr("sage.llm_tasks.make_executor", lambda provider, settings: FakeExecutor())

    result = execute_task(config, task_manifest=manifest, dry_run=True)

    assert result["status"] == "READY_TO_EXECUTE"
    assert result["qualification_status"] == "PROVISIONAL_UNQUALIFIED"
    assert result["model"] == "gpt-5.6-sol"
    assert result["reasoning_effort"] == "medium"
    assert result["selection_mode"] == "PROVISIONAL_PROVIDER_DEFAULT"
    assert result["qualification_evidence_sha256"] is None
    assert len(result["routing_basis_sha256"]) == 64


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
            assert "CANONICAL REPORT NARRATIVE LANGUAGE: English (`en`)" in request.prompt
            assert "interface_language" not in request.prompt
            assert "secondary_language" not in request.prompt
            payload = {
                "schema_version": "1.0",
                "task_id": "synthetic-task-1",
                "files": {"output/result.txt": "accepted\n"},
            }
            return ProviderResponse(
                "codex", request.model, json.dumps(payload), {"fake": True}, request.reasoning_effort
            )

    monkeypatch.setattr("sage.llm_tasks.make_executor", lambda provider, settings: FakeExecutor())
    result = execute_task(config, task_manifest=manifest)
    assert result["status"] == "EXECUTED"
    assert result["schema_version"] == "2.0"
    assert result["skill_id"] == "bic-inspect"
    assert result["routing_mode"] == "AUTOMATIC"
    assert result["qualification_status"] == "RECOMMENDED"
    assert result["routing_policy_version"] == "alpha1-1"
    assert result["qualification_evidence_sha256"] == "d" * 64
    assert result["model_identity_strength"] == "ALIASED"
    assert len(result["capability_fingerprint"]) == 64
    assert len(result["route_id"]) == 64
    assert (manifest.parent / "output" / "result.txt").read_text(encoding="utf-8") == "accepted\n"
    assert (manifest.parent / "validation" / "llm-execution-receipt.json").is_file()
    files = [p.relative_to(manifest.parent).as_posix() for p in manifest.parent.rglob("*") if p.is_file()]
    assert "output/result.txt" in files
    assert not any(path.startswith("output/") and path != "output/result.txt" for path in files)
    raw = manifest.parent / "validation" / "provider-responses" / "response-01.txt"
    assert result["provider_responses"] == [
        {"phase": 1, "path": "validation/provider-responses/response-01.txt", "sha256": sha256_file(raw)}
    ]
    assert sha256_file(raw) == result["provider_response_sha256"][0]


def test_rejected_provider_response_is_preserved_and_task_stays_open(make_workspace, monkeypatch) -> None:
    """A response that fails parsing is archived verbatim and classified for a same-task retry."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    manifest = _synthetic_task(root)
    config = load_ecosystem(root / "ecosystem.yml")

    class FakeExecutor:
        """Return a response that is not the governed JSON envelope."""

        def status(self, **_kwargs):
            """Expose a deterministic live catalog for policy routing."""
            return _fake_codex_status()

        def execute(self, request):
            """Return prose instead of the response envelope."""
            return ProviderResponse(
                "codex", request.model, "I could not finish.", {"fake": True}, request.reasoning_effort
            )

    monkeypatch.setattr("sage.llm_tasks.make_executor", lambda provider, settings: FakeExecutor())
    with pytest.raises(ValidationError) as caught:
        execute_task(config, task_manifest=manifest)
    assert caught.value.code == "LLM_PROVIDER_RESPONSE_INVALID"
    assert classify_exception(caught.value)[0] == "TASK_OUTPUT_REJECTED"
    attempt = Path(caught.value.details["provider_attempt_path"])
    assert attempt.parent == manifest.parent / "attempts"
    assert (attempt / "provider-responses" / "response-01.txt").read_text(encoding="utf-8") == "I could not finish."
    receipt = json.loads((attempt / "attempt-receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "TASK_OUTPUT_REJECTED"
    assert receipt["reason_code"] == "LLM_PROVIDER_RESPONSE_INVALID"
    assert not (manifest.parent / "output").exists() or not any((manifest.parent / "output").rglob("*"))
    assert not (manifest.parent / "validation" / "llm-execution-receipt.json").exists()


def test_provisional_execution_receipt_uses_policy_basis_not_qualification_evidence(
    make_workspace,
    monkeypatch,
) -> None:
    """Inventing an evidence hash or omitting the policy basis must invalidate provenance."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    manifest = _synthetic_task(root, qualified=False)
    config = load_ecosystem(root / "ecosystem.yml")

    class FakeExecutor:
        """Return one valid output through the provisional route."""

        def status(self, **_kwargs):
            """Return the live-looking no-data capability snapshot."""
            return _fake_codex_status()

        def execute(self, request):
            """Return the allowlisted synthetic output without external execution."""
            payload = {
                "schema_version": "1.0",
                "task_id": "synthetic-task-1",
                "files": {"output/result.txt": "accepted\n"},
            }
            return ProviderResponse(
                "codex", request.model, json.dumps(payload), {}, request.reasoning_effort
            )

    monkeypatch.setattr("sage.llm_tasks.make_executor", lambda provider, settings: FakeExecutor())

    result = execute_task(config, task_manifest=manifest)

    assert result["qualification_status"] == "PROVISIONAL_UNQUALIFIED"
    assert result["selection_mode"] == "PROVISIONAL_PROVIDER_DEFAULT"
    assert result["qualification_evidence_sha256"] is None
    assert len(result["routing_basis_sha256"]) == 64


def test_provider_handoff_blocks_missing_narrative_language() -> None:
    """A provider schema cannot be built without one explicit Job-owned report language."""
    with pytest.raises(ValidationError) as caught:
        _output_schema({"task_id": "missing-language", "allowed_writes": ["output/result.txt"]})
    assert caught.value.code == "LLM_TASK_REPORT_LANGUAGE_MISSING"


def test_clear_spanish_saw_narrative_gets_one_english_correction_retry(
    make_workspace, monkeypatch
) -> None:
    """A clear source-language leak is rejected once before canonical findings are written."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    wip_evidence = root / "synthetic-wip-es.txt"
    reference_evidence = root / "synthetic-reference-es.txt"
    wip_evidence.write_text("\u00bfQui\u00e9n puede aceptar esta ense\u00f1anza?\n", encoding="utf-8")
    reference_evidence.write_text("Nadie puede aceptar esta ense\u00f1anza.\n", encoding="utf-8")
    task = storage_layout(root, create=True).system_root / "synthetic-saw-language-task"
    task.mkdir(parents=True, exist_ok=True)
    (task / "ACT.md").write_text("# Governed task\nReturn bounded findings.\n", encoding="utf-8")
    manifest = {
        "task_id": "synthetic-saw-language-1",
        "skill_id": "rtc-focused-check",
        "task_fingerprint": "language-fingerprint",
        "execution_mode": "SAGE_GOVERNED_TASK_V1",
        "workflow": "saw",
        "operation": "focused",
        "rtc_stage": None,
        "scope": "MAT 1:1",
        "focus": "Does the WIP preserve the Reference question?",
        "check_type": "MEANING_EQUIVALENCE",
        "evidence_policy": task_evidence_policy("saw"),
        "narrative_language": {
            "tag": "en",
            "authority": "CANONICAL_REPORT_NARRATIVE",
        },
        "allowed_reads": [
            {
                "path": wip_evidence.relative_to(root).as_posix(),
                "sha256": sha256_file(wip_evidence),
                "evidence_class": AUTHORIZED_CONTENT_EVIDENCE,
            },
            {
                "path": reference_evidence.relative_to(root).as_posix(),
                "sha256": sha256_file(reference_evidence),
                "evidence_class": AUTHORIZED_CONTENT_EVIDENCE,
            },
        ],
        "conditional_reads": [],
        "allowed_writes": ["output/findings.json"],
        "allowed_evidence_ids": ["WIP", "REFERENCE"],
        "expected_references": ["MAT 1:1"],
        "review_requirements": {
            "expected_work_unit_ids": ["SAW-LANGUAGE-U001"],
            "required_checks": ["MEANING_EQUIVALENCE"],
        },
    }
    manifest_path = task / "task-manifest.json"
    atomic_write_json(manifest_path, manifest)
    _qualify_test_route(
        root,
        skill_id="rtc-focused-check",
        model="gpt-5.6-sol",
        reasoning_id="high",
    )
    prompts: list[str] = []

    # The fake provider intentionally leaks the Spanish evidence language once so
    # this remains an execution-boundary regression rather than a detector unit test.
    class FakeExecutor:
        """Return a Spanish leak followed by the corrected English narrative."""

        def status(self, **_kwargs):
            """Expose a deterministic live catalog for policy routing."""
            return _fake_codex_status()

        def execute(self, request):
            """Capture the bounded correction retry and return one schema envelope."""
            prompts.append(request.prompt)
            spanish = len(prompts) == 1
            semantic = {
                "review_summary": (
                    "La traducción cambia la pregunta de referencia y por eso la forma debe revisarse con la evidencia disponible."
                    if spanish
                    else "The translation changes the Reference question, so the form must be revised from the available evidence."
                ),
                "findings": [{
                    "finding_id": "F001",
                    "target_reference": "MAT 1:1",
                    "category": "MEANING",
                    "issue": (
                        "La traducción cambia la pregunta y el significado de la referencia en esta forma."
                        if spanish
                        else "The translation changes the question and meaning of the Reference in this form."
                    ),
                    "required_action": (
                        "Debe conservar la pregunta y revisar la traducción con la evidencia de referencia."
                        if spanish
                        else "Preserve the question and revise the translation from the Reference evidence."
                    ),
                    "action_level": "CHANGE",
                    "confidence": "HIGH",
                    "evidence_ids": ["WIP", "REFERENCE"],
                    "grammar_rule_ids": [],
                    "original_language_evidence": "",
                }],
                "answer": (
                    "La traducción no conserva la pregunta de referencia y debe revisarse."
                    if spanish
                    else "The translation does not preserve the Reference question and must be revised."
                ),
                "structural_adjudications": [],
            }
            payload = {
                "schema_version": "1.0",
                "task_id": manifest["task_id"],
                "files": {"output/findings.json": semantic},
            }
            return ProviderResponse(
                "codex", request.model, json.dumps(payload), {"attempt": len(prompts)}, request.reasoning_effort
            )

    monkeypatch.setattr("sage.llm_tasks.make_executor", lambda provider, settings: FakeExecutor())
    result = execute_task(load_ecosystem(root / "ecosystem.yml"), task_manifest=manifest_path)

    assert len(prompts) == 2
    assert "\u00bfQui\u00e9n puede aceptar esta ense\u00f1anza?" in prompts[0]
    assert "Nadie puede aceptar esta ense\u00f1anza." in prompts[0]
    assert "LANGUAGE-CORRECTION RETRY" in prompts[1]
    assert result["language_retry_count"] == 1
    assert result["phase_count"] == 2
    findings = json.loads((task / "output" / "findings.json").read_text(encoding="utf-8"))
    assert findings["narrative_language"] == {
        "tag": "en",
        "authority": "CANONICAL_REPORT_NARRATIVE",
    }
    assert findings["findings"][0]["issue"].startswith("The translation")


def test_rtc_provider_schema_requests_only_stage_semantics() -> None:
    """RTC provider schema omits deterministic identity, coverage, and receipt boilerplate."""
    manifest = {
        "task_id": "rtc-mat-example",
        "task_fingerprint": "fingerprint",
        "workflow": "rtc",
        "operation": "rtc",
        "rtc_stage": "REFERENCE_TEXT_COMPARISON",
        "scope": "MAT 1:1",
        "focus": None,
        "check_type": None,
        "expected_references": ["MAT 1:1"],
        "review_requirements": {
            "expected_work_unit_ids": ["RTC-U001"],
            "required_checks": ["MEANING_EQUIVALENCE", "GRAMMAR"],
        },
        "allowed_writes": ["output/findings.json"],
        "narrative_language": {
            "tag": "en",
            "authority": "CANONICAL_REPORT_NARRATIVE",
        },
    }

    schema = _output_schema(manifest)
    findings_schema = schema["properties"]["files"]["properties"]["output/findings.json"]

    assert findings_schema["type"] == "object"
    assert set(findings_schema["required"]) == {
        "review_summary",
        "findings",
        "ol_review_requests",
        "candidate_adjudications",
    }
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
    assert "English (`en`)" in finding_properties["issue"]["description"]
    legacy_request = findings_schema["properties"]["ol_review_requests"]["items"]
    assert set(legacy_request["required"]) == {
        "request_id",
        "deferred_finding_id",
        "target_reference",
        "question",
        "reason",
        "evidence_ids",
    }


def test_saw_v1_provider_schema_requires_closed_ol_referral_admission() -> None:
    """A V1 meaning task cannot emit an open-ended source referral."""
    manifest = {
        "task_id": "saw-rtc-jhn-v1",
        "workflow": "saw",
        "operation": "rtc",
        "rtc_stage": "REFERENCE_TEXT_COMPARISON",
        "ol_referral_contract": "SAW_OL_REFERRAL_ADMISSION_V1",
        "scope": "JHN 1:1",
        "allowed_writes": ["output/findings.json"],
        "allowed_evidence_ids": ["WIP", "REFERENCE"],
        "narrative_language": {
            "tag": "en",
            "authority": "CANONICAL_REPORT_NARRATIVE",
        },
    }

    schema = _output_schema(manifest)
    request = schema["properties"]["files"]["properties"]["output/findings.json"][
        "properties"
    ]["ol_review_requests"]["items"]

    assert set(request["required"]) == {
        "request_id",
        "deferred_finding_id",
        "target_reference",
        "question",
        "reason",
        "evidence_ids",
        "conflict_class",
        "wip_proposition",
        "reference_proposition",
        "fundamental_impact",
        "source_dependency",
    }
    assert set(request["properties"]["conflict_class"]["enum"]) == {
        "NEGATION_OR_POLARITY_CONFLICT",
        "PARTICIPANT_IDENTITY_OR_ROLE_CONFLICT",
        "CORE_EVENT_OR_STATE_CONFLICT",
        "CORE_PROPOSITION_OMISSION_OR_ADDITION",
    }
    assert request["properties"]["source_dependency"]["enum"] == [
        "UNRESOLVED_REQUIRES_ORIGINAL_LANGUAGE"
    ]


def test_stc_provider_schema_uses_only_stc_semantics() -> None:
    """STC must not inherit RTC stages, categories, or conditional OL request fields."""
    manifest = {
        "task_id": "stc-phm-example",
        "workflow": "stc",
        "operation": "stc",
        "scope": "PHM",
        "allowed_writes": ["output/findings.json"],
        "narrative_language": {
            "tag": "en",
            "authority": "CANONICAL_REPORT_NARRATIVE",
        },
    }

    schema = _output_schema(manifest)
    findings_schema = schema["properties"]["files"]["properties"]["output/findings.json"]

    assert set(findings_schema["required"]) == {"review_summary", "findings", "candidate_adjudications"}
    assert "ol_review_requests" not in findings_schema["properties"]
    finding = findings_schema["properties"]["findings"]["items"]
    assert set(finding["required"]) == {
        "category", "target_reference", "summary", "wip_evidence", "ol_evidence", "ol_words"
    }
    # Claimed original-language words carry MACULA's own vocabularies so SAGE can check them exactly.
    ol_word = finding["properties"]["ol_words"]["items"]
    assert {"surface", "lemma", "tense", "stem", "person"} <= set(ol_word["required"])
    assert set(finding["properties"]["category"]["enum"]) == {
        "OMISSION", "ADDITION", "VARIATION", "CONSISTENCY"
    }
    assert "issue" not in finding["properties"]
    assert "action_level" not in finding["properties"]


def test_current_rtc_provider_semantics_are_materialized_canonically() -> None:
    """Current RTC uses the compact schema and controller-owned output envelope."""
    manifest = {
        "task_id": "rtc-mat-example",
        "task_fingerprint": "fingerprint",
        "workflow": "rtc",
        "operation": "rtc",
        "rtc_stage": "REFERENCE_TEXT_COMPARISON",
        "scope": "MAT 1:1",
        "expected_references": ["MAT 1:1"],
        "review_requirements": {
            "expected_work_unit_ids": ["RTC-U001"],
            "required_checks": ["MEANING_EQUIVALENCE"],
        },
        "narrative_language": {
            "tag": "en",
            "authority": "CANONICAL_REPORT_NARRATIVE",
        },
    }
    files = {
        "output/findings.json": json.dumps({
            "review_summary": "Compared the routed WIP and Reference evidence.",
            "findings": [],
            "ol_review_requests": [],
        })
    }

    document = json.loads(_materialize_provider_files(manifest, files)["output/findings.json"])

    assert document["task_id"] == "rtc-mat-example"
    assert document["review_receipts"][0]["work_unit_id"] == "RTC-U001"
    assert "SAW" not in json.dumps(document)


def test_stc_semantics_materialize_as_stc_submission_not_rtc_findings() -> None:
    """SAGE retains STC review_summary and injects only controller-owned report language."""
    manifest = {
        "task_id": "saw-stc-phm-example",
        "operation": "stc",
        "scope": "PHM",
        "narrative_language": {
            "tag": "en",
            "authority": "CANONICAL_REPORT_NARRATIVE",
        },
    }
    semantic = {
        "review_summary": "Reviewed all assigned coordinates against routed Greek.",
        "findings": [{
            "category": "VARIATION",
            "target_reference": "PHM 1:9",
            "summary": "The WIP changes the source relationship.",
            "wip_evidence": "WIP phrase",
            "ol_evidence": "Greek phrase",
        }],
    }

    document = _materialize_saw_findings(manifest, semantic)

    assert document == {
        **semantic,
        "report_language": "en",
        "candidate_adjudications": [],
    }
    assert "stage" not in document
    assert "review_receipts" not in document


def test_saw_semantic_result_materializes_identity_coverage_and_receipt_locally() -> None:
    """SAGE expands compact SAW semantics to the canonical findings document before submission."""
    manifest = {
        "task_id": "saw-rtc-mat-example",
        "task_fingerprint": "fingerprint",
        "operation": "rtc",
        "rtc_stage": "REFERENCE_TEXT_COMPARISON",
        "scope": "MAT 1:1-2",
        "focus": None,
        "check_type": None,
        "expected_references": ["MAT 1:1", "MAT 1:2"],
        "review_requirements": {
            "expected_work_unit_ids": ["SAW-RTC-U001"],
            "required_checks": ["MEANING_EQUIVALENCE", "GRAMMAR"],
        },
        "narrative_language": {
            "tag": "en",
            "authority": "CANONICAL_REPORT_NARRATIVE",
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
    assert document["stage"] == "REFERENCE_TEXT_COMPARISON"
    assert document["coverage"] == {
        "status": "COMPLETE",
        "reviewed_references": ["MAT 1:1", "MAT 1:2"],
    }
    assert document["review_receipts"][0]["work_unit_id"] == "SAW-RTC-U001"
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
        "task_id": "saw-rtc-exo-selective",
        "task_fingerprint": "fingerprint",
        "workflow": "saw",
        "operation": "rtc",
        "rtc_stage": "SELECTIVE_OL_ADJUDICATION",
        "scope": "EXO 1:10",
        "expected_references": ["EXO 1:10"],
        "allowed_evidence_ids": [
            "WIP", "REFERENCE", "PROJECT-GRAMMAR", "ORIGINAL_LANGUAGE_HEBREW"
        ],
        "original_language_sources": [{
            "role": "ORIGINAL_LANGUAGE_HEBREW", "project": "HEB", "routing": "DIRECT"
        }],
        "review_requirements": {
            "expected_work_unit_ids": ["SAW-RTC-EXO-U001"],
            "required_checks": ["WIP_REFERENCE_SOURCE_ADJUDICATION"],
        },
        "allowed_writes": ["output/findings.json"],
        "narrative_language": {
            "tag": "en",
            "authority": "CANONICAL_REPORT_NARRATIVE",
        },
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
        "task_id": "saw-rtc-mat-example",
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
    schemas: list[dict] = []
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
            schemas.append(request.schema)
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
            def candidate(identifier: str, rendering: str) -> dict:
                """Build one model-facing candidate."""
                return {
                    "candidate_id": identifier,
                    "form": rendering,
                    "meaning_features": ["event"],
                    "tone_and_force": "neutral",
                    "register": "plain",
                    "main_risk": "sense drift",
                    "rejection_code": "",
                    "rejection_reason": "",
                }

            challenge = {
                "challenges": [
                    {
                        "challenge_id": "CH-1",
                        "scripture_reference": "MAT 1:1",
                        "category": "VERB_CHOICE",
                        "summary": "Resolve the disputed verb",
                        "confidence": "MEDIUM",
                        "candidates": [candidate("C1", "phase1"), candidate("C2", "phase2")],
                        "recommended_candidate_id": "C1",
                        "risk": {"before_ol": 2, "material_triggers": ["COMPETING_NON_EQUIVALENT_SENSES"]},
                        "inherited_challenge_ids": [],
                        "recommended_action": "Review the verb.",
                    }
                ],
                "minor_summary": {"by_category": {"REGISTER": 2}, "notes": []},
            }
            grammar = {
                "rules": [
                    {"rule_id": "R1", "status": "PASS", "evidence": ""},
                    {"rule_id": "R2", "status": "NOT_APPLICABLE", "evidence": ""},
                ],
                "unresolved": [],
            }
            payload = {
                "schema_version": "1.0",
                "task_id": "synthetic-task-1",
                "files": {
                    "output/rewrite.usfm": "\\id MAT Fixture\n\\c 1\n\\v 1 phase1\n",
                    "output/grammar-assessment.json": grammar,
                    "output/translation-challenges.json": challenge,
                },
            }
            return ProviderResponse(
                "codex", request.model, json.dumps(payload), {"phase": len(prompts)}, request.reasoning_effort
            )

    monkeypatch.setattr("sage.llm_tasks.make_executor", lambda provider, settings: FakeExecutor())
    result = execute_task(config, task_manifest=manifest)
    assert result["phase_count"] == 2
    assert result["conditional_evidence_used"] is True
    assert "conditional OL evidence" not in prompts[0]
    assert "conditional OL evidence" in prompts[1]
    assert "PHASE 1 DRAFT OUTPUTS" not in prompts[1]
    assert "SAGE BIC CONDITIONAL OL MICRO-ADJUDICATION" in prompts[1]
    assert "LOCAL EVIDENCE BOUNDARY: CONTENT EVIDENCE IS SAGE-LOCAL ONLY." in prompts[0]
    assert "READ CLASS: AUTHORIZED_CONTENT_EVIDENCE" in prompts[0]
    rewrite_contract = (root / "system/skills/bic-rewrite/references/PROTECTED-REWRITE-DETAIL-RULES.md").read_text(encoding="utf-8")
    verb_policy = (root / "system/config/contracts/bic-verb-selection-policy.yml").read_text(encoding="utf-8")
    for prompt in prompts:
        assert "=== PROTECTED CONTRACTS ===" in prompt
        assert rewrite_contract in prompt
        assert verb_policy in prompt
        assert "deterministic projection of the bounded USJ" in prompt
    reads_start = prompts[0].index("=== AUTHORIZED READS ===")
    assert prompts[0].index("=== END ACT CAPSULE ===") < prompts[0].index("=== PROTECTED CONTRACTS ===") < reads_start
    assert [item["id"] for item in result["protected_contracts"]] == [
        "BIC4_PROTECTED_REWRITE_DETAIL_RULES",
        "BIC_PROTECTED_VERB_SELECTION_POLICY",
    ]
    assert [item["bytes"] for item in result["protected_contracts"]] == [
        len(rewrite_contract.encode("utf-8")),
        len(verb_policy.encode("utf-8")),
    ]
    assert all(len(item["sha256"]) == 64 for item in result["protected_contracts"])
    assert efforts == ["high", "high"]
    assert result["phase_reasoning_efforts"] == ["high", "high"]
    assert result["routing_mode"] == "AUTOMATIC"
    assert result["qualification_status"] == "RECOMMENDED"
    assert len(status_calls) == 1
    assert len(prevalidated_calls) == 2
    rewrite = (manifest.parent / "output" / "rewrite.usfm").read_text(encoding="utf-8")
    assert "\\v 1 phase2" in rewrite
    ledger = json.loads((manifest.parent / "output" / "translation-challenges.json").read_text(encoding="utf-8"))
    assert ledger["challenges"][0]["recommended_candidate_id"] == "C2"
    assert ledger["challenges"][0]["ol_referral"]["performed"] is True

    # The model never sees or returns identity or derived fields; SAGE sets them after the last merge.
    from sage.act_outputs import validate_grammar_assessment
    from sage.rewrite_risk import validate_rewrite_challenges

    files = schemas[0]["properties"]["files"]["properties"]
    challenge_schema = files["output/translation-challenges.json"]
    assert set(challenge_schema["properties"]) == {"challenges", "minor_summary"}
    row_schema = challenge_schema["properties"]["challenges"]["items"]
    assert not {"selected_candidate_id", "ol_referral", "task_id", "output_sha256"} & set(row_schema["properties"])
    assert set(row_schema["properties"]["risk"]["properties"]) == {"before_ol", "material_triggers"}
    assert row_schema["properties"]["category"]["enum"] == sorted(row_schema["properties"]["category"]["enum"])
    assert row_schema["properties"]["risk"]["properties"]["before_ol"] == {"type": "integer", "enum": [0, 1, 2, 3, 4]}
    grammar_schema = files["output/grammar-assessment.json"]
    assert set(grammar_schema["properties"]) == {"rules", "unresolved"}
    assert grammar_schema["properties"]["rules"]["items"]["properties"]["rule_id"]["enum"] == ["R1", "R2"]
    for schema in (challenge_schema, grammar_schema):
        _assert_strict_object_schema(schema)
    assignment = json.loads(prompts[0].split("SAGE sets output identity, scope, fingerprints, hashes, and derived fields):", 1)[1].splitlines()[1])
    assert assignment["grammar_rule_ids"] == ["R1", "R2"]
    assert assignment["marker_policy"] == "SEMANTIC_STRUCTURE_V1"
    assert assignment["reporting_languages"] == ["en"]
    assert not {"rtc_stage", "structural_candidate_ids", "allowed_evidence_ids", "expected_ol_requests"} & set(assignment)

    output_root = manifest.parent / "output"
    rewrite_path = output_root / "rewrite.usfm"
    grammar = validate_grammar_assessment(
        output_root / "grammar-assessment.json",
        task_id="synthetic-task-1",
        scope_value="MAT 1:1",
        profile_id="GRAMMAR-1",
        profile_sha256="a" * 64,
        output_path=rewrite_path,
        required_rule_ids=["R1", "R2"],
    )
    assert grammar["output_sha256"] == sha256_file(rewrite_path)
    normalized = validate_rewrite_challenges(
        output_root / "translation-challenges.json",
        task_id="synthetic-task-1",
        operation="rewrite",
        scope_value="MAT 1:1",
        output_path=rewrite_path,
        human_output=config.human_output,
        source_language=config.project("idKKHv0").language_code,
        target_language=config.project("usBOLx1").language_code,
    )
    row = normalized["challenges"][0]
    assert row["risk"] == {"before_ol": 2, "after_ol": 1, "urgency": 1, "material_triggers": ["COMPETING_NON_EQUIVALENT_SENSES"]}
    assert row["selected_candidate_id"] == "C2"
    # Two supplied minor matters plus the OL-resolved challenge, now below the material threshold.
    assert normalized["reporting"]["minor_summary"]["total"] == 3
    assert ledger["minor_summary"]["total"] == 2
    assert ledger["output_sha256"] == sha256_file(rewrite_path)


def test_failed_ol_micro_check_keeps_the_pass_one_candidate_and_marks_only_that_challenge(
    make_workspace, monkeypatch
) -> None:
    """An OL micro-response that is unusable leaves the pass-1 candidate in place and records OL as unavailable."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    manifest = _synthetic_task(root, conditional=True)
    config = load_ecosystem(root / "ecosystem.yml")
    calls: list[int] = []

    def row(challenge_id: str) -> dict:
        """Build one risk-triggering first-pass challenge with two candidates."""
        def candidate(identifier: str, rendering: str) -> dict:
            """Build one model-facing candidate."""
            return {
                "candidate_id": identifier,
                "form": rendering,
                "meaning_features": ["event"],
                "tone_and_force": "neutral",
                "register": "plain",
                "main_risk": "sense drift",
                "rejection_code": "",
                "rejection_reason": "",
            }

        return {
            "challenge_id": challenge_id,
            "scripture_reference": "MAT 1:1",
            "category": "VERB_CHOICE",
            "summary": "Resolve the disputed verb",
            "confidence": "MEDIUM",
            "candidates": [candidate("C1", "phase1"), candidate("C2", "phase2")],
            "recommended_candidate_id": "C1",
            "risk": {"before_ol": 2, "material_triggers": ["COMPETING_NON_EQUIVALENT_SENSES"]},
            "inherited_challenge_ids": [],
            "recommended_action": "Review the verb.",
        }

    class FakeExecutor:
        """Return a risk-triggering full pass, then an OL micro-response that cannot be used."""

        def status(self, **_kwargs):
            """Expose a deterministic live catalog for policy routing."""
            return _fake_codex_status()

        def execute_prevalidated(self, request, status):
            """Reuse the task-scoped readiness snapshot for every provider phase."""
            return self.execute(request)

        def execute(self, request):
            """Answer the first pass normally and every later phase with unusable text."""
            calls.append(1)
            if len(calls) > 1:
                return ProviderResponse("codex", request.model, "this is not json", {}, request.reasoning_effort)
            payload = {
                "schema_version": "1.0",
                "task_id": "synthetic-task-1",
                "files": {
                    "output/rewrite.usfm": "\\id MAT Fixture\n\\c 1\n\\v 1 phase1\n",
                    "output/grammar-assessment.json": {
                        "rules": [
                            {"rule_id": "R1", "status": "PASS", "evidence": ""},
                            {"rule_id": "R2", "status": "NOT_APPLICABLE", "evidence": ""},
                        ],
                        "unresolved": [],
                    },
                    "output/translation-challenges.json": {
                        "challenges": [row("CH-1")],
                        "minor_summary": {"by_category": {}, "notes": []},
                    },
                },
            }
            return ProviderResponse("codex", request.model, json.dumps(payload), {}, request.reasoning_effort)

    monkeypatch.setattr("sage.llm_tasks.make_executor", lambda provider, settings: FakeExecutor())
    result = execute_task(config, task_manifest=manifest)
    assert len(calls) == 2
    assert [row["challenge_id"] for row in result["conditional_ol_micro_failures"]] == ["CH-1"]
    assert result["conditional_ol_micro_failures"][0]["code"] == "LLM_PROVIDER_RESPONSE_INVALID"
    output_root = manifest.parent / "output"
    assert "\\v 1 phase1" in (output_root / "rewrite.usfm").read_text(encoding="utf-8")
    ledger = json.loads((output_root / "translation-challenges.json").read_text(encoding="utf-8"))
    assert ledger["challenges"][0]["recommended_candidate_id"] == "C1"
    assert ledger["challenges"][0]["ol_referral"]["unavailable"] is True

    from sage.rewrite_risk import validate_rewrite_challenges

    normalized = validate_rewrite_challenges(
        output_root / "translation-challenges.json",
        task_id="synthetic-task-1",
        operation="rewrite",
        scope_value="MAT 1:1",
        output_path=output_root / "rewrite.usfm",
        human_output=config.human_output,
        source_language=config.project("idKKHv0").language_code,
        target_language=config.project("usBOLx1").language_code,
    )
    assert [item["code"] for item in normalized["salvage_records"]] == ["OL_UNAVAILABLE"]
    assert normalized["challenges"][0]["selected_candidate_id"] == "C1"


def test_bic_inspect_identity_is_materialized_and_payload_decoded(make_workspace) -> None:
    """INSPECT identity comes from the sealed task; the model supplies proposals and challenges only."""
    from sage.bic_memory import validate_inspect_submission
    from sage.bic_output_contract import INSPECT_FILE, file_schemas, materialize_files

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    manifest = {
        "task_id": "inspect-1",
        "workflow": "bic",
        "operation": "inspect",
        "scope": "MAT 1",
        "resource_fingerprints": {"settings": "c" * 64},
        "allowed_writes": [INSPECT_FILE],
    }
    schema = file_schemas(config, manifest, "Write in English.")[INSPECT_FILE]
    _assert_strict_object_schema(schema)
    assert set(schema["properties"]) == {"proposals", "challenges"}
    assert "submitted_id" not in schema["properties"]["proposals"]["items"]["properties"]
    model_file = {
        "proposals": [
            {"record_type": "LEXICAL_ENTRY", "payload_json": json.dumps({"lemma": "x"}), "evidence_refs": []}
        ],
        "challenges": [
            {
                "scripture_reference": "MAT 1:1",
                "challenge_type": "LEXICAL",
                "summary": "s",
                "recommended_action": "a",
            }
        ],
    }
    files = materialize_files(config, manifest, {INSPECT_FILE: json.dumps(model_file)})
    document = json.loads(files[INSPECT_FILE])
    assert document["operation_id"] == "inspect-1"
    assert document["scope"] == "MAT 1"
    assert document["resource_fingerprints"] == {"settings": "c" * 64}
    assert document["proposals"][0]["payload"] == {"lemma": "x"}
    normalized = validate_inspect_submission(document, expected_scope="MAT 1")
    assert normalized["proposals"][0]["submitted_id"] == "P0001"
    assert normalized["challenges"][0]["submitted_id"] == "C0001"

    # A defective item is dropped and reported; the good item beside it and an empty result both stand.
    broken = dict(
        model_file,
        proposals=[{**model_file["proposals"][0], "payload_json": "{not json"}, model_file["proposals"][0]],
        challenges=[
            *model_file["challenges"],
            {**model_file["challenges"][0], "scripture_reference": "MAT 2:1"},
            {**model_file["challenges"][0], "challenge_type": "NOT_A_TYPE"},
        ],
    )
    salvaged = json.loads(materialize_files(config, manifest, {INSPECT_FILE: json.dumps(broken)})[INSPECT_FILE])
    assert [row["submitted_id"] for row in salvaged["dropped_items"]] == ["P0001"]
    result = validate_inspect_submission(salvaged, expected_scope="MAT 1")
    assert [row["submitted_id"] for row in result["proposals"]] == ["P0002"]
    assert [row["submitted_id"] for row in result["challenges"]] == ["C0001"]
    assert [(row["collection"], row["submitted_id"], row["code"]) for row in result["dropped_items"]] == [
        ("proposals", "P0001", "INSPECT_ITEM_INVALID"),
        ("challenges", "C0002", "INSPECT_REFERENCE_OUTSIDE_SCOPE"),
        ("challenges", "C0003", "INSPECT_ITEM_INVALID"),
    ]
    empty = validate_inspect_submission({**document, "proposals": [], "challenges": []}, expected_scope="MAT 1")
    assert empty["proposals"] == [] and empty["challenges"] == [] and empty["dropped_items"] == []


def test_bic_self_check_grammar_identity_is_bound_to_the_final_candidate(make_workspace) -> None:
    """SELF-CHECK grammar identity and candidate hash are set by SAGE, never echoed by the model."""
    from sage.bic_output_contract import GRAMMAR_FILE, materialize_files
    from sage.hashing import sha256_bytes

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    manifest = {
        "task_id": "check-1",
        "workflow": "bic",
        "operation": "self_check",
        "scope": "MAT 1",
        "project_grammar": {"profile_id": "G", "profile_sha256": "d" * 64, "rule_ids": ["R1"]},
    }
    candidate = "\\id MAT\n\\c 1\n\\v 1 text\n"
    model_grammar = {"rules": [{"rule_id": "R1", "status": "PASS", "evidence": ""}], "unresolved": []}
    files = materialize_files(
        config,
        manifest,
        {"output/self-check.usfm": candidate, GRAMMAR_FILE: json.dumps(model_grammar)},
    )
    document = json.loads(files[GRAMMAR_FILE])
    assert document["task_id"] == "check-1"
    assert document["profile_id"] == "G"
    assert document["profile_sha256"] == "d" * 64
    assert document["output_sha256"] == sha256_bytes(candidate.encode("utf-8"))
    assert files["output/self-check.usfm"] == candidate
    with pytest.raises(ValidationError) as caught:
        materialize_files(config, manifest, {GRAMMAR_FILE: json.dumps(model_grammar)})
    assert caught.value.code == "LLM_PROVIDER_RESPONSE_INVALID"


def test_bic_rewrite_fails_closed_without_matching_protected_contracts(make_workspace, monkeypatch) -> None:
    """A REWRITE task never reaches the provider without both sealed, pin-matching contracts."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    manifest_path = _synthetic_task(root, conditional=True)
    config = load_ecosystem(root / "ecosystem.yml")
    monkeypatch.setattr(
        "sage.llm_tasks.make_executor",
        lambda provider, settings: pytest.fail("provider must not run without protected contracts"),
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    missing = dict(manifest)
    del missing["protected_verb_selection_contract"]
    atomic_write_json(manifest_path, missing)
    with pytest.raises(ValidationError) as caught:
        execute_task(config, task_manifest=manifest_path, dry_run=True)
    assert caught.value.code == "BIC_PROTECTED_CONTRACT_MISSING"

    stale = json.loads(json.dumps(manifest))
    stale["protected_rewrite_contract"]["sha256"] = "0" * 64
    atomic_write_json(manifest_path, stale)
    with pytest.raises(ValidationError) as caught:
        execute_task(config, task_manifest=manifest_path, dry_run=True)
    assert caught.value.code == "BIC_PROTECTED_CONTRACT_STALE"


def test_task_execution_rejects_direct_route_bypass(make_workspace) -> None:
    """Operational execution cannot accept provider, model, reasoning, or policy bypasses."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    manifest = _synthetic_task(root)
    config = load_ecosystem(root / "ecosystem.yml")
    attempts = (
        {"provider": "codex"},
        {"model": "gpt-5.6-terra"},
        {"reasoning_effort": "medium"},
        {"policy_override": True},
    )
    for values in attempts:
        with pytest.raises(ValidationError) as caught:
            execute_task(config, task_manifest=manifest, dry_run=True, **values)
        assert caught.value.code == "TASK_ROUTE_BYPASS_PROHIBITED"


def test_task_execution_rejects_manifest_skill_workflow_mismatch(
    make_workspace, monkeypatch
) -> None:
    """The manifest Skill ID must own its declared workflow and operation exactly."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    manifest_path = _synthetic_task(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["operation"] = "rewrite"
    atomic_write_json(manifest_path, manifest)
    monkeypatch.setattr(
        "sage.llm_tasks.make_executor",
        lambda provider, settings: pytest.fail("provider probing must follow Skill validation"),
    )
    with pytest.raises(ValidationError) as caught:
        execute_task(load_ecosystem(root / "ecosystem.yml"), task_manifest=manifest_path)
    assert caught.value.code == "LLM_TASK_SKILL_IDENTITY_INVALID"


def test_task_execution_rejects_known_failed_route_before_prompt(
    make_workspace, monkeypatch
) -> None:
    """Known failed evidence blocks after status probing and before task execution."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    manifest = _synthetic_task(root)
    seed_path = root / "system/config/model-qualification-seeds.json"
    seeds = json.loads(seed_path.read_text(encoding="utf-8"))
    seeds["routes"][0]["qualification_status"] = "FAILED"
    seed_path.write_text(json.dumps(seeds, indent=2) + "\n", encoding="utf-8")

    class FakeExecutor:
        """Expose live capabilities and reject any attempt to send task evidence."""

        def status(self):
            """Return capabilities that exactly match the known failed evidence."""
            return _fake_codex_status()

        def execute(self, _request):
            """Fail if route rejection occurs after prompt execution."""
            raise AssertionError("unqualified route must not execute")

    monkeypatch.setattr("sage.llm_tasks.make_executor", lambda provider, settings: FakeExecutor())
    with pytest.raises(ValidationError) as caught:
        execute_task(load_ecosystem(root / "ecosystem.yml"), task_manifest=manifest)
    assert caught.value.code == "MODEL_QUALIFICATION_FAILED"


def test_task_execution_uses_exact_audited_global_override(make_workspace, monkeypatch) -> None:
    """A qualified advanced override becomes the immutable route on the task receipt."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    manifest = _synthetic_task(root)
    status = _fake_codex_status()
    route = resolve_skill_route(root, "bic-inspect", [status])
    set_global_override(root, selection=route.identity.to_dict(), statuses=[status])

    class FakeExecutor:
        """Return a deterministic output through the overridden exact route."""

        def status(self):
            """Return the same capability identity used to enable the override."""
            return status

        def execute(self, request):
            """Return one valid sealed response."""
            payload = {
                "schema_version": "1.0",
                "task_id": "synthetic-task-1",
                "files": {"output/result.txt": "accepted\n"},
            }
            return ProviderResponse(
                "codex", request.model, json.dumps(payload), {}, request.reasoning_effort
            )

    monkeypatch.setattr("sage.llm_tasks.make_executor", lambda provider, settings: FakeExecutor())
    result = execute_task(load_ecosystem(root / "ecosystem.yml"), task_manifest=manifest)
    assert result["routing_mode"] == "GLOBAL_OVERRIDE"
    assert result["route_id"] == route.identity.route_id



def test_model_policy_recommends_task_specific_model_and_reasoning(make_workspace) -> None:
    """Verify live availability is filtered through SAGE qualification and task policy."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    status = _fake_codex_status()
    _qualify_test_route(root, skill_id="bic-inspect", model="gpt-5.6-terra", reasoning_id="medium")
    _qualify_test_route(root, skill_id="bic-rewrite", model="gpt-5.6-sol", reasoning_id="high")
    _qualify_test_route(root, skill_id="bic-self-check", model="gpt-5.6-sol", reasoning_id="xhigh")
    inspect = recommend_model(root=root, status=status, workflow="bic", operation="inspect")
    rewrite = recommend_model(root=root, status=status, workflow="bic", operation="rewrite")
    self_check = recommend_model(root=root, status=status, workflow="bic", operation="self_check")
    assert (inspect.model, inspect.reasoning_effort) == ("gpt-5.6-terra", "medium")
    assert (rewrite.model, rewrite.reasoning_effort) == ("gpt-5.6-sol", "high")
    assert rewrite.conditional_second_pass_reasoning_effort == "high"
    assert (self_check.model, self_check.reasoning_effort) == ("gpt-5.6-sol", "xhigh")


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


def test_routed_sfm_sizing_tokenizes_only_routed_sfm(monkeypatch) -> None:
    """Prompt, schema, profiles, and controller JSON must never reach the sizing tokenizer."""
    import sage.llm_tasks as llm_tasks
    import sage.sfm_slicer as sfm_slicer

    calls: list[str] = []

    def fake_estimator(text: str) -> int:
        """Record estimator inputs so the test can detect any non-SFM tokenization."""
        calls.append(text)
        return 7

    monkeypatch.setattr(sfm_slicer, "estimate_tokens", fake_estimator)
    sfm = "\\id MAT\n\\c 1\n\\v 1 Scripture text\n"
    measurement = llm_tasks._route_measurement(
        "PROMPT CONTROLLER TEXT",
        {"type": "object", "properties": {"x": {"type": "string"}}},
        [
            ("packet/wip.sfm", sfm, "SUBJECT_TEXT"),
            ("packet/wip-grammar-contract.json", '{"dialect":"governed"}', "LINGUISTIC_COMPETENCE_RULES"),
        ],
    )

    assert calls == [sfm]
    assert measurement["measurement_scope"] == "routed_reads_bytes_and_sfm_tokens"
    assert measurement["total_estimated_tokens"] == 7
    # Every routed read counts against the byte budget; only SFM is sized in tokens.
    assert measurement["total_bytes"] == measurement["evidence_projection"]["model_bytes"]
    assert measurement["total_bytes"] > len(sfm.encode("utf-8"))
    assert measurement["transport_bytes"] > measurement["total_bytes"]
