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
    assert "\\n" not in report and report.count("\n") > 5


def test_aggregation_reports_an_unplannable_span_as_not_assessed(make_workspace) -> None:
    """A span no work unit could hold is planned out, reported once, and never claimed as reviewed."""
    config = load_ecosystem(make_workspace() / "ecosystem.yml")
    plan_path = _plan(config, "SAW-RTC-NA-SPAN", ("FINALIZED", "FINALIZED"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["expected_references"].append("MAT 1:3")
    plan["not_assessed_spans"] = [{
        "references": ["MAT 1:3"],
        "code": "WORK_UNIT_RECORD_EXCEEDS_LIMIT",
        "message": "Single verse record MAT 1:3 exceeds hard limits.",
    }]
    plan_path.write_text(json.dumps(plan) + "\n", encoding="utf-8")
    result = aggregate_act_plan(config, plan_path)

    coverage = result["coverage"]
    assert coverage["status"] == "PARTIAL"
    assert coverage["reviewed_references"] == ["MAT 1:1", "MAT 1:2"]
    assert coverage["not_assessed_references"] == ["MAT 1:3"]
    assert [row["code"] for row in result["exceptions"]] == ["WORK_UNIT_RECORD_EXCEEDS_LIMIT"]


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
    assert finished.status == "COMPLETE_WITH_EXCEPTIONS"


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
    assert canonical["status"] == "PARTIAL"
    assert canonical["coverage"]["not_assessed_references"] == ["MAT 1:2"]
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
    assert "`NOT_ASSESSED` (0 assessed, 1 not assessed coordinates)" in report
    assert "`COMPLETE` (0 coordinates)" not in report


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
    # The fixture TARGET already has MAT 1 text; these chains test retries, not the replacement question.
    monkeypatch.setattr("sage.menu.existing_target_text", lambda _project, _scope=None: {})
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


def _replacement_chain(make_workspace, monkeypatch, answers: list[str]):
    """Run the BIC chain against a Paratext TARGET whose scope already has text, answering the question."""
    import io

    center, job, run, attempts = _bic_chain(
        make_workspace, monkeypatch, {"inspect": "OK", "rewrite": "OK", "self_check": "OK"}
    )
    monkeypatch.setattr(
        "sage.menu.existing_target_text", lambda _project, _scope=None: {"MAT": ["MAT 1:1", "MAT 1:2"]}
    )
    center.io = MenuIO(input_func=ScriptedInput(answers), output=io.StringIO())
    return center, job, run, attempts


def test_bic_chain_asks_before_replacing_existing_target_text(make_workspace, monkeypatch) -> None:
    """A confirmed replacement runs SELF-CHECK and is remembered for the rest of the Run."""
    center, job, run, attempts = _replacement_chain(make_workspace, monkeypatch, ["y"])
    finished = center._continue_bic(job, run)

    assert attempts == ["inspect", "rewrite", "self_check"]
    assert finished.status == "COMPLETE"
    output = center.io.output.getvalue()
    assert "already has text in 2 verse(s)" in output and "MAT 1:1, MAT 1:2" in output
    assert json.loads((run.root / "target-replacement-confirmed.json").read_text(encoding="utf-8"))["references"] == [
        "MAT 1:1", "MAT 1:2"
    ]


def test_declined_target_replacement_keeps_target_and_reports(make_workspace, monkeypatch) -> None:
    """Declining skips SELF-CHECK, keeps the staged rewrite, and reports the scope; the Run still completes."""
    center, job, run, attempts = _replacement_chain(make_workspace, monkeypatch, ["n"])
    finished = center._continue_bic(job, run)

    assert attempts == ["inspect", "rewrite"]
    assert finished.status == "COMPLETE"
    assert "existing TARGET text was kept" in center.io.output.getvalue()
    [row] = exceptions_for_run(run.root)
    assert row["code"] == "BIC_TARGET_REPLACEMENT_DECLINED"
    assert row["effect"] == NOT_ASSESSED and row["coordinates"] == ["MAT 1:1", "MAT 1:2"]


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


def _composite_fixture(make_workspace, stages: list[dict]):
    """Write a composite RTC plan whose stages are given as (stage name, manifest writer) rows."""
    root = make_workspace()
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1:1-2")
    config = load_ecosystem(store.ensure_runtime_files(job))
    rows = []
    for stage in stages:
        manifest = run.root / "tasks" / stage["stage"].lower() / "task-manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({"task_id": f"T-{stage['stage']}", "scope": "MAT 1:1-2", "expected_references": stage.get("refs", [])})
            + "\n",
            encoding="utf-8",
        )
        if stage["state"] == NOT_ASSESSED:
            write_not_assessed_result(
                manifest,
                ExceptionRecord(
                    tool="rtc",
                    code="LLM_PROVIDER_RESPONSE_INVALID",
                    message="Output rejected three times.",
                    effect=NOT_ASSESSED,
                    task_id=f"T-{stage['stage']}",
                    coordinates=tuple(stage.get("refs", [])),
                    attempts=3,
                ),
            )
        else:
            validation = manifest.parent / "validation"
            validation.mkdir(parents=True, exist_ok=True)
            (validation / "submission.json").write_text(json.dumps({"status": "FINALIZED"}) + "\n", encoding="utf-8")
            (validation / "normalized-findings.json").write_text(json.dumps(stage["result"]) + "\n", encoding="utf-8")
        rows.append({"kind": "TASK", "stage": stage["stage"], "manifest_path": str(manifest.resolve())})
    plan_path = run.root / "plans" / "RTC-COMPOSITE-X.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        json.dumps(
            {
                "plan_type": "RTC_COMPOSITE",
                "status": "PARTITIONED",
                "plan_id": "RTC-COMPOSITE-X",
                "workflow": "saw",
                "job_id": job.job_id,
                "run_id": run.run_id,
                "requested_scope": "MAT 1:1-2",
                "output_project": "usWIP",
                "contemporary_source": "usREF",
                "stages": rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return config, plan_path


def test_composite_rtc_continues_to_meaning_stage_after_not_assessed_structural_stage(make_workspace, monkeypatch) -> None:
    """A lost structural adjudication does not leave the rest of the scope unreviewed."""
    import sage.act_tasks as act_tasks

    config, plan_path = _composite_fixture(
        make_workspace, [{"stage": "STRUCTURAL_ADJUDICATION", "state": NOT_ASSESSED, "refs": ["MAT 1:2"]}]
    )
    calls: list[dict] = []
    pending = plan_path.parent.parent / "tasks" / "meaning" / "task-manifest.json"
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(json.dumps({"task_id": "T-MEANING", "scope": "MAT 1:1-2"}) + "\n", encoding="utf-8")

    def fake_create(_config, **kwargs):
        """Record the requested stage and return the pending meaning-stage task."""
        calls.append(kwargs)
        return {"status": "CREATED", "manifest_path": str(pending)}

    monkeypatch.setattr(act_tasks, "create_act_task", fake_create)
    result = continue_analysis_plan(config, plan_path)

    assert result["status"] == "NEXT_WORK_UNIT"
    assert result["composite_stage"] == "REFERENCE_TEXT_COMPARISON"
    assert calls[0]["rtc_stage"] == "REFERENCE_TEXT_COMPARISON"
    assert calls[0]["rtc_predecessor_files"] == []


def test_composite_rtc_reports_not_assessed_ol_stage_references(make_workspace) -> None:
    """A lost OL adjudication keeps its deferred verse NOT_ASSESSED instead of COMPLETE coverage."""
    meaning = {
        "schema_version": "2.0",
        "operation": "rtc",
        "coverage": {"status": "COMPLETE", "reviewed_references": ["MAT 1:1", "MAT 1:2"]},
        "findings": [],
        "ol_review_requests": [{"request_id": "OLR-001", "deferred_finding_id": "F001", "target_reference": "MAT 1:2"}],
    }
    config, plan_path = _composite_fixture(
        make_workspace,
        [
            {"stage": "REFERENCE_TEXT_COMPARISON", "state": "FINALIZED", "result": meaning},
            {"stage": "SELECTIVE_OL_ADJUDICATION", "state": NOT_ASSESSED},
        ],
    )

    result = continue_analysis_plan(config, plan_path)

    final = json.loads(Path(result["aggregate_path"]).read_text(encoding="utf-8"))
    assert final["coverage"]["status"] == "PARTIAL"
    assert final["coverage"]["reviewed_references"] == ["MAT 1:1"]
    assert final["coverage"]["not_assessed_references"] == ["MAT 1:2"]
    assert final["exceptions"][0]["coordinates"] == ["MAT 1:2"]
    assert "Exceptions — not assessed" in Path(result["report_path"]).read_text(encoding="utf-8")


def test_action_report_renders_ol_resolutions_without_findings() -> None:
    """NO_FINDING and INSUFFICIENT_EVIDENCE adjudications are visible with their decision and rationale."""
    from sage.act_outputs import render_action_report

    report = render_action_report(
        {
            "operation": "rtc",
            "workflow": "rtc",
            "scope": "MAT 1:2",
            "coverage": {"status": "COMPLETE", "reviewed_references": ["MAT 1:2"]},
            "findings": [],
            "ol_resolutions": [
                {
                    "request_id": "OLR-001",
                    "target_reference": "MAT 1:2",
                    "outcome": "NO_FINDING",
                    "decision": "BOTH_DEFENSIBLE",
                    "finding_id": None,
                    "rationale": "Both renderings follow the Greek aorist.",
                }
            ],
        }
    )
    assert "## Original-language adjudications" in report
    assert "Outcome: `NO_FINDING`; Decision: `BOTH_DEFENSIBLE`" in report
    assert "Both renderings follow the Greek aorist." in report


def test_composite_rtc_reports_prohibited_ol_requests_instead_of_stalling(make_workspace) -> None:
    """A sealed meaning stage with OL requests under a PROHIBITED policy finishes with a record."""
    meaning = {
        "schema_version": "2.0",
        "operation": "rtc",
        "coverage": {"status": "COMPLETE", "reviewed_references": ["MAT 1:1", "MAT 1:2"]},
        "findings": [],
        "ol_review_requests": [{"request_id": "OLR-001", "deferred_finding_id": "F001", "target_reference": "MAT 1:2"}],
    }
    config, plan_path = _composite_fixture(
        make_workspace, [{"stage": "REFERENCE_TEXT_COMPARISON", "state": "FINALIZED", "result": meaning}]
    )

    result = continue_analysis_plan(config, plan_path)

    assert result["status"] == "COMPLETE"
    records = exceptions_for_run(plan_path.parent.parent)
    assert [(row["code"], row["effect"], row["coordinates"]) for row in records] == [
        ("SAW_OL_REQUEST_PROHIBITED", "FLAGGED", ["MAT 1:2"])
    ]


def test_run_with_not_assessed_units_closes_with_its_own_status(make_workspace) -> None:
    """A Run that lost units closes COMPLETE_WITH_EXCEPTIONS, still DONE, never plain COMPLETE."""
    root = make_workspace()
    center = _center(root)
    job = next(item for item in center.store.bootstrap_default_jobs() if item.tool == "saw")
    run = center.store.create_run(job, operation="stc", scope="MAT 1:1-2")
    assert center._saw_completion_status(run) == "COMPLETE"
    record_exception(
        run.root,
        ExceptionRecord(tool="stc", code="X", message="m", effect=NOT_ASSESSED, coordinates=("MAT 1:2",)),
    )

    status = center._saw_completion_status(run)
    closed = center.store.update_run(run, status=status, current_stage=status)

    assert status == "COMPLETE_WITH_EXCEPTIONS"
    assert closed.result == "DONE"


def test_provider_configuration_and_controller_failures_stop_the_run() -> None:
    """A logged-out provider or a controller crash must not be retried into NOT_ASSESSED units."""
    for code in (
        "CODEX_EXECUTION_NOT_READY",
        "MENU_CONTROLLER_COMMAND_FAILED",
        "CONFIGURATION_ERROR",
        "PROVIDER_ROUTE_UNAVAILABLE",
        "LLM_RESPONSE_ROUTE_MISMATCH",
        "RTC_TASK_CONTRACT_INVALID",
        "STC_TASK_CONTRACT_INVALID",
        "STC_OL_AUTHORITY_MISMATCH",
        "TASK_SUBMISSION_TAMPERED",
        "EXECUTION_RECEIPT_MISSING",
    ):
        assert unit_failure_action(code, "ERROR", 1) == "STOP", code


def test_circuit_breaker_stops_a_recurring_non_content_failure() -> None:
    """The same non-content code sealing units again and again is systemic; content rejections are not."""
    assert unit_failure_action("SAGE_ERROR", "ERROR", 1, prior_not_assessed_codes=["SAGE_ERROR"]) == "RETRY"
    assert (
        unit_failure_action("SAGE_ERROR", "ERROR", 1, prior_not_assessed_codes=["SAGE_ERROR", "SAGE_ERROR"])
        == "STOP"
    )
    assert (
        unit_failure_action(
            "RTC_OUTPUT_INVALID",
            "TASK_OUTPUT_REJECTED",
            1,
            prior_not_assessed_codes=["RTC_OUTPUT_INVALID"] * 5,
        )
        == "RETRY"
    )


def test_single_task_run_applies_the_unit_failure_policy(make_workspace, monkeypatch) -> None:
    """A one-unit Run retries, seals the unit NOT_ASSESSED, and closes instead of stalling."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1:1")
    manifest = run.root / "tasks" / "unit-1" / "task-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"task_id": "T-SINGLE", "scope": "MAT 1:1", "expected_references": ["MAT 1:1"]}) + "\n",
        encoding="utf-8",
    )
    run = store.update_run(run, task_manifests=[str(manifest)])
    center = _center(root)
    attempts: list[int] = []

    def failing_action(_job, current, _path):
        """Fail every attempt with a rejected-output event."""
        attempts.append(1)
        center._last_execution_event = {
            "reason_code": "RTC_OUTPUT_INVALID",
            "disposition": "TASK_OUTPUT_REJECTED",
            "message": "The provider output was rejected.",
            "report_path": "",
        }
        return current, False

    monkeypatch.setattr(center, "_task_action", failing_action)
    finished = center._continue_saw(job, run)

    assert len(attempts) == MAX_UNIT_ATTEMPTS
    assert json.loads((manifest.parent / "validation" / "submission.json").read_text(encoding="utf-8"))["status"] == NOT_ASSESSED
    assert finished.status == "COMPLETE_WITH_EXCEPTIONS"


def test_job_defaults_cannot_change_while_a_run_is_open(make_workspace) -> None:
    """Changing defaults rewrites sealed runtime settings, so it waits until the open Run closes."""
    from sage.errors import ValidationError

    root = make_workspace()
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    with pytest.raises(ValidationError) as caught:
        store.revise_job(job, defaults={"rtc_policy": {}})
    assert caught.value.code == "JOB_DEFAULTS_RUN_OPEN"
    store.update_run(run, status="ABANDONED", current_stage="ABANDONED")
    assert store.revise_job(store.load_job(job.job_id), defaults={"note": "x"}).defaults == {"note": "x"}


def test_rtc_task_without_a_job_is_refused(make_workspace) -> None:
    """The CLI shortcut no longer mints an orphan Job for a canonical RTC task."""
    from sage.act_tasks import create_act_task
    from sage.errors import ValidationError

    root = make_workspace()
    with pytest.raises(ValidationError) as caught:
        create_act_task(
            load_ecosystem(root / "ecosystem.yml"),
            workflow="rtc",
            operation="rtc",
            output_project_id="usWIP",
            contemporary_source_id="usNIVv2",
            scope_value="MAT 1:1",
        )
    assert caught.value.code == "RTC_JOB_REQUIRED"


def test_composite_rtc_final_result_includes_deterministic_structural_findings(make_workspace) -> None:
    """Findings decided in code at composite creation are merged with run-global identity."""
    meaning = {
        "schema_version": "2.0",
        "operation": "rtc",
        "coverage": {"status": "COMPLETE", "reviewed_references": ["MAT 1:1", "MAT 1:2"]},
        "findings": [],
    }
    config, plan_path = _composite_fixture(
        make_workspace, [{"stage": "REFERENCE_TEXT_COMPARISON", "state": "FINALIZED", "result": meaning}]
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["deterministic_findings"] = [
        {
            "finding_id": "D-VRS-1",
            "target_reference": "MAT 1:2",
            "category": "STRUCTURE",
            "issue": "usWIP MAT 1:2 maps to MAT 1:2, which has text in usWIP but none in usREF.",
            "required_action": "Check whether text is missing from usREF at this coordinate.",
            "action_level": "REVIEW",
            "confidence": "HIGH",
            "evidence_ids": ["WIP", "REFERENCE"],
            "grammar_rule_ids": [],
            "original_language_evidence": "",
        }
    ]
    plan_path.write_text(json.dumps(plan) + "\n", encoding="utf-8")

    result = continue_analysis_plan(config, plan_path)

    final = json.loads(Path(result["aggregate_path"]).read_text(encoding="utf-8"))
    [finding] = final["findings"]
    assert finding["category"] == "STRUCTURE"
    assert finding["submitted_id"] == "D-VRS-1"
    assert finding["finding_id"] != "D-VRS-1"


def test_menu_runs_plan_continuation_in_process(make_workspace, monkeypatch) -> None:
    """Continue, submit, and aggregate no longer spawn a CLI subprocess per call."""
    import subprocess

    meaning = {
        "schema_version": "2.0",
        "operation": "rtc",
        "coverage": {"status": "COMPLETE", "reviewed_references": ["MAT 1:1", "MAT 1:2"]},
        "findings": [],
    }
    config, plan_path = _composite_fixture(
        make_workspace, [{"stage": "REFERENCE_TEXT_COMPARISON", "state": "FINALIZED", "result": meaning}]
    )
    center = _center(config.root)
    job = center.store.load_job(json.loads(plan_path.read_text(encoding="utf-8"))["job_id"])

    def no_subprocess(*_args, **_kwargs):
        """Fail if the controller tries to start a process."""
        raise AssertionError("controller spawned a subprocess")

    monkeypatch.setattr(subprocess, "Popen", no_subprocess)
    result = center.controller(job, ["task", "continue", "--plan", str(plan_path)])

    assert result["status"] == "COMPLETE"
    assert isinstance(result["aggregate_path"], str)


def test_cli_task_failure_applies_the_shared_unit_policy(make_workspace, monkeypatch) -> None:
    """A CLI-run RTC task failure is counted and sealed the same way the menu does it."""
    from sage.cli import _cli_unit_failure
    from sage.errors import ValidationError

    root = make_workspace()
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1:1")
    config = load_ecosystem(store.ensure_runtime_files(job))
    manifest = run.root / "tasks" / "unit" / "task-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "task_id": "T-CLI",
                "workflow": "saw",
                "operation": "rtc",
                "job_id": job.job_id,
                "run_id": run.run_id,
                "expected_references": ["MAT 1:1"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SAGE_MENU_DRIVER", raising=False)
    for _ in range(MAX_UNIT_ATTEMPTS):
        _cli_unit_failure(config, manifest, ValidationError("bad output", code="RTC_OUTPUT_INVALID"))

    assert [row["effect"] for row in exceptions_for_run(run.root)] == ["RETRY", "RETRY", NOT_ASSESSED]
    assert load_not_assessed_result(manifest)["exception"]["coordinates"] == ["MAT 1:1"]
    monkeypatch.setenv("SAGE_MENU_DRIVER", "1")
    _cli_unit_failure(config, manifest, ValidationError("bad output", code="RTC_OUTPUT_INVALID"))
    assert len(exceptions_for_run(run.root)) == 3


def test_a_run_driven_by_one_session_is_locked_for_another(make_workspace) -> None:
    """The Run driver lock refuses a second live owner."""
    from sage.errors import LockError
    from sage.locking import WorkspaceLock

    root = make_workspace()
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    run = store.create_run(job, operation="rtc", scope="MAT 1")
    path = run.root / "locks" / "run-driver"
    with WorkspaceLock(path, "first", break_stale=True):
        with pytest.raises(LockError):
            WorkspaceLock(path, "second", break_stale=True).acquire()
