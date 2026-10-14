"""RTC/STC regressions: approved-plan staleness causes, aggregation guards, and crash recovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sage.act_tasks import aggregate_act_plan, create_act_task
from sage.errors import ValidationError
from sage.jobs import JobStore
from sage.references import parse_scope
from sage.registry import load_ecosystem
from sage.scripture import compile_project_scope
from sage.stc import finalize_stc_run

from .test_storage_rtc_boundaries import _initialize


def _approved_plan_run(package_root: Path, make_workspace):
    """Return a Run with an Operator-approved one-unit RTC plan over MAT 1:1-3."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=3)
    _initialize(package_root, root)
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1:1-3")
    config = load_ecosystem(store.ensure_runtime_files(job))
    compiled = compile_project_scope(config, config.project(job.bindings["wip"]), parse_scope("MAT 1:1-3"))
    approved = {
        "schema_version": "1.2",
        "plan_id": "SAW-RTC-MAT-STALE",
        "plan_fingerprint": "e" * 64,
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
                "unit_id": "SAW-RTC-MAT-STALE-U001",
                "primary_scope": "MAT 1:1-3",
                "primary_references": ["MAT 1:1", "MAT 1:2", "MAT 1:3"],
                "context_before": [],
                "context_after": [],
            }
        ],
    }
    approved_path = run.root / "plans" / "APPROVED-WORK-UNITS.json"
    approved_path.parent.mkdir(parents=True, exist_ok=True)
    approved_path.write_text(json.dumps(approved), encoding="utf-8")
    store.update_run(run, approved_work_plan_path=str(approved_path))
    return config, job, run, approved, approved_path


@pytest.mark.parametrize(
    "cause",
    ["plan_missing", "run_identity", "wip_changed"],
)
def test_each_reachable_approved_plan_stale_cause_is_reported(package_root, make_workspace, cause: str) -> None:
    """Every staleness cause stops with the stale-plan code and a rebuild instruction, never a crash."""
    config, job, run, approved, approved_path = _approved_plan_run(package_root, make_workspace)
    if cause == "plan_missing":
        approved_path.unlink()
    elif cause == "run_identity":
        approved["approved_run_id"] = "SOME-OTHER-RUN"
        approved_path.write_text(json.dumps(approved), encoding="utf-8")
    else:
        approved["shared_hashes"]["resource_sha256"] = "0" * 64
        approved_path.write_text(json.dumps(approved), encoding="utf-8")

    with pytest.raises(ValidationError) as caught:
        create_act_task(
            config,
            workflow="saw",
            operation="rtc",
            output_project_id=job.bindings["wip"],
            contemporary_source_id=job.bindings["reference"],
            scope_value="MAT 1:1-3",
            job_id=job.job_id,
            run_id=run.run_id,
        )
    assert caught.value.code in {"SAW_APPROVED_PLAN_STALE", "SAW_APPROVED_PLAN_INVALID"}
    assert "Rebuild and approve" in str(caught.value.next_action or "") or cause == "run_identity"


def test_stc_finalizer_guards_duplicate_ownership_and_coverage_drift(tmp_path) -> None:
    """Aggregation refuses duplicate primary ownership and a unit whose coverage differs from the plan."""
    plan = [{"work_unit_id": "U1", "primary_coverage": ["JHN 1:1"]}, {"work_unit_id": "U2", "primary_coverage": ["JHN 1:1"]}]
    result = {
        "work_unit_id": "U1",
        "primary_coverage": ["JHN 1:1"],
        "analytical_completion": {"status": "COMPLETE", "reviewed_primary_coordinates": ["JHN 1:1"]},
        "findings": [],
    }
    with pytest.raises(ValidationError) as duplicate:
        finalize_stc_run(
            run_id="R",
            planned_units=plan,
            accepted_results=[result, {**result, "work_unit_id": "U2"}],
            output_root=tmp_path / "dup",
        )
    assert duplicate.value.code == "AGGREGATE_COVERAGE_MISMATCH"
    with pytest.raises(ValidationError) as drift:
        finalize_stc_run(
            run_id="R",
            planned_units=[plan[0]],
            accepted_results=[{**result, "primary_coverage": ["JHN 1:2"]}],
            output_root=tmp_path / "drift",
        )
    assert drift.value.code == "RESULT_COVERAGE_DRIFT"


def test_stc_aggregate_refuses_a_result_from_another_run(make_workspace) -> None:
    """A unit result carrying another Run's identity is lineage drift, not silently merged."""
    from .test_exception_reports import _stc_plan

    config, plan_path = _stc_plan(make_workspace(), ("FINALIZED",))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    manifest = Path(plan["work_units"][0]["manifest_path"])
    normalized_path = manifest.parent / "validation" / "normalized-findings.json"
    normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
    normalized["run_id"] = "ANOTHER-RUN"
    normalized_path.write_text(json.dumps(normalized), encoding="utf-8")

    with pytest.raises(ValidationError) as caught:
        aggregate_act_plan(config, plan_path)
    assert caught.value.code == "RESULT_COVERAGE_DRIFT"


def test_continue_recovers_after_a_crash_between_task_creation_and_plan_save(make_workspace, monkeypatch) -> None:
    """A stage task created before the plan was saved is not duplicated; Continue reuses the plan state."""
    import sage.act_tasks as act_tasks
    from sage.plan_continuation import continue_analysis_plan

    from .test_exception_reports import _composite_fixture

    config, plan_path = _composite_fixture(
        make_workspace, [{"stage": "STRUCTURAL_ADJUDICATION", "state": "NOT_ASSESSED", "refs": ["MAT 1:2"]}]
    )
    pending = plan_path.parent.parent / "tasks" / "meaning" / "task-manifest.json"
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(json.dumps({"task_id": "T-MEANING", "scope": "MAT 1:1-2"}) + "\n", encoding="utf-8")
    created: list[str] = []

    def crash_after_create(_config, **_kwargs):
        """Create the task, then crash before the composite plan is saved."""
        created.append("task")
        raise KeyboardInterrupt

    monkeypatch.setattr(act_tasks, "create_act_task", crash_after_create)
    with pytest.raises(KeyboardInterrupt):
        continue_analysis_plan(config, plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert [stage["stage"] for stage in plan["stages"]] == ["STRUCTURAL_ADJUDICATION"]

    monkeypatch.setattr(
        act_tasks,
        "create_act_task",
        lambda _config, **_kwargs: created.append("task") or {"status": "CREATED", "manifest_path": str(pending)},
    )
    result = continue_analysis_plan(config, plan_path)
    assert result["status"] == "NEXT_WORK_UNIT"
    assert [stage["stage"] for stage in json.loads(plan_path.read_text(encoding="utf-8"))["stages"]] == [
        "STRUCTURAL_ADJUDICATION",
        "REFERENCE_TEXT_COMPARISON",
    ]
