"""Shared exception reports: integrity guards stop, everything else is retried then reported NOT_ASSESSED."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sage.act_tasks import aggregate_act_plan
from sage.exception_reports import (
    INTEGRITY_CODES,
    MAX_UNIT_ATTEMPTS,
    NCA_INTEGRITY_FAILURE_CODES,
    NOT_ASSESSED,
    ExceptionRecord,
    coverage_document,
    exceptions_for_run,
    failed_attempts,
    is_integrity_code,
    load_not_assessed_result,
    record_exception,
    render_exceptions_section,
    unit_failure_action,
    write_not_assessed_result,
)
from sage.jobs import JobStore
from sage.menu import MenuIO, ScriptedInput, SageControlCenter
from sage.plan_continuation import continue_analysis_plan
from sage.registry import load_ecosystem


def test_integrity_codes_merge_nca_stale_binding_path_and_contract_guards() -> None:
    """One list covers every guard that may stop a Run; content problems are absent from it."""
    assert NCA_INTEGRITY_FAILURE_CODES <= INTEGRITY_CODES
    for code in (
        "NCA_REFERENCE_PACKAGE_STALE",  # stale input
        "PROJECT_BINDING_MISMATCH",  # binding
        "EXTERNAL_PATH_ESCAPE",  # path safety
        "BIC_PROTECTED_CONTRACT_HASH_MISMATCH",  # pinned contract
        "TARGET_REVERT_CONFLICT",  # corrupt governed commit state
        "SOMETHING_NEW_STALE",  # fragment rule
    ):
        assert is_integrity_code(code), code
    for code in ("LLM_PROVIDER_RESPONSE_INVALID", "BIC_OUTPUT_INVALID", "STC_REPORT_LANGUAGE_MISMATCH"):
        assert not is_integrity_code(code), code


def test_unit_failure_policy_stops_retries_then_reports_not_assessed() -> None:
    """Integrity and environment conditions stop; other failures retry up to the cap."""
    assert unit_failure_action("NCA_PHASE_CHECKPOINT_INVALID", "BLOCKED", 1) == "STOP"
    assert unit_failure_action("CODEX_CHATGPT_AUTH_REQUIRED", "INPUT_REQUIRED", 1) == "STOP"
    assert unit_failure_action("LLM_PROVIDER_TIMEOUT", "TASK_PAUSED", 1) == "STOP"
    for attempt in range(1, MAX_UNIT_ATTEMPTS):
        assert unit_failure_action("BIC_OUTPUT_INVALID", "TASK_OUTPUT_REJECTED", attempt) == "RETRY"
    assert unit_failure_action("BIC_OUTPUT_INVALID", "TASK_OUTPUT_REJECTED", MAX_UNIT_ATTEMPTS) == NOT_ASSESSED


def test_exception_records_persist_per_run_and_count_failed_attempts(tmp_path: Path) -> None:
    """Records are append-only evidence; attempts are counted from them per task."""
    run_root = tmp_path / "run"
    for attempt, effect in ((1, "RETRY"), (2, "RETRY")):
        record_exception(
            run_root,
            ExceptionRecord(tool="rtc", code="X", message="m", effect=effect, task_id="T1", attempts=attempt),
        )
    record_exception(run_root, ExceptionRecord(tool="rtc", code="X", message="m", effect="RETRY", task_id="T2"))
    assert [row["attempts"] for row in exceptions_for_run(run_root) if row["task_id"] == "T1"] == [1, 2]
    assert failed_attempts(run_root, "T1") == 2
    assert failed_attempts(run_root, "T3") == 0
    with pytest.raises(ValueError):
        ExceptionRecord(tool="rtc", code="X", message="m", effect="SHRUG")


def test_coverage_document_goes_through_assess_coverage() -> None:
    """Complete coverage keeps its shape; unassessed coordinates change status and add the exception detail."""
    complete = coverage_document(["MAT 1:1"], [], findings_present=False)
    assert complete == {"status": "COMPLETE", "reviewed_references": ["MAT 1:1"]}
    partial = coverage_document(["MAT 1:1"], ["MAT 1:2"], findings_present=True)
    assert partial["status"] == "PARTIAL"
    assert partial["not_assessed_references"] == ["MAT 1:2"]
    assert partial["confidence_basis"] == "LIMITED"
    nothing = coverage_document([], ["MAT 1:1", "MAT 1:2"], findings_present=False)
    assert nothing["status"] == "NOT_ASSESSED"
    assert nothing["result"] == "NOT_ASSESSED"


def test_shared_report_section_lists_only_not_assessed_coordinates() -> None:
    """The section is absent when nothing was lost and names coordinates, code, and attempts otherwise."""
    assert render_exceptions_section([{"effect": "RETRY", "code": "X"}]) == []
    section = render_exceptions_section(
        [
            {
                "effect": NOT_ASSESSED,
                "code": "BIC_OUTPUT_INVALID",
                "coordinates": ["MAT 1:2"],
                "attempts": 3,
                "severity": "WARNING",
                "message": "Output rejected.",
            }
        ]
    )
    text = "\n".join(section)
    assert "Exceptions — not assessed" in text
    assert "MAT 1:2" in text and "BIC_OUTPUT_INVALID" in text and "`3`" in text


def _unit(active_root: Path, plan_id: str, index: int, reference: str, job_id: str, run_id: str, status: str) -> dict:
    """Write one sealed work unit with a FINALIZED or NOT_ASSESSED terminal result."""
    unit_id = f"{plan_id}-U{index:03d}"
    manifest = active_root / unit_id / "task-manifest.json"
    validation = manifest.parent / "validation"
    validation.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"task_id": unit_id, "scope": reference, "expected_references": [reference]}) + "\n",
        encoding="utf-8",
    )
    if status == NOT_ASSESSED:
        write_not_assessed_result(
            manifest,
            ExceptionRecord(
                tool="rtc",
                code="LLM_PROVIDER_RESPONSE_INVALID",
                message="Provider output rejected three times.",
                effect=NOT_ASSESSED,
                task_id=unit_id,
                work_unit=unit_id,
                coordinates=(reference,),
                attempts=3,
            ),
        )
    else:
        (validation / "submission.json").write_text(
            json.dumps({"status": "FINALIZED", "task_id": unit_id, "scope": reference}) + "\n", encoding="utf-8"
        )
        (validation / "normalized-findings.json").write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "run_id": run_id,
                    "output_project": "usWIP",
                    "contemporary_source": "usNIVv2",
                    "resource_fingerprints": {"project.usWIP": "WIP-SHA", "project.usNIVv2": "REF-SHA"},
                    "resource_bindings": {"wip": "usWIP", "reference": "usNIVv2"},
                    "coverage": {"status": "COMPLETE", "reviewed_references": [reference]},
                    "review_receipts": [],
                    "structural_adjudications": [],
                    "ol_review_requests": [],
                    "ol_resolutions": [],
                    "resolved_ol_request_ids": [],
                    "findings": [
                        {
                            "finding_id": "F001",
                            "target_reference": reference,
                            "category": "MEANING",
                            "issue": f"Issue in {reference}",
                        }
                    ],
                    "finding_count": 1,
                }
            )
            + "\n",
            encoding="utf-8",
        )
    return {"unit_id": unit_id, "task_id": unit_id, "scope": reference, "manifest_path": str(manifest.resolve())}


def _plan(config, plan_id: str, statuses: tuple[str, ...]) -> Path:
    """Write one partitioned RTC plan whose units end with the given terminal statuses."""
    job_id, run_id = "SAW_usWIP-usNIVv2", "SAW-RUN-001"
    active_root = config.workflow("saw").output_root / "active"
    references = [f"MAT 1:{index}" for index in range(1, len(statuses) + 1)]
    units = [
        _unit(active_root, plan_id, index, reference, job_id, run_id, status)
        for index, (reference, status) in enumerate(zip(references, statuses), start=1)
    ]
    plan_path = config.workflow("saw").output_root / "plans" / f"{plan_id}.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        json.dumps(
            {
                "workflow": "saw",
                "operation": "rtc",
                "status": "PARTITIONED",
                "plan_id": plan_id,
                "job_id": job_id,
                "run_id": run_id,
                "requested_scope": f"MAT 1:1-{len(statuses)}",
                "output_project": "usWIP",
                "contemporary_source": "usNIVv2",
                "expected_references": references,
                "work_units": units,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return plan_path


def test_continuation_treats_not_assessed_as_terminal(make_workspace) -> None:
    """A NOT_ASSESSED unit is finished work: the plan advances instead of reopening it."""
    config = load_ecosystem(make_workspace() / "ecosystem.yml")
    store = JobStore(config.root, config.settings_path)
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="SAW_usWIP-usNIVv2",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
    )
    runtime = load_ecosystem(store.ensure_runtime_files(job))
    plan_path = _plan(runtime, "SAW-RTC-NA-CONTINUE", ("FINALIZED", NOT_ASSESSED))
    result = continue_analysis_plan(runtime, plan_path)
    assert result["status"] == "READY_TO_AGGREGATE"
    assert result["completed_units"] == result["total_units"] == 2


def test_aggregation_reports_partial_coverage_instead_of_failing(make_workspace) -> None:
    """Assessed coordinates keep their findings; the lost one is reported, never claimed as reviewed."""
    config = load_ecosystem(make_workspace() / "ecosystem.yml")
    plan_path = _plan(config, "SAW-RTC-NA-AGGREGATE", ("FINALIZED", NOT_ASSESSED, "FINALIZED"))
    result = aggregate_act_plan(config, plan_path)

    assert result["finding_count"] == 2
    coverage = result["coverage"]
    assert coverage["status"] == "PARTIAL"
    assert coverage["reviewed_references"] == ["MAT 1:1", "MAT 1:3"]
    assert coverage["not_assessed_references"] == ["MAT 1:2"]
    assert [row["code"] for row in result["exceptions"]] == ["LLM_PROVIDER_RESPONSE_INVALID"]
    assert {row["status"] for row in result["work_units"] if row.get("status")} == {NOT_ASSESSED}
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Exceptions — not assessed" in report
    assert "Not assessed coordinates: `1`" in report


def test_aggregation_of_a_fully_assessed_plan_is_unchanged(make_workspace) -> None:
    """With nothing lost, coverage keeps its original COMPLETE shape and no exceptions section appears."""
    config = load_ecosystem(make_workspace() / "ecosystem.yml")
    plan_path = _plan(config, "SAW-RTC-NA-NONE", ("FINALIZED", "FINALIZED"))
    result = aggregate_act_plan(config, plan_path)
    assert result["coverage"]["status"] == "COMPLETE"
    assert "not_assessed_references" not in result["coverage"]
    assert result["exceptions"] == []
    assert "Exceptions — not assessed" not in Path(result["report_path"]).read_text(encoding="utf-8")


def _center(root: Path) -> SageControlCenter:
    """Build a deterministic control center for plan-runner tests."""
    import io

    return SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput([]), output=io.StringIO()),
        skip_setup=True,
        dry_run_provider=True,
    )


def _runner(make_workspace, monkeypatch, *, code: str, disposition: str):
    """Wire a plan runner whose only unit always fails with the given event; return its pieces."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    plan_path = run.root / "plans" / "composite.json"
    run = store.update_run(run, plan_path=str(plan_path), status="COMPOSITE")
    manifest = run.root / "tasks" / "unit-1" / "task-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"task_id": "T-UNIT-1", "scope": "MAT 1:1", "expected_references": ["MAT 1:1"]}) + "\n",
        encoding="utf-8",
    )
    center = _center(root)
    attempts: list[int] = []

    def controller(_job, _arguments):
        """Report the next unit until it is sealed, then complete the plan."""
        if (manifest.parent / "validation" / "submission.json").is_file():
            return {"status": "COMPLETE", "report_directory": ""}
        return {
            "status": "NEXT_WORK_UNIT",
            "completed_units": 0,
            "total_units": 1,
            "next_unit": {"unit_id": "UNIT-1", "manifest_path": str(manifest), "scope": "MAT 1:1"},
        }

    def failing_action(_job, current, _path):
        """Fail every attempt with the configured recorded event."""
        attempts.append(1)
        center._last_execution_event = {
            "reason_code": code,
            "disposition": disposition,
            "message": "The provider output was rejected.",
            "report_path": "diagnostics/BLOCK-REPORT.md",
        }
        return current, False

    monkeypatch.setattr(center, "controller", controller)
    monkeypatch.setattr(center, "_task_action", failing_action)
    return center, job, run, manifest, attempts


def test_runner_retries_then_reports_not_assessed_and_continues(make_workspace, monkeypatch) -> None:
    """A unit failing every attempt is retried up to the cap, sealed NOT_ASSESSED, and the Run finishes."""
    center, job, run, manifest, attempts = _runner(
        make_workspace, monkeypatch, code="BIC_OUTPUT_INVALID", disposition="TASK_OUTPUT_REJECTED"
    )
    finished = center._continue_saw_plan(job, run)

    assert len(attempts) == MAX_UNIT_ATTEMPTS
    submission = json.loads((manifest.parent / "validation" / "submission.json").read_text(encoding="utf-8"))
    assert submission["status"] == NOT_ASSESSED
    evidence = load_not_assessed_result(manifest)
    assert evidence["exception"]["coordinates"] == ["MAT 1:1"]
    assert evidence["exception"]["attempts"] == MAX_UNIT_ATTEMPTS
    rows = exceptions_for_run(run.root)
    assert [row["effect"] for row in rows] == ["RETRY", "RETRY", NOT_ASSESSED]
    output = center.io.output.getvalue()
    assert "reported as NOT_ASSESSED" in output
    assert "1 work unit(s) were not assessed" in output
    assert finished.status in {"COMPLETE", "COMPLETE_WITH_STRUCTURE_PROBLEMS"}


def test_runner_stops_without_sealing_on_an_integrity_code(make_workspace, monkeypatch) -> None:
    """An integrity guard stops the Run at the first failure: no retry, no NOT_ASSESSED result."""
    center, job, run, manifest, attempts = _runner(
        make_workspace, monkeypatch, code="NCA_REFERENCE_PACKAGE_STALE", disposition="STALE"
    )
    center._continue_saw_plan(job, run)

    assert len(attempts) == 1
    assert not (manifest.parent / "validation" / "submission.json").exists()
    assert exceptions_for_run(run.root) == []


def test_runner_pauses_instead_of_sealing_on_an_environment_condition(make_workspace, monkeypatch) -> None:
    """A provider outage says nothing about content, so it never turns coordinates into NOT_ASSESSED."""
    center, job, run, manifest, attempts = _runner(
        make_workspace, monkeypatch, code="LLM_PROVIDER_TIMEOUT", disposition="TASK_PAUSED"
    )
    center._continue_saw_plan(job, run)

    assert len(attempts) == 1
    assert not (manifest.parent / "validation" / "submission.json").exists()


def _stc_plan(root: Path, statuses: tuple[str, ...]):
    """Write one partitioned STC plan whose units end FINALIZED or NOT_ASSESSED; return its parts."""
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="stc", scope=f"MAT 1:1-{len(statuses)}")
    config = load_ecosystem(store.ensure_runtime_files(job))
    plan_id = f"SAW-STC-NA-{len(statuses)}"
    lineage = {"project.usWIP": "WIP-SHA", "project.GRK": "GRK-SHA"}
    units = []
    for index, status in enumerate(statuses, start=1):
        reference = f"MAT 1:{index}"
        unit_id = f"{plan_id}-U{index:03d}"
        manifest = config.workflow("saw").output_root / "active" / unit_id / "task-manifest.json"
        validation = manifest.parent / "validation"
        validation.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                {
                    "task_id": unit_id,
                    "task_fingerprint": "TASK-SHA",
                    "scope": reference,
                    "expected_references": [reference],
                    "resource_fingerprints": lineage,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        if status == NOT_ASSESSED:
            write_not_assessed_result(
                manifest,
                ExceptionRecord(
                    tool="stc",
                    code="STC_OUTPUT_INVALID",
                    message="Output rejected three times.",
                    effect=NOT_ASSESSED,
                    task_id=unit_id,
                    work_unit=unit_id,
                    coordinates=(reference,),
                    attempts=3,
                ),
            )
        else:
            (validation / "submission.json").write_text(
                json.dumps({"status": "FINALIZED", "task_id": unit_id, "scope": reference}) + "\n",
                encoding="utf-8",
            )
            (validation / "normalized-findings.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "operation": "stc",
                        "task_id": unit_id,
                        "work_unit_id": unit_id,
                        "task_fingerprint": "TASK-SHA",
                        "scope": reference,
                        "job_id": job.job_id,
                        "run_id": run.run_id,
                        "output_project": "usWIP",
                        "contemporary_source": None,
                        "primary_ol_authority": "GRK",
                        "resource_fingerprints": lineage,
                        "resource_bindings": {"WIP": "usWIP", "ORIGINAL_LANGUAGE_GREEK": "GRK"},
                        "primary_coverage": [reference],
                        "analytical_completion": {
                            "status": "COMPLETE",
                            "review_item": "STC_CORRESPONDENCE",
                            "reviewed_primary_coordinates": [reference],
                        },
                        "source_comparison_status": "COMPLETE",
                        "source_text_issues": [],
                        "finding_count": 0,
                        "findings": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        units.append(
            {
                "unit_id": unit_id,
                "task_id": unit_id,
                "manifest_path": str(manifest.resolve()),
                "task_fingerprint": "TASK-SHA",
                "primary_coverage_atoms": [reference],
            }
        )
    plan_path = config.workflow("saw").output_root / "plans" / f"{plan_id}.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": "PARTITIONED",
                "plan_id": plan_id,
                "workflow": "saw",
                "operation": "stc",
                "job_id": job.job_id,
                "run_id": run.run_id,
                "requested_scope": f"MAT 1:1-{len(statuses)}",
                "output_project": "usWIP",
                "contemporary_source": None,
                "primary_ol_authority": "GRK",
                "authority_family": "GRK",
                "authority_role": "PRIMARY",
                "expected_references": [f"MAT 1:{index}" for index in range(1, len(statuses) + 1)],
                "work_units": units,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return config, plan_path


def test_stc_aggregation_reports_a_not_assessed_unit(make_workspace) -> None:
    """STC finalization accepts a NOT_ASSESSED unit and reports it beside the assessed coordinates."""
    config, plan_path = _stc_plan(make_workspace(), ("FINALIZED", NOT_ASSESSED))
    result = aggregate_act_plan(config, plan_path)

    assert result["status"] == "FINALIZED"
    assert result["work_unit_count"] == 1
    assert result["coverage"]["status"] == "PARTIAL"
    assert result["coverage"]["not_assessed_references"] == ["MAT 1:2"]
    assert [row["code"] for row in result["exceptions"]] == ["STC_OUTPUT_INVALID"]
    canonical = json.loads(Path(result["canonical_artifacts"]["run_result"]).read_text(encoding="utf-8"))
    assert canonical["planned_primary_coverage"] == ["MAT 1:1"]
    assert canonical["exceptions"][0]["coordinates"] == ["MAT 1:2"]
    assert "Exceptions — not assessed" in Path(result["canonical_artifacts"]["report"]).read_text(encoding="utf-8")
    assert "Exceptions — not assessed" in Path(result["report_path"]).read_text(encoding="utf-8")


def test_stc_aggregation_finalizes_when_every_unit_is_not_assessed(make_workspace) -> None:
    """Even with nothing assessed, STC publishes a report that says so instead of failing the Run."""
    config, plan_path = _stc_plan(make_workspace(), (NOT_ASSESSED,))
    result = aggregate_act_plan(config, plan_path)

    assert result["status"] == "FINALIZED"
    assert result["coverage"]["status"] == "NOT_ASSESSED"
    assert result["canonical_artifacts"] == {}
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Exceptions — not assessed" in report
    assert "MAT 1:1" in report


def test_composite_rtc_finalizes_when_its_only_stage_is_not_assessed(make_workspace) -> None:
    """A single-task stage that could not be assessed ends the composite with an honest report."""
    root = make_workspace()
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1:1-2")
    config = load_ecosystem(store.ensure_runtime_files(job))
    manifest = run.root / "tasks" / "meaning" / "task-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {"task_id": "T-MEANING", "scope": "MAT 1:1-2", "expected_references": ["MAT 1:1", "MAT 1:2"]}
        )
        + "\n",
        encoding="utf-8",
    )
    write_not_assessed_result(
        manifest,
        ExceptionRecord(
            tool="rtc",
            code="LLM_PROVIDER_RESPONSE_INVALID",
            message="Output rejected three times.",
            effect=NOT_ASSESSED,
            task_id="T-MEANING",
            coordinates=("MAT 1:1", "MAT 1:2"),
            attempts=3,
        ),
    )
    plan_path = run.root / "plans" / "RTC-COMPOSITE-NA.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        json.dumps(
            {
                "plan_type": "RTC_COMPOSITE",
                "status": "PARTITIONED",
                "plan_id": "RTC-COMPOSITE-NA",
                "workflow": "saw",
                "job_id": job.job_id,
                "run_id": run.run_id,
                "requested_scope": "MAT 1:1-2",
                "stages": [
                    {"kind": "TASK", "stage": "REFERENCE_TEXT_COMPARISON", "manifest_path": str(manifest.resolve())}
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = continue_analysis_plan(config, plan_path)

    assert result["status"] == "COMPLETE"
    final = json.loads(Path(result["aggregate_path"]).read_text(encoding="utf-8"))
    assert final["coverage"]["status"] == "NOT_ASSESSED"
    assert final["coverage"]["not_assessed_references"] == ["MAT 1:1", "MAT 1:2"]
    assert final["exceptions"][0]["code"] == "LLM_PROVIDER_RESPONSE_INVALID"
    assert "Exceptions — not assessed" in Path(result["report_path"]).read_text(encoding="utf-8")


def test_consolidation_keeps_a_coordinate_reviewed_by_any_input(tmp_path: Path) -> None:
    """Coverage is reviewed if any Run reviewed it; only genuinely unassessed coordinates stay reported."""
    from sage.consolidation import consolidate_result_documents

    lost = {
        "effect": NOT_ASSESSED,
        "code": "X",
        "coordinates": ["MAT 1:2"],
    }
    first = {
        "scope": "MAT 1",
        "operation": "rtc",
        "task_id": "A",
        "coverage": {
            "status": "PARTIAL",
            "reviewed_references": ["MAT 1:1"],
            "not_assessed_references": ["MAT 1:2", "MAT 1:3"],
        },
        "exceptions": [lost, {"effect": NOT_ASSESSED, "code": "Y", "coordinates": ["MAT 1:3"]}],
        "findings": [],
    }
    second = {
        "scope": "MAT 1",
        "operation": "rtc",
        "task_id": "B",
        "coverage": {"status": "COMPLETE", "reviewed_references": ["MAT 1:2"]},
        "findings": [],
    }
    merged = consolidate_result_documents([first, second])

    assert merged["coverage"]["status"] == "PARTIAL"
    assert merged["coverage"]["reviewed_references"] == ["MAT 1:1", "MAT 1:2"]
    assert merged["coverage"]["not_assessed_references"] == ["MAT 1:3"]
    assert [row["code"] for row in merged["exceptions"]] == ["Y"]


def _bic_chain(make_workspace, monkeypatch, behavior: dict[str, str]):
    """Drive the real BIC chain with fake task creation and execution; return its pieces.

    ``behavior`` maps each operation to "OK", or to the reason code with which every attempt fails.
    """
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "bic")
    run = store.create_run(job, operation="bic", scope="MAT 1")
    center = _center(root)
    attempts: list[str] = []
    committed = {"inspect": "COMMITTED", "rewrite": "STAGED_VALIDATED", "self_check": "COMMITTED"}

    def create_task(_project, current, operation, *, scope=None, predecessor=None):
        """Create one minimal sealed task for the operation."""
        manifest = current.root / "tasks" / f"{operation}-{scope or 'all'}" / "task-manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                {
                    "task_id": f"T-{operation}-{scope or 'all'}",
                    "operation": operation,
                    "scope": scope or current.scope,
                    "expected_references": [f"{scope or current.scope}:1"],
                    "allowed_writes": ["output/result.txt"],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return center._append_task(current, str(manifest)), {"act_path": str(manifest.parent / "ACT.md")}

    def task_action(_project, current, path):
        """Succeed by sealing the task, or fail with the configured recorded event."""
        operation = json.loads(path.read_text(encoding="utf-8"))["operation"]
        attempts.append(operation)
        outcome = behavior[operation]
        if outcome == "OK":
            (path.parent / "validation").mkdir(parents=True, exist_ok=True)
            (path.parent / "validation" / "submission.json").write_text(
                json.dumps({"status": committed[operation]}) + "\n", encoding="utf-8"
            )
            return current, True
        center._last_execution_event = {
            "reason_code": outcome,
            "disposition": "STALE" if "STALE" in outcome else "TASK_OUTPUT_REJECTED",
            "message": "Output rejected.",
            "report_path": "diagnostics/BLOCK-REPORT.md",
        }
        return current, False

    monkeypatch.setattr(center, "_create_task", create_task)
    monkeypatch.setattr(center, "_task_action", task_action)
    return center, job, run, attempts


def test_bic_chain_runs_every_stage_in_one_continue(make_workspace, monkeypatch) -> None:
    """With nothing failing, one Continue carries INSPECT, REWRITE, and SELF-CHECK to completion."""
    center, job, run, attempts = _bic_chain(
        make_workspace, monkeypatch, {"inspect": "OK", "rewrite": "OK", "self_check": "OK"}
    )
    finished = center._continue_bic(job, run)

    assert attempts == ["inspect", "rewrite", "self_check"]
    assert finished.status == "COMPLETE"
    assert "bounded target commit is recorded" in center.io.output.getvalue()
    assert exceptions_for_run(run.root) == []


def test_bic_chain_seals_a_stage_that_keeps_failing_and_finishes(make_workspace, monkeypatch) -> None:
    """A REWRITE failing every attempt is reported NOT_ASSESSED; SELF-CHECK never runs on it."""
    center, job, run, attempts = _bic_chain(
        make_workspace, monkeypatch, {"inspect": "OK", "rewrite": "BIC_OUTPUT_INVALID", "self_check": "OK"}
    )
    finished = center._continue_bic(job, run)

    assert attempts == ["inspect", *["rewrite"] * MAX_UNIT_ATTEMPTS]
    assert finished.status == "COMPLETE"
    assert [row["effect"] for row in exceptions_for_run(run.root)] == ["RETRY", "RETRY", NOT_ASSESSED]
    report = (run.root / "diagnostics" / "EXCEPTIONS-NOT-ASSESSED.md").read_text(encoding="utf-8")
    assert "Exceptions — not assessed" in report and "BIC_OUTPUT_INVALID" in report
    output = center.io.output.getvalue()
    assert "no TARGET text was written" in output
    assert "Exception report:" in output


def test_bic_chain_stops_on_an_integrity_guard(make_workspace, monkeypatch) -> None:
    """A stale-input guard stops the chain at once and leaves the Run open and resumable."""
    center, job, run, attempts = _bic_chain(
        make_workspace, monkeypatch, {"inspect": "OK", "rewrite": "BIC_EVIDENCE_COHORT_STALE", "self_check": "OK"}
    )
    stopped = center._continue_bic(job, run)

    assert attempts == ["inspect", "rewrite"]
    assert stopped.status not in {"COMPLETE", "ABANDONED"}
    assert exceptions_for_run(run.root) == []


def test_partitioned_bic_skips_an_unassessed_unit_and_finishes_the_rest(make_workspace, monkeypatch) -> None:
    """One unit sealed NOT_ASSESSED does not stop the next unit from being rewritten."""
    center, job, run, attempts = _bic_chain(
        make_workspace, monkeypatch, {"inspect": "OK", "rewrite": "OK", "self_check": "OK"}
    )
    units = []
    for scope in ("MAT 1", "MAT 2"):
        manifest = run.root / "tasks" / f"inspect-{scope}" / "task-manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                {
                    "task_id": f"T-{scope}",
                    "operation": "inspect",
                    "scope": scope,
                    "expected_references": [f"{scope}:1"],
                    "allowed_writes": ["output/result.txt"],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        units.append({"unit_id": f"U-{scope}", "scope": scope, "manifest_path": str(manifest)})
        run = center._append_task(run, str(manifest))
    plan = run.root / "plans" / "bic-plan.json"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(json.dumps({"work_units": units}) + "\n", encoding="utf-8")
    run = center.store.update_run(run, plan_path=str(plan), status="PARTITIONED_IN_PROGRESS")
    write_not_assessed_result(
        Path(units[0]["manifest_path"]),
        ExceptionRecord(
            tool="bic",
            code="BIC_OUTPUT_INVALID",
            message="Rejected.",
            effect=NOT_ASSESSED,
            task_id="T-MAT 1",
            coordinates=("MAT 1:1",),
            attempts=3,
        ),
    )
    record_exception(
        run.root,
        ExceptionRecord(
            tool="bic",
            code="BIC_OUTPUT_INVALID",
            message="Rejected.",
            effect=NOT_ASSESSED,
            task_id="T-MAT 1",
            coordinates=("MAT 1:1",),
            attempts=3,
        ),
    )

    finished = center._continue_bic(job, run)

    assert finished.status == "COMPLETE"
    assert attempts == ["inspect", "rewrite", "self_check"]
    created = {json.loads(Path(path).read_text(encoding="utf-8"))["task_id"] for path in finished.task_manifests}
    assert "T-rewrite-MAT 1" not in created and "T-rewrite-MAT 2" in created
    assert "1 work unit(s) were not assessed" in center.io.output.getvalue()


def test_nca_report_renders_the_shared_exceptions_section() -> None:
    """NCA chapter reports show the same section as RTC, STC, and BIC for groups that were not assessed."""
    from sage.nca_reporting import render_nca_action_report

    report = {
        "scope": "MAT 1",
        "narrative_language": {"tag": "en"},
        "resource_bindings": {"WIP": "usWIP", "ORIGINAL_LANGUAGE_GREEK": "GRK"},
        "coverage": {"status": "PARTIAL", "checked": 1, "not_indexed": 0},
        "authority_header": [],
        "findings": [],
        "advisories": [{"reference": "MAT 1:2", "code": "NOT_ASSESSED"}],
        "exceptions": [
            {
                "effect": NOT_ASSESSED,
                "code": "NOT_ASSESSED",
                "coordinates": ["MAT 1:2"],
                "attempts": 0,
                "severity": "WARNING",
                "message": "NCA could not compare these numbers, so none were checked.",
            }
        ],
        "notes": [],
    }
    text = render_nca_action_report(report)
    assert "Exceptions — not assessed" in text
    assert "MAT 1:2" in text
    without = render_nca_action_report({**report, "exceptions": []})
    assert "Exceptions — not assessed" not in without
