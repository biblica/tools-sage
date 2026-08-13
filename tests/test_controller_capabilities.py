"""Controller coverage for reset, continuation, grammar, and resource rights."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from sage_core.grammar_governance import (
    active_grammar_review,
    configured_grammar_profiles,
    grammar_profile_is_approved,
    list_grammar_profile_reviews,
    record_grammar_profile_review,
)
from sage_core.plan_continuation import continue_saw_plan
from sage_core.registry import load_ecosystem
from sage_core.resource_rights import validate_resource_rights
from sage_core.stage_reset import reset_workflow_stage
from sage_core.errors import ValidationError
from sage_core.jobs import JobStore, default_job_name


def _write_json(path: Path, value: object) -> None:
    """Write one compact JSON fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _saw_job(config):
    """Create one canonical SAW Job and return its Job-scoped runtime config."""
    store = JobStore(config.root, config.settings_path)
    job_id = default_job_name("saw", "usWIP", "usNIVv2")
    job = store.create_job(
        tool="saw",
        job_id=job_id,
        display_name=job_id,
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
    )
    return job, load_ecosystem(store.ensure_runtime_files(job))


def _task_control(root: Path, workflow: str, operation: str, task_id: str) -> tuple[Path, Path]:
    """Create one governed-looking task root and control fixture."""
    task_root = root / "workspace-data" / workflow / "output" / "active" / task_id
    task_root.mkdir(parents=True)
    _write_json(
        task_root / "task-manifest.json",
        {"task_id": task_id, "workflow": workflow, "operation": operation},
    )
    control_path = root / "workspace-data" / workflow / "state" / "act-tasks" / f"{task_id}.json"
    _write_json(
        control_path,
        {
            "task_id": task_id,
            "workflow": workflow,
            "operation": operation,
            "task_root": str(task_root.resolve()),
        },
    )
    return task_root, control_path


def test_stage_reset_removes_only_selected_workflow_stage(make_workspace) -> None:
    """Preserve another workflow and another stage while writing an audit receipt."""
    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    qa_root, qa_control = _task_control(root, "saw", "qa", "SAW-QA-001")
    ol_root, ol_control = _task_control(root, "saw", "ol", "SAW-OL-001")
    bic_root, bic_control = _task_control(root, "bic", "inspect", "BIC-INSPECT-001")
    plan_path = root / "workspace-data" / "saw" / "output" / "plans" / "SAW-QA-PLAN.json"
    _write_json(
        plan_path,
        {
            "schema_version": "1.0",
            "status": "PARTITIONED",
            "plan_id": "SAW-QA-PLAN",
            "workflow": "saw",
            "operation": "qa",
            "work_units": [],
        },
    )

    result = reset_workflow_stage(
        config,
        workflow_id="saw",
        stage="qa",
        operator="operator-1",
        decision_id="RESET-SAW-QA-001",
        notes="Restart bounded QA only.",
    )
    assert result["workflow"] == "saw"
    assert result["stage"] == "qa"
    assert result["task_ids"] == ["SAW-QA-001"]
    assert not qa_root.exists() and not qa_control.exists() and not plan_path.exists()
    assert ol_root.exists() and ol_control.exists()
    assert bic_root.exists() and bic_control.exists()
    assert Path(result["receipt_path"]).is_file()


def test_bic_stage_reset_requires_downstream_first(make_workspace) -> None:
    """Block an upstream reset while a downstream BIC task still exists."""
    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    _task_control(root, "bic", "inspect", "BIC-INSPECT-001")
    _task_control(root, "bic", "rewrite", "BIC-REWRITE-001")
    with pytest.raises(ValidationError) as blocked:
        reset_workflow_stage(
            config,
            workflow_id="bic",
            stage="inspect",
            operator="operator-1",
            decision_id="RESET-BIC-INSPECT-001",
        )
    assert blocked.value.code == "STAGE_RESET_DOWNSTREAM_EXISTS"


def test_saw_continuation_returns_exact_next_unit_and_aggregate_action(make_workspace) -> None:
    """Advance one sequential plan only after each prior submission is finalised."""
    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    job, runtime = _saw_job(config)
    plans_root = runtime.workflow("saw").output_root / "plans"
    active_root = runtime.workflow("saw").output_root / "active"
    units = []
    for index in range(1, 4):
        task_root = active_root / f"SAW-QA-{index:03d}"
        manifest_path = task_root / "task-manifest.json"
        _write_json(manifest_path, {"task_id": task_root.name})
        units.append(
            {
                "unit_id": f"UNIT-{index:03d}",
                "task_id": task_root.name,
                "scope": f"MAT 1:{index}",
                "manifest_path": str(manifest_path.resolve()),
            }
        )
    plan_path = plans_root / "SAW-QA-PLAN.json"
    _write_json(
        plan_path,
        {
            "schema_version": "1.0",
            "status": "PARTITIONED",
            "plan_id": "SAW-QA-PLAN",
            "workflow": "saw",
            "operation": "qa",
            "job_id": job.job_id,
            "work_units": units,
        },
    )
    first = continue_saw_plan(config, plan_path)
    assert first["status"] == "NEXT_WORK_UNIT"
    assert first["next_unit"]["unit_id"] == "UNIT-001"

    _write_json(
        Path(units[0]["manifest_path"]).parent / "validation" / "submission.json",
        {"task_id": units[0]["task_id"], "status": "FINALIZED"},
    )
    second = continue_saw_plan(config, plan_path)
    assert second["completed_units"] == 1
    assert second["next_unit"]["unit_id"] == "UNIT-002"

    for unit in units[1:]:
        _write_json(
            Path(unit["manifest_path"]).parent / "validation" / "submission.json",
            {"task_id": unit["task_id"], "status": "FINALIZED"},
        )
    ready = continue_saw_plan(config, plan_path)
    assert ready["status"] == "READY_TO_AGGREGATE"
    assert ready["completed_units"] == ready["total_units"] == 3
    assert "task aggregate" in ready["aggregate_command"]


def test_saw_continuation_detects_out_of_order_finalization(make_workspace) -> None:
    """Reject later finalised work when its predecessor is unfinished."""
    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    job, runtime = _saw_job(config)
    active_root = runtime.workflow("saw").output_root / "active"
    units = []
    for index in range(1, 3):
        manifest_path = active_root / f"TASK-{index}" / "task-manifest.json"
        _write_json(manifest_path, {"task_id": f"TASK-{index}"})
        units.append(
            {
                "unit_id": f"UNIT-{index}",
                "task_id": f"TASK-{index}",
                "scope": f"MAT 1:{index}",
                "manifest_path": str(manifest_path.resolve()),
            }
        )
    plan_path = runtime.workflow("saw").output_root / "plans" / "PLAN.json"
    _write_json(
        plan_path,
        {"workflow": "saw", "status": "PARTITIONED", "plan_id": "PLAN", "job_id": job.job_id, "work_units": units},
    )
    _write_json(
        Path(units[1]["manifest_path"]).parent / "validation" / "submission.json",
        {"status": "FINALIZED"},
    )
    with pytest.raises(ValidationError) as out_of_order:
        continue_saw_plan(config, plan_path)
    assert out_of_order.value.code == "SAW_SEQUENTIAL_ORDER_VIOLATION"


def test_grammar_review_binds_exact_profile_hash(make_workspace) -> None:
    """Lift PROJECT_REVIEW_REQUIRED only for the exact human-reviewed file content."""
    root = make_workspace()
    profile_path = root / "profiles" / "languages" / "en" / "bol-target.yml"
    value = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    value["profile"]["status"] = "PROJECT_REVIEW_REQUIRED"
    profile_path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    profile = configured_grammar_profiles(config)["en/bol-target"]
    assert not grammar_profile_is_approved(config, profile)

    receipt = record_grammar_profile_review(
        config,
        profile_key="en/bol-target",
        decision_id="GRAMMAR-APPROVAL-001",
        operator="local-consultant",
        decision="APPROVED",
        notes="Reviewed against approved project decisions.",
    )
    assert receipt["profile_sha256"] == profile.sha256
    assert grammar_profile_is_approved(config, profile)
    assert active_grammar_review(config, profile)["decision"] == "APPROVED"
    listed = {row["profile_key"]: row for row in list_grammar_profile_reviews(config)}
    assert listed["en/bol-target"]["effective_status"] == "ACTIVE"

    changed = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    changed["checks"][0]["review"] += " Updated after approval."
    profile_path.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")
    changed_profile = configured_grammar_profiles(config)["en/bol-target"]
    assert changed_profile.sha256 != profile.sha256
    assert active_grammar_review(config, changed_profile) is None
    assert not grammar_profile_is_approved(config, changed_profile)


def _complete_resource_metadata(project_id: str, *, generated: bool) -> dict[str, object]:
    """Return one complete rights/provenance fixture."""
    rights: dict[str, object] = {
        "status": "NOT_APPLICABLE_GENERATED" if generated else "CONFIRMED",
        "copyright_holder": "Fixture rights holder",
        "license_identifier": "FIXTURE-LICENCE-1.0",
        "authority_record_id": f"AUTH-{project_id}",
        "import_authorized": True,
        "redistribution_authorized": True,
        "distribution_scope": "controlled test package",
        "reviewed_utc": "2026-08-05T00:00:00Z",
    }
    if generated:
        rights["generation_authority_record_id"] = f"GEN-{project_id}"
    return {
        "schema_version": "1.0",
        "project_id": project_id,
        "provenance": {
            "source_name": f"Fixture {project_id}",
            "source_version": "1.0",
            "source_archive_sha256": "a" * 64,
            "import_authority_id": f"IMPORT-{project_id}",
            "imported_utc": "2026-08-05T00:00:00Z",
        },
        "rights": rights,
    }


def test_resource_rights_validator_is_machine_readable_and_blocking(make_workspace) -> None:
    """Report exact missing fields, then pass only complete per-project records."""
    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    metadata_root = root / "resource-provenance" / "metadata" / "projects"
    metadata_root.mkdir(parents=True)
    (metadata_root / "idKKHv0.yml").write_text("project_id: idKKHv0\n", encoding="utf-8")
    blocked = validate_resource_rights(config, metadata_root=metadata_root.parent)
    assert blocked["status"] == "BLOCKED"
    id_result = next(row for row in blocked["projects"] if row["project_id"] == "idKKHv0")
    assert {error["code"] for error in id_result["errors"]} >= {
        "RESOURCE_METADATA_SCHEMA_INVALID",
        "RESOURCE_PROVENANCE_FIELD_MISSING",
        "RESOURCE_RIGHTS_FIELD_MISSING",
    }

    for project_id, project in config.projects.items():
        metadata = _complete_resource_metadata(
            project_id,
            generated=project.kind == "GENERATED_SCRIPTURE",
        )
        (metadata_root / f"{project_id}.yml").write_text(
            yaml.safe_dump(metadata, sort_keys=False),
            encoding="utf-8",
        )
    ready = validate_resource_rights(config, metadata_root=metadata_root.parent)
    assert ready["status"] == "READY"
    assert ready["blocking_projects"] == 0
    assert Path(ready["report_path"]).is_file()
    assert Path(ready["human_report_path"]).is_file()
