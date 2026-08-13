"""Bounded storage, composite-QA, project-grammar, and recovery invariants."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage_core.act_outputs import validate_saw_findings
from sage_core.act_tasks import create_act_task, submit_act_task
from sage_core.bounded_target import merge_bounded_usfm, revert_target_scope
from sage_core.canon import PROJECT_ROLE_VALUES
from sage_core.errors import ConfigurationError, TransactionError, ValidationError
from sage_core.grammar import load_grammar_profile
from sage_core.hashing import sha256_file
from sage_core.plan_continuation import continue_saw_plan
from sage_core.registry import load_ecosystem
from sage_core.reset_state import reset_project_state
from sage_core.resource_mounts import set_resource_mount
from sage_core.external_access import READ_WRITE_TARGET
from sage_core.jobs import JobStore
from sage_core.transactions import FileTransaction


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
        timeout=40,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def _write_bic_assessment(task: dict, output_path: Path) -> None:
    """Write governed grammar evidence required by BIC REWRITE/SELF-CHECK submission."""
    grammar = task["project_grammar"]
    (output_path.parent / "grammar-assessment.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "task_id": task["task_id"],
            "scope": task["scope"],
            "profile_id": grammar["profile_id"],
            "profile_sha256": grammar["profile_sha256"],
            "output_sha256": sha256_file(output_path),
            "rules": [
                {"rule_id": rule_id, "status": "PASS", "evidence": "Checked against the bounded candidate."}
                for rule_id in grammar["rule_ids"]
            ],
            "unresolved": [],
        }),
        encoding="utf-8",
    )
    if task["operation"] == "rewrite":
        (output_path.parent / "translation-challenges.json").write_text(
            json.dumps({
                "schema_version": "1.2",
                "task_id": task["task_id"],
                "operation": "rewrite",
                "scope": task["scope"],
                "output_sha256": sha256_file(output_path),
                "challenges": [],
            }),
            encoding="utf-8",
        )


def _submit_inspect(config, task: dict) -> None:
    """Submit one valid bounded INSPECT proposal."""
    manifest = Path(task["manifest_path"])
    payload = {
        "schema_version": "1.0",
        "operation_id": task["task_id"],
        "scope": task["scope"],
        "resource_fingerprints": task["resource_fingerprints"],
        "proposals": [{
            "submitted_id": "P1",
            "record_type": "LANGUAGE_RENDERING",
            "payload": {"source": "fixture", "target": "fixture"},
            "evidence_refs": [task["scope"]],
        }],
        "challenges": [],
    }
    (manifest.parent / "output" / "inspect-submission.json").write_text(json.dumps(payload), encoding="utf-8")
    submit_act_task(config, manifest)


def _meaning_document(manifest: dict, *, request_ref: str | None = None) -> dict:
    """Return one complete meaning-stage output with an optional OL deferral."""
    document = {
        "schema_version": "2.0",
        "task_id": manifest["task_id"],
        "operation": "qa",
        "stage": "TRANSLATION_AND_MEANING_QA",
        "scope": manifest["scope"],
        "focus": None,
        "check_type": None,
        "coverage": {"status": "COMPLETE", "reviewed_references": list(manifest["expected_references"])},
        "structural_adjudications": [],
        "review_receipts": [{
            "receipt_id": "R-1",
            "work_unit_id": manifest["review_requirements"]["expected_work_unit_ids"][0],
            "task_fingerprint": manifest["task_fingerprint"],
            "reviewed_references": list(manifest["expected_references"]),
            "checks_performed": list(manifest["review_requirements"]["required_checks"]),
            "evidence_summary": "Reviewed the full bounded meaning scope against all routed evidence.",
        }],
        "findings": [],
    }
    if request_ref:
        document["ol_review_requests"] = [{
            "request_id": "OLR-1",
            "deferred_finding_id": "OL-F-001",
            "target_reference": request_ref,
            "question": "Resolve this exact bounded semantic ambiguity from the OL evidence.",
            "reason": "WIP and REFERENCE evidence do not resolve the issue.",
            "evidence_ids": [manifest["allowed_evidence_ids"][0]],
        }]
    return document


def test_bounded_target_merge_preserves_out_of_scope_content() -> None:
    """Replace only governed verses while retaining all neighbouring TARGET content."""
    target = "\\id MAT Target\n\\c 1\n\\p\n\\v 1 OLD ONE\n\\v 2 KEEP TWO\n\\v 3 KEEP THREE\n"
    candidate = "\\id MAT Candidate\n\\c 1\n\\p\n\\v 1 NEW ONE\n"
    merged = merge_bounded_usfm(target, candidate, "MAT 1:1")
    assert "\\v 1 NEW ONE" in merged
    assert "\\v 2 KEEP TWO" in merged
    assert "\\v 3 KEEP THREE" in merged
    assert "OLD ONE" not in merged


def test_mapped_target_commit_preserves_existing_filename_and_reverts_scope(package_root: Path, make_workspace, tmp_path: Path) -> None:
    """Commit and revert one bounded scope in the existing mapped Paratext book without duplication."""
    root = make_workspace(qualification_status="VALIDATED")
    external = tmp_path / "PTTarget"
    external.mkdir()
    target = external / "41MAT.SFM"
    target.write_text("\\id MAT Existing\n\\c 1\n\\p\n\\v 1 OLD ONE\n\\v 2 KEEP TWO\n", encoding="utf-8")
    set_resource_mount(root, project_id="usBOLx1", external_path=external, access_mode=READ_WRITE_TARGET)
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    inspect = create_act_task(config, workflow="bic", operation="inspect", output_project_id="usBOLx1", contemporary_source_id="idKKHv0", scope_value="MAT 1:1")
    _submit_inspect(config, inspect)
    rewrite = create_act_task(config, workflow="bic", operation="rewrite", output_project_id="usBOLx1", contemporary_source_id="idKKHv0", scope_value="MAT 1:1")
    rewrite_manifest = Path(rewrite["manifest_path"])
    rewrite_output = rewrite_manifest.parent / "output" / "rewrite.usfm"
    rewrite_output.write_text("\\id MAT Candidate\n\\c 1\n\\p\n\\v 1 NEW ONE\n", encoding="utf-8")
    _write_bic_assessment(rewrite, rewrite_output)
    submit_act_task(config, rewrite_manifest)
    check = create_act_task(config, workflow="bic", operation="self_check", output_project_id="usBOLx1", contemporary_source_id="idKKHv0", scope_value="MAT 1:1", predecessor_task=str(rewrite_manifest))
    check_manifest = Path(check["manifest_path"])
    check_output = check_manifest.parent / "output" / "self-check.usfm"
    check_output.write_text("\\id MAT Candidate\n\\c 1\n\\p\n\\v 1 NEW ONE\n", encoding="utf-8")
    _write_bic_assessment(check, check_output)
    result = submit_act_task(config, check_manifest)

    assert Path(result["commit"]["target_file"]) == target.resolve()
    assert sorted(path.name for path in external.glob("*.SFM")) == ["41MAT.SFM"]
    assert "\\v 1 NEW ONE" in target.read_text(encoding="utf-8")
    assert "\\v 2 KEEP TWO" in target.read_text(encoding="utf-8")

    store = JobStore(config.root, config.settings_path)
    project = store.load_job(check["job_id"], tool="bic")
    reverted = revert_target_scope(
        job_root=project.root,
        target_file=target,
        scope_value="MAT 1:1",
        transaction_root=config.workflow("bic").transaction_root,
        allowed_roots=(external,),
    )
    assert reverted["scope"] == "MAT 1:1"
    restored = target.read_text(encoding="utf-8")
    assert "\\v 1 OLD ONE" in restored
    assert "\\v 2 KEEP TWO" in restored


def test_transaction_refuses_target_changed_after_staging(tmp_path: Path) -> None:
    """Never overwrite a target whose bytes changed after transaction staging."""
    target = tmp_path / "41MAT.SFM"
    target.write_text("before", encoding="utf-8")
    tx = FileTransaction(tmp_path / "tx", "TEST", allowed_roots=(tmp_path,))
    tx.stage_text(target, "after")
    target.write_text("operator change", encoding="utf-8")
    with pytest.raises(TransactionError, match="changed after staging"):
        tx.commit()
    assert target.read_text(encoding="utf-8") == "operator change"


def test_invalid_job_binding_leaves_no_persisted_job(make_workspace) -> None:
    """Resolve semantic resource bindings before creating Job state on disk."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    store = JobStore(config.root, config.settings_path)
    project_id = "BIC_idKKHv0-usNIVv2-DOES_NOT_EXIST"
    with pytest.raises((ConfigurationError, ValidationError)):
        store.create_job(
            tool="bic",
            job_id=project_id,
            display_name="Invalid",
            bindings={
                "content_source": "idKKHv0",
                "lexical_donor": "usNIVv2",
                "generated_target": "DOES_NOT_EXIST",
                "original_language_greek": "GRK",
                "original_language_hebrew": "HEB",
            },
        )
    assert not (root / "jobs" / "bic" / project_id).exists()



def test_job_load_rejects_semantically_tampered_binding(make_workspace) -> None:
    """Reject a persisted Job whose resource binding no longer satisfies its declared role."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    store = JobStore(config.root, config.settings_path)
    project = store.create_job(
        tool="bic",
        job_id="BIC_idKKHv0-usNIVv2-usBOLx1",
        display_name="Tamper test",
        bindings={
            "content_source": "idKKHv0",
            "lexical_donor": "usNIVv2",
            "generated_target": "usBOLx1",
            "original_language_greek": "GRK",
            "original_language_hebrew": "HEB",
        },
    )
    raw = yaml.safe_load(project.manifest_path.read_text(encoding="utf-8"))
    raw["bindings"]["generated_target"] = "usWIP"
    project.manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="canonical identity does not match bindings"):
        store.load_job(project.job_id, tool="bic")

def test_direct_bic_chain_reuses_same_run(package_root: Path, make_workspace) -> None:
    """Direct BIC stages for the same project/scope continue one governed Run."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    inspect = create_act_task(config, workflow="bic", operation="inspect", output_project_id="usBOLx1", contemporary_source_id="idKKHv0", scope_value="MAT 1:1")
    _submit_inspect(config, inspect)
    rewrite = create_act_task(config, workflow="bic", operation="rewrite", output_project_id="usBOLx1", contemporary_source_id="idKKHv0", scope_value="MAT 1:1")
    assert inspect["job_id"] == rewrite["job_id"]
    assert inspect["run_id"] == rewrite["run_id"]
    manifest = json.loads(Path(rewrite["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["resource_bindings"] == {
        "SOURCE": "idKKHv0",
        "DONOR": "usNIVv2",
        "TARGET": "usBOLx1",
        "ORIGINAL_LANGUAGE_GREEK": "GRK",
        "ORIGINAL_LANGUAGE_HEBREW": "HEB",
    }


def test_restart_and_reset_state_do_not_modify_target_scripture(package_root: Path, make_workspace) -> None:
    """Analytical restart and runtime reset preserve committed TARGET Scripture bytes."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(config, workflow="bic", operation="inspect", output_project_id="usBOLx1", contemporary_source_id="idKKHv0", scope_value="MAT 1:1")
    target = config.project("usBOLx1").path / "41MAT.SFM"
    before = sha256_file(target)
    store = JobStore(config.root, config.settings_path)
    project = store.load_job(task["job_id"], tool="bic")
    restarted = store.restart_bic_scope(project, scope="MAT 1:1")
    assert restarted.run_id != task["run_id"]
    assert sha256_file(target) == before
    reset_project_state(config)
    assert sha256_file(target) == before


def test_selective_ol_stage_is_exactly_scoped_and_requires_ol_evidence(package_root: Path, make_workspace) -> None:
    """Selective OL reviews only requested coordinates and cannot submit a finding without OL evidence."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=3)
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    plan = create_act_task(config, workflow="saw", operation="qa", output_project_id="usWIP", contemporary_source_id="usNIVv2", scope_value="MAT 1:1-3")
    assert plan["current_stage"] == "TRANSLATION_AND_MEANING_QA"
    meaning_path = Path(plan["manifest_path"])
    meaning = json.loads(meaning_path.read_text(encoding="utf-8"))
    (meaning_path.parent / "output" / "findings.json").write_text(json.dumps(_meaning_document(meaning, request_ref="MAT 1:2")), encoding="utf-8")
    submit_act_task(config, meaning_path)
    next_stage = continue_saw_plan(config, Path(plan["plan_path"]))
    ol_path = Path(next_stage["next_unit"]["manifest_path"])
    ol = json.loads(ol_path.read_text(encoding="utf-8"))
    assert ol["expected_references"] == ["MAT 1:2"]
    assert ol["review_requirements"]["expected_ol_request_ids"] == ["OLR-1"]

    bad = {
        "schema_version": "2.0",
        "task_id": ol["task_id"],
        "operation": "qa",
        "stage": "SELECTIVE_OL_ADJUDICATION",
        "scope": ol["scope"],
        "focus": None,
        "check_type": None,
        "coverage": {"status": "COMPLETE", "reviewed_references": ["MAT 1:2"]},
        "review_receipts": [{
            "receipt_id": "R-OL",
            "work_unit_id": ol["review_requirements"]["expected_work_unit_ids"][0],
            "task_fingerprint": ol["task_fingerprint"],
            "reviewed_references": ["MAT 1:2"],
            "checks_performed": list(ol["review_requirements"]["required_checks"]),
            "evidence_summary": "Reviewed the exact inherited OL request.",
        }],
        "structural_adjudications": [],
        "ol_resolutions": [{
            "request_id": "OLR-1",
            "target_reference": "MAT 1:2",
            "outcome": "FINDING",
            "finding_id": "OL-F-001",
            "original_language_evidence": "",
            "rationale": "Claims a finding without evidence.",
        }],
        "findings": [{
            "finding_id": "OL-F-001",
            "target_reference": "MAT 1:2",
            "category": "MEANING",
            "issue": "Fixture issue.",
            "required_action": "Review.",
            "action_level": "REVIEW",
            "confidence": "MEDIUM",
            "evidence_ids": [ol["allowed_evidence_ids"][0]],
            "grammar_rule_ids": [],
            "original_language_evidence": "",
        }],
    }
    bad_path = ol_path.parent / "output" / "bad-findings.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValidationError, match="original_language_evidence"):
        validate_saw_findings(
            bad_path,
            task_id=ol["task_id"],
            operation="qa",
            qa_stage="SELECTIVE_OL_ADJUDICATION",
            scope_value=ol["scope"],
            focus=None,
            check_type=None,
            expected_references=ol["expected_references"],
            structural_candidate_ids=ol["review_requirements"].get("structural_candidate_ids", []),
            grammar_rule_ids=ol["project_grammar"]["rule_ids"],
            allowed_evidence_ids=ol["allowed_evidence_ids"],
            expected_work_unit_ids=ol["review_requirements"]["expected_work_unit_ids"],
            task_fingerprint=ol["task_fingerprint"],
            required_review_checks=ol["review_requirements"]["required_checks"],
            expected_ol_request_ids=ol["review_requirements"]["expected_ol_request_ids"],
            expected_ol_requests=ol["review_requirements"]["expected_ol_requests"],
        )

    bad_path.unlink()
    good = dict(bad)
    good["ol_resolutions"] = [{
        "request_id": "OLR-1",
        "target_reference": "MAT 1:2",
        "outcome": "NO_FINDING",
        "original_language_evidence": "The routed Greek evidence resolves the inherited question without supporting a finding.",
        "rationale": "No discrepancy remains after exact OL adjudication.",
    }]
    good["findings"] = []
    output_path = ol_path.parent / "output" / "findings.json"
    output_path.write_text(json.dumps(good), encoding="utf-8")
    submit_act_task(config, ol_path)
    final = continue_saw_plan(config, Path(plan["plan_path"]))
    aggregate = json.loads(Path(final["aggregate_path"]).read_text(encoding="utf-8"))
    assert aggregate["ol_review_requests"][0]["request_id"] == "OLR-1"
    assert aggregate["ol_resolutions"][0]["outcome"] == "NO_FINDING"



def test_structural_stage_covers_only_candidate_coordinates(package_root: Path, make_workspace) -> None:
    """Structural adjudication must use candidate coordinates rather than claiming parent QA coverage."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=3)
    (root / "projects/usWIP/custom.vrs").write_text("#! &MAT 1:2-3 = MAT 1:2\n", encoding="utf-8")
    settings = root / "ecosystem.yml"
    settings_data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    settings_data["projects"]["usWIP"]["versification"]["custom_file"] = "custom.vrs"
    settings.write_text(yaml.safe_dump(settings_data, sort_keys=False), encoding="utf-8")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    plan = create_act_task(
        config, workflow="saw", operation="qa", output_project_id="usWIP",
        contemporary_source_id="usNIVv2", scope_value="MAT 1:1-3",
    )
    assert plan["current_stage"] == "STRUCTURAL_ADJUDICATION"
    manifest = json.loads(Path(plan["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["scope"] == "MAT 1:1-3"
    assert manifest["expected_references"] == ["MAT 1:2", "MAT 1:3"]
    assert manifest["structural_candidate_ids"] == ["VRS-001"]


def test_current_contract_surfaces_have_no_removed_workflow_vocabulary(package_root: Path) -> None:
    """Lint all current human/model contract surfaces, excluding history and retained source baselines."""
    files: list[Path] = [package_root / "README.md", package_root / "HELP.md"]
    for root_name in ("docs", "jobs", "workflows", "skills"):
        root = package_root / root_name
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".md", ".yml", ".yaml"}:
                continue
            if "history" in path.parts or path.name.startswith("ORIGINAL-"):
                continue
            files.append(path)
    files.extend([package_root / "core/sage_core/natural_language.py", package_root / "core/sage_core/menu.py"])
    text = "\n".join(path.read_text(encoding="utf-8") for path in files).casefold()
    forbidden = (
        "sessions, pins",
        "review an existing `usbol` target",
        "saw qa - review a bounded target",
        "deterministic preflight/direct findings",
        "generation pin",
    )
    for phrase in forbidden:
        assert phrase not in text, phrase


def test_grammar_date_is_true_iso_calendar_date(make_workspace) -> None:
    """Reject impossible dates even when they match YYYY-MM-DD text shape."""
    root = make_workspace(qualification_status="VALIDATED")
    path = root / "profiles/languages/en/bol-target.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["profile"]["last_reviewed"] = "2026-99-99"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="valid ISO calendar date"):
        load_grammar_profile(path, expected_profile_id="bol-target", expected_language="en", expected_role="TARGET")


def test_project_role_schema_exactly_matches_runtime_canonical_set(package_root: Path) -> None:
    """Keep declarative project-role grammar byte-for-concept aligned with executable canonical vocabulary."""
    schema = yaml.safe_load((package_root / "meta/schemas/project-scope.schema.yml").read_text(encoding="utf-8"))
    assert set(schema["roles"]["values"]) == PROJECT_ROLE_VALUES


def test_external_project_format_usj_is_rejected(make_workspace) -> None:
    """Keep USJ as an internal representation rather than an external Scripture resource format."""
    root = make_workspace(qualification_status="VALIDATED")
    settings = root / "ecosystem.yml"
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    data["projects"]["idKKHv0"]["format"] = "USJ"
    settings.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="format"):
        load_ecosystem(settings)
