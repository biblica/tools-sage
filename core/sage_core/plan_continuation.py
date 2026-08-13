"""Sequential SAW partition-plan continuation helper."""

from __future__ import annotations

import json
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json, atomic_write_text
from .act_outputs import render_action_report, render_operator_note_text
from .errors import ValidationError
from .hashing import sha256_file
from .registry import EcosystemConfig, load_ecosystem
from .runtime_paths import plan_is_governed, task_is_governed
from .jobs import JobStore


def _report_scope_slug(scope: str) -> str:
    """Render a scope as uppercase text with three-digit numeric components."""
    parts = re.findall(r"[A-Za-z]+|\d+", str(scope))
    rendered = [f"{int(part):03d}" if part.isdigit() else part.upper() for part in parts]
    return "-".join(rendered) or "SCOPE"


def _report_book_code(scope: str) -> str:
    """Return the canonical uppercase book component used as a report subdirectory."""
    match = re.search(r"[A-Za-z]+", str(scope))
    return match.group(0).upper() if match else "GENERAL"


def _job_reports_root(plan_path: Path) -> Path:
    """Resolve the owning Job's shared reports directory from a Run plan path."""
    run_root = plan_path.parent.parent
    if plan_path.parent.name != "plans" or run_root.parent.name != "runs":
        raise ValidationError("SAW report plan is not inside a canonical Job Run")
    return run_root.parent.parent / "reports"


def _report_paths_owned_by_other_plans(plan_path: Path) -> set[Path]:
    """Return report paths referenced by other finalised plans in the same Job."""
    job_root = _job_reports_root(plan_path).parent
    owned: set[Path] = set()
    for candidate in (job_root / "runs").glob("*/plans/*.json"):
        if candidate.resolve() == plan_path.resolve():
            continue
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or value.get("status") != "FINALIZED":
            continue
        for key in ("report_path", "operator_note_text_path"):
            raw = str(value.get(key) or "").strip()
            if raw:
                owned.add(Path(raw).expanduser().resolve())
    return owned


def _report_bundle_paths(plan_path: Path, scope: str) -> tuple[Path, Path]:
    """Allocate one scope/date/serial basename in the Job's book report directory."""
    reports_root = _job_reports_root(plan_path) / _report_book_code(scope)
    reports_root.mkdir(parents=True, exist_ok=True)
    scope_slug = _report_scope_slug(scope)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pattern = re.compile(rf"^{re.escape(scope_slug)}_{re.escape(date)}_(\d+)_")
    serials = [
        int(match.group(1))
        for item in reports_root.iterdir()
        if item.is_file() and (match := pattern.match(item.name)) is not None
    ]
    base = f"{scope_slug}_{date}_{max(serials, default=0) + 1:03d}"
    return (
        reports_root / f"{base}_ACTION-REPORT.md",
        reports_root / f"{base}_OPERATOR-NOTE.txt",
    )


def _ensure_finalized_report_layout(path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Migrate legacy human reports into the Job's shared reports directory."""
    job_reports_root = _job_reports_root(path)
    requested_scope = str(plan.get("requested_scope") or "SCOPE")
    reports_root = job_reports_root / _report_book_code(requested_scope)
    legacy_run_reports = path.parent.parent / "reports"
    scope_slug = _report_scope_slug(requested_scope)
    other_owned_paths = _report_paths_owned_by_other_plans(path)
    report_path = Path(str(plan.get("report_path") or "")).expanduser()
    note_path = Path(str(plan.get("operator_note_text_path") or "")).expanduser()
    aggregate_path = Path(str(plan.get("aggregate_path") or "")).expanduser()
    if not aggregate_path.is_file():
        raise ValidationError("Finalised composite QA plan is missing its aggregate result")
    document = _load_object(aggregate_path, "composite QA aggregate")
    declared_layout_is_canonical = (
        report_path.parent.resolve() == reports_root.resolve()
        and note_path.parent.resolve() == reports_root.resolve()
        and report_path.name.startswith(f"{scope_slug}_")
        and note_path.name.startswith(f"{scope_slug}_")
        and report_path.resolve() not in other_owned_paths
        and note_path.resolve() not in other_owned_paths
    )
    if declared_layout_is_canonical:
        expected_report = render_action_report(document)
        expected_note = render_operator_note_text(document)
        if not report_path.is_file() or report_path.read_text(encoding="utf-8") != expected_report:
            atomic_write_text(report_path, expected_report)
        if not note_path.is_file() or note_path.read_text(encoding="utf-8") != expected_note:
            atomic_write_text(note_path, expected_note)
        return plan
    migrated_report, migrated_note = _report_bundle_paths(
        path,
        str(plan.get("requested_scope") or document.get("scope") or "SCOPE"),
    )
    atomic_write_text(migrated_report, render_action_report(document))
    atomic_write_text(migrated_note, render_operator_note_text(document))
    generated = {migrated_report.resolve(), migrated_note.resolve()}
    governed_report_roots = {
        path.parent.resolve(),
        legacy_run_reports.resolve(),
        job_reports_root.resolve(),
        reports_root.resolve(),
    }
    for legacy in (report_path, note_path):
        if (
            legacy.is_file()
            and legacy.resolve() not in generated
            and legacy.resolve() not in other_owned_paths
            and legacy.parent.resolve() in governed_report_roots
        ):
            legacy.unlink()
    plan["report_path"] = str(migrated_report)
    plan["operator_note_text_path"] = str(migrated_note)
    atomic_write_json(path, plan)
    return plan


def _load_object(path: Path, label: str) -> dict[str, Any]:
    """Load one JSON object with a bounded error surface."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must contain one JSON object")
    return dict(value)


def _continue_partitioned_plan(config: EcosystemConfig, plan_path: Path) -> dict[str, Any]:
    """Return the one next sequential SAW work unit, or the exact aggregation action."""
    path = plan_path.expanduser().resolve()
    if not plan_is_governed(config.workflow("saw"), path):
        raise ValidationError("SAW continuation plan must be inside the governed plans directory")
    plan = _load_object(path, "SAW continuation plan")
    if plan.get("workflow") != "saw":
        raise ValidationError("Only SAW plans can use the sequential continuation helper")
    if plan.get("status") == "FINALIZED":
        return {
            "schema_version": "1.0",
            "status": "COMPLETE",
            "plan_id": plan.get("plan_id"),
            "plan_path": str(path),
            "aggregate_path": plan.get("aggregate_path"),
        }
    if plan.get("status") != "PARTITIONED":
        raise ValidationError("Only PARTITIONED or FINALIZED SAW plans can be continued")
    units = plan.get("work_units")
    if not isinstance(units, list) or not units or any(not isinstance(unit, dict) for unit in units):
        raise ValidationError("SAW plan work_units must be a nonempty list of objects")

    states: list[dict[str, Any]] = []
    first_unfinished: int | None = None
    finalized_after_gap: list[str] = []
    for index, unit in enumerate(units):
        manifest_path = Path(str(unit.get("manifest_path", ""))).expanduser()
        if not manifest_path.is_absolute():
            manifest_path = config.root / manifest_path
        manifest_path = manifest_path.resolve()
        if not task_is_governed(config.workflow("saw"), manifest_path.parent):
            raise ValidationError("SAW work-unit manifest escapes the governed task root")
        submission_path = manifest_path.parent / "validation" / "submission.json"
        status = "CREATED"
        submission_sha256 = None
        if submission_path.is_file():
            submission = _load_object(submission_path, f"submission for {unit.get('unit_id')}")
            status = str(submission.get("status", "UNKNOWN"))
            submission_sha256 = sha256_file(submission_path)
        finalized = status == "FINALIZED"
        if not finalized and first_unfinished is None:
            first_unfinished = index
        elif finalized and first_unfinished is not None:
            finalized_after_gap.append(str(unit.get("unit_id")))
        states.append(
            {
                "index": index + 1,
                "unit_id": unit.get("unit_id"),
                "task_id": unit.get("task_id"),
                "scope": unit.get("scope"),
                "status": status,
                "manifest_path": str(manifest_path),
                "submission_sha256": submission_sha256,
            }
        )
    if finalized_after_gap:
        raise ValidationError(
            "SAW plan contains finalised work units after an unfinished predecessor",
            code="SAW_SEQUENTIAL_ORDER_VIOLATION",
            next_action="Resolve the earliest unfinished unit before continuing later units.",
            details={"out_of_order_units": finalized_after_gap},
        )
    if first_unfinished is None:
        return {
            "schema_version": "1.0",
            "status": "READY_TO_AGGREGATE",
            "plan_id": plan.get("plan_id"),
            "plan_path": str(path),
            "completed_units": len(states),
            "total_units": len(states),
            "aggregate_command": f"./sage task aggregate --plan {shlex.quote(str(path))}",
            "work_units": states,
        }
    next_unit = states[first_unfinished]
    return {
        "schema_version": "1.0",
        "status": "NEXT_WORK_UNIT",
        "plan_id": plan.get("plan_id"),
        "plan_path": str(path),
        "completed_units": first_unfinished,
        "total_units": len(states),
        "next_unit": next_unit,
        "act_path": str(Path(next_unit["manifest_path"]).parent / "ACT.md"),
        "submit_command": (
            "./sage task submit --task " + shlex.quote(str(next_unit["manifest_path"]))
        ),
        "work_units": states,
    }


def _composite_stage_result(config: EcosystemConfig, stage: dict[str, Any]) -> tuple[str, str | None, dict[str, Any] | None]:
    """Return state, result path, and continuation details for one composite QA stage."""
    if stage.get("kind") == "TASK":
        manifest = Path(str(stage.get("manifest_path", ""))).expanduser()
        if not manifest.is_absolute():
            manifest = (config.root / manifest).resolve()
        else:
            manifest = manifest.resolve()
        submission = manifest.parent / "validation" / "submission.json"
        normalized = manifest.parent / "validation" / "normalized-findings.json"
        if not submission.is_file():
            return "PENDING", None, {
                "schema_version": "1.0",
                "status": "NEXT_WORK_UNIT",
                "next_unit": {
                    "unit_id": stage.get("stage"),
                    "scope": None,
                    "manifest_path": str(manifest),
                },
                "act_path": str(manifest.parent / "ACT.md"),
                "submit_command": "./sage task submit --task " + shlex.quote(str(manifest)),
            }
        receipt = _load_object(submission, f"submission for {stage.get('stage')}")
        if receipt.get("status") != "FINALIZED" or not normalized.is_file():
            raise ValidationError(f"Composite QA stage {stage.get('stage')} is not FINALIZED")
        return "FINALIZED", str(normalized), None
    if stage.get("kind") == "PARTITIONED_PLAN":
        child = Path(str(stage.get("plan_path", ""))).expanduser()
        if not child.is_absolute():
            child = (config.root / child).resolve()
        else:
            child = child.resolve()
        child_plan = _load_object(child, f"partition plan for {stage.get('stage')}")
        if child_plan.get("status") == "FINALIZED":
            aggregate = child_plan.get("aggregate_path")
            if not aggregate:
                raise ValidationError("Finalised partition plan is missing aggregate_path")
            return "FINALIZED", str(aggregate), None
        continuation = _continue_partitioned_plan(config, child)
        if continuation.get("status") == "READY_TO_AGGREGATE":
            continuation["aggregate_plan_path"] = str(child)
        return "PENDING", None, continuation
    raise ValidationError(f"Unsupported composite QA stage kind: {stage.get('kind')}")


def _finalize_composite_qa(config: EcosystemConfig, path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Merge completed Normal-QA stages and render deterministic Operator-facing outputs."""
    findings: list[dict[str, Any]] = []
    adjudications: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    seen_findings: set[str] = set()
    coverage_refs: list[str] = []
    stage_results: list[dict[str, Any]] = []
    ol_review_requests: list[dict[str, Any]] = []
    ol_resolutions: list[dict[str, Any]] = []
    for stage in plan.get("stages", []):
        state, result_path, _ = _composite_stage_result(config, stage)
        if state != "FINALIZED" or not result_path:
            raise ValidationError("Cannot finalize composite QA before every created stage is FINALIZED")
        result = _load_object(Path(result_path), f"composite result for {stage.get('stage')}")
        stage_results.append({"stage": stage.get("stage"), "result_path": result_path})
        refs = list((result.get("coverage") or {}).get("reviewed_references", []))
        if stage.get("stage") == "TRANSLATION_AND_MEANING_QA":
            coverage_refs = refs
        receipts.extend(result.get("review_receipts", []))
        adjudications.extend(result.get("structural_adjudications", []))
        ol_review_requests.extend(result.get("ol_review_requests", []))
        ol_resolutions.extend(result.get("ol_resolutions", []))
        for finding in result.get("findings", []):
            finding_id = str(finding.get("finding_id", ""))
            if finding_id in seen_findings:
                raise ValidationError(f"Duplicate finding_id across composite QA stages: {finding_id}")
            seen_findings.add(finding_id)
            findings.append(dict(finding))
    if not coverage_refs:
        raise ValidationError("Composite QA finalisation is missing meaning-stage coordinate coverage")
    document = {
        "schema_version": "2.0",
        "task_id": plan["plan_id"],
        "operation": "qa",
        "stage": "COMPOSITE_FINALIZED",
        "scope": plan["requested_scope"],
        "focus": None,
        "check_type": None,
        "answer": "",
        "coverage": {"status": "COMPLETE", "reviewed_references": coverage_refs},
        "review_receipts": receipts,
        "structural_adjudications": adjudications,
        "ol_review_requests": ol_review_requests,
        "ol_resolutions": ol_resolutions,
        "resolved_ol_request_ids": [str(row.get("request_id", "")) for row in ol_resolutions],
        "findings": findings,
        "finding_count": len(findings),
    }
    final_path = path.with_name(f"{plan['plan_id']}-final.json")
    report_path, note_path = _report_bundle_paths(path, str(plan["requested_scope"]))
    atomic_write_json(final_path, document)
    atomic_write_text(report_path, render_action_report(document))
    atomic_write_text(note_path, render_operator_note_text(document))
    plan["status"] = "FINALIZED"
    plan["aggregate_path"] = str(final_path)
    plan["report_path"] = str(report_path)
    plan["operator_note_text_path"] = str(note_path)
    plan["stage_results"] = stage_results
    atomic_write_json(path, plan)
    return {
        "schema_version": "1.0",
        "status": "COMPLETE",
        "plan_id": plan["plan_id"],
        "plan_path": str(path),
        "aggregate_path": str(final_path),
        "report_path": str(report_path),
        "operator_note_text_path": str(note_path),
        "finding_count": len(findings),
    }


def _continue_saw_qa_composite(config: EcosystemConfig, path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Advance one composite Normal-QA plan by exactly one governed stage/action."""
    stages = plan.get("stages")
    if not isinstance(stages, list) or not stages or any(not isinstance(item, dict) for item in stages):
        raise ValidationError("Composite SAW QA plan has no valid stage inventory")
    current = stages[-1]
    state, result_path, continuation = _composite_stage_result(config, current)
    if state != "FINALIZED":
        assert continuation is not None
        return {**continuation, "plan_id": plan.get("plan_id"), "plan_path": str(path), "composite_stage": current.get("stage")}

    stage_name = str(current.get("stage"))
    expected_requests: list[dict[str, Any]] = []
    stage_references: list[str] = []
    if stage_name == "STRUCTURAL_ADJUDICATION":
        next_stage = "TRANSLATION_AND_MEANING_QA"
        expected_ids: list[str] = []
        predecessor_files = [str(result_path)]
    elif stage_name == "TRANSLATION_AND_MEANING_QA":
        meaning = _load_object(Path(str(result_path)), "SAW QA meaning-stage result")
        requests = list(meaning.get("ol_review_requests", []))
        if not requests:
            return _finalize_composite_qa(config, path, plan)
        next_stage = "SELECTIVE_OL_ADJUDICATION"
        expected_requests = [dict(item) for item in requests]
        expected_ids = [str(item.get("request_id", "")).upper() for item in requests]
        stage_references = [str(item.get("target_reference", "")).strip() for item in requests]
        predecessor_files = [
            str(value)
            for value in [
                *[
                    _composite_stage_result(config, row)[1]
                    for row in stages
                    if row.get("stage") == "STRUCTURAL_ADJUDICATION"
                ],
                result_path,
            ]
            if value
        ]
    elif stage_name == "SELECTIVE_OL_ADJUDICATION":
        return _finalize_composite_qa(config, path, plan)
    else:
        raise ValidationError(f"Unsupported composite QA stage: {stage_name}")

    from .act_tasks import _stage_record, create_act_task
    result = create_act_task(
        config,
        workflow="saw",
        operation="qa",
        output_project_id=str(plan["output_project"]),
        contemporary_source_id=str(plan["contemporary_source"]),
        scope_value=str(plan["requested_scope"]),
        grammar_override_id=plan.get("grammar_override_id"),
        auto_partition=True,
        parent_plan_id=str(plan["plan_id"]),
        job_id=str(plan.get("job_id") or plan["job_id"]),
        run_id=str(plan.get("run_id") or plan["run_id"]),
        qa_stage=next_stage,
        qa_predecessor_files=predecessor_files,
        expected_ol_request_ids=expected_ids,
        expected_ol_requests=expected_requests,
        qa_stage_references=stage_references,
    )
    new_stage = _stage_record(result, next_stage)
    stages.append(new_stage)
    plan["stages"] = stages
    plan["updated_utc"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).replace(microsecond=0).isoformat()
    atomic_write_json(path, plan)
    new_state, _, new_continuation = _composite_stage_result(config, new_stage)
    if new_state == "FINALIZED":
        raise ValidationError("New composite QA stage unexpectedly finalised before execution")
    assert new_continuation is not None
    return {**new_continuation, "plan_id": plan.get("plan_id"), "plan_path": str(path), "composite_stage": next_stage}


def continue_saw_plan(config: EcosystemConfig, plan_path: Path) -> dict[str, Any]:
    """Continue either a partitioned SAW plan or the staged composite Normal-QA plan."""
    path = plan_path.expanduser().resolve()
    plan = _load_object(path, "SAW continuation plan")
    job_id = str(plan.get("job_id", "")).strip()
    if not job_id:
        raise ValidationError("SAW continuation plan is missing canonical Job identity")
    store = JobStore(config.root, config.settings_path)
    job = store.load_job(job_id, tool="saw")
    config = load_ecosystem(store.ensure_runtime_files(job))
    if not plan_is_governed(config.workflow("saw"), path):
        raise ValidationError("SAW continuation plan must be inside the governed plans directory")
    if plan.get("plan_type") == "SAW_QA_COMPOSITE":
        if plan.get("status") == "FINALIZED":
            plan = _ensure_finalized_report_layout(path, plan)
            return {
                "schema_version": "1.0",
                "status": "COMPLETE",
                "plan_id": plan.get("plan_id"),
                "plan_path": str(path),
                "aggregate_path": plan.get("aggregate_path"),
                "report_path": plan.get("report_path"),
                "operator_note_text_path": plan.get("operator_note_text_path"),
            }
        return _continue_saw_qa_composite(config, path, plan)
    return _continue_partitioned_plan(config, path)
