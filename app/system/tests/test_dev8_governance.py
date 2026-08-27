"""Dev.8 project, ACT-boundary, output-grammar, and process tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage.storage import storage_layout
from sage.act_tasks import create_act_task, submit_act_task
from sage.bounded_target import extract_scope_usfm
from sage.bic_memory import record_human_memory_review
from sage.errors import InputRequiredError, ConfigurationError, MemoryGovernanceError, ValidationError
from sage.hashing import sha256_file
from sage.registry import load_ecosystem
from sage.jobs import JobStore
from sage.runtime_paths import workflow_memory_root


def run_cli(package_root: Path, workspace: Path, *args: str):
    """Run the SAGE CLI in an isolated subprocess for this test."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "system" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sage.cli",
            "--settings",
            str(workspace / "ecosystem.yml"),
            *args,
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )


def mutate(root: Path, fn) -> None:
    """Apply the controlled fixture mutation required by this test."""
    path = root / "ecosystem.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def initialize(package_root: Path, root: Path) -> None:
    """Initialize the isolated test workspace and return its result."""
    result = run_cli(package_root, root, "workspace", "initialize")
    assert result.returncode == 0, result.stderr + result.stdout


def saw_document(task: dict, *, findings: list[dict] | None = None, answer: str = "") -> dict:
    """Build a complete bounded SAW submission fixture for this test."""
    stage = {
        "rtc": "REFERENCE_TEXT_COMPARISON",
        "focused": "FOCUSED_CHECK",
        "ol": "FOCUSED_OL",
    }[task["operation"]]
    value = {
        "schema_version": "2.0",
        "narrative_language": task["narrative_language"],
        "task_id": task["task_id"],
        "operation": task["operation"],
        "stage": stage,
        "scope": task["scope"],
        "focus": task.get("focus"),
        "check_type": task.get("check_type"),
        "coverage": {
            "status": "COMPLETE",
            "reviewed_references": list(task["expected_references"]),
        },
        "structural_adjudications": [
            {
                "candidate_id": candidate_id,
                "outcome": "NO_FINDING",
                "finding_id": None,
                "rationale": "The bounded VRS evidence does not require an actionable finding.",
            }
            for candidate_id in task.get("structural_candidate_ids", [])
        ],
        "review_receipts": [
            {
                "receipt_id": f"R-{task['task_id']}",
                "work_unit_id": task["review_requirements"]["expected_work_unit_ids"][0],
                "task_fingerprint": task["task_fingerprint"],
                "reviewed_references": list(task["expected_references"]),
                "checks_performed": list(task["review_requirements"]["required_checks"]),
                "evidence_summary": "The reviewer compared every bounded coordinate against all routed evidence and completed each required check.",
            }
        ],
        "findings": findings or [],
    }
    if task.get("focus"):
        value["answer"] = answer or "The bounded evidence supports no additional action."
    return value


def approve_bic_review(config, scope: str, suffix: str = "1") -> None:
    """Record the governed BIC review receipt in the canonical owning Job."""
    store = JobStore(config.root, config.settings_path)
    jobs = store.discover("bic")
    assert len(jobs) == 1
    runtime = load_ecosystem(store.ensure_runtime_files(jobs[0]))
    record_human_memory_review(
        memory_root=workflow_memory_root(runtime.workflow("bic")),
        transaction_root=runtime.workflow("bic").transaction_root,
        scope=scope,
        decision_id=f"REVIEW-{suffix}",
        reviewer="Fixture Reviewer",
        decision="APPROVED_FOR_REWRITE",
        notes="Fixture approval after reviewing INSPECT proposals and challenges.",
    )


def write_bic_assessment(task: dict, output_path: Path) -> None:
    """Write a complete BIC grammar-assessment fixture for one candidate."""
    grammar = task["project_grammar"]
    value = {
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
                "evidence": "The bounded candidate was checked against this rule.",
            }
            for rule_id in grammar["rule_ids"]
        ],
        "unresolved": [],
    }
    (output_path.parent / "grammar-assessment.json").write_text(
        json.dumps(value), encoding="utf-8"
    )
    if str(task.get("operation", "")) == "rewrite":
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


def test_roles_are_required_and_never_inferred(make_workspace):
    """Verify that roles are required and never inferred."""
    root = make_workspace()
    mutate(root, lambda data: data["projects"]["usNIVv2"]["scope"].pop("roles"))
    with pytest.raises(ConfigurationError, match="roles"):
        load_ecosystem(root / "ecosystem.yml")


def test_content_state_is_required(make_workspace):
    """Verify that content state is required."""
    root = make_workspace()
    mutate(root, lambda data: data["projects"]["usNIVv2"].pop("content_state"))
    with pytest.raises(ConfigurationError, match="content_state"):
        load_ecosystem(root / "ecosystem.yml")


def test_extensionless_vrs_alias_is_rejected(make_workspace):
    """Verify that extensionless VRS alias is rejected."""
    root = make_workspace()
    mutate(
        root,
        lambda data: data["projects"]["usNIVv2"]["versification"].__setitem__(
            "base_file", "eng"
        ),
    )
    with pytest.raises(ConfigurationError, match=r"\.vrs"):
        load_ecosystem(root / "ecosystem.yml")


def test_portions_requires_explicit_books(make_workspace):
    """Verify that portions requires explicit books."""
    root = make_workspace()
    mutate(
        root,
        lambda data: data["projects"]["idKKHv0"]["scope"].__setitem__(
            "expected_books", "auto"
        ),
    )
    with pytest.raises(ConfigurationError, match="PORTIONS"):
        load_ecosystem(root / "ecosystem.yml")


def test_init_compiles_operator_review(package_root, make_workspace):
    """Verify that INIT compiles operator review."""
    root = make_workspace()
    result = run_cli(package_root, root, "--json", "project", "init", "--non-interactive")
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "READY_FOR_EDIT_OR_INITIALIZE"
    assert all("roles" in item and "content_state" in item for item in payload["projects"])
    assert Path(payload["report"]).is_file()


def test_act_creation_requires_initialization(make_workspace):
    """Verify that ACT creation requires prior initialization."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    with pytest.raises(InputRequiredError, match="initialize"):
        create_act_task(
            config,
            workflow="saw",
            operation="rtc",
            output_project_id="usWIP",
            contemporary_source_id="usNIVv2",
            scope_value="MAT 1",
        )


def test_job_runtime_initialization_authorizes_act_without_root_state(package_root, make_workspace):
    """ACT readiness uses the initialized Job runtime instead of unrelated root state."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Job-local readiness",
        bindings={
            "wip": "usWIP",
            "reference": "usNIVv2",
            "original_language_greek": "GRK",
            "original_language_hebrew": "HEB",
        },
    )
    runtime_path = store.ensure_runtime_files(job)
    root_state = storage_layout(root).state_root / "ecosystem.json"
    job_state = job.controller_root / "state" / "ecosystem.json"
    receipt = json.loads(root_state.read_text(encoding="utf-8"))
    receipt["settings_sha256"] = sha256_file(runtime_path)
    job_state.parent.mkdir(parents=True, exist_ok=True)
    job_state.write_text(json.dumps(receipt), encoding="utf-8")
    root_state.unlink()

    task = create_act_task(
        load_ecosystem(runtime_path),
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    assert task["job_id"] == job.job_id


def test_act_task_routes_ol_only_for_ol_operation(package_root, make_workspace):
    """Verify that ACT task routes OL only for OL operation."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    rtc = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:2",
    )
    assert rtc["original_language_sources"] == []
    assert not (Path(rtc["manifest_path"]).parent / "packet" / "original-language.usj.json").exists()
    packet = Path(rtc["manifest_path"]).parent / "packet" / "reference.usj.json"
    comparison = json.loads(packet.read_text(encoding="utf-8"))
    assert comparison["sage"]["atomic_references"] == ["MAT 1:2"]
    assert [record["number"] for record in comparison["sage"]["verse_records"]] == ["2"]

    ol = create_act_task(
        config,
        workflow="saw",
        operation="ol",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:2",
        focus="Does the target preserve the Greek participant relationship?",
    )
    assert ol["original_language_sources"] == [
        {
            "role": "ORIGINAL_LANGUAGE_GREEK",
            "project": "GRK",
            "routing": "DIRECT",
        }
    ]
    assert (Path(ol["manifest_path"]).parent / "packet" / "original-language.usj.json").is_file()

def test_focused_and_ol_require_one_focus(package_root, make_workspace):
    """Verify that focused and OL require one focus."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    for operation in ("focused", "ol"):
        with pytest.raises(ValidationError, match="requires --focus"):
            create_act_task(
                config,
                workflow="saw",
                operation=operation,
                output_project_id="usWIP",
                contemporary_source_id="usNIVv2",
                scope_value="MAT 1:1",
            )


def test_act_rejects_working_contemporary_source(package_root, make_workspace):
    """Verify that ACT rejects working contemporary source."""
    root = make_workspace(qualification_status="VALIDATED")
    mutate(root, lambda data: data["projects"]["usNIVv2"].__setitem__("content_state", "UNDER_REVIEW"))
    config = load_ecosystem(root / "ecosystem.yml")
    with pytest.raises(ConfigurationError, match="requires content_state LOCKED"):
        create_act_task(
            config,
            workflow="saw",
            operation="rtc",
            output_project_id="usWIP",
            contemporary_source_id="usNIVv2",
            scope_value="MAT 1",
        )


def test_blocked_project_cannot_create_task(package_root, make_workspace):
    """Verify that blocked project cannot create task."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    source = storage_layout(root).projects_root / "usNIVv2" / "41MAT.SFM"
    source.write_text("not usfm\n", encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    with pytest.raises(ValidationError, match="BLOCKED"):
        create_act_task(
            config,
            workflow="saw",
            operation="rtc",
            output_project_id="usWIP",
            contemporary_source_id="usNIVv2",
            scope_value="MAT 1",
        )


def test_manifest_mutation_is_rejected(package_root, make_workspace):
    """Verify that manifest mutation is rejected."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1",
    )
    manifest = Path(task["manifest_path"])
    manifest.chmod(0o644)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["scope"] = "MAT 1:1"
    manifest.write_text(json.dumps(value), encoding="utf-8")
    output = manifest.parent / "output" / "findings.json"
    output.write_text(json.dumps(saw_document(task)), encoding="utf-8")
    with pytest.raises(ValidationError, match="manifest changed"):
        submit_act_task(config, manifest)


def test_write_allowlist_escape_is_rejected(package_root, make_workspace):
    """Verify that write allowlist escape is rejected."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1",
    )
    control = Path(task["control_path"])
    control.chmod(0o644)
    value = json.loads(control.read_text(encoding="utf-8"))
    value["allowed_writes"] = ["../escaped.txt"]
    control.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValidationError, match="control write allowlist is corrupt"):
        submit_act_task(config, Path(task["manifest_path"]))


def test_empty_saw_object_is_rejected(package_root, make_workspace):
    """Verify that empty SAW object is rejected."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1",
    )
    manifest = Path(task["manifest_path"])
    (manifest.parent / "output" / "findings.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="schema_version"):
        submit_act_task(config, manifest)


def test_valid_saw_output_renders_reports(package_root, make_workspace):
    """Verify that valid SAW output renders reports."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    manifest = Path(task["manifest_path"])
    findings = [
        {
            "finding_id": "SAW-001",
            "target_reference": "MAT 1:1",
            "category": "PARTICIPANT_REFERENCE",
            "issue": "The participant reference is unclear.",
            "required_action": "Ask the project team to review the participant reference.",
            "action_level": "REVIEW",
            "confidence": "MEDIUM",
            "evidence_ids": [task["allowed_evidence_ids"][0]],
            "grammar_rule_ids": [],
            "original_language_evidence": "",
        }
    ]
    output = manifest.parent / "output" / "findings.json"
    output.write_text(json.dumps(saw_document(task, findings=findings)), encoding="utf-8")
    result = submit_act_task(config, manifest)
    assert result["status"] == "FINALIZED"
    assert (manifest.parent / "validation" / "ACTION-REPORT.md").is_file()
    assert not (manifest.parent / "validation" / "PARATEXT-NOTES.txt").exists()


def test_bic_rewrite_logs_pending_human_memory_review_without_blocking(package_root, make_workspace):
    """Verify committed INSPECT permits REWRITE while pending review remains visible."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    inspect = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1:1",
    )
    manifest = Path(inspect["manifest_path"])
    payload = {
        "schema_version": "1.0",
        "operation_id": inspect["task_id"],
        "scope": inspect["scope"],
        "resource_fingerprints": inspect["resource_fingerprints"],
        "proposals": [
            {
                "submitted_id": "P1",
                "record_type": "LANGUAGE_RENDERING",
                "payload": {"source": "fixture", "target": "fixture"},
                "evidence_refs": ["MAT 1:1"],
            }
        ],
        "challenges": [],
    }
    (manifest.parent / "output" / "inspect-submission.json").write_text(json.dumps(payload), encoding="utf-8")
    submit_act_task(config, manifest)
    rewrite = create_act_task(
        config,
        workflow="bic",
        operation="rewrite",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1:1",
    )
    review = rewrite["human_memory_review"]
    assert review["review_status"] == "PENDING"
    assert review["attention"]["next_stage_allowed"] is True


def test_plain_text_bic_usfm_is_rejected(package_root, make_workspace):
    """Verify that plain text BIC USFM is rejected."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1",
    )
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
                "evidence_refs": ["MAT 1:1"],
            }
        ],
        "challenges": [],
    }
    (manifest.parent / "output" / "inspect-submission.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    submit_act_task(config, manifest)
    approve_bic_review(config, task["scope"], "plain-usfm")
    rewrite = create_act_task(
        config,
        workflow="bic",
        operation="rewrite",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1",
    )
    rewrite_manifest = Path(rewrite["manifest_path"])
    invalid_output = rewrite_manifest.parent / "output" / "rewrite.usfm"
    invalid_output.write_text("plain text\n", encoding="utf-8")
    write_bic_assessment(rewrite, invalid_output)
    with pytest.raises(ValidationError, match="USFM"):
        submit_act_task(config, rewrite_manifest)


def test_bic_rewrite_and_self_check_are_separate_and_commit(package_root, make_workspace):
    """Verify that BIC rewrite and self check are separate and commit."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    inspect = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1",
    )
    inspect_manifest = Path(inspect["manifest_path"])
    inspect_payload = {
        "schema_version": "1.0",
        "operation_id": inspect["task_id"],
        "scope": inspect["scope"],
        "resource_fingerprints": inspect["resource_fingerprints"],
        "proposals": [
            {
                "submitted_id": "P1",
                "record_type": "LANGUAGE_RENDERING",
                "payload": {"source": "fixture", "target": "fixture"},
                "evidence_refs": ["MAT 1:1"],
            }
        ],
        "challenges": [],
    }
    (inspect_manifest.parent / "output" / "inspect-submission.json").write_text(
        json.dumps(inspect_payload), encoding="utf-8"
    )
    submit_act_task(config, inspect_manifest)
    approve_bic_review(config, inspect["scope"], "rewrite-self-check")

    rewrite = create_act_task(
        config,
        workflow="bic",
        operation="rewrite",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1",
    )
    rewrite_manifest = Path(rewrite["manifest_path"])
    rewrite_output = rewrite_manifest.parent / "output" / "rewrite.usfm"
    rewrite_output.write_text(
        "\\id MAT Fixture\n" + extract_scope_usfm(
            (storage_layout(root).projects_root / "idKKHv0" / "41MAT.SFM").read_text(encoding="utf-8"),
            "MAT 1",
        ),
        encoding="utf-8",
    )
    write_bic_assessment(rewrite, rewrite_output)
    submit_act_task(config, rewrite_manifest)

    self_check = create_act_task(
        config,
        workflow="bic",
        operation="self_check",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1",
        predecessor_task=str(rewrite_manifest),
    )
    self_manifest = Path(self_check["manifest_path"])
    assert not any("rationale" in item["path"].lower() for item in self_check["allowed_reads"])
    assert not any(item["path"].endswith("original-language.usj.json") for item in self_check["allowed_reads"])
    assert not (self_manifest.parent / "packet" / "original-language.usj.json").exists()
    assert not (self_manifest.parent / "packet" / "inherited-ol-vrs-evidence.json").exists()
    staged = self_manifest.parent / "packet" / "staged-target.usj.json"
    assert staged.is_file()
    self_output = self_manifest.parent / "output" / "self-check.usfm"
    self_output.write_bytes(rewrite_output.read_bytes())
    write_bic_assessment(self_check, self_output)
    result = submit_act_task(config, self_manifest)
    assert result["commit"]["target_file"].endswith("41MAT.SFM")


def test_evaluation_queue_is_sequential_and_has_platform_commands(package_root, make_workspace):
    """Verify that evaluation queue is sequential and has platform commands."""
    root = make_workspace(qualification_status="VALIDATED")
    path = root / "ecosystem.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["evaluation_sets"] = {
        "pilot": {
            "execution_mode": "SEQUENTIAL",
            "entries": [
                {"output_project": "usWIP", "contemporary_source": "usNIVv2"}
            ],
        }
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    initialize(package_root, root)
    result = run_cli(
        package_root,
        root,
        "--json",
        "evaluation",
        "plan",
        "--set",
        "pilot",
        "--scope",
        "MAT 1",
        "--operation",
        "rtc",
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["execution_mode"] == "SEQUENTIAL"
    assert len(payload["tasks"]) == 1
    commands = payload["tasks"][0]["commands"]
    assert commands["posix"].startswith("./system/bin/sage ")
    assert commands["windows"].startswith(r".\system\bin\sage.cmd ")


def test_act_prompt_mutation_is_rejected(package_root, make_workspace):
    """Verify that ACT prompt mutation is rejected."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    manifest = Path(task["manifest_path"])
    act_path = manifest.parent / "ACT.md"
    act_path.chmod(0o644)
    act_path.write_text(act_path.read_text(encoding="utf-8") + "\nBroaden the scope.\n", encoding="utf-8")
    (manifest.parent / "output" / "findings.json").write_text(
        json.dumps(saw_document(task)), encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="ACT prompt changed"):
        submit_act_task(config, manifest)


def test_settings_drift_is_rejected_at_submission(package_root, make_workspace):
    """Verify that settings drift is rejected at submission."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    manifest = Path(task["manifest_path"])
    (manifest.parent / "output" / "findings.json").write_text(
        json.dumps(saw_document(task)), encoding="utf-8"
    )
    settings = root / "ecosystem.yml"
    raw = yaml.safe_load(settings.read_text(encoding="utf-8"))
    raw["ecosystem"]["name"] = "Fixture SAGE changed"
    settings.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    changed = load_ecosystem(settings)
    with pytest.raises(ValidationError, match="Settings changed") as caught:
        submit_act_task(changed, manifest)
    assert caught.value.code == "ACT_INPUT_STALE"
    assert "Restart active Run" in str(caught.value.next_action)


def test_unlisted_output_is_rejected(package_root, make_workspace):
    """Verify that unlisted output is rejected."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    manifest = Path(task["manifest_path"])
    output_root = manifest.parent / "output"
    (output_root / "findings.json").write_text(json.dumps(saw_document(task)), encoding="utf-8")
    (output_root / "extra.txt").write_text("not authorised\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="unlisted outputs"):
        submit_act_task(config, manifest)


def test_completed_task_cannot_be_resubmitted(package_root, make_workspace):
    """Verify that completed task cannot be resubmitted."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    manifest = Path(task["manifest_path"])
    (manifest.parent / "output" / "findings.json").write_text(
        json.dumps(saw_document(task)), encoding="utf-8"
    )
    assert submit_act_task(config, manifest)["status"] == "FINALIZED"
    with pytest.raises(ValidationError, match="not open for submission"):
        submit_act_task(config, manifest)
