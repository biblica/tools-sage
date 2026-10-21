"""ACT plan aggregation: partitioned RTC and STC work units merged into one governed result and report.

Split from act_tasks.py, which re-exports every name defined here.
"""

from __future__ import annotations

from .act_outputs import aggregate_execution_routes
from .act_outputs import render_execution_section
from .atomic import atomic_write_json
from .atomic import atomic_write_text
from .config import load_json
from .errors import ValidationError
from .exception_reports import NOT_ASSESSED, ExceptionRecord
from .exception_reports import coverage_document
from .exception_reports import load_not_assessed_result
from .exception_reports import render_exceptions_section
from .findings import dedupe_findings
from .findings import globalize_result_finding_ids
from .findings import validate_global_finding_ids
from .hashing import sha256_file
from .human_output import render_report_language_authority
from .human_output import report_language_authority
from .references import atomic_reference_labels
from .references import expand_reference_atoms
from .registry import EcosystemConfig
from .runtime_paths import plan_is_governed
from .source_coverage import source_comparison_status
from .source_coverage import unique_source_text_issues
from .state import utc_now
from .stc import LEGACY_STC_PLANNER_VERSION
from .stc import STC_PLANNER_VERSION
from .stc import finalize_stc_run
from .stc import stc_gap_findings
from .stc_reporting import publish_stc_reports
from .storage import resolve_persisted_path
from .workflow_identity import is_analysis_workflow
from pathlib import Path
from typing import Any
from typing import Mapping
from typing import Sequence
import json
from .act_common import (
    _analysis_code,
    _narrative_language_contract,
)



def _coverage_reconciliation_details(
    expected: Sequence[str],
    observed: Sequence[str],
    *,
    reason: str,
    unit_id: str | None = None,
) -> dict[str, Any]:
    """Return bounded exact-coverage diagnostics for one failed reconciliation."""
    expected_set = set(expected)
    observed_set = set(observed)
    details: dict[str, Any] = {
        "reason": reason,
        "missing_coordinates": sorted(expected_set - observed_set),
        "extra_coordinates": sorted(observed_set - expected_set),
        "duplicate_expected_coordinates": sorted({
            value for value in expected if expected.count(value) > 1
        }),
        "duplicate_observed_coordinates": sorted({
            value for value in observed if observed.count(value) > 1
        }),
        "expected_coordinate_count": len(expected),
        "observed_coordinate_count": len(observed),
    }
    if unit_id:
        details["unit_id"] = unit_id
    return details


def _aggregate_stc_plan(config: EcosystemConfig, path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Aggregate one partitioned STC plan against immutable WIP+PRIMARY-OL lineage."""
    output_project = str(plan.get("output_project") or "").strip()
    ol_authority = str(plan.get("primary_ol_authority") or "").strip()
    family = str(plan.get("authority_family") or "").strip().upper()
    if not output_project or not ol_authority or family not in {"GRK", "HEB"}:
        raise ValidationError("STC aggregate plan lacks governed WIP/primary-OL identity", code="STC_WORK_UNIT_PLAN_INVALID")
    # Seal one planner lineage across every child before accepting terminal results.
    stc_planner_version = str(
        plan.get("stc_planner_version") or LEGACY_STC_PLANNER_VERSION
    )
    if stc_planner_version not in {
        STC_PLANNER_VERSION,
        LEGACY_STC_PLANNER_VERSION,
    }:
        raise ValidationError(
            f"Unsupported persisted STC planner version: {stc_planner_version}",
            code="STC_PLANNER_VERSION_UNSUPPORTED",
        )
    expected_lineage_keys = {f"project.{output_project}", f"project.{ol_authority}"}
    planned_units: list[dict[str, Any]] = []
    accepted_results: list[dict[str, Any]] = []
    exception_rows: list[dict[str, Any]] = []
    not_assessed_atoms: list[str] = []
    lineage: dict[str, str] | None = None
    seen_units: set[str] = set()
    seen_tasks: set[str] = set()
    for unit in plan.get("work_units", []):
        if not isinstance(unit, dict):
            raise ValidationError("STC aggregate plan contains an invalid work unit", code="STC_WORK_UNIT_PLAN_INVALID")
        unit_id = str(unit.get("unit_id") or "").strip()
        task_id = str(unit.get("task_id") or "").strip()
        if not unit_id or unit_id in seen_units or (task_id and task_id in seen_tasks):
            raise ValidationError("Duplicate or missing STC work-unit/result identity", code="DUPLICATE_WORK_UNIT_RESULT")
        seen_units.add(unit_id)
        if task_id:
            seen_tasks.add(task_id)
        manifest_path = resolve_persisted_path(config.root, str(unit.get("manifest_path") or ""), "STC work-unit manifest")
        manifest = load_json(manifest_path)
        manifest_planner_version = str(
            manifest.get("stc_planner_version") or LEGACY_STC_PLANNER_VERSION
        )
        if manifest_planner_version != stc_planner_version:
            raise ValidationError(
                "STC work-unit planner version differs from its immutable plan",
                code="RESULT_COVERAGE_DRIFT",
            )
        planned_fingerprint = str(unit.get("task_fingerprint") or "")
        if planned_fingerprint and str(manifest.get("task_fingerprint") or "") != planned_fingerprint:
            raise ValidationError("STC work-unit task fingerprint differs from immutable plan", code="RESULT_COVERAGE_DRIFT")
        validation_root = manifest_path.parent / "validation"
        submission_path = validation_root / "submission.json"
        normalized_path = validation_root / "normalized-findings.json"
        if submission_path.is_file() and load_json(submission_path).get("status") == NOT_ASSESSED:
            record = dict(load_not_assessed_result(manifest_path)["exception"])
            not_assessed_atoms.extend(
                str(value)
                for value in (
                    unit.get("primary_coverage_atoms") or manifest.get("expected_references") or record.get("coordinates", [])
                )
            )
            exception_rows.append(record)
            continue
        if not submission_path.is_file() or not normalized_path.is_file():
            raise ValidationError("Missing STC terminal work-unit result", code="MISSING_WORK_UNIT_RESULT")
        submission = load_json(submission_path)
        if str(submission.get("status") or "") != "FINALIZED":
            raise ValidationError("STC work unit is not FINALIZED", code="MISSING_WORK_UNIT_RESULT")
        normalized = load_json(normalized_path)
        if str(normalized.get("operation") or "") != "stc":
            raise ValidationError("STC aggregate received a non-STC terminal result", code="RESULT_COVERAGE_DRIFT")
        normalized_family = str(normalized.get("authority_family") or family).strip().upper()
        if normalized_family != family:
            raise ValidationError("STC work-unit authority family differs from its plan", code="RESULT_COVERAGE_DRIFT")
        normalized["authority_family"] = family
        normalized.setdefault("primary_ol_authority", ol_authority)
        if str(normalized.get("job_id") or "") != str(plan.get("job_id") or "") or str(normalized.get("run_id") or "") != str(plan.get("run_id") or ""):
            raise ValidationError("STC work-unit Job/Run identity differs from its plan", code="RESULT_COVERAGE_DRIFT")
        if str(normalized.get("output_project") or "") != output_project or str(normalized.get("primary_ol_authority") or "") != ol_authority:
            raise ValidationError("STC work-unit WIP/OL authority differs from its plan", code="RESULT_COVERAGE_DRIFT")
        fingerprints = normalized.get("resource_fingerprints")
        if not isinstance(fingerprints, dict):
            raise ValidationError("STC work unit lacks resource fingerprints", code="RESULT_COVERAGE_DRIFT")
        current_lineage = {key: str(fingerprints[key]) for key in expected_lineage_keys if key in fingerprints}
        if set(current_lineage) != expected_lineage_keys:
            raise ValidationError("STC work unit lacks WIP/PRIMARY-OL lineage fingerprints", code="RESULT_COVERAGE_DRIFT")
        if lineage is None:
            lineage = current_lineage
        elif current_lineage != lineage:
            raise ValidationError("STC work-unit resource lineage is inconsistent", code="RESULT_COVERAGE_DRIFT")
        planned_atoms = list(unit.get("primary_coverage_atoms") or manifest.get("expected_references") or [])
        planned_units.append({
            "work_unit_id": unit_id,
            "primary_coverage": planned_atoms,
            "scope": str(unit.get("scope") or normalized.get("scope") or ""),
            "authority_family": family,
            "authority_role": "PRIMARY",
        })
        accepted_results.append(normalized)
    for portion in plan.get("not_assessed_portions") or []:
        # Scope the WIP has no text for: planned out of the work units, reported as not assessed.
        if not isinstance(portion, dict) or not str(portion.get("scope") or "").strip():
            continue
        exception_rows.append(
            ExceptionRecord(
                tool="STC",
                code=str(portion.get("code") or "STC_WIP_PORTION_MISSING"),
                message=str(portion.get("message") or "The WIP has no text in this portion."),
                effect=NOT_ASSESSED,
                run_id=str(plan.get("run_id") or "") or None,
                job_id=str(plan.get("job_id") or "") or None,
                stage="STC",
                coordinates=(str(portion["scope"]).strip(),),
            ).to_dict()
        )
        not_assessed_atoms.append(str(portion["scope"]).strip())
    plan_gaps = [dict(row) for row in plan.get("coverage_gap_issues") or [] if isinstance(row, dict)]
    if plan_gaps and accepted_results:
        # Plan-level omissions (including whole missing chapters) belong to no single unit; the first
        # accepted result carries them so finalization and reports include them once.
        carrier = accepted_results[0]
        carrier["source_text_issues"] = unique_source_text_issues(
            [*carrier.get("source_text_issues", []), *plan_gaps]
        )
        known = {str(row.get("finding_id")) for row in carrier.get("findings", [])}
        carrier["findings"] = [
            *carrier.get("findings", []),
            *(
                row
                for row in stc_gap_findings(
                    plan_gaps, work_unit_id=str(plan["plan_id"]), authority_family=family
                )
                if row["finding_id"] not in known
            ),
        ]
        carrier["finding_count"] = len(carrier["findings"])
    canonical_root = path.with_name(f"{plan['plan_id']}-stc")
    artifacts = (
        finalize_stc_run(
            run_id=str(plan.get("run_id") or plan.get("plan_id") or "STC-RUN"),
            planned_units=planned_units,
            accepted_results=accepted_results,
            output_root=canonical_root,
            exceptions=exception_rows,
        )
        if planned_units
        else {}
    )
    publication = publish_stc_reports(
        config,
        job_id=str(plan.get("job_id") or ""),
        run_id=str(plan.get("run_id") or ""),
        requested_scope=str(plan.get("requested_scope") or ""),
        results=accepted_results,
        exceptions=exception_rows,
        fallback_identity={
            "output_project": output_project,
            "primary_ol_authority": ol_authority,
            "authority_family": family,
        },
    )
    source_issue_rows = unique_source_text_issues(
        dict(row)
        for result in accepted_results
        for row in result.get("source_text_issues", [])
        if isinstance(row, Mapping)
    )
    result = {
        "schema_version": "1.0",
        "status": "FINALIZED",
        "workflow": str(plan.get("workflow") or "stc").lower(),
        "operation": "stc",
        "plan_id": plan["plan_id"],
        "job_id": plan.get("job_id"),
        "run_id": plan.get("run_id"),
        "requested_scope": plan.get("requested_scope"),
        "output_project": output_project,
        "primary_ol_authority": ol_authority,
        "authority_family": family,
        "stc_planner_version": stc_planner_version,
        "finding_count": sum(int(row.get("finding_count") or 0) for row in accepted_results),
        "source_comparison_status": source_comparison_status(source_issue_rows),
        "structural_issues": source_issue_rows,
        "source_text_issues": source_issue_rows,
        "work_unit_count": len(accepted_results),
        "coverage": coverage_document(
            [str(value) for row in planned_units for value in row["primary_coverage"]],
            not_assessed_atoms,
            findings_present=any(int(row.get("finding_count") or 0) for row in accepted_results),
        ),
        "exceptions": exception_rows,
        "resource_fingerprints": lineage or {},
        "execution_routes": aggregate_execution_routes(accepted_results),
        "canonical_artifacts": {key: str(value) for key, value in artifacts.items()},
        **publication,
        "finalized_utc": utc_now(),
    }
    aggregate_path = path.with_name(f"{plan['plan_id']}-aggregate.json")
    atomic_write_json(aggregate_path, result)
    plan["status"] = "FINALIZED"
    plan["aggregate_path"] = str(aggregate_path)
    plan["canonical_artifacts"] = result["canonical_artifacts"]
    plan.update(publication)
    atomic_write_json(path, plan)
    return {**result, "aggregate_path": str(aggregate_path)}


def aggregate_act_plan(config: EcosystemConfig, plan_path: Path) -> dict[str, Any]:
    """Aggregate validated analysis work units with exact plan-level coverage."""
    # Maintenance invariant: aggregate only same-Job/same-Run work with stable WIP/REFERENCE fingerprints.
    path = plan_path.expanduser().resolve()
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid ACT aggregate plan: {exc}") from exc
    workflow = str(plan.get("workflow") or "").strip().lower()
    if not is_analysis_workflow(workflow):
        raise ValidationError("Only RTC/STC or sealed legacy SAW plans can be aggregated")
    if not plan_is_governed(config.workflow(workflow), path):
        raise ValidationError("Analysis aggregate plan must be inside its governed plans directory")
    if plan.get("status") != "PARTITIONED":
        raise ValidationError("Only PARTITIONED analysis plans can be aggregated")
    if str(plan.get("operation") or "").lower() == "stc":
        return _aggregate_stc_plan(config, path, plan)
    raw_expected = [str(value) for value in plan.get("expected_references", [])]
    try:
        expected = list(atomic_reference_labels(raw_expected))
    except ValidationError as exc:
        raise ValidationError(
            "Aggregate plan contains a non-canonical coverage inventory",
            code="AGGREGATE_COVERAGE_MISMATCH",
            details={"reason": "PLAN_COVERAGE_INVALID", "error": exc.message},
        ) from exc
    legacy_raw_spans = [
        value for value in raw_expected if len(expand_reference_atoms(value)) > 1
    ]
    observed: list[str] = []
    planned_by_unit: list[str] = []
    planned_ol_request_ids: list[str] = []
    receipts: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    adjudications: list[dict[str, Any]] = []
    ol_review_requests: list[dict[str, Any]] = []
    ol_resolutions: list[dict[str, Any]] = []
    resolved_ol_request_ids: list[str] = []
    source_issue_rows: list[dict[str, Any]] = []
    child_results: list[dict[str, Any]] = []
    not_assessed_atoms: list[str] = []
    unassessed_ol_request_ids: list[str] = []
    exception_rows: list[dict[str, Any]] = []
    lineage_fingerprints: dict[str, str] | None = None
    lineage_bindings: dict[str, Any] | None = None
    lineage_display_names: dict[str, str] | None = None
    seen_unit_ids: set[str] = set()
    seen_task_ids: set[str] = set()
    for unit in plan.get("work_units", []):
        unit_id = str(unit.get("unit_id") or "").strip()
        task_id = str(unit.get("task_id") or "").strip()
        if not unit_id or unit_id in seen_unit_ids or (task_id and task_id in seen_task_ids):
            raise ValidationError(
                "Aggregate plan contains a duplicate or missing work-unit/result identity",
                code="AGGREGATE_COVERAGE_MISMATCH",
                details={
                    "reason": "DUPLICATE_WORK_UNIT_RESULT",
                    "unit_id": unit_id,
                    "task_id": task_id,
                },
            )
        seen_unit_ids.add(unit_id)
        if task_id:
            seen_task_ids.add(task_id)
        manifest_path = resolve_persisted_path(
            config.root, str(unit.get("manifest_path", "")), "analysis work-unit manifest"
        )
        manifest = load_json(manifest_path)
        unit_ol_request_ids = unit.get("ol_request_ids")
        if not isinstance(unit_ol_request_ids, list):
            unit_ol_request_ids = list(
                dict(manifest.get("review_requirements") or {}).get(
                    "expected_ol_request_ids", []
                )
            )
        planned_ol_request_ids.extend(
            str(value).strip().upper()
            for value in unit_ol_request_ids
            if str(value).strip()
        )
        planned_fingerprint = str(unit.get("task_fingerprint") or "")
        if planned_fingerprint and str(manifest.get("task_fingerprint") or "") != planned_fingerprint:
            raise ValidationError(
                f"Work unit {unit_id} task fingerprint differs from its aggregate plan",
                code="AGGREGATE_COVERAGE_MISMATCH",
                details={"reason": "WORK_UNIT_PLAN_DRIFT", "unit_id": unit_id},
            )
        raw_unit_atoms = unit.get("primary_coverage_atoms")
        if not isinstance(raw_unit_atoms, list) or not raw_unit_atoms:
            raw_unit_atoms = manifest.get("expected_references", [])
        unit_atoms = (
            list(atomic_reference_labels(str(value) for value in raw_unit_atoms))
            if isinstance(raw_unit_atoms, list) and raw_unit_atoms
            else []
        )
        validation_root = manifest_path.parent / "validation"
        submission_path = validation_root / "submission.json"
        normalized_path = validation_root / "normalized-findings.json"
        if (
            submission_path.is_file()
            and json.loads(submission_path.read_text(encoding="utf-8")).get("status") == NOT_ASSESSED
        ):
            # A terminal exception result: report it, never claim coverage or findings for it.
            record = dict(load_not_assessed_result(manifest_path)["exception"])
            unit_atoms = unit_atoms or [str(value) for value in record.get("coordinates", [])]
            planned_by_unit.extend(unit_atoms)
            not_assessed_atoms.extend(unit_atoms)
            unassessed_ol_request_ids.extend(
                str(value).strip().upper() for value in unit_ol_request_ids if str(value).strip()
            )
            exception_rows.append(record)
            child_results.append({
                "unit_id": unit_id,
                "task_id": task_id,
                "scope": unit.get("scope"),
                "status": NOT_ASSESSED,
                "primary_coverage_atoms": unit_atoms,
                "review_portion_id": unit.get("review_portion_id"),
                "review_portion_index": unit.get("review_portion_index"),
                "review_portion_total": unit.get("review_portion_total"),
                "review_portion_scope": unit.get("review_portion_scope"),
                "parent_review_portion_id": unit.get("parent_review_portion_id"),
                "stage_case_index": unit.get("stage_case_index"),
                "stage_case_total": unit.get("stage_case_total"),
            })
            continue
        if not submission_path.is_file() or not normalized_path.is_file():
            raise ValidationError(
                f"Work unit {unit.get('unit_id')} is not `FINALIZED`",
                code="WORK_UNIT_NOT_FINALIZED",
                next_action="Submit every child ACT task before aggregation.",
            )
        submission = json.loads(submission_path.read_text(encoding="utf-8"))
        if submission.get("status") != "FINALIZED":
            raise ValidationError(f"Work unit {unit.get('unit_id')} is not FINALIZED")
        normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
        if str(normalized.get("job_id", "")) != str(plan.get("job_id", "")):
            raise ValidationError("Aggregated work unit belongs to a different Job")
        if str(normalized.get("run_id", "")) != str(plan.get("run_id", "")):
            raise ValidationError("Aggregated work unit belongs to a different Run")
        if str(normalized.get("output_project", "")) != str(plan.get("output_project", "")):
            raise ValidationError("Aggregated work unit WIP resource differs from its plan")
        if str(normalized.get("contemporary_source", "")) != str(plan.get("contemporary_source", "")):
            raise ValidationError("Aggregated work unit REFERENCE resource differs from its plan")
        child_fingerprints = normalized.get("resource_fingerprints")
        if not isinstance(child_fingerprints, dict):
            raise ValidationError("Aggregated work unit lacks resource fingerprints")
        required_lineage = {
            key: str(value)
            for key, value in child_fingerprints.items()
            if key in {
                f"project.{plan['output_project']}",
                f"project.{plan['contemporary_source']}",
            }
        }
        if set(required_lineage) != {
            f"project.{plan['output_project']}",
            f"project.{plan['contemporary_source']}",
        }:
            raise ValidationError("Aggregated work unit lacks WIP/REFERENCE lineage fingerprints")
        if lineage_fingerprints is None:
            lineage_fingerprints = required_lineage
            bindings = normalized.get("resource_bindings")
            lineage_bindings = dict(bindings) if isinstance(bindings, dict) else {}
            names = normalized.get("resource_display_names")
            lineage_display_names = dict(names) if isinstance(names, dict) else {}
        elif lineage_fingerprints != required_lineage:
            raise ValidationError("Aggregated work-unit resource lineage is inconsistent")
        normalized_for_globalization = {
            **normalized,
            "findings": [
                {
                    **dict(row),
                    **(
                        {"execution_route": dict(normalized["execution_route"])}
                        if isinstance(normalized.get("execution_route"), Mapping)
                        and not isinstance(row.get("execution_route"), Mapping)
                        else {}
                    ),
                }
                for row in normalized.get("findings", [])
                if isinstance(row, Mapping)
            ],
        }
        if (
            plan.get("rtc_stage") == "REFERENCE_TEXT_COMPARISON"
            and unit.get("review_portion_id")
        ):
            normalized_for_globalization["ol_review_requests"] = [
                {
                    **dict(row),
                    "parent_review_portion_id": unit["review_portion_id"],
                    "review_portion_index": unit["review_portion_index"],
                    "review_portion_total": unit["review_portion_total"],
                    "review_portion_scope": unit["review_portion_scope"],
                }
                for row in normalized.get("ol_review_requests", [])
                if isinstance(row, Mapping)
            ]
        globalized = globalize_result_finding_ids(
            normalized_for_globalization,
            unit_id=unit_id or str(submission.get("task_id") or "UNIT"),
            run_id=str(plan.get("run_id") or plan.get("plan_id") or "RUN"),
            prefix=workflow.upper(),
        )
        result_atoms = list(atomic_reference_labels(
            str(value)
            for value in globalized["coverage"]["reviewed_references"]
        ))
        # Legacy partition plans did not persist per-unit atoms. Their sealed child
        # manifest remains the immutable coverage authority; synthetic pre-contract
        # fixtures fall back to their already validated normalized result.
        if not unit_atoms:
            unit_atoms = list(result_atoms)
        result_not_assessed = [
            str(value) for value in (globalized["coverage"] or {}).get("not_assessed_references", [])
        ]
        if result_not_assessed:
            result_atoms = [*result_atoms, *atomic_reference_labels(result_not_assessed)]
        if (
            len(result_atoms) != len(set(result_atoms))
            or len(unit_atoms) != len(set(unit_atoms))
            or set(result_atoms) != set(unit_atoms)
        ):
            raise ValidationError(
                f"Work unit {unit_id} result coverage differs from its immutable plan",
                code="AGGREGATE_COVERAGE_MISMATCH",
                next_action=(
                    "Restart this Run with current settings; sealed work-unit coverage "
                    "cannot be rewritten safely."
                ),
                details=_coverage_reconciliation_details(
                    unit_atoms,
                    result_atoms,
                    reason="RESULT_COVERAGE_DRIFT",
                    unit_id=unit_id,
                ),
            )
        planned_by_unit.extend(unit_atoms)
        observed.extend(unit_atoms)
        unit_not_assessed = list(atomic_reference_labels(
            str(value) for value in (normalized.get("coverage") or {}).get("not_assessed_references", [])
        ))
        if unit_not_assessed:
            # Partial coverage inside a unit: the unreviewed coordinates stay planned but are not assessed.
            not_assessed_atoms.extend(unit_not_assessed)
            exception_rows.extend(dict(row) for row in normalized.get("exceptions", []) if isinstance(row, Mapping))
        receipts.extend(globalized.get("review_receipts", []))
        adjudications.extend(globalized.get("structural_adjudications", []))
        ol_review_requests.extend(globalized.get("ol_review_requests", []))
        ol_resolutions.extend(globalized.get("ol_resolutions", []))
        resolved_ol_request_ids.extend(globalized.get("resolved_ol_request_ids", []))
        findings.extend(globalized.get("findings", []))
        unit_source_issues = [
            dict(row)
            for row in normalized.get("source_text_issues", [])
            if isinstance(row, Mapping)
        ]
        source_issue_rows.extend(unit_source_issues)
        child_results.append({
            "unit_id": unit_id,
            "task_id": submission.get("task_id"),
            "scope": submission.get("scope"),
            "primary_coverage_atoms": unit_atoms,
            "source_spans": dict(unit.get("source_spans") or {}),
            "submission_sha256": sha256_file(submission_path),
            "execution_route": normalized.get("execution_route"),
            "review_portion_id": unit.get("review_portion_id"),
            "review_portion_index": unit.get("review_portion_index"),
            "review_portion_total": unit.get("review_portion_total"),
            "review_portion_scope": unit.get("review_portion_scope"),
            "parent_review_portion_id": unit.get("parent_review_portion_id"),
            "stage_case_index": unit.get("stage_case_index"),
            "stage_case_total": unit.get("stage_case_total"),
            "source_text_issues": unit_source_issues,
            "structural_issues": unit_source_issues,
        })
    for span in plan.get("not_assessed_spans") or []:
        # A span no work unit can hold within the hard limits: planned out of the units, reported as not assessed.
        if not isinstance(span, dict) or not span.get("references"):
            continue
        span_atoms = [str(value) for value in span["references"]]
        planned_by_unit.extend(span_atoms)
        not_assessed_atoms.extend(span_atoms)
        exception_rows.append(
            ExceptionRecord(
                tool=workflow.upper(),
                code=str(span.get("code") or "WORK_UNIT_SPAN_EXCEEDS_LIMIT"),
                message=str(span.get("message") or "No work unit can hold this span within the hard limits."),
                effect=NOT_ASSESSED,
                run_id=str(plan.get("run_id") or "") or None,
                job_id=str(plan.get("job_id") or "") or None,
                stage=str(plan.get("rtc_stage") or plan.get("operation") or "").upper() or None,
                coordinates=tuple(span_atoms),
            ).to_dict()
        )
    # Chapters left out at planning (compile defects): never planned, so outside coverage reconciliation.
    left_out_portions: list[str] = []
    for portion in plan.get("not_assessed_portions") or []:
        if not isinstance(portion, dict) or not str(portion.get("scope") or "").strip():
            continue
        label = str(portion["scope"]).strip()
        left_out_portions.append(label)
        exception_rows.append(
            ExceptionRecord(
                tool=workflow.upper(),
                code=str(portion.get("code") or "SCOPE_CHAPTER_COMPILE_DEFECT"),
                message=str(portion.get("message") or f"{label} was left out because of a compile defect."),
                effect=NOT_ASSESSED,
                run_id=str(plan.get("run_id") or "") or None,
                job_id=str(plan.get("job_id") or "") or None,
                stage=str(plan.get("rtc_stage") or plan.get("operation") or "").upper() or None,
                coordinates=(label,),
            ).to_dict()
        )
    findings, _duplicates = dedupe_findings(findings)
    validate_global_finding_ids(findings)
    if len(expected) != len(set(expected)):
        raise ValidationError(
            "Aggregate plan duplicates canonical expected coverage",
            code="AGGREGATE_COVERAGE_MISMATCH",
            details=_coverage_reconciliation_details(
                expected,
                planned_by_unit,
                reason="DUPLICATE_PLANNED_ATOM",
            ),
        )
    selective_ol_cases = plan.get("rtc_stage") == "SELECTIVE_OL_ADJUDICATION"
    if (
        (not selective_ol_cases and len(planned_by_unit) != len(set(planned_by_unit)))
        or set(planned_by_unit) != set(expected)
    ):
        reason = (
            "DUPLICATE_PRIMARY_OWNER"
            if len(planned_by_unit) != len(set(planned_by_unit))
            else "MISSING_PRIMARY_OWNER"
        )
        raise ValidationError(
            "Aggregated work units do not reconcile exact, non-overlapping plan coverage",
            code="AGGREGATE_COVERAGE_MISMATCH",
            details=_coverage_reconciliation_details(
                expected,
                planned_by_unit,
                reason=reason,
            ),
        )
    if (
        (not selective_ol_cases and len(observed) != len(set(observed)))
        or set(observed) | set(not_assessed_atoms) != set(expected)
    ):
        raise ValidationError(
            "Accepted work-unit results do not reconcile exact plan coverage",
            code="AGGREGATE_COVERAGE_MISMATCH",
            details=_coverage_reconciliation_details(
                expected,
                observed,
                reason="MISSING_WORK_UNIT_RESULT",
            ),
        )
    if selective_ol_cases:
        resolved_request_ids = [str(value).strip().upper() for value in resolved_ol_request_ids]
        assessed_request_ids = [
            value for value in planned_ol_request_ids if value not in set(unassessed_ol_request_ids)
        ]
        if (
            len(planned_ol_request_ids) != len(set(planned_ol_request_ids))
            or len(resolved_request_ids) != len(set(resolved_request_ids))
            or set(resolved_request_ids) != set(assessed_request_ids)
        ):
            raise ValidationError(
                "Selective OL work units do not reconcile one resolution per isolated request",
                code=_analysis_code(workflow, "SAW_OL_CASE_ISOLATION_INVALID"),
                details={
                    "planned_request_ids": planned_ol_request_ids,
                    "resolved_request_ids": resolved_request_ids,
                },
            )
    source_issue_rows = unique_source_text_issues(source_issue_rows)
    aggregate = {
        "schema_version": "1.0",
        "status": "FINALIZED",
        "workflow": workflow,
        "plan_id": plan["plan_id"],
        "job_id": plan["job_id"],
        "run_id": plan["run_id"],
        "requested_scope": plan["requested_scope"],
        "output_project": plan["output_project"],
        "contemporary_source": plan["contemporary_source"],
        "resource_bindings": lineage_bindings or {},
        "resource_display_names": lineage_display_names or {},
        "resource_fingerprints": lineage_fingerprints or {},
        "rtc_stage": plan.get("rtc_stage"),
        "coverage": {
            **coverage_document(
                [value for value in expected if value not in set(not_assessed_atoms)],
                [*not_assessed_atoms, *left_out_portions],
                findings_present=bool(findings),
            ),
            "legacy_raw_spans_expanded": legacy_raw_spans,
        },
        "exceptions": exception_rows,
        "review_receipts": receipts,
        "structural_adjudications": adjudications,
        "ol_review_requests": ol_review_requests,
        "ol_resolutions": ol_resolutions,
        "resolved_ol_request_ids": resolved_ol_request_ids,
        "findings": findings,
        "finding_count": len(findings),
        "source_comparison_status": source_comparison_status(source_issue_rows),
        "structural_issues": source_issue_rows,
        "source_text_issues": source_issue_rows,
        "work_units": child_results,
        "execution_routes": aggregate_execution_routes(child_results),
        "finalized_utc": utc_now(),
        "narrative_language": _narrative_language_contract(config),
    }
    authority = report_language_authority(
        config.human_output.logs_and_reports,
        operator_language=config.human_output.operator_language,
    )
    if authority:
        aggregate["language_authority"] = authority
    aggregate_path = path.with_name(f"{plan['plan_id']}-aggregate.json")
    atomic_write_json(aggregate_path, aggregate)
    report_path = path.with_name(f"{plan['plan_id']}-aggregate.md")
    aggregate_lines = [
        f"# {workflow.upper()} Aggregate: {plan['plan_id']}",
        "",
        f"- Status: `FINALIZED`",
        f"- Scope: `{plan['requested_scope']}`",
        f"- Work units: `{len(child_results)}`",
        f"- Reviewed coordinates: `{len(expected) - len(set(not_assessed_atoms))}`",
        *([f"- Not assessed coordinates: `{len(set(not_assessed_atoms))}`"] if not_assessed_atoms else []),
        *([f"- Left out (not assessed): `{'; '.join(left_out_portions)}`"] if left_out_portions else []),
        f"- Review receipts: `{len(receipts)}`",
        f"- Findings: `{len(findings)}`",
        f"- Source comparison: `{source_comparison_status(source_issue_rows)}`",
        "",
    ]
    authority_notice = render_report_language_authority(authority, markdown=True)
    if authority_notice:
        aggregate_lines.extend([authority_notice, ""])
    aggregate_lines.extend(render_execution_section(aggregate["execution_routes"]))
    aggregate_lines.extend(render_exceptions_section(exception_rows))
    atomic_write_text(report_path, "\n".join(aggregate_lines).rstrip() + "\n")
    plan["status"] = "FINALIZED"
    plan["aggregate_path"] = str(aggregate_path)
    plan["aggregate_sha256"] = sha256_file(aggregate_path)
    atomic_write_json(path, plan)
    return {**aggregate, "aggregate_path": str(aggregate_path), "report_path": str(report_path)}

