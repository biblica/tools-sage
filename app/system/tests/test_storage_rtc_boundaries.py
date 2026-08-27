"""Bounded storage, composite-RTC, project-grammar, and recovery invariants."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage.storage import storage_layout
from sage.act_outputs import validate_saw_findings
from sage.act_tasks import create_act_task, submit_act_task
from sage.bounded_target import merge_bounded_usfm, revert_target_scope
from sage.canon import PROJECT_ROLE_VALUES
from sage.errors import ConfigurationError, TransactionError, ValidationError
from sage.grammar import load_grammar_profile
from sage.hashing import sha256_file
from sage.plan_continuation import continue_saw_plan
from sage.registry import load_ecosystem
from sage.references import parse_scope
from sage.reset_state import reset_project_state
from sage.resource_mounts import set_resource_mount
from sage.scripture import compile_project_scope
from sage.external_access import READ_WRITE_TARGET
from sage.jobs import JobStore
from sage.transactions import FileTransaction


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
        "narrative_language": manifest["narrative_language"],
        "task_id": manifest["task_id"],
        "operation": "rtc",
        "stage": "REFERENCE_TEXT_COMPARISON",
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
    assert not (storage_layout(root).jobs_root / "bic" / project_id).exists()



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
    assert manifest["schema_version"] == "2.4"
    assert manifest["narrative_language"] == {
        "tag": "en",
        "authority": "CANONICAL_REPORT_NARRATIVE",
    }
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


def test_saw_submission_canonicalizes_provider_local_finding_id_syntax(package_root: Path, make_workspace) -> None:
    """Provider punctuation in a local finding handle must not abort a completed SAW unit."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=3)
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    plan = create_act_task(
        config, workflow="saw", operation="rtc", output_project_id="usWIP",
        contemporary_source_id="usNIVv2", scope_value="MAT 1:1-3"
    )
    manifest_path = Path(plan["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    document = _meaning_document(manifest)
    submitted_id = "MAT 1:1 finding #1"
    document["findings"] = [{
        "finding_id": submitted_id,
        "target_reference": "MAT 1:1",
        "category": "MEANING",
        "issue": "Fixture discrepancy.",
        "required_action": "Review the bounded wording.",
        "action_level": "REVIEW",
        "confidence": "MEDIUM",
        "evidence_ids": [manifest["allowed_evidence_ids"][0]],
        "grammar_rule_ids": [],
        "original_language_evidence": "",
    }]
    output_path = manifest_path.parent / "output" / "findings.json"
    output_path.write_text(json.dumps(document), encoding="utf-8")

    result = submit_act_task(config, manifest_path)

    assert result["status"] == "FINALIZED"
    normalized = json.loads(
        (manifest_path.parent / "validation" / "normalized-findings.json").read_text(encoding="utf-8")
    )
    finding_id = normalized["findings"][0]["finding_id"]
    assert finding_id != submitted_id.upper()
    assert finding_id.startswith("MAT-1-1-FINDING-1-")
    assert len(finding_id) <= 64


def test_selective_ol_stage_is_exactly_scoped_and_requires_ol_evidence(package_root: Path, make_workspace) -> None:
    """Selective OL reviews only requested coordinates and cannot submit a finding without OL evidence."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=3)
    _initialize(package_root, root)
    saw_profile = root / "system" / "config" / "workflows" / "saw" / "profile.yml"
    saw_raw = yaml.safe_load(saw_profile.read_text(encoding="utf-8"))
    saw_raw["check_policy"]["rtc"]["original_language"]["source_text_drift_adjudication"] = "ENABLED"
    saw_profile.write_text(yaml.safe_dump(saw_raw, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    plan = create_act_task(config, workflow="saw", operation="rtc", output_project_id="usWIP", contemporary_source_id="usNIVv2", scope_value="MAT 1:1-3")
    assert plan["current_stage"] == "REFERENCE_TEXT_COMPARISON"
    meaning_path = Path(plan["manifest_path"])
    meaning = json.loads(meaning_path.read_text(encoding="utf-8"))
    act_text = (meaning_path.parent / "ACT.md").read_text(encoding="utf-8")
    assert "Defer every material content-bearing variance" in act_text
    assert "OT requests to the Job-bound Hebrew resource and NT requests to the Job-bound Greek resource" in act_text
    assert "Grammar, readability, punctuation, spelling, USFM/structure, style, and ordinary consistency defects remain direct RTC findings" in act_text
    (meaning_path.parent / "output" / "findings.json").write_text(json.dumps(_meaning_document(meaning, request_ref="MAT 1:2")), encoding="utf-8")
    submit_act_task(config, meaning_path)
    next_stage = continue_saw_plan(config, Path(plan["plan_path"]))
    ol_path = Path(next_stage["next_unit"]["manifest_path"])
    ol = json.loads(ol_path.read_text(encoding="utf-8"))
    assert ol["expected_references"] == ["MAT 1:2"]
    assert ol["review_requirements"]["expected_ol_request_ids"] == ["OLR-1"]
    assert ol["packets"]["original_language"]["evidence_id"] == "ORIGINAL_LANGUAGE_GREEK"
    assert "ORIGINAL_LANGUAGE_GREEK" in ol["allowed_evidence_ids"]
    assert "ORIGINAL_LANGUAGE" not in ol["allowed_evidence_ids"]

    bad = {
        "schema_version": "2.0",
        "narrative_language": ol["narrative_language"],
        "task_id": ol["task_id"],
        "operation": "rtc",
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
            operation="rtc",
            rtc_stage="SELECTIVE_OL_ADJUDICATION",
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


def test_partitioned_selective_ol_stage_preserves_inherited_request_contracts(
    package_root: Path,
    make_workspace,
    monkeypatch,
) -> None:
    """Automatic partitioning must retain each inherited OL request and exact source scope."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=3)
    _initialize(package_root, root)
    saw_profile = root / "system" / "config" / "workflows" / "saw" / "profile.yml"
    saw_raw = yaml.safe_load(saw_profile.read_text(encoding="utf-8"))
    saw_raw["check_policy"]["rtc"]["original_language"]["source_text_drift_adjudication"] = "ENABLED"
    saw_profile.write_text(yaml.safe_dump(saw_raw, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")

    plan = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1-3",
    )
    meaning_path = Path(plan["manifest_path"])
    meaning_manifest = json.loads(meaning_path.read_text(encoding="utf-8"))
    meaning = _meaning_document(meaning_manifest, request_ref="MAT 1:1")
    meaning["ol_review_requests"].extend([
        {
            "request_id": "OLR-2",
            "deferred_finding_id": "OL-F-002",
            "target_reference": "MAT 1:2",
            "question": "Resolve the second exact bounded semantic ambiguity from the OL evidence.",
            "reason": "WIP and REFERENCE evidence do not resolve the second issue.",
            "evidence_ids": [meaning_manifest["allowed_evidence_ids"][0]],
        },
        {
            "request_id": "OLR-3",
            "deferred_finding_id": "OL-F-003",
            "target_reference": "MAT 1:3",
            "question": "Resolve the third exact bounded semantic ambiguity from the OL evidence.",
            "reason": "WIP and REFERENCE evidence do not resolve the third issue.",
            "evidence_ids": [meaning_manifest["allowed_evidence_ids"][0]],
        },
    ])
    (meaning_path.parent / "output" / "findings.json").write_text(
        json.dumps(meaning),
        encoding="utf-8",
    )
    submit_act_task(config, meaning_path)

    from dataclasses import replace
    import sage.act_tasks as act_tasks

    original_enforce = act_tasks._enforce_context_budget
    enforce_calls = 0

    def force_parent_partition(telemetry, policy, **kwargs):
        """Force only the parent selective-OL task through its partition fallback."""
        nonlocal enforce_calls
        enforce_calls += 1
        if enforce_calls == 1:
            raise act_tasks.EvidenceLimitError("Force the selective-OL parent through partitioning.")
        return original_enforce(telemetry, policy, **kwargs)

    original_partition_policy = act_tasks._partition_evidence_policy

    def one_verse_partition_policy(workflow, operation, policy):
        """Make the regression fixture create one governed child per requested verse."""
        return replace(
            original_partition_policy(workflow, operation, policy),
            maximum_primary_verse_units=1,
        )

    monkeypatch.setattr(act_tasks, "_enforce_context_budget", force_parent_partition)
    monkeypatch.setattr(act_tasks, "_partition_evidence_policy", one_verse_partition_policy)

    next_stage = continue_saw_plan(config, Path(plan["plan_path"]))
    assert next_stage["status"] == "NEXT_WORK_UNIT"
    composite = json.loads(Path(plan["plan_path"]).read_text(encoding="utf-8"))
    selective_stage = composite["stages"][-1]
    assert selective_stage["stage"] == "SELECTIVE_OL_ADJUDICATION"
    assert selective_stage["kind"] == "PARTITIONED_PLAN"

    manifests = [
        json.loads(Path(path).read_text(encoding="utf-8"))
        for path in selective_stage["task_manifests"]
    ]
    assert [manifest["scope"] for manifest in manifests] == [
        "MAT 1:1",
        "MAT 1:2",
        "MAT 1:3",
    ]
    for index, manifest in enumerate(manifests, start=1):
        reference = f"MAT 1:{index}"
        request_id = f"OLR-{index}"
        requirements = manifest["review_requirements"]
        assert requirements["expected_ol_request_ids"] == [request_id]
        assert [row["request_id"] for row in requirements["expected_ol_requests"]] == [request_id]
        assert requirements["stage_references"] == [reference]
        assert manifest["expected_references"] == [reference]
        assert manifest["packets"]["original_language"]["atomic_references"] == [reference]


def test_operator_approved_saw_preview_is_the_runtime_partition_plan(package_root: Path, make_workspace) -> None:
    """Meaning RTC must execute the exact work units approved before Run creation."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=3)
    _initialize(package_root, root)
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1:1-3")
    config = load_ecosystem(store.ensure_runtime_files(job))
    compiled = compile_project_scope(
        config, config.project(job.bindings["wip"]), parse_scope("MAT 1:1-3")
    )
    approved = {
        "schema_version": "1.2",
        "plan_id": "SAW-RTC-MAT-APPROVED",
        "plan_fingerprint": "a" * 64,
        "workflow_id": "saw",
        "operation": "rtc",
        "operator_scope": "MAT 1:1-3",
        "project_id": job.bindings["wip"],
        "approval_status": "OPERATOR_APPROVED",
        "approved_job_id": job.job_id,
        "approved_run_id": run.run_id,
        "shared_hashes": {
            "resource_sha256": compiled["resource_sha256"],
            "compiled_files_sha256": compiled["compiled_files_sha256"],
            "effective_vrs_sha256": compiled["effective_vrs"]["effective_sha256"],
            "structure_policy_sha256": compiled["structure_policy"]["effective_sha256"],
        },
        "units": [
            {
                "unit_id": "SAW-RTC-MAT-APPROVED-U001",
                "primary_scope": "MAT 1:1-2",
                "primary_references": ["MAT 1:1", "MAT 1:2"],
                "context_before": [],
                "context_after": ["MAT 1:3"],
            },
            {
                "unit_id": "SAW-RTC-MAT-APPROVED-U002",
                "primary_scope": "MAT 1:3",
                "primary_references": ["MAT 1:3"],
                "context_before": ["MAT 1:2"],
                "context_after": [],
            },
        ],
    }
    approved_path = run.root / "plans" / "APPROVED-WORK-UNITS.json"
    approved_path.write_text(json.dumps(approved), encoding="utf-8")
    run = store.update_run(run, approved_work_plan_path=str(approved_path))

    result = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id=job.bindings["wip"],
        contemporary_source_id=job.bindings["reference"],
        scope_value=run.scope,
        job_id=job.job_id,
        run_id=run.run_id,
    )

    assert result["status"] == "COMPOSITE"
    assert result["current_stage"] == "REFERENCE_TEXT_COMPARISON"
    assert result["approved_work_plan_fingerprint"] == "a" * 64
    stage_plan = json.loads(Path(result["stages"][0]["plan_path"]).read_text(encoding="utf-8"))
    assert [item["scope"] for item in stage_plan["work_units"]] == ["MAT 1:1-2", "MAT 1:3"]
    manifests = [json.loads(Path(item["manifest_path"]).read_text(encoding="utf-8")) for item in stage_plan["work_units"]]
    assert [item["work_unit_id"] for item in manifests] == [
        "SAW-RTC-MAT-APPROVED-U001", "SAW-RTC-MAT-APPROVED-U002"
    ]


def test_new_rtc_approved_plan_becomes_stale_when_reference_changes(
    package_root: Path,
    make_workspace,
) -> None:
    """Current RTC approval fingerprints REF as well as both boundary streams."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=3)
    _initialize(package_root, root)
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1:1-3")
    runtime_settings = store.ensure_runtime_files(job)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "system" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    preview_path = run.root / "plans" / "PREVIEW.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sage.cli",
            "--settings",
            str(runtime_settings),
            "--json",
            "workflow",
            "plan",
            "--workflow",
            "saw",
            "--operation",
            "rtc",
            "--scope",
            run.scope,
            "--output",
            str(preview_path),
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=40,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    approved = json.loads(result.stdout)
    approved.update({
        "approval_status": "OPERATOR_APPROVED",
        "approved_job_id": job.job_id,
        "approved_run_id": run.run_id,
    })
    approved_path = run.root / "plans" / "APPROVED-WORK-UNITS.json"
    approved_path.write_text(json.dumps(approved), encoding="utf-8")
    store.update_run(run, approved_work_plan_path=str(approved_path))

    reference_file = storage_layout(root).projects_root / job.bindings["reference"] / "41MAT.SFM"
    reference_file.write_text(
        reference_file.read_text(encoding="utf-8") + "\\p Revised reference metadata.\n",
        encoding="utf-8",
    )
    config = load_ecosystem(store.ensure_runtime_files(job))

    with pytest.raises(ValidationError) as error:
        create_act_task(
            config,
            workflow="saw",
            operation="rtc",
            output_project_id=job.bindings["wip"],
            contemporary_source_id=job.bindings["reference"],
            scope_value=run.scope,
            job_id=job.job_id,
            run_id=run.run_id,
        )
    assert error.value.code == "SAW_APPROVED_PLAN_STALE"


@pytest.mark.parametrize(
    ("bridge_wip", "bridge_reference"),
    ((True, False), (False, True), (True, True)),
)
def test_operator_approved_saw_plan_reconciles_verse_bridge_coordinates(
    package_root: Path,
    make_workspace,
    bridge_wip: bool,
    bridge_reference: bool,
) -> None:
    """Route every WIP/REFERENCE bridge shape into the primary bridge-check contract."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=3)
    projects_root = storage_layout(root).projects_root
    bridged_text = (
        "\\id MAT Fixture\n\\c 1\n\\p\n"
        "\\v 1-2 Bridged verses.\n\\v 3 Verse 3.\n"
    )
    if bridge_wip:
        (projects_root / "usWIP" / "41MAT.SFM").write_text(
            bridged_text,
            encoding="utf-8",
        )
    if bridge_reference:
        (projects_root / "usNIVv2" / "41MAT.SFM").write_text(
            bridged_text,
            encoding="utf-8",
        )
    _initialize(package_root, root)
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1:1-3")
    config = load_ecosystem(store.ensure_runtime_files(job))
    compiled = compile_project_scope(
        config, config.project(job.bindings["wip"]), parse_scope(run.scope)
    )
    approved = {
        "schema_version": "1.2",
        "plan_id": "SAW-RTC-MAT-BRIDGE-APPROVED",
        "plan_fingerprint": "b" * 64,
        "workflow_id": "saw",
        "operation": "rtc",
        "operator_scope": run.scope,
        "project_id": job.bindings["wip"],
        "approval_status": "OPERATOR_APPROVED",
        "approved_job_id": job.job_id,
        "approved_run_id": run.run_id,
        "shared_hashes": {
            "resource_sha256": compiled["resource_sha256"],
            "compiled_files_sha256": compiled["compiled_files_sha256"],
            "effective_vrs_sha256": compiled["effective_vrs"]["effective_sha256"],
            "structure_policy_sha256": compiled["structure_policy"]["effective_sha256"],
        },
        "units": [{
            "unit_id": "SAW-RTC-MAT-BRIDGE-APPROVED-U001",
            "primary_scope": run.scope,
            "primary_references": (
                ["MAT 1:1-2", "MAT 1:3"]
                if bridge_wip
                else ["MAT 1:1", "MAT 1:2", "MAT 1:3"]
            ),
            "context_before": [],
            "context_after": [],
        }],
    }
    approved_path = run.root / "plans" / "APPROVED-WORK-UNITS.json"
    approved_path.write_text(json.dumps(approved), encoding="utf-8")
    store.update_run(run, approved_work_plan_path=str(approved_path))

    result = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id=job.bindings["wip"],
        contemporary_source_id=job.bindings["reference"],
        scope_value=run.scope,
        job_id=job.job_id,
        run_id=run.run_id,
    )

    assert result["status"] == "COMPOSITE"
    assert result["approved_work_plan_fingerprint"] == "b" * 64
    manifest_path = Path(result["stages"][0]["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required_checks = manifest["review_requirements"]["required_checks"]
    assert "VERSE_BRIDGE_MAPPING" in required_checks
    assert "VERSE_BRIDGE_CONTENT" in required_checks
    assert "CROSS_REFERENCE" in required_checks
    act_text = (manifest_path.parent / "ACT.md").read_text(encoding="utf-8")
    assert "check the complete bridged text" in act_text
    assert "Review every WIP and Reference cross-reference span" in act_text
    assert "Canonical report narrative MUST use the Job-owned language tag `en`" in act_text



def test_structural_stage_covers_only_candidate_coordinates(package_root: Path, make_workspace) -> None:
    """Structural adjudication must use candidate coordinates rather than claiming parent RTC coverage."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=3)
    (storage_layout(root).projects_root / "usWIP/custom.vrs").write_text("#! &MAT 1:2-3 = MAT 1:2\n", encoding="utf-8")
    settings = root / "ecosystem.yml"
    settings_data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    settings_data["projects"]["usWIP"]["versification"]["custom_file"] = "custom.vrs"
    settings.write_text(yaml.safe_dump(settings_data, sort_keys=False), encoding="utf-8")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    plan = create_act_task(
        config, workflow="saw", operation="rtc", output_project_id="usWIP",
        contemporary_source_id="usNIVv2", scope_value="MAT 1:1-3",
    )
    assert plan["current_stage"] == "STRUCTURAL_ADJUDICATION"
    manifest = json.loads(Path(plan["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["scope"] == "MAT 1:1-3"
    assert manifest["expected_references"] == ["MAT 1:2", "MAT 1:3"]
    assert manifest["structural_candidate_ids"] == ["VRS-001"]


def test_current_contract_surfaces_have_no_removed_workflow_vocabulary(package_root: Path) -> None:
    """Lint all current human/model contract surfaces, excluding history and retained source baselines."""
    files: list[Path] = [package_root / "README.md", package_root / "docs/OPERATOR-GUIDE.md"]
    for root_name in ("docs", "jobs", "workflows", "skills"):
        root = package_root / root_name
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".md", ".yml", ".yaml"}:
                continue
            if "history" in path.parts or path.name.startswith("ORIGINAL-"):
                continue
            files.append(path)
    files.extend([package_root / "system/src/sage/natural_language.py", package_root / "system/src/sage/menu.py"])
    text = "\n".join(path.read_text(encoding="utf-8") for path in files).casefold()
    forbidden = (
        "sessions, pins",
        "review an existing `usbol` target",
        "saw rtc - review a bounded target",
        "deterministic preflight/direct findings",
        "generation pin",
    )
    for phrase in forbidden:
        assert phrase not in text, phrase


def test_grammar_date_is_true_iso_calendar_date(make_workspace) -> None:
    """Reject impossible dates even when they match YYYY-MM-DD text shape."""
    root = make_workspace(qualification_status="VALIDATED")
    path = root / "system/config/profiles/grammar/en/bol-target.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["profile"]["last_reviewed"] = "2026-99-99"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="valid ISO calendar date"):
        load_grammar_profile(path, expected_profile_id="bol-target", expected_language="en", expected_role="TARGET")


def test_project_role_schema_exactly_matches_runtime_canonical_set(package_root: Path) -> None:
    """Keep declarative project-role grammar byte-for-concept aligned with executable canonical vocabulary."""
    schema = yaml.safe_load((package_root / "system/config/schemas/project-scope.schema.yml").read_text(encoding="utf-8"))
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


def test_saw_finding_accepts_discontiguous_portion_reporting(tmp_path: Path) -> None:
    """One finding may cite multiple bounded portions without turning the citation into a book token."""
    payload = {
        "schema_version": "2.0",
        "task_id": "saw-rtc-amo-fixture",
        "operation": "rtc",
        "stage": "REFERENCE_TEXT_COMPARISON",
        "scope": "AMO 1:11-15",
        "focus": None,
        "check_type": None,
        "coverage": {
            "status": "COMPLETE",
            "reviewed_references": [
                "AMO 1:11",
                "AMO 1:12",
                "AMO 1:13",
                "AMO 1:14",
                "AMO 1:15",
            ],
        },
        "review_receipts": [{
            "receipt_id": "RR-AMO",
            "work_unit_id": "WU-AMO-1",
            "task_fingerprint": "fixture-fingerprint",
            "reviewed_references": [
                "AMO 1:11",
                "AMO 1:12",
                "AMO 1:13",
                "AMO 1:14",
                "AMO 1:15",
            ],
            "checks_performed": ["MEANING"],
            "evidence_summary": "Reviewed the complete Amos work unit.",
        }],
        "structural_adjudications": [],
        "ol_review_requests": [],
        "findings": [{
            "finding_id": "F001",
            "target_reference": "AMO 1:11; AMO 1:14",
            "category": "MEANING",
            "issue": "The same issue affects two non-contiguous portions.",
            "required_action": "Review both cited portions.",
            "action_level": "REVIEW",
            "confidence": "HIGH",
            "evidence_ids": ["REFERENCE", "WIP"],
            "grammar_rule_ids": [],
            "original_language_evidence": "",
        }],
    }
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = validate_saw_findings(
        path,
        task_id="saw-rtc-amo-fixture",
        operation="rtc",
        rtc_stage="REFERENCE_TEXT_COMPARISON",
        scope_value="AMO 1:11-15",
        focus=None,
        check_type=None,
        expected_references=[
            "AMO 1:11",
            "AMO 1:12",
            "AMO 1:13",
            "AMO 1:14",
            "AMO 1:15",
        ],
        structural_candidate_ids=[],
        grammar_rule_ids=[],
        allowed_evidence_ids=["REFERENCE", "WIP"],
        task_fingerprint="fixture-fingerprint",
        required_review_checks=["MEANING"],
        expected_work_unit_ids=["WU-AMO-1"],
    )
    assert result["findings"][0]["target_reference"] == "AMO 1:11; AMO 1:14"


def test_saw_finding_discontiguous_portion_must_remain_inside_work_unit(tmp_path: Path) -> None:
    """Every portion in a multi-part finding citation remains bounded by the immutable task scope."""
    payload = {
        "schema_version": "2.0",
        "task_id": "saw-rtc-amo-fixture",
        "operation": "rtc",
        "stage": "REFERENCE_TEXT_COMPARISON",
        "scope": "AMO 1:11-15",
        "focus": None,
        "check_type": None,
        "coverage": {"status": "COMPLETE", "reviewed_references": ["AMO 1:11"]},
        "review_receipts": [{
            "receipt_id": "RR-AMO",
            "work_unit_id": "WU-AMO-1",
            "task_fingerprint": "fixture-fingerprint",
            "reviewed_references": ["AMO 1:11"],
            "checks_performed": ["MEANING"],
            "evidence_summary": "Reviewed the bounded coordinate.",
        }],
        "structural_adjudications": [],
        "ol_review_requests": [],
        "findings": [{
            "finding_id": "F001",
            "target_reference": "AMO 1:11; AMO 2:1",
            "category": "MEANING",
            "issue": "Fixture issue.",
            "required_action": "Review.",
            "action_level": "REVIEW",
            "confidence": "HIGH",
            "evidence_ids": ["REFERENCE", "WIP"],
            "grammar_rule_ids": [],
            "original_language_evidence": "",
        }],
    }
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="outside the bounded task scope"):
        validate_saw_findings(
            path,
            task_id="saw-rtc-amo-fixture",
            operation="rtc",
            rtc_stage="REFERENCE_TEXT_COMPARISON",
            scope_value="AMO 1:11-15",
            focus=None,
            check_type=None,
            expected_references=["AMO 1:11"],
            structural_candidate_ids=[],
            grammar_rule_ids=[],
            allowed_evidence_ids=["REFERENCE", "WIP"],
            task_fingerprint="fixture-fingerprint",
            required_review_checks=["MEANING"],
            expected_work_unit_ids=["WU-AMO-1"],
        )


def test_meaning_stage_rejects_stale_original_language_filler(package_root: Path, make_workspace) -> None:
    """A non-OL RTC stage cannot preserve legacy 'not consulted/prohibited' OL text."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=2)
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    plan = create_act_task(
        config, workflow="saw", operation="rtc", output_project_id="usWIP",
        contemporary_source_id="usNIVv2", scope_value="MAT 1:1-2",
    )
    manifest_path = Path(plan["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    document = _meaning_document(manifest)
    document["findings"] = [{
        "finding_id": "F-STALE-OL",
        "target_reference": "MAT 1:1",
        "category": "MEANING",
        "issue": "Fixture issue.",
        "required_action": "Review.",
        "action_level": "REVIEW",
        "confidence": "MEDIUM",
        "evidence_ids": [manifest["allowed_evidence_ids"][0]],
        "grammar_rule_ids": [],
        "original_language_evidence": "Not consulted, as prohibited for this stage.",
    }]
    (manifest_path.parent / "output" / "findings.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValidationError, match="must be empty outside an OL review stage"):
        submit_act_task(config, manifest_path)


def test_scoped_predecessor_projection_drops_unrelated_large_chapter_payload() -> None:
    """Partition children inherit only predecessor evidence intersecting their Scripture scope."""
    from sage.act_tasks import _scope_project_predecessor
    from sage.references import parse_scope

    unrelated = "X" * 240_000
    document = {
        "scope": "DAN",
        "coverage": {"status": "COMPLETE", "reviewed_references": ["DAN 1:1", "DAN 2:1"]},
        "review_receipts": [
            {"receipt_id": "R1", "reviewed_references": ["DAN 1:1"]},
            {"receipt_id": "R2", "reviewed_references": ["DAN 2:1"]},
        ],
        "findings": [
            {"finding_id": "F1", "target_reference": "DAN 1:1", "issue": "chapter one"},
            {"finding_id": "F2", "target_reference": "DAN 2:1", "issue": unrelated},
        ],
        "ol_review_requests": [
            {"request_id": "OL1", "target_reference": "DAN 1:1"},
            {"request_id": "OL2", "target_reference": "DAN 2:1", "question": unrelated},
        ],
        "ol_resolutions": [],
        "work_units": [{"scope": "DAN 1:1"}, {"scope": "DAN 2:1"}],
    }
    scoped = _scope_project_predecessor(document, parse_scope("DAN 1"))
    serialized = json.dumps(scoped)
    assert unrelated not in serialized
    assert scoped["coverage"]["reviewed_references"] == ["DAN 1:1"]
    assert [row["finding_id"] for row in scoped["findings"]] == ["F1"]
    assert [row["request_id"] for row in scoped["ol_review_requests"]] == ["OL1"]
    assert [row["scope"] for row in scoped["work_units"]] == ["DAN 1:1"]
