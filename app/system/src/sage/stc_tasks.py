"""STC task creation: the approved STC work-plan builder.

Split from act_tasks.py, which re-exports every name defined here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from typing import Sequence



from .act_common import _assert_enabled
from .act_common import _assert_initialized_and_ready
from .act_common import _assert_project_scope
from .act_common import _load_owning_job
from .act_common import _narrative_language_contract
from .act_common import _one_book_file
from .act_common import _relative
from .act_common import _rollback_unregistered_stage_tasks
from .act_common import _select_ol_project
from .act_common import _skill_files
from .act_common import load_skill_registry
from .act_evidence import _bounded_sfm_packet
from .act_evidence import _canonical_gap_source_issues
from .act_evidence import _copy_ol_authority_profile
from .act_evidence import _records_intersecting_reference_values
from .act_evidence import _write_grammar_contract
from .act_evidence import _write_report_language_contract
from .atomic import atomic_write_json
from .candidates import candidate_inventory
from .errors import EvidenceLimitError
from .errors import SageError
from .errors import ValidationError
from .evidence import TOKEN_ESTIMATOR
from .evidence_policy import AUTHORITY_INTERPRETATION_RULES
from .evidence_policy import AUTHORIZED_CONTENT_EVIDENCE
from .evidence_policy import LINGUISTIC_COMPETENCE_RULES
from .evidence_policy import PROCESS_CONTROL
from .evidence_policy import SUBJECT_TEXT
from .evidence_policy import task_evidence_policy
from .hashing import sha256_bytes
from .name_alignment import NAME_ALIGNER_VERSION
from .name_alignment import wip_name_candidate_table
from .ol_analysis import load_ol_analysis
from .scripture import compile_project
from .hashing import sha256_file
from .numeric_candidates import numeric_candidates
from .platform_commands import render_sage_command
from .profiles import load_workflow_profile
from .project_context import identity_bindings
from .project_context import identity_display_names
from .project_context import resolve_project_identities
from .references import AnalysisScope
from .references import analysis_scope_portions
from .references import expand_reference_atoms
from .registry import EcosystemConfig
from .runtime_paths import plan_container
from .runtime_paths import task_container
from .source_coverage import source_text_issues
from .state import utc_now
from .stc import STC_PLANNER_VERSION
from .stc import length_outliers
from .stc import plan_stc_work_units
from .stc import routed_ol_text_filter_for_book
from .stc import stc_authority_family
from .text_coverage import omission_rows
from .task_sealing import seal_task
from .text_coverage import psalm_title_chapters
from .verse_alignment import ProjectVerseIndex
from .verse_alignment import align_records
from .verse_alignment import record_correspondence
from .versification_service import VersificationService
from .vrs import VerseRef
from .work_units import records_from_project_result
from .work_units import select_records_for_scope


def _stc_name_check(
    config: EcosystemConfig,
    output: Any,
    service: VersificationService,
    primary_wip: Sequence[Any],
) -> dict[str, Any]:
    """Name candidates for the primary verses, learned from the whole WIP; never blocks the task.

    Any failure (no MACULA package, a book that does not compile) leaves the names unchecked with the reason.
    """
    try:
        analysis = load_ol_analysis(config.root)
        if analysis is None:
            return {"status": "NOT_CHECKED", "reason": "SAGE has no original-language analysis package", "candidates": []}
        compiled_wip = compile_project(config, output)
        usable = {**compiled_wip, "files": [row for row in compiled_wip.get("files", []) if Path(str(row.get("cache", ""))).is_file()]}
        records = records_from_project_result(output.project_id, usable, resource_role="WIP")
        index = ProjectVerseIndex.cached(output.project_id, records, service.project_schema(output))
        table = wip_name_candidate_table(
            analysis,
            records,
            index.records_for_canonical,
            cache_dir=config.cache_root / "name-alignment",
        )
    except (SageError, OSError, ValueError, KeyError) as exc:
        return {"status": "NOT_CHECKED", "reason": f"name check unavailable: {exc}", "candidates": []}
    return {
        "status": "CHECKED",
        "aligner": NAME_ALIGNER_VERSION,
        "package_id": analysis.package_id,
        "candidates": [row for record in primary_wip for row in table.get(record.reference, [])],
    }


def _create_stc_task(
    config: EcosystemConfig,
    *,
    workflow: str,
    output_project_id: str,
    scope: AnalysisScope,
    contemporary_source_id: str | None,
    grammar_override_id: str | None,
    auto_partition: bool,
    parent_plan_id: str | None,
    work_unit_id: str | None,
    job_id: str,
    run_id: str,
    stc_planner_version: str,
    context_before: Sequence[str],
    context_after: Sequence[str],
) -> dict[str, Any]:
    """Create STC independently from Reference, routing only bounded WIP+primary-OL SFM."""
    from .act_tasks import create_act_task  # act_tasks imports this module
    # STC maintenance boundary: controller identity and validation stay outside model evidence;
    # only bounded WIP+OL SFM and their complete canonical profiles are routed to the provider.
    if grammar_override_id:
        raise ValidationError("STC does not accept ad-hoc grammar-profile overrides; recreate the Job profile binding instead")
    output = config.project(output_project_id)
    _assert_enabled(output, "STC WIP")
    _assert_project_scope(output, scope, "STC WIP")
    if "WIP" not in output.scope.roles or output.content_state != "UNDER_REVIEW":
        raise ValidationError(f"STC requires an UNDER_REVIEW WIP Project: {output.project_id}")
    ol_role, ol_project = _select_ol_project(config, scope, required=True, workflow=workflow, job_id=job_id)
    assert ol_project is not None
    family = stc_authority_family(scope.book)
    expected_role = "ORIGINAL_LANGUAGE_GREEK" if family == "GRK" else "ORIGINAL_LANGUAGE_HEBREW"
    if ol_role != expected_role:
        raise ValidationError("STC testament routing differs from the selected primary OL authority", code="STC_OL_AUTHORITY_MISMATCH")
    compiled = _assert_initialized_and_ready(
        config,
        workflow,
        [("STC WIP", output), ("Original-language", ol_project)],
        scope,
    )
    wip_records_all = records_from_project_result(output.project_id, compiled[output.project_id], resource_role="WIP")
    ol_records_all = records_from_project_result(ol_project.project_id, compiled[ol_project.project_id], resource_role=family)
    wip_index: ProjectVerseIndex | None = None
    ol_index: ProjectVerseIndex | None = None
    if stc_planner_version == STC_PLANNER_VERSION:
        service = VersificationService(config)
        wip_index = ProjectVerseIndex.cached(
            output.project_id,
            wip_records_all,
            service.project_schema(output),
        )
        ol_index = ProjectVerseIndex.cached(
            ol_project.project_id,
            ol_records_all,
            service.project_schema(ol_project),
        )
    policy = load_workflow_profile(config, config.workflow(workflow)).evidence_policy("stc")
    # A portion the WIP has no text for cannot be compared; it is reported NOT_ASSESSED, not a reason to stop.
    absent_portions: list[str] = []
    unplannable_spans: list[dict[str, Any]] = []
    planned_units: list[Any] = []
    for portion_index, portion in enumerate(analysis_scope_portions(scope), start=1):
        portion_records = tuple(
            record for record in wip_records_all if any(portion.contains(ref) for ref in record.refs)
        )
        if not portion_records and work_unit_id is None:
            absent_portions.append(portion.label())
            continue
        portion_records = select_records_for_scope(wip_records_all, portion)
        planned_units.extend(
            plan_stc_work_units(
                portion_records,
                (
                    ol_records_all
                    if stc_planner_version == STC_PLANNER_VERSION
                    else tuple(
                        record
                        for record in ol_records_all
                        if any(portion.contains(ref) for ref in record.refs)
                    )
                ),
                policy,
                unit_prefix=(parent_plan_id or f"STC-{scope.book}")
                + f"-P{portion_index:03d}",
                wip_index=wip_index,
                ol_index=ol_index,
                context_pool=wip_records_all,
                planner_version=stc_planner_version,
                excluded=unplannable_spans if work_unit_id is None else None,
            )
        )
    if not planned_units and not unplannable_spans:
        raise ValidationError(
            f"The WIP has no text in the requested scope {scope.label()}",
            code="STC_WIP_MISSING",
            affected_scope=scope.label(),
        )
    units = tuple(planned_units)
    if (
        stc_planner_version == STC_PLANNER_VERSION
        and work_unit_id is None
        and len(units) == 1
        and not context_before
        and not context_after
    ):
        # A scope that fits one unit still gets the planner's boundary context verses.
        only_unit = units[0].to_dict()
        context_before = tuple(only_unit.get("context_before") or ())
        context_after = tuple(only_unit.get("context_after") or ())
    # OL text the WIP lacks anywhere in the requested scope, including whole missing chapters.
    stc_omissions: list[dict[str, Any]] = []
    if stc_planner_version == STC_PLANNER_VERSION and work_unit_id is None:
        assert wip_index is not None and ol_index is not None
        wip_book_file = _one_book_file(output, scope.book)
        stc_omissions = omission_rows(
            wip_records_all,
            wip_index,
            ol_records_all,
            ol_index,
            scope,
            workflow="STC",
            authority_stream=f"{family}:PRIMARY",
            authority_project_id=ol_project.project_id,
            wip_project_id=output.project_id,
            title_chapters=(
                psalm_title_chapters(wip_book_file.read_text(encoding="utf-8-sig"))
                if wip_book_file is not None and scope.book == "PSA"
                else ()
            ),
        )
    if auto_partition and work_unit_id is None and (len(units) > 1 or absent_portions or unplannable_spans):
        seed = sha256_bytes(json.dumps({
            "job_id": job_id, "run_id": run_id, "scope": scope.label(),
            "wip": output.project_id, "ol": ol_project.project_id, "family": family,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        plan_id = f"STC-{scope.book}-{seed[:10].upper()}"
        children: list[dict[str, Any]] = []
        created_children = []
        try:
            for unit in units:
                item = unit.to_dict()
                child = create_act_task(
                    config,
                    workflow=workflow,
                    operation="stc",
                    output_project_id=output.project_id,
                    contemporary_source_id=contemporary_source_id,
                    scope_value=item["primary_scope"],
                    auto_partition=False,
                    parent_plan_id=plan_id,
                    work_unit_id=unit.unit_id,
                    job_id=job_id,
                    run_id=run_id,
                    stc_planner_version=stc_planner_version,
                    context_before_references=item["context_before"],
                    context_after_references=item["context_after"],
                )
                created_children.append(child)
                children.append({
                    "unit_id": unit.unit_id,
                    "scope": item["primary_scope"],
                    "task_id": child["task_id"],
                    "manifest_path": child["manifest_path"],
                    "task_fingerprint": child["task_fingerprint"],
                    "primary_coverage_atoms": item["primary_coverage_atoms"],
                })
        except Exception:
            # A partitioner that fails mid-loop must not leave orphan child tasks behind.
            _rollback_unregistered_stage_tasks(config, workflow, run_id, created_children)
            raise
        expected = [ref.label() for ref in sorted({ref for unit in units for ref in unit.primary_refs})]
        plan = {
            "schema_version": "1.0", "status": "PARTITIONED", "plan_id": plan_id,
            "workflow": workflow, "operation": "stc", "job_id": job_id, "run_id": run_id,
            "requested_scope": scope.label(), "output_project": output.project_id,
            "contemporary_source": None, "primary_ol_authority": ol_project.project_id,
            "authority_family": family, "authority_role": "PRIMARY",
            "stc_planner_version": stc_planner_version,
            "expected_references": expected, "work_units": children,
            "coverage_gap_issues": stc_omissions,
            "not_assessed_portions": [
                {
                    "scope": label,
                    "code": "STC_WIP_PORTION_MISSING",
                    "message": f"The WIP has no text in {label}, so it was not compared with the original language.",
                }
                for label in absent_portions
            ] + [
                {
                    "scope": (
                        span["references"][0]
                        if len(span["references"]) == 1
                        else f"{span['references'][0]}-{span['references'][-1]}"
                    ),
                    "code": span["code"],
                    "message": f"No work unit could hold {span['references'][0]} within the hard limits, so it was not compared with the original language.",
                }
                for span in unplannable_spans
            ],
        }
        plan_path = plan_container(config.workflow(workflow), run_id) / f"{plan_id}.json"
        atomic_write_json(plan_path, plan)
        return {**plan, "plan_path": str(plan_path), "task_manifests": [row["manifest_path"] for row in children]}

    output_file = _one_book_file(output, scope.book)
    ol_file = _one_book_file(ol_project, scope.book)
    assert output_file is not None and ol_file is not None
    all_context = tuple(context_before) + tuple(context_after)
    stc_alignment: dict[str, Any] | None = None
    stc_source_issue_rows: list[dict[str, Any]] | None = None
    ol_primary_references: list[str] | None = None
    ol_context_references: list[str] = list(all_context)
    if stc_planner_version == STC_PLANNER_VERSION:
        assert wip_index is not None and ol_index is not None
        primary_wip = select_records_for_scope(wip_records_all, scope)
        context_wip = _records_intersecting_reference_values(
            wip_records_all,
            all_context,
        )
        primary_alignment = align_records(primary_wip, wip_index, ol_index)
        context_alignment = align_records(context_wip, wip_index, ol_index)
        authority_stream = f"{family}:PRIMARY"
        ol_primary_references = [
            record.reference for record in primary_alignment.authority_records
        ]
        ol_context_references = [
            record.reference for record in context_alignment.authority_records
        ]
        stc_alignment = {
            "primary_local_atoms": [
                ref.label() for ref in sorted(primary_alignment.primary_local_refs)
            ],
            "canonical_atoms": [
                ref.label() for ref in sorted(primary_alignment.canonical_refs)
            ],
            "authority_stream": authority_stream,
            "authority_local_spans": ol_primary_references,
            "missing_canonical_atoms": [
                ref.label() for ref in sorted(primary_alignment.missing_canonical_refs)
            ],
            # WIP verses whose original-language verses carry other numbers (shift, merge, or split).
            "verse_correspondence": record_correspondence(primary_wip, wip_index, ol_index),
            # Verses far shorter or longer than their OL text: candidates for omissions and additions.
            "length_outliers": length_outliers(primary_wip, wip_records_all, wip_index, ol_index),
            # Verses missing the WIP's usual rendering of an original-language name.
            "name_check": _stc_name_check(config, output, service, primary_wip),
            "numeric_candidates": numeric_candidates(
                config,
                [
                    (
                        VerseRef(record.book, record.chapter, record.verse_start),
                        record.reference,
                        str(record.payload.get("body_text") or ""),
                    )
                    for record in primary_wip
                ],
            ),
        }
        stc_source_issue_rows = _canonical_gap_source_issues(
            primary_wip,
            wip_index,
            primary_alignment.missing_canonical_refs,
            workflow="STC",
            source_stream=authority_stream,
            source_project_id=ol_project.project_id,
            wip_project_id=output.project_id,
            scope=scope.label(),
        ) + stc_omissions
    seed = sha256_bytes(json.dumps({
        "job_id": job_id, "run_id": run_id, "scope": scope.label(),
        "wip": output.project_id, "ol": ol_project.project_id, "family": family,
        "work_unit_id": work_unit_id, "context": list(all_context),
        "stc_planner_version": stc_planner_version,
        "stc_alignment": stc_alignment,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    base_task_id = f"stc-{scope.book.lower()}-{seed[:12]}"
    task_id = base_task_id
    active_root = task_container(config.workflow(workflow), run_id)
    sequence = 1
    while (active_root / task_id).exists():
        sequence += 1
        task_id = f"{base_task_id}-r{sequence}"
    task_root = active_root / task_id
    packet_root = task_root / "packet"
    output_root = task_root / "output"
    packet_root.mkdir(parents=True, exist_ok=False)
    output_root.mkdir(parents=True, exist_ok=False)
    try:
        wip_path = packet_root / "wip.sfm"
        ol_path = packet_root / "original-language.sfm"
        wip_packet = _bounded_sfm_packet(output_file, scope, wip_path, context_references=all_context)
        ol_packet = _bounded_sfm_packet(
            ol_file,
            scope,
            ol_path,
            primary_references=ol_primary_references,
            context_references=ol_context_references,
            allow_empty=True,
            text_filter=routed_ol_text_filter_for_book(scope.book),
        )
        expected_references = list(wip_packet["primary_references"])
        source_issue_rows = (
            stc_source_issue_rows
            if stc_source_issue_rows is not None
            else list(source_text_issues(
                (ref for value in expected_references for ref in expand_reference_atoms(value)),
                (
                    ref
                    for value in ol_packet["primary_references"]
                    for ref in expand_reference_atoms(str(value))
                ),
                workflow="STC",
                source_stream=f"{family}:PRIMARY",
                source_project_id=ol_project.project_id,
                wip_project_id=output.project_id,
                scope=scope.label(),
            ))
        )
        target_grammar_path, target_profile = _write_grammar_contract(config, output, packet_root, "wip")
        if target_grammar_path is None or target_profile is None:
            raise ValidationError(
                f"STC WIP {output.project_id} has no canonical LANGUAGE_PROFILE",
                code="LINGUISTIC_PROFILE_MISSING",
            )
        bound_job = _load_owning_job(config, job_id, workflow)
        report_grammar_path, report_profile = _write_report_language_contract(
            config,
            bound_job.primary_report_language,
            packet_root,
            "report-primary",
        )
        if sha256_file(report_grammar_path) == sha256_file(target_grammar_path):
            report_grammar_path.unlink(missing_ok=True)
            report_grammar_path = target_grammar_path
        ol_profile_path = packet_root / "ol-authority-profile.yml"
        ol_profile = _copy_ol_authority_profile(ol_project, family, ol_profile_path)
        ol_profile["path"] = _relative(config.root, ol_profile_path)
        skill_registry = load_skill_registry(config.root)
        skill = skill_registry.get((workflow, "stc")) or skill_registry[("saw", "stc")]
        skill_files = [{"path": _relative(config.root, item), "sha256": sha256_file(item)} for item in _skill_files(skill)]
        allowed_reads = [
            {"path": _relative(config.root, wip_path), "sha256": sha256_file(wip_path), "evidence_class": SUBJECT_TEXT},
            {"path": _relative(config.root, ol_path), "sha256": sha256_file(ol_path), "evidence_class": AUTHORIZED_CONTENT_EVIDENCE},
            {"path": _relative(config.root, target_grammar_path), "sha256": sha256_file(target_grammar_path), "evidence_class": LINGUISTIC_COMPETENCE_RULES},
            {"path": _relative(config.root, ol_profile_path), "sha256": sha256_file(ol_profile_path), "evidence_class": AUTHORITY_INTERPRETATION_RULES},
        ]
        if report_grammar_path != target_grammar_path:
            allowed_reads.append({
                "path": _relative(config.root, report_grammar_path),
                "sha256": sha256_file(report_grammar_path),
                "evidence_class": LINGUISTIC_COMPETENCE_RULES,
            })
        governance_inputs = [
            {"path": _relative(config.root, config.workflow(workflow).profile_path), "sha256": sha256_file(config.workflow(workflow).profile_path), "evidence_class": PROCESS_CONTROL},
            *[{"path": item["path"], "sha256": item["sha256"], "evidence_class": PROCESS_CONTROL} for item in skill_files],
        ]
        narrative_language = _narrative_language_contract(config)
        ol_binding_key = expected_role
        project_identities = resolve_project_identities(
            config.root,
            {"WIP": output.project_id, ol_binding_key: ol_project.project_id},
            config.projects,
            compiled,
        )
        resource_bindings = identity_bindings(project_identities)
        resource_display_names = identity_display_names(project_identities)
        project_fingerprints = {
            identity.project_id: identity.content_fingerprint
            for identity in project_identities.values()
        }
        route_bytes = int(wip_packet["serialized_bytes"]) + int(ol_packet["serialized_bytes"])
        route_tokens = int(wip_packet["estimated_tokens"]) + int(ol_packet["estimated_tokens"])
        if route_bytes > policy.hard_serialized_bytes or route_tokens > policy.hard_estimated_tokens:
            raise EvidenceLimitError(
                "STC routed WIP+OL SFM exceeds the hard review-item limit",
                affected_scope=scope.label(),
                details={"serialized_bytes": route_bytes, "estimated_tokens": route_tokens},
            )
        linguistic_profile_bindings = [
            {
                "stream_id": "WIP", "profile_class": "LANGUAGE_PROFILE",
                "profile_id": target_profile.profile_id, "language": target_profile.language,
                "path": _relative(config.root, target_grammar_path), "sha256": sha256_file(target_grammar_path),
            },
            {
                "stream_id": "REPORT:PRIMARY", "profile_class": "LANGUAGE_PROFILE",
                "profile_id": report_profile.profile_id, "language": report_profile.language,
                "path": _relative(config.root, report_grammar_path), "sha256": sha256_file(report_grammar_path),
            },
            {
                "stream_id": f"{family}:PRIMARY", **ol_profile,
            },
        ]
        identity = {
            "schema_version": "2.4", "execution_mode": "SAGE_GOVERNED_TASK_V1",
            "workflow": workflow, "operation": "stc", "rtc_stage": None,
            "stc_planner_version": stc_planner_version,
            "stc_alignment": stc_alignment,
            "deterministic_candidates": candidate_inventory(
                numeric=(stc_alignment or {}).get("numeric_candidates"),
                lengths=(stc_alignment or {}).get("length_outliers", []),
                names=((stc_alignment or {}).get("name_check") or {}).get("candidates", []),
            ),
            "skill_id": skill.skill_id,
            "job_id": job_id, "run_id": run_id,
            "resource_bindings": resource_bindings,
            "resource_display_names": resource_display_names,
            "output_project": output.project_id, "output_content_state": output.content_state,
            "contemporary_source": None, "primary_ol_authority": ol_project.project_id,
            "original_language_sources": [{
                "role": expected_role, "project": ol_project.project_id, "routing": "DIRECT",
                "authority_family": family, "authority_role": "PRIMARY",
            }],
            "lexical_donor": None, "scope": scope.label(), "focus": None, "check_type": None,
            "parent_plan_id": parent_plan_id, "work_unit_id": work_unit_id or task_id,
            "context_references": {"mode": "CONTEXT_ONLY", "before": list(context_before), "after": list(context_after)},
            "skill": {
                "id": skill.skill_id, "entrypoint": _relative(config.root, skill.path), "files": skill_files,
                "source_system": skill.source_system, "source_version": skill.source_version,
                "original_file": _relative(config.root, skill.original_file), "original_sha256": skill.original_sha256,
                "adapted_sha256": skill.adapted_sha256, "qualification_status": skill.qualification_status,
            },
            "project_grammar": {
                "profile_id": target_profile.profile_id, "language": target_profile.language,
                "status": target_profile.status, "profile_sha256": target_profile.sha256,
                "rule_ids": [row["rule_id"] for row in target_profile.checks],
                "contract": _relative(config.root, target_grammar_path),
            },
            "source_grammar": None,
            "linguistic_profile_bindings": linguistic_profile_bindings,
            "evidence_policy": task_evidence_policy(workflow),
            "packets": {"wip": wip_packet, "original_language": {**ol_packet, "evidence_id": expected_role}},
            "structural_issues": source_issue_rows,
            "source_text_issues": source_issue_rows,
            "preflight": None,
            "resource_fingerprints": {
                "settings": sha256_file(config.settings_path), "workflow_profile": sha256_file(config.workflow(workflow).profile_path),
                "skill_entrypoint": sha256_file(skill.path),
                f"project.{output.project_id}": project_fingerprints[output.project_id],
                f"project.{ol_project.project_id}": project_fingerprints[ol_project.project_id],
                "packet.wip": sha256_file(wip_path), "packet.original_language": sha256_file(ol_path),
                "profile.wip": sha256_file(target_grammar_path),
                "profile.report_primary": sha256_file(report_grammar_path),
                "profile.ol": sha256_file(ol_profile_path),
            },
            "expected_references": expected_references, "primary_coverage": expected_references,
            "structural_candidate_ids": [], "allowed_evidence_ids": ["WIP", expected_role],
            "governance_inputs": governance_inputs, "allowed_reads": allowed_reads, "conditional_reads": [],
            "allowed_writes": ["output/findings.json"],
            "narrative_language": narrative_language,
            "human_output": {
                "logs_and_reports": {"primary_language": config.human_output.logs_and_reports.primary_language, "secondary_language": config.human_output.logs_and_reports.secondary_language, "bilingual": config.human_output.logs_and_reports.bilingual},
            },
            "output_grammar": "STC_FINDINGS_1.0",
            "review_requirements": {"required_checks": ["STC_CORRESPONDENCE"], "controller_checks": [], "expected_work_unit_ids": [work_unit_id or task_id]},
            "context_budget": {
                "estimator": TOKEN_ESTIMATOR, "measurement_scope": "routed_analysis_sfm",
                "planning_basis": "ROUTED_SFM_ONLY", "serialized_bytes": route_bytes, "estimated_tokens": route_tokens,
                "final_serialized_bytes": route_bytes, "final_estimated_tokens": route_tokens, "policy": policy.to_dict(),
            },
            "forbidden_actions": ["broaden_scope", "read_unlisted_files", "use_external_content_evidence", "modify_locked_projects"],
        }
        fingerprint = sha256_bytes(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        submit_argv = ["--settings", config.settings_path.name, "task", "submit", "--task", _relative(config.root, task_root / "task-manifest.json")]
        submit_commands = {"posix": render_sage_command(submit_argv, windows=False), "windows": render_sage_command(submit_argv, windows=True)}
        manifest = {**identity, "task_id": task_id, "task_root": _relative(config.root, task_root), "submit_commands": submit_commands, "task_fingerprint": fingerprint, "created_utc": utc_now()}
        manifest_path = task_root / "task-manifest.json"
        act_path = task_root / "ACT.md"
        act_text = "\n".join([
            f"# SAGE ACT Task: {task_id}", "", "SAGE EXECUTION MODE: GOVERNED TASK V1", "",
            "Execute only this bounded Source Text Correspondence (STC) review.",
            f"- WIP: `{output.project_id}`", f"- Primary OL authority: `{ol_project.project_id}` (`{family}`, PRIMARY)",
            f"- Scope: `{scope.label()}`", f"- Work unit: `{work_unit_id or task_id}`", "",
            "## Evidence", "",
            "Use only the supplied WIP + OL slice as evidence.",
            "Do not use ANY information outside that slice to form or support a finding.",
            "If a finding cannot be established from the supplied WIP + OL slice, do not report it.",
            "The complete routed linguistic profiles govern language, dialect, and historical register but are not Scripture evidence.",
            "Do not infer canonical language identity from the text; obey the bound profiles.", "",
            "## Task", "",
            "Compare OL element/phrase/construction with the WIP rendering. Do not assume one-to-one lexical alignment.",
            "Report only governed OMISSION, ADDITION, VARIATION, or CONSISTENCY findings established by the bounded evidence.",
            "Review every assigned primary coordinate even if there are zero findings.",
            "Cite `target_reference` in WIP verse numbering; `wip_to_original_language_verses` lists the WIP verses whose OL verses carry other numbers.",
            "Quote `wip_evidence` and `ol_evidence` verbatim from the supplied slice; SAGE checks every quotation against it.",
            "SAGE already reports text present on only one side as OMISSION or ADDITION; do not restate those coordinates.",
            "Names: a `NAME` candidate is a verse whose original-language text has a name but whose WIP text lacks the WIP's usual rendering of it. Report a CONSISTENCY finding when the name is spelled differently, replaced by another name, or left out so the meaning changes; a pronoun or restructured sentence that keeps the meaning is not a finding.",
            "Check each `verse_length_outliers` verse closely for a material omission or addition; its length alone is not a finding.",
            "Numbers: `numeric_candidates` compares WIP digits with the number index (see its caveat). Report no number finding for a `MATCH` verse; the NCA tool checks numbers in full.",
            "Original-language words: in each finding's `ol_words`, list the original-language words the finding depends on, with their lemma and parse; SAGE checks each against MACULA and marks a finding whose analysis MACULA contradicts as unverified.", "",
            *(
                [
                    "## Structural issues", "",
                    "Do not invent wording for source coordinates reported as absent; continue the run using only supplied evidence.",
                    *[f"- `{row['reference']}` — {row['message']}" for row in source_issue_rows], "",
                ]
                if source_issue_rows
                else []
            ),
            "## Allowed model reads", "",
            *[f"- `{item['path']}` — `{item['evidence_class']}`" for item in allowed_reads], "",
            "## Allowed writes", "", "- `output/findings.json`", "",
            f"Canonical generated narrative language: `{narrative_language['tag']}`.",
        ])
        return seal_task(
            config, workflow=workflow, operation="stc", job_id=job_id, run_id=run_id, task_root=task_root,
            manifest_path=manifest_path, manifest=manifest, act_path=act_path, act_text=act_text,
            allowed_writes=["output/findings.json"],
        )
    except Exception:
        import shutil
        shutil.rmtree(task_root, ignore_errors=True)
        raise
