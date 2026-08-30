"""Build-policy, external-resource, workflow-independence, and evidence invariants."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage.storage import storage_layout
from sage.act_tasks import _partition_evidence_policy, create_act_task, submit_act_task
from sage.rtc_planner import rtc_slicing_policy
from sage.bounded_target import extract_scope_usfm
from sage.build_policy import ENABLED_AUTOMATED_PROVIDER_IDS, FUTURE_PROVIDER_IDS
from sage.errors import ConfigurationError, ValidationError
from sage.evidence import EvidencePolicy, RTCSizingPolicy
from sage.executors.base import ProviderRequest
from sage.executors.ollama import OllamaExecutor
from sage.executors import PROVIDER_IDS, make_executor
from sage.external_access import (
    READ_ONLY_SCRIPTURE,
    READ_WRITE_TARGET,
    validate_external_companion_file,
    validate_external_file,
)
from sage.llm_settings import (
    DEFAULT_LLM_SETTINGS,
    SAGE_LOCAL_ADMIN_CONTEXT_WINDOW,
    SAGE_LOCAL_ADMIN_KEEP_ALIVE,
    SAGE_LOCAL_ADMIN_MODEL,
    load_llm_settings,
)
from sage.model_service import ModelService
from sage.registry import load_ecosystem
from sage.resource_mounts import set_base_vrs_root, set_resource_mount
from sage.hashing import sha256_file
from sage.scripture import discover_usfm_files
from sage.jobs import JobStore, default_job_name
from sage.vrs import resolve_project_vrs_paths




def test_rtc_partition_policy_keeps_wip_soft_target_but_uses_complete_route_hard_limit() -> None:
    """RTC keeps its WIP target while the complete WIP+Reference SFM route owns the hard guard."""
    complete = EvidencePolicy(
        target_estimated_tokens=28000,
        hard_estimated_tokens=32000,
        hard_serialized_bytes=224000,
        minimum_target_tokens=6000,
        maximum_primary_verse_units=220,
    )
    sizing = RTCSizingPolicy.from_mapping({
        "provider": "codex",
        "estimator": "SAGE_MULTILINGUAL_HEURISTIC_1",
        "wip_target_min_tokens": 6000,
        "wip_target_max_tokens": 7000,
        "wip_hard_exclusive_tokens": 8000,
        "route_hard_max_tokens": 32000,
        "route_hard_serialized_bytes": 224000,
    })

    derived = rtc_slicing_policy(complete, sizing)

    assert derived.target_estimated_tokens == 6000
    assert derived.minimum_target_tokens == 5000
    assert derived.preferred_max_estimated_tokens == 7000
    assert derived.hard_estimated_tokens == 32000
    assert derived.hard_serialized_bytes == 224000


def test_rtc_sizing_rejects_route_cap_below_wip_hard_limit() -> None:
    """RTC configuration must fail when the routed-SFM hard guard cannot contain WIP."""
    value = {
        "provider": "codex",
        "estimator": "SAGE_MULTILINGUAL_HEURISTIC_1",
        "wip_target_min_tokens": 6000,
        "wip_target_max_tokens": 7000,
        "wip_hard_exclusive_tokens": 8000,
        "route_hard_max_tokens": 7000,
        "route_hard_serialized_bytes": 224000,
    }

    with pytest.raises(ConfigurationError, match="WIP hard maximum exceeds"):
        RTCSizingPolicy.from_mapping(value)

def _initialize(package_root: Path, root: Path) -> None:
    """Initialize one disposable workspace through the public CLI."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "system" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "sage.cli", "--settings", str(root / "ecosystem.yml"), "workspace", "initialize"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout




def _write_bic_assessment(task: dict, output_path: Path) -> None:
    """Write a complete grammar assessment and empty challenge ledger for one BIC fixture."""
    grammar = task["project_grammar"]
    (output_path.parent / "grammar-assessment.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "task_id": task["task_id"],
                "scope": task["scope"],
                "profile_id": grammar["profile_id"],
                "profile_sha256": grammar["profile_sha256"],
                "output_sha256": sha256_file(output_path),
                "rules": [
                    {
                        "rule_id": rule_id,
                        "status": "PASS",
                        "evidence": "Checked against the bounded fixture candidate.",
                    }
                    for rule_id in grammar["rule_ids"]
                ],
                "unresolved": [],
            }
        ),
        encoding="utf-8",
    )
    if task["operation"] == "rewrite":
        (output_path.parent / "translation-challenges.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.2",
                    "task_id": task["task_id"],
                    "operation": "rewrite",
                    "scope": task["scope"],
                    "output_sha256": sha256_file(output_path),
                    "challenges": [],
                }
            ),
            encoding="utf-8",
        )


def _submit_empty_inspect(config, task: dict) -> Path:
    """Submit one bounded INSPECT fixture and return its manifest path."""
    manifest = Path(task["manifest_path"])
    payload = {
        "schema_version": "1.0",
        "operation_id": task["task_id"],
        "scope": task["scope"],
        "resource_fingerprints": task["resource_fingerprints"],
        "proposals": [
            {
                "submitted_id": "P1",
                "record_type": "LANGUAGE_RENDERING",
                "payload": {"source": "fixture", "target": "fixture"},
                "evidence_refs": [task["scope"]],
            }
        ],
        "challenges": [],
    }
    (manifest.parent / "output" / "inspect-submission.json").write_text(json.dumps(payload), encoding="utf-8")
    submit_act_task(config, manifest)
    return manifest


def test_provider_build_policy_enables_only_codex_and_preserves_ollama_admin(tmp_path: Path) -> None:
    """Verify Codex-only workflow execution while retaining the governed Ollama assistant."""
    assert PROVIDER_IDS == ("codex", "ollama")
    assert ENABLED_AUTOMATED_PROVIDER_IDS == ("codex",)
    assert set(FUTURE_PROVIDER_IDS) >= {"grok", "gemini"}
    with pytest.raises(ConfigurationError, match="disabled by the 0.01beta2 build policy"):
        make_executor("ollama", DEFAULT_LLM_SETTINGS)

    sage_root = tmp_path / "SAGE" / "app"
    sage_root.mkdir(parents=True)
    service = ModelService(sage_root)
    provisioned = service.provision(provider="ollama", model=SAGE_LOCAL_ADMIN_MODEL)
    assert provisioned["status"] == "PROVISIONED_DISABLED"
    ollama = load_llm_settings(sage_root)["providers"]["ollama"]
    assert ollama["model"] == SAGE_LOCAL_ADMIN_MODEL
    assert ollama["context_window"] == SAGE_LOCAL_ADMIN_CONTEXT_WINDOW
    assert ollama["keep_alive"] == SAGE_LOCAL_ADMIN_KEEP_ALIVE
    with pytest.raises(ConfigurationError, match="supports only"):
        service.provision(provider="ollama", model="qwen-local")
    with pytest.raises(ConfigurationError, match="disabled for automated execution"):
        service.select(provider="ollama", model=SAGE_LOCAL_ADMIN_MODEL)


def test_sage_local_admin_ollama_request_is_pinned_and_unloaded(monkeypatch) -> None:
    """Verify the single local model uses the governed 16K, immediate-unload request."""
    captured: dict = {}

    monkeypatch.setattr(
        "sage.executors.ollama.get_json",
        lambda _url: {"models": [{"name": SAGE_LOCAL_ADMIN_MODEL}]},
    )

    def fake_post(url: str, payload: dict, *, timeout: int) -> dict:
        """Capture the governed Ollama request and return one valid local response."""
        captured.update({"url": url, "payload": payload, "timeout": timeout})
        return {"message": {"content": '{"status":"OK"}'}, "done_reason": "stop"}

    monkeypatch.setattr("sage.executors.ollama.post_json", fake_post)
    executor = OllamaExecutor()
    response = executor.execute(
        ProviderRequest(
            prompt="Return status.",
            schema={"type": "object"},
            model=SAGE_LOCAL_ADMIN_MODEL,
            timeout_seconds=12,
        )
    )

    assert response.model == SAGE_LOCAL_ADMIN_MODEL
    assert captured["payload"]["model"] == SAGE_LOCAL_ADMIN_MODEL
    assert captured["payload"]["options"]["num_ctx"] == SAGE_LOCAL_ADMIN_CONTEXT_WINDOW
    assert captured["payload"]["keep_alive"] == SAGE_LOCAL_ADMIN_KEEP_ALIVE
    assert captured["payload"]["think"] is False


def test_external_scripture_extensions_are_case_insensitive_and_narrow(tmp_path: Path) -> None:
    """Verify external access accepts case-insensitive SFM/VRS and rejects other file types."""
    root = tmp_path / "PT"
    root.mkdir()
    sfm = root / "41MAT.SfM"
    vrs = root / "ENG.VrS"
    xml = root / "Settings.xml"
    usfm = root / "41MAT.USFM"
    for path in (sfm, vrs, xml, usfm):
        path.write_text("fixture", encoding="utf-8")

    assert validate_external_file(sfm, roots=(root,)) == sfm.resolve()
    assert validate_external_file(vrs, roots=(root,)) == vrs.resolve()
    assert validate_external_file(sfm, roots=(root,), write=True) == sfm.resolve()
    with pytest.raises(ValidationError, match="not allowed"):
        validate_external_file(vrs, roots=(root,), write=True)
    with pytest.raises(ValidationError, match="not allowed"):
        validate_external_file(xml, roots=(root,))
    with pytest.raises(ValidationError, match="not allowed"):
        validate_external_file(usfm, roots=(root,))
    assert discover_usfm_files(root) == [sfm]


def test_external_companion_access_allows_only_an_explicit_governed_filename(
    tmp_path: Path,
) -> None:
    """Authority metadata may be read without broadly permitting external YAML files."""
    root = tmp_path / "OL"
    root.mkdir()
    authority = root / "authority-profile.yml"
    unrelated = root / "settings.yml"
    authority.write_text("profile: {}\n", encoding="utf-8")
    unrelated.write_text("settings: {}\n", encoding="utf-8")

    assert validate_external_companion_file(
        authority,
        roots=(root,),
        allowed_filenames=("authority-profile.yml",),
    ) == authority.resolve()
    with pytest.raises(ValidationError, match="companion read is not allowed"):
        validate_external_companion_file(
            unrelated,
            roots=(root,),
            allowed_filenames=("authority-profile.yml",),
        )


def test_external_path_escape_is_rejected(tmp_path: Path) -> None:
    """Verify external resource paths cannot escape their authorized root."""
    root = tmp_path / "PT"
    root.mkdir()
    outside = tmp_path / "outside.SFM"
    outside.write_text("fixture", encoding="utf-8")
    with pytest.raises(ValidationError, match="escapes its authorized root"):
        validate_external_file(outside, roots=(root,))


def test_mapped_project_vrs_precedes_configurable_base_vrs_root(make_workspace, tmp_path: Path) -> None:
    """Verify project-local VRS takes precedence over the configurable base VRS root."""
    root = make_workspace(configured=True)
    mapped = tmp_path / "MappedSource"
    mapped.mkdir()
    (mapped / "41MAT.sFm").write_text("\\id MAT\n\\c 1\n\\v 1 External source.\n", encoding="utf-8")
    local_vrs = mapped / "ENG.VRS"
    local_vrs.write_text("MAT 1:1\n", encoding="utf-8")
    base_root = tmp_path / "BaseVRS"
    base_root.mkdir()
    fallback = base_root / "eng.vrs"
    fallback.write_text("MAT 1:3\n", encoding="utf-8")
    (base_root / "org.vrs").write_text("MAT 1:3\n", encoding="utf-8")

    set_resource_mount(root, project_id="idKKHv0", external_path=mapped, access_mode=READ_ONLY_SCRIPTURE)
    set_base_vrs_root(root, base_vrs_root=base_root)
    config = load_ecosystem(root / "ecosystem.yml")
    base, _ = resolve_project_vrs_paths(config, config.project("idKKHv0"))
    assert base == local_vrs.resolve()

    local_vrs.unlink()
    config = load_ecosystem(root / "ecosystem.yml")
    base, _ = resolve_project_vrs_paths(config, config.project("idKKHv0"))
    assert base == fallback.resolve()


def test_writable_external_mode_is_reserved_for_bic_generated_target(make_workspace, tmp_path: Path) -> None:
    """Verify writable external mode is restricted to a BIC generated TARGET."""
    root = make_workspace(configured=True)
    external = tmp_path / "External"
    external.mkdir()
    set_resource_mount(root, project_id="usWIP", external_path=external, access_mode=READ_WRITE_TARGET)
    with pytest.raises(ConfigurationError, match="allowed only for a BIC GENERATED_TARGET"):
        load_ecosystem(root / "ecosystem.yml")

    set_resource_mount(root, project_id="usWIP", external_path=external, access_mode=READ_ONLY_SCRIPTURE)
    set_resource_mount(root, project_id="usBOLx1", external_path=external, access_mode=READ_WRITE_TARGET)
    config = load_ecosystem(root / "ecosystem.yml")
    assert config.project("usWIP").external_readonly is True
    assert config.project("usBOLx1").external_writable_target is True


def test_saw_job_binding_assigns_reference_purpose_to_locked_project(package_root: Path, make_workspace) -> None:
    """Verify a SAW Job assigns REFERENCE purpose to a compatible locked registration."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    assert task["output_project"] == "usWIP"
    alternate = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIRVv2",
        scope_value="MAT 1:1",
    )
    assert alternate["resource_bindings"]["REFERENCE"] == "usNIRVv2"


def test_bic_default_identity_includes_source_donor_and_target() -> None:
    """Verify default BIC identity contains SOURCE, DONOR, and TARGET."""
    assert default_job_name("bic", "usBOLx1", "idKKHv0", "usNIVv2") == "BIC_idKKHv0-usNIVv2-usBOLx1"


def test_bic_existing_project_id_rejects_changed_donor(make_workspace) -> None:
    """Verify an existing BIC project ID rejects changed resource bindings."""
    root = make_workspace(configured=True)
    settings = root / "ecosystem.yml"
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    data["projects"]["usNIV2"] = json.loads(json.dumps(data["projects"]["usNIVv2"]))
    data["projects"]["usNIV2"]["path"] = "usNIV2"
    settings.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    donor_folder = storage_layout(root).projects_root / "usNIV2"
    donor_folder.mkdir()
    (donor_folder / "41MAT.SFM").write_text((storage_layout(root).projects_root / "usNIVv2" / "41MAT.SFM").read_text(encoding="utf-8"), encoding="utf-8")
    store = JobStore(root, settings)
    project_id = "BIC_idKKHv0-usNIVv2-usBOLx1"
    base = {
        "content_source": "idKKHv0",
        "lexical_donor": "usNIVv2",
        "generated_target": "usBOLx1",
        "original_language_greek": "GRK",
        "original_language_hebrew": "HEB",
    }
    store.create_job(tool="bic", job_id=project_id, display_name="fixture", bindings=base)
    changed = dict(base)
    changed["lexical_donor"] = "usNIV2"
    with pytest.raises(ValidationError, match="canonical binding-derived name"):
        store.create_job(tool="bic", job_id=project_id, display_name="fixture", bindings=changed)


def test_bic_donor_language_must_match_target(package_root: Path, make_workspace) -> None:
    """Verify BIC DONOR language must match TARGET language."""
    root = make_workspace(qualification_status="VALIDATED")
    settings = root / "ecosystem.yml"
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    donor = data["projects"]["usNIRVv2"]
    donor["scope"]["roles"].append("LEXICAL_DONOR")
    donor["language"] = {"code": "id", "profile": "id"}
    settings.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    _initialize(package_root, root)
    config = load_ecosystem(settings)
    with pytest.raises(ValidationError, match="must match TARGET language"):
        create_act_task(
            config,
            workflow="bic",
            operation="inspect",
            output_project_id="usBOLx1",
            contemporary_source_id="idKKHv0",
            lexical_donor_id="usNIRVv2",
            scope_value="MAT 1:1",
        )


def test_bic_rewrite_rejects_changed_inspect_evidence_cohort(package_root: Path, make_workspace) -> None:
    """Verify REWRITE rejects SOURCE evidence changed after committed INSPECT."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    inspect = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1:1",
    )
    _submit_empty_inspect(config, inspect)
    source = storage_layout(root).projects_root / "idKKHv0" / "41MAT.SFM"
    source.write_text(source.read_text(encoding="utf-8") + "\\rem changed after INSPECT\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="evidence changed after INSPECT"):
        create_act_task(
            config,
            workflow="bic",
            operation="rewrite",
            output_project_id="usBOLx1",
            contemporary_source_id="idKKHv0",
            scope_value="MAT 1:1",
        )


def test_ai_drafted_grammar_is_an_accepted_operational_state(package_root: Path, make_workspace) -> None:
    """Verify AI_DRAFTED grammar is accepted without implying human approval."""
    root = make_workspace(qualification_status="VALIDATED")
    profile = root / "system" / "config" / "profiles" / "grammar" / "id" / "source.yml"
    data = yaml.safe_load(profile.read_text(encoding="utf-8"))
    data["profile"]["status"] = "AI_DRAFTED"
    data["provenance"] = {
        "type": "LLM_GENERAL_LANGUAGE_KNOWLEDGE",
        "provider": "OPENAI",
        "model": "fixture-model",
        "project_validated": False,
    }
    profile.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1:1",
    )
    assert task["source_grammar"]["status"] == "AI_DRAFTED"
    assert task["grammar_override"] is None


def test_registry_rejects_shared_bic_target_and_saw_wip_identity(make_workspace) -> None:
    """Verify one registry resource cannot simultaneously be BIC TARGET and SAW WIP."""
    root = make_workspace(configured=True)
    settings = root / "ecosystem.yml"
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    data["projects"]["usBOLx1"]["scope"]["roles"].append("WIP")
    settings.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="cannot be both BIC GENERATED_TARGET and SAW WIP"):
        load_ecosystem(settings)


def test_external_bic_target_commit_writes_only_designated_sfm(package_root: Path, make_workspace, tmp_path: Path) -> None:
    """Verify governed SELF-CHECK can commit only the designated external TARGET SFM."""
    root = make_workspace(qualification_status="VALIDATED")
    external_target = tmp_path / "ParatextTarget"
    external_target.mkdir()
    set_resource_mount(root, project_id="usBOLx1", external_path=external_target, access_mode=READ_WRITE_TARGET)
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    inspect = create_act_task(
        config, workflow="bic", operation="inspect", output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0", scope_value="MAT 1:1",
    )
    _submit_empty_inspect(config, inspect)

    rewrite = create_act_task(
        config, workflow="bic", operation="rewrite", output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0", scope_value="MAT 1:1",
    )
    rewrite_manifest = Path(rewrite["manifest_path"])
    rewrite_output = rewrite_manifest.parent / "output" / "rewrite.usfm"
    rewrite_output.write_text(
        "\\id MAT Fixture\n" + extract_scope_usfm(
            (storage_layout(root).projects_root / "idKKHv0" / "41MAT.SFM").read_text(encoding="utf-8"),
            "MAT 1:1",
        ),
        encoding="utf-8",
    )
    _write_bic_assessment(rewrite, rewrite_output)
    submit_act_task(config, rewrite_manifest)

    self_check = create_act_task(
        config, workflow="bic", operation="self_check", output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0", scope_value="MAT 1:1", predecessor_task=str(rewrite_manifest),
    )
    self_manifest = Path(self_check["manifest_path"])
    self_output = self_manifest.parent / "output" / "self-check.usfm"
    self_output.write_bytes(rewrite_output.read_bytes())
    _write_bic_assessment(self_check, self_output)
    result = submit_act_task(config, self_manifest)

    target = Path(result["commit"]["target_file"])
    assert target.parent == external_target.resolve()
    assert target.suffix.casefold() == ".sfm"
    assert target.is_file()
    assert not list(external_target.glob("*.VRS"))


def test_read_only_external_bic_target_refuses_commit(package_root: Path, make_workspace, tmp_path: Path) -> None:
    """Verify a read-only external BIC TARGET rejects the commit boundary."""
    root = make_workspace(qualification_status="VALIDATED")
    external_target = tmp_path / "ReadOnlyTarget"
    external_target.mkdir()
    set_resource_mount(root, project_id="usBOLx1", external_path=external_target, access_mode=READ_ONLY_SCRIPTURE)
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    inspect = create_act_task(
        config, workflow="bic", operation="inspect", output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0", scope_value="MAT 1:1",
    )
    _submit_empty_inspect(config, inspect)
    rewrite = create_act_task(
        config, workflow="bic", operation="rewrite", output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0", scope_value="MAT 1:1",
    )
    rewrite_manifest = Path(rewrite["manifest_path"])
    rewrite_output = rewrite_manifest.parent / "output" / "rewrite.usfm"
    rewrite_output.write_text(
        "\\id MAT Fixture\n" + extract_scope_usfm(
            (storage_layout(root).projects_root / "idKKHv0" / "41MAT.SFM").read_text(encoding="utf-8"),
            "MAT 1:1",
        ),
        encoding="utf-8",
    )
    _write_bic_assessment(rewrite, rewrite_output)
    submit_act_task(config, rewrite_manifest)
    self_check = create_act_task(
        config, workflow="bic", operation="self_check", output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0", scope_value="MAT 1:1", predecessor_task=str(rewrite_manifest),
    )
    self_manifest = Path(self_check["manifest_path"])
    self_output = self_manifest.parent / "output" / "self-check.usfm"
    self_output.write_bytes(rewrite_output.read_bytes())
    _write_bic_assessment(self_check, self_output)
    with pytest.raises(ValidationError, match="External BIC TARGET usBOLx1 is read-only"):
        submit_act_task(config, self_manifest)
