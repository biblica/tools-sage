"""Composite RTC task creation: the approved-plan stage builder, selective-OL case partitioning, and
the composite RTC entry point.

Split from act_tasks.py, which re-exports every name defined here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from typing import Mapping
from typing import Sequence



from .act_common import _analysis_code
from .act_common import _analysis_identity
from .act_common import _approved_rtc_work_plan
from .act_common import _load_owning_job
from .act_common import _review_portion_for_reference
from .act_common import _rollback_unregistered_stage_tasks
from .act_common import _scope_for_case_atoms
from .act_common import _stage_record
from .act_evidence import _rtc_alignment_inputs
from .act_evidence import _rtc_marker_review
from .act_evidence import _rtc_omission_rows
from .act_evidence import _structural_candidates
from .act_evidence import _structural_triage
from .atomic import atomic_write_json
from .config import load_json
from .errors import EvidenceLimitError
from .errors import ValidationError
from .hashing import sha256_bytes
from .jobs import JobStore
from .ol_referrals import ol_referral_contract
from .profiles import load_workflow_profile
from .references import AnalysisScope
from .references import ScriptureScope
from .references import ScriptureScopeSet
from .references import atomic_reference_labels
from .references import expand_reference_atoms
from .registry import EcosystemConfig
from .rtc_planner import LEGACY_RTC_PLANNER_VERSION
from .rtc_planner import RTC_PLANNER_VERSION
from .rtc_policy import load_run_policy_snapshot
from .runtime_paths import plan_container
from .state import utc_now


def _create_approved_rtc_stage(
    config: EcosystemConfig,
    *,
    workflow: str,
    approved_plan: Mapping[str, Any],
    output_project_id: str,
    contemporary_source_id: str,
    scope: AnalysisScope,
    grammar_override_id: str | None,
    parent_plan_id: str,
    job_id: str,
    run_id: str,
    rtc_stage: str,
    rtc_predecessor_files: Sequence[str],
    ol_referral_contract: str | None,
    rtc_stage_references: Sequence[str] = (),
) -> dict[str, Any]:
    """Create the exact approved work units for a partitionable RTC stage."""
    from .act_tasks import create_act_task  # act_tasks imports this module
    units = [dict(item) for item in approved_plan.get("units", [])]
    rtc_planner_version = str(
        dict(approved_plan.get("rtc_planner") or {}).get("version")
        or LEGACY_RTC_PLANNER_VERSION
    )
    references_by_portion: dict[str, list[str]] = {}
    # Structural evidence is report-only and may cross approved RTC boundaries.
    # Route each atomic coordinate to its existing parent; meaning stages retain
    # every approved portion and source-record bridges were protected at planning.
    for reference in rtc_stage_references:
        progress = _review_portion_for_reference(
            units, str(reference), workflow=workflow
        )
        references_by_portion.setdefault(progress["review_portion_id"], []).append(
            str(reference)
        )
    if references_by_portion:
        units = [
            unit
            for unit in units
            if str(unit["review_portion_id"]) in references_by_portion
        ]
    stage_plan_id = f"{parent_plan_id}-{rtc_stage}"
    children: list[dict[str, Any]] = []
    created_tasks: list[dict[str, Any]] = []
    for unit in units:
        stage_unit_references = references_by_portion.get(
            str(unit["review_portion_id"]),
            [],
        )
        raw_atoms = stage_unit_references or unit.get("primary_coverage_atoms")
        if not isinstance(raw_atoms, list) or not raw_atoms:
            raw_atoms = unit.get("primary_references", [])
        unit_atoms = list(atomic_reference_labels(str(value) for value in raw_atoms))
        try:
            child = create_act_task(
                config,
                workflow=workflow,
                operation="rtc",
                output_project_id=output_project_id,
                contemporary_source_id=contemporary_source_id,
                scope_value=str(unit["primary_scope"]),
                grammar_override_id=grammar_override_id,
                auto_partition=False,
                parent_plan_id=stage_plan_id,
                work_unit_id=str(unit["unit_id"]),
                job_id=job_id,
                run_id=run_id,
                rtc_stage=rtc_stage,
                rtc_planner_version=rtc_planner_version,
                rtc_predecessor_files=rtc_predecessor_files,
                ol_referral_contract=ol_referral_contract,
                review_portion_id=str(unit["review_portion_id"]),
                review_portion_index=int(unit["review_portion_index"]),
                review_portion_total=int(unit["review_portion_total"]),
                review_portion_scope=str(unit["review_portion_scope"]),
                parent_review_portion_id=(
                    str(unit["review_portion_id"])
                    if stage_unit_references
                    else None
                ),
                stage_case_index=1 if stage_unit_references else None,
                stage_case_total=1 if stage_unit_references else None,
                rtc_stage_references=stage_unit_references,
                context_before_references=[str(value) for value in unit.get("context_before", [])],
                context_after_references=[str(value) for value in unit.get("context_after", [])],
            )
        except EvidenceLimitError as exc:
            _rollback_unregistered_stage_tasks(config, workflow, run_id, created_tasks)
            raise ValidationError(
                f"Approved {_analysis_identity(workflow)} RTC work-unit boundaries no longer fit the exact provider handoff",
                code=_analysis_code(workflow, "SAW_APPROVED_PLAN_STALE"),
                affected_scope=str(unit.get("primary_scope") or scope.label()),
                next_action=f"Rebuild and approve the affected {_analysis_identity(workflow)} Run plan; boundaries will not change silently.",
                details={"limit_error": exc.to_dict()},
            ) from exc
        except Exception:
            _rollback_unregistered_stage_tasks(config, workflow, run_id, created_tasks)
            raise
        created_tasks.append(child)
        child_manifest = load_json(Path(str(child["manifest_path"])))
        child_atoms = list(child_manifest.get("expected_references", []))
        if child_atoms != unit_atoms:
            _rollback_unregistered_stage_tasks(config, workflow, run_id, created_tasks)
            raise ValidationError(
                f"Approved {_analysis_identity(workflow)} RTC work-unit atoms differ from the generated sealed task",
                code=_analysis_code(workflow, "SAW_APPROVED_PLAN_STALE"),
                affected_scope=str(unit.get("primary_scope") or scope.label()),
                next_action=f"Rebuild and approve the affected {_analysis_identity(workflow)} Run plan.",
                details={
                    "unit_id": str(unit.get("unit_id") or ""),
                    "planned_atoms": unit_atoms,
                    "task_atoms": child_atoms,
                },
            )
        package = dict(unit.get("rtc_package") or {})
        children.append({
            "unit_id": str(unit["unit_id"]),
            "scope": str(unit["primary_scope"]),
            "task_id": child["task_id"],
            "manifest_path": child["manifest_path"],
            "task_fingerprint": child["task_fingerprint"],
            "primary_coverage_atoms": unit_atoms,
            "source_spans": dict(package.get("source_spans") or {}),
            "context_budget": child.get("context_budget"),
            "review_portion_id": unit["review_portion_id"],
            "review_portion_index": unit["review_portion_index"],
            "review_portion_total": unit["review_portion_total"],
            "review_portion_scope": unit["review_portion_scope"],
            "parent_review_portion_id": (
                unit["review_portion_id"] if stage_unit_references else None
            ),
            "stage_case_index": 1 if stage_unit_references else None,
            "stage_case_total": 1 if stage_unit_references else None,
        })
    if len(children) == 1:
        child = children[0]
        manifest = load_json(Path(str(child["manifest_path"])))
        return {
            "schema_version": "1.0",
            "status": "TASK_CREATED",
            "task_id": child["task_id"],
            "manifest_path": child["manifest_path"],
            "act_path": str(Path(str(child["manifest_path"])).parent / "ACT.md"),
            "task_fingerprint": child["task_fingerprint"],
            "scope": child["scope"],
            "expected_references": manifest.get("expected_references", []),
            "context_budget": child.get("context_budget"),
            "review_portion_id": child.get("review_portion_id"),
            "review_portion_index": child.get("review_portion_index"),
            "review_portion_total": child.get("review_portion_total"),
            "review_portion_scope": child.get("review_portion_scope"),
        }
    unplannable_spans = (
        [dict(item) for item in approved_plan.get("not_assessed_spans") or [] if isinstance(item, Mapping)]
        if not references_by_portion
        else []
    )
    plan = {
        "schema_version": "1.0",
        "status": "PARTITIONED",
        "plan_id": stage_plan_id,
        "workflow": workflow,
        "operation": "rtc",
        "rtc_stage": rtc_stage,
        **({"not_assessed_spans": unplannable_spans} if unplannable_spans else {}),
        "ol_referral_contract": ol_referral_contract,
        "requested_scope": scope.label(),
        "output_project": output_project_id,
        "contemporary_source": contemporary_source_id,
        "job_id": job_id,
        "run_id": run_id,
        "approved_work_plan_path": approved_plan.get("approved_manifest_path"),
        "approved_work_plan_fingerprint": approved_plan.get("plan_fingerprint"),
        "expected_references": [
            atom
            for unit in children
            for atom in unit.get("primary_coverage_atoms", [])
        ] + [
            atom
            for span in unplannable_spans
            for atom in span.get("references", [])
        ],
        "work_units": children,
        "created_utc": utc_now(),
    }
    plan_path = plan_container(config.workflow(workflow), run_id) / f"{stage_plan_id}.json"
    try:
        atomic_write_json(plan_path, plan)
    except Exception:
        _rollback_unregistered_stage_tasks(config, workflow, run_id, created_tasks)
        raise
    return {**plan, "plan_path": str(plan_path)}


def _partition_selective_ol_cases(
    config: EcosystemConfig,
    *,
    workflow: str,
    operation: str,
    output_project_id: str,
    contemporary_source_id: str,
    lexical_donor_id: str | None,
    scope: ScriptureScope,
    focus: str | None,
    check_type: str | None,
    predecessor_task: str | None,
    grammar_override_id: str | None,
    plan_seed: str,
    job_id: str | None,
    run_id: str | None,
    rtc_planner_version: str,
    rtc_predecessor_files: Sequence[str],
    expected_ol_request_ids: Sequence[str],
    expected_ol_requests: Sequence[Mapping[str, Any]],
    ol_referral_contract: str | None,
) -> dict[str, Any]:
    """Create exactly one isolated model task for each inherited selective-OL case."""
    from .act_tasks import create_act_task  # act_tasks imports this module
    requests = [dict(row) for row in expected_ol_requests]
    declared_ids = [str(value).strip().upper() for value in expected_ol_request_ids]
    request_ids = [str(row.get("request_id") or "").strip().upper() for row in requests]
    if not requests or any(not value for value in request_ids):
        raise ValidationError(
            "Selective OL adjudication requires a nonempty inherited request inventory",
            code=_analysis_code(workflow, "SAW_OL_REQUEST_INVENTORY_INVALID"),
        )
    if request_ids != declared_ids or len(request_ids) != len(set(request_ids)):
        raise ValidationError(
            "Selective OL request identities must be exact, ordered, and run-unique",
            code=_analysis_code(workflow, "SAW_OL_REQUEST_INVENTORY_INVALID"),
        )

    parent_totals: dict[str, int] = {}
    progress_rows: list[dict[str, Any]] = []
    for request in requests:
        parent_id = str(request.get("parent_review_portion_id") or "").strip()
        portion_id = str(request.get("review_portion_id") or parent_id).strip()
        try:
            portion_index = int(request["review_portion_index"])
            portion_total = int(request["review_portion_total"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(
                "Selective OL request lacks inherited review-portion progress",
                code=_analysis_code(workflow, "SAW_STAGE_CASE_PORTION_MISMATCH"),
            ) from exc
        portion_scope = str(request.get("review_portion_scope") or "").strip()
        if not parent_id or portion_id != parent_id or not portion_scope:
            raise ValidationError(
                "Selective OL request has inconsistent review-portion provenance",
                code=_analysis_code(workflow, "SAW_STAGE_CASE_PORTION_MISMATCH"),
            )
        progress_rows.append(
            {
                "review_portion_id": portion_id,
                "review_portion_index": portion_index,
                "review_portion_total": portion_total,
                "review_portion_scope": portion_scope,
                "parent_review_portion_id": parent_id,
            }
        )
        parent_totals[parent_id] = parent_totals.get(parent_id, 0) + 1

    policy = load_workflow_profile(config, config.workflow(workflow)).evidence_policy(operation)
    plan_id = f"{workflow.upper()}-{operation.upper()}-{scope.book}-{plan_seed[:10].upper()}"
    children: list[dict[str, Any]] = []
    created_tasks: list[dict[str, Any]] = []
    parent_positions: dict[str, int] = {}
    # Keep request order as the immutable parent aggregate declared it; task IDs and
    # aggregation reconciliation both depend on this stable one-case sequence.
    try:
        for index, request in enumerate(requests, start=1):
            progress = progress_rows[index - 1]
            parent_id = str(progress["parent_review_portion_id"])
            parent_positions[parent_id] = parent_positions.get(parent_id, 0) + 1
            stage_case_index = parent_positions[parent_id]
            stage_case_total = parent_totals[parent_id]
            target_reference = str(request.get("target_reference") or "").strip()
            atoms = tuple(sorted(set(expand_reference_atoms(target_reference))))
            if not atoms or any(not scope.contains(ref) for ref in atoms):
                raise ValidationError(
                    f"Selective OL request {request_ids[index - 1]} is outside the parent scope",
                    code=_analysis_code(workflow, "SAW_OL_REQUEST_INVENTORY_INVALID"),
                    affected_scope=scope.label(),
                )
            case_scope = _scope_for_case_atoms(atoms)
            unit_id = f"{plan_id}-U{index:03d}"
            atom_labels = [ref.label() for ref in atoms]
            child = create_act_task(
                config,
                workflow=workflow,
                operation=operation,
                output_project_id=output_project_id,
                contemporary_source_id=contemporary_source_id,
                lexical_donor_id=lexical_donor_id,
                scope_value=case_scope.label(),
                focus=focus,
                check_type=check_type,
                predecessor_task=predecessor_task,
                grammar_override_id=grammar_override_id,
                auto_partition=False,
                parent_plan_id=plan_id,
                work_unit_id=unit_id,
                job_id=job_id,
                run_id=run_id,
                rtc_stage="SELECTIVE_OL_ADJUDICATION",
                rtc_planner_version=rtc_planner_version,
                rtc_predecessor_files=rtc_predecessor_files,
                expected_ol_request_ids=[request_ids[index - 1]],
                expected_ol_requests=[request],
                rtc_stage_references=atom_labels,
                ol_referral_contract=ol_referral_contract,
                review_portion_id=str(progress["review_portion_id"]),
                review_portion_index=int(progress["review_portion_index"]),
                review_portion_total=int(progress["review_portion_total"]),
                review_portion_scope=str(progress["review_portion_scope"]),
                parent_review_portion_id=parent_id,
                stage_case_index=stage_case_index,
                stage_case_total=stage_case_total,
            )
            created_tasks.append(child)
            manifest = load_json(Path(str(child["manifest_path"])))
            child_atoms = list(atomic_reference_labels(
                str(value) for value in manifest.get("expected_references", [])
            ))
            child_request_ids = list(
                dict(manifest.get("review_requirements") or {}).get(
                    "expected_ol_request_ids", []
                )
            )
            if child_atoms != atom_labels or child_request_ids != [request_ids[index - 1]]:
                raise ValidationError(
                    "Selective OL case task differs from its one-request controller plan",
                    code=_analysis_code(workflow, "SAW_OL_CASE_ISOLATION_INVALID"),
                    affected_scope=case_scope.label(),
                    details={
                        "unit_id": unit_id,
                        "planned_request_id": request_ids[index - 1],
                        "task_request_ids": child_request_ids,
                        "planned_atoms": atom_labels,
                        "task_atoms": child_atoms,
                    },
                )
            children.append({
                "unit_id": unit_id,
                "scope": case_scope.label(),
                "task_id": child["task_id"],
                "manifest_path": child["manifest_path"],
                "task_fingerprint": child["task_fingerprint"],
                "primary_coverage_atoms": child_atoms,
                "ol_request_ids": child_request_ids,
                "context_budget": child.get("context_budget"),
                **progress,
                "stage_case_index": stage_case_index,
                "stage_case_total": stage_case_total,
            })
    except Exception:
        # A partitioner that fails mid-loop must not leave orphan child tasks behind.
        _rollback_unregistered_stage_tasks(config, workflow, run_id, created_tasks)
        raise

    if len(created_tasks) == 1:
        return {
            **created_tasks[0],
            "partition_basis": "ONE_OL_REQUEST_PER_MODEL_TASK",
        }

    expected_refs = sorted({
        atom
        for child in children
        for atom in child["primary_coverage_atoms"]
    }, key=lambda value: next(iter(expand_reference_atoms(value))))
    plan = {
        "schema_version": "1.0",
        "status": "PARTITIONED",
        "plan_id": plan_id,
        "workflow": workflow,
        "operation": operation,
        "rtc_stage": "SELECTIVE_OL_ADJUDICATION",
        "ol_referral_contract": ol_referral_contract,
        "partition_basis": "ONE_OL_REQUEST_PER_MODEL_TASK",
        "requested_scope": scope.label(),
        "output_project": output_project_id,
        "contemporary_source": contemporary_source_id,
        "lexical_donor": None,
        "job_id": job_id,
        "run_id": run_id,
        "policy": policy.to_dict(),
        "expected_references": expected_refs,
        "expected_ol_request_ids": request_ids,
        "work_units": children,
        "created_utc": utc_now(),
    }
    plan_root = plan_container(config.workflow(workflow), run_id)
    plan_path = plan_root / f"{plan_id}.json"
    atomic_write_json(plan_path, plan)
    return {**plan, "plan_path": str(plan_path)}


def _create_rtc_composite(
    config: EcosystemConfig,
    *,
    workflow: str,
    output_project_id: str,
    contemporary_source_id: str,
    scope: AnalysisScope,
    grammar_override_id: str | None,
    job_id: str,
    run_id: str,
    auto_partition: bool,
) -> dict[str, Any]:
    """Create the first governed stage of one composite RTC Run."""
    from .act_tasks import create_act_task  # act_tasks imports this module
    output = config.project(output_project_id)
    job_store = JobStore(config.root, config.settings_path)
    owning_job = _load_owning_job(config, job_id, workflow)
    run = job_store.load_run(owning_job, run_id)
    rtc_policy = load_run_policy_snapshot(
        run.root,
        profile_path=config.workflow(workflow).profile_path,
        workflow=workflow,
    )
    approved_work_plan = _approved_rtc_work_plan(
        config,
        workflow=workflow,
        job_id=job_id,
        run_id=run_id,
        output_project_id=output_project_id,
        scope=scope,
    )
    rtc_planner_version = str(
        dict((approved_work_plan or {}).get("rtc_planner") or {}).get("version")
        or (
            LEGACY_RTC_PLANNER_VERSION
            if approved_work_plan is not None
            else RTC_PLANNER_VERSION
        )
    )
    structure_enabled = bool(dict(rtc_policy.get("checks") or {}).get("structure_completeness", True))
    reference_project = config.project(contemporary_source_id)
    # One compile and one pair of verse indexes serve every deterministic check of this composite.
    alignment_inputs = (
        _rtc_alignment_inputs(config, workflow, output, reference_project, scope) if structure_enabled else None
    )
    triage = (
        _structural_triage(
            config,
            workflow,
            output,
            reference_project,
            scope,
            _structural_candidates(config, output, scope),
            alignment_inputs,
        )
        if alignment_inputs is not None
        else {"model": [], "findings": [], "resolved": []}
    )
    marker = (
        _rtc_marker_review(alignment_inputs, output, reference_project, scope)
        if alignment_inputs is not None
        else {"findings": [], "candidates": []}
    )
    # Only equivalence groups the code cannot decide reach the model stage.
    candidates = triage["model"]
    first_stage = "STRUCTURAL_ADJUDICATION" if candidates else "REFERENCE_TEXT_COMPARISON"
    plan_seed = sha256_bytes(
        json.dumps(
            {
                "job_id": job_id,
                "run_id": run_id,
                "scope": scope.label(),
                "wip": output_project_id,
                "reference": contemporary_source_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    plan_id = f"RTC-{scope.book}-{plan_seed[:10].upper()}"
    # The approved inventory is copied into lightweight progress provenance; the
    # signed/approved source plan itself is never rewritten by stage creation.
    review_portions = (
        [
            {
                "review_portion_id": str(unit["review_portion_id"]),
                "review_portion_index": int(unit["review_portion_index"]),
                "review_portion_total": int(unit["review_portion_total"]),
                "review_portion_scope": str(unit["review_portion_scope"]),
            }
            for unit in approved_work_plan.get("units", [])
        ]
        if approved_work_plan is not None
        else [
            {
                "review_portion_id": f"{plan_id}-P001",
                "review_portion_index": 1,
                "review_portion_total": 1,
                "review_portion_scope": scope.label(),
            }
        ]
    )
    stage_references = (
        [ref.label() for ref in sorted({
            atom
            for candidate in candidates
            for reference in candidate.get("references", [])
            for atom in expand_reference_atoms(str(reference))
        })]
        if first_stage == "STRUCTURAL_ADJUDICATION"
        else []
    )
    if approved_work_plan is not None and stage_references:
        approved_atoms = {
            atom
            for unit in approved_work_plan.get("units", [])
            for value in (
                unit.get("primary_coverage_atoms")
                or unit.get("primary_references")
                or []
            )
            for atom in expand_reference_atoms(str(value))
        }
        stage_references = [
            value
            for value in stage_references
            if tuple(expand_reference_atoms(value))[0] in approved_atoms
        ]
        if first_stage == "STRUCTURAL_ADJUDICATION" and not stage_references:
            first_stage = "REFERENCE_TEXT_COMPARISON"
    if approved_work_plan is not None:
        result = _create_approved_rtc_stage(
            config,
            workflow=workflow,
            approved_plan=approved_work_plan,
            output_project_id=output_project_id,
            contemporary_source_id=contemporary_source_id,
            scope=scope,
            grammar_override_id=grammar_override_id,
            parent_plan_id=plan_id,
            job_id=job_id,
            run_id=run_id,
            rtc_stage=first_stage,
            rtc_predecessor_files=(),
            ol_referral_contract=ol_referral_contract(workflow),
            rtc_stage_references=stage_references,
        )
    else:
        if isinstance(scope, ScriptureScopeSet):
            raise ValidationError(
                "A discontinuous RTC Run requires its approved work-unit plan",
                code=_analysis_code(workflow, "SAW_APPROVED_PLAN_INVALID"),
                affected_scope=scope.label(),
                next_action="Build and approve the RTC Run plan, then retry task creation.",
            )
        result = create_act_task(
            config,
            workflow=workflow,
            operation="rtc",
            output_project_id=output_project_id,
            contemporary_source_id=contemporary_source_id,
            scope_value=scope.label(),
            grammar_override_id=grammar_override_id,
            auto_partition=auto_partition,
            parent_plan_id=plan_id,
            job_id=job_id,
            run_id=run_id,
            rtc_stage=first_stage,
            rtc_planner_version=rtc_planner_version,
            rtc_stage_references=stage_references,
            ol_referral_contract=ol_referral_contract(workflow),
        )
    stage = _stage_record(result, first_stage)
    plan = {
        "schema_version": "1.0",
        "plan_type": "SAW_RTC_COMPOSITE" if workflow == "saw" else "RTC_COMPOSITE",
        "status": "COMPOSITE_IN_PROGRESS",
        "plan_id": plan_id,
        "workflow": workflow,
        "operation": "rtc",
        "job_id": job_id,
        "run_id": run_id,
        "requested_scope": scope.label(),
        "output_project": output_project_id,
        "contemporary_source": contemporary_source_id,
        "grammar_override_id": grammar_override_id,
        "structural_stage_required": bool(candidates),
        # Structural candidates decided in code: findings join the final result, resolutions are provenance.
        "deterministic_findings": [*triage["findings"], *marker["findings"]],
        "structural_resolutions": triage["resolved"],
        # REFERENCE text the WIP lacks; finalization reports these and promotes them to findings.
        "coverage_gap_issues": (
            _rtc_omission_rows(alignment_inputs, output, reference_project, scope)
            if alignment_inputs is not None
            else []
        ),
        "rtc_policy": rtc_policy,
        "rtc_planner_version": rtc_planner_version,
        "ol_referral_contract": ol_referral_contract(workflow),
        "review_portions": review_portions,
        "approved_work_plan_path": (
            approved_work_plan.get("approved_manifest_path")
            if approved_work_plan is not None
            else None
        ),
        "approved_work_plan_fingerprint": (
            approved_work_plan.get("plan_fingerprint")
            if approved_work_plan is not None
            else None
        ),
        "stages": [stage],
        "created_utc": utc_now(),
    }
    plan_root = plan_container(config.workflow(workflow), run_id)
    plan_path = plan_root / f"{plan_id}.json"
    atomic_write_json(plan_path, plan)
    response = {
        **(dict(result) if stage["kind"] == "TASK" else {}),
        **plan,
        "status": "COMPOSITE",
        "plan_path": str(plan_path),
        "task_manifests": list(stage["task_manifests"]),
        "current_stage": first_stage,
    }
    if stage["kind"] == "TASK":
        for key in ("task_id", "manifest_path", "act_path", "task_fingerprint", "scope", "expected_references", "structural_candidate_ids"):
            if key in result:
                response[key] = result[key]
    return response
