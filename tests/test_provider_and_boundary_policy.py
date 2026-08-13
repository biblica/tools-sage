"""Build-policy, external-resource, workflow-independence, and evidence invariants."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage_core.act_tasks import create_act_task, submit_act_task
from sage_core.build_policy import ENABLED_AUTOMATED_PROVIDER_IDS, FUTURE_PROVIDER_IDS
from sage_core.errors import ConfigurationError, ValidationError
from sage_core.executors import make_executor
from sage_core.external_access import READ_ONLY_SCRIPTURE, READ_WRITE_TARGET, validate_external_file
from sage_core.llm_settings import DEFAULT_LLM_SETTINGS, load_llm_settings
from sage_core.model_service import ModelService
from sage_core.registry import load_ecosystem
from sage_core.resource_mounts import set_base_vrs_root, set_resource_mount
from sage_core.hashing import sha256_file
from sage_core.scripture import discover_usfm_files
from sage_core.jobs import JobStore, default_job_name
from sage_core.vrs import resolve_project_vrs_paths


def _initialize(package_root: Path, root: Path) -> None:
    """Initialise one disposable workspace through the public CLI."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "core")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "sage_core.cli", "--settings", str(root / "ecosystem.yml"), "workspace", "initialize"],
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


def test_provider_build_policy_enables_only_codex_and_preserves_future_slots(tmp_path: Path) -> None:
    """Verify Codex-only execution while preserving disabled and future provider slots."""
    assert ENABLED_AUTOMATED_PROVIDER_IDS == ("codex",)
    assert set(FUTURE_PROVIDER_IDS) >= {"grok", "gemini"}
    with pytest.raises(ConfigurationError, match="disabled by the 0.01-rc7.04 build policy"):
        make_executor("ollama", DEFAULT_LLM_SETTINGS)
    with pytest.raises(ConfigurationError, match="disabled by the 0.01-rc7.04 build policy"):
        make_executor("lmstudio", DEFAULT_LLM_SETTINGS)

    service = ModelService(tmp_path)
    provisioned = service.provision(provider="ollama", model="qwen-local")
    assert provisioned["status"] == "PROVISIONED_DISABLED"
    assert load_llm_settings(tmp_path)["providers"]["ollama"]["model"] == "qwen-local"
    with pytest.raises(ConfigurationError, match="disabled for automated execution"):
        service.select(provider="ollama", model="qwen-local")


def test_disabled_provider_selection_migrates_to_codex_without_losing_provisioning(tmp_path: Path) -> None:
    """Verify disabled selection migrates to Codex without dropping provisioned configuration."""
    state = tmp_path / "state"
    state.mkdir()
    value = json.loads(json.dumps(DEFAULT_LLM_SETTINGS))
    value["selected_provider"] = "lmstudio"
    value["providers"]["lmstudio"]["model"] = "local-model"
    (state / "llm-settings.json").write_text(json.dumps(value), encoding="utf-8")
    loaded = load_llm_settings(tmp_path)
    assert loaded["selected_provider"] == "codex"
    assert loaded["providers"]["lmstudio"]["model"] == "local-model"


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


def test_external_path_escape_is_rejected(tmp_path: Path) -> None:
    """Verify external resource paths cannot escape their authorised root."""
    root = tmp_path / "PT"
    root.mkdir()
    outside = tmp_path / "outside.SFM"
    outside.write_text("fixture", encoding="utf-8")
    with pytest.raises(ValidationError, match="escapes its authorised root"):
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
        operation="qa",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    assert task["output_project"] == "usWIP"
    alternate = create_act_task(
        config,
        workflow="saw",
        operation="qa",
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
    donor_folder = root / "projects" / "usNIV2"
    donor_folder.mkdir()
    (donor_folder / "41MAT.SFM").write_text((root / "projects/usNIVv2/41MAT.SFM").read_text(encoding="utf-8"), encoding="utf-8")
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
    source = root / "projects" / "idKKHv0" / "41MAT.SFM"
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
    profile = root / "profiles" / "languages" / "id" / "source.yml"
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
    rewrite_output.write_bytes((rewrite_manifest.parent / "packet" / "source.usfm").read_bytes())
    _write_bic_assessment(rewrite, rewrite_output)
    submit_act_task(config, rewrite_manifest)

    self_check = create_act_task(
        config, workflow="bic", operation="self_check", output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0", scope_value="MAT 1:1", predecessor_task=str(rewrite_manifest),
    )
    self_manifest = Path(self_check["manifest_path"])
    self_output = self_manifest.parent / "output" / "self-check.usfm"
    self_output.write_bytes((self_manifest.parent / "packet" / "staged-target.usfm").read_bytes())
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
    rewrite_output.write_bytes((rewrite_manifest.parent / "packet" / "source.usfm").read_bytes())
    _write_bic_assessment(rewrite, rewrite_output)
    submit_act_task(config, rewrite_manifest)
    self_check = create_act_task(
        config, workflow="bic", operation="self_check", output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0", scope_value="MAT 1:1", predecessor_task=str(rewrite_manifest),
    )
    self_manifest = Path(self_check["manifest_path"])
    self_output = self_manifest.parent / "output" / "self-check.usfm"
    self_output.write_bytes((self_manifest.parent / "packet" / "staged-target.usfm").read_bytes())
    _write_bic_assessment(self_check, self_output)
    with pytest.raises(ValidationError, match="External BIC TARGET usBOLx1 is read-only"):
        submit_act_task(config, self_manifest)
