"""ACT task submission: integrity checks against the sealed control record (verify_sealed_submission), then
per-workflow validation and salvage records (submit_act_task).

Split from act_tasks.py, which re-exports every name defined here.
"""

from __future__ import annotations

from .act_outputs import classify_bic_usfm_verses
from .act_outputs import execution_route_from_receipt
from .act_outputs import render_action_report
from .act_outputs import render_operator_note_text
from .act_outputs import validate_analysis_findings
from .act_outputs import validate_bic_inspect_output
from .act_outputs import validate_grammar_assessment
from .atomic import atomic_write_json
from .atomic import atomic_write_text
from .bic_memory import submit_inspect_transactionally
from .bounded_target import drop_verse_blocks
from .bounded_target import expand_unsafe_drops
from .bounded_target import merge_bounded_usfm
from .bounded_target import record_target_commit
from .errors import ValidationError
from .evidence_policy import PROCESS_CONTROL
from .evidence_policy import task_evidence_policy
from .evidence_policy import validate_read_class
from .exception_reports import ExceptionRecord
from .exception_reports import NOT_ASSESSED
from .exception_reports import record_exception
from .external_access import validate_external_file
from .hashing import sha256_bytes
from .hashing import sha256_file
from .human_output import report_language_authority
from .jobs import Job, JobStore
from .ol_analysis import make_ol_checker
from .locking import WorkspaceLock
from .references import parse_scope
from .registry import EcosystemConfig
from .registry import load_ecosystem
from .rewrite_risk import render_rewrite_challenge_report
from .rewrite_risk import validate_rewrite_challenges
from .runtime_paths import validate_context_id
from .runtime_paths import workflow_for_task
from .source_coverage import source_comparison_status
from .source_coverage import unique_source_text_issues
from .state import utc_now
from .stc import LEGACY_STC_PLANNER_VERSION
from .stc import finalize_stc_run
from .stc import stc_gap_findings
from .stc import validate_stc_submission
from .stc_reporting import publish_stc_reports
from .storage import StorageError
from .storage import resolve_declared_path
from .storage import resolve_persisted_path
from .task_retry import provider_output_contract
from .transactions import FileTransaction
from .vrs import VerseRef
from .workflow_identity import is_analysis_workflow
from .workflow_identity import legacy_saw_workflow
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Mapping
from typing import Sequence
import json
import os
from .act_common import (
    ACT_OPERATIONS,
    _analysis_code,
    _expected_outputs,
    _load_owning_job,
    _memory_root,
    _narrative_language_contract,
    _one_book_file,
    _safe_task_output,
    _target_book_filename,
)



def _load_control(config: EcosystemConfig, workflow: str, task_id: str) -> tuple[Path, dict[str, Any]]:
    """Load an immutable ACT control file and require a JSON object."""
    path = config.workflow(workflow).state_root / "act-tasks" / f"{task_id}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Trusted ACT control record is missing or invalid: {path}") from exc
    if not isinstance(value, dict):
        raise ValidationError("Trusted ACT control record must be a JSON object")
    return path, value


def _update_control(path: Path, value: dict[str, Any]) -> None:
    """Update generated control state only through the controller-owned atomic write path."""
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass
    atomic_write_json(path, value)
    try:
        os.chmod(path, 0o444)
    except OSError:
        pass


def _optional_text(path: Path) -> str | None:
    """Read one routed packet as text, or None when the task has no such packet."""
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError:
        return None


def _record_salvage_exceptions(
    run_root: Path,
    *,
    workflow: str,
    job_id: str,
    run_id: str,
    task_id: str,
    stage: str,
    scope: str,
    items: Sequence[Mapping[str, Any]],
    effect: str = "FLAGGED",
) -> None:
    """Report each item the controller dropped, corrected, or flagged while still accepting the unit's output."""
    for item in items:
        coordinate = str(item.get("coordinate") or item.get("reference") or "") or scope
        record_exception(
            run_root,
            ExceptionRecord(
                tool=workflow.upper(),
                code=str(item.get("code") or "ITEM_SALVAGED"),
                message=str(item.get("message") or "Defective model output was salvaged."),
                effect=str(item.get("effect") or effect),
                run_id=run_id,
                job_id=job_id,
                task_id=task_id,
                work_unit=str(item.get("challenge_id") or item.get("submitted_id") or "") or None,
                stage=stage,
                coordinates=(coordinate,),
            ),
        )


@dataclass(frozen=True)
class SealedSubmission:
    """A submission whose sealed task, inputs, outputs, and execution receipt passed integrity checks."""

    config: EcosystemConfig
    task_root: Path
    workflow_hint: str
    job_id: str
    run_id: str
    job_store: JobStore
    owning_job: Job
    workflow: str
    task_id: str
    control_path: Path
    control: dict[str, Any]
    raw: dict[str, Any]
    operation: str
    allowed_writes: tuple[str, ...]
    output_paths: dict[str, Path]
    execution_route: dict[str, Any]


def verify_sealed_submission(config: EcosystemConfig, task_manifest: Path) -> SealedSubmission:
    """Check a task's immutable controls, exact reads, outputs, and receipt before any per-tool validation."""
    # Revalidate immutable controls before interpreting model output or committing workflow state.
    path = task_manifest.expanduser().resolve()
    task_root = path.parent
    try:
        prelim = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid ACT task manifest: {exc}") from exc
    if not isinstance(prelim, dict):
        raise ValidationError("ACT task manifest must be a JSON object")
    workflow_hint = str(prelim.get("workflow", "")).strip().lower()
    job_id = validate_context_id(prelim.get("job_id"), "job_id")
    run_id = validate_context_id(prelim.get("run_id"), "run_id")
    if workflow_hint not in ACT_OPERATIONS or not job_id or not run_id:
        raise ValidationError("ACT task manifest is missing canonical workflow/Job/Run identity")
    job_store = JobStore(config.root, config.settings_path)
    owning_job = _load_owning_job(config, job_id, workflow_hint)
    runtime_settings = (
        owning_job.runtime_settings_path
        if workflow_hint == "nca" and owning_job.runtime_settings_path.is_file()
        else job_store.ensure_runtime_files(owning_job)
    )
    config = load_ecosystem(runtime_settings)
    workflow = workflow_for_task(config, task_root)
    task_id = task_root.name
    control_path, control = _load_control(config, workflow, task_id)
    if control.get("status") != "CREATED":
        raise ValidationError(f"ACT task is not open for submission: {control.get('status')}")
    if control.get("settings_sha256") != sha256_file(config.settings_path):
        raise ValidationError(
            "Settings changed after ACT task creation; the sealed task cannot be submitted",
            code="ACT_INPUT_STALE",
            next_action="Use Restart active Run from the Job menu; the old Run will be preserved.",
        )
    if resolve_persisted_path(config.root, str(control.get("manifest_path", "")), "ACT manifest") != path:
        raise ValidationError("ACT manifest path differs from the trusted control record", code="TASK_SUBMISSION_TAMPERED")
    if resolve_persisted_path(config.root, str(control.get("task_root", "")), "ACT task root") != task_root:
        raise ValidationError("ACT task root differs from the trusted control record", code="TASK_SUBMISSION_TAMPERED")
    if sha256_file(path) != control.get("manifest_sha256"):
        raise ValidationError("ACT task manifest changed after task creation", code="TASK_SUBMISSION_TAMPERED")
    act_path = resolve_persisted_path(config.root, str(control.get("act_path", "")), "ACT prompt")
    if act_path != (task_root / "ACT.md").resolve() or not act_path.is_file():
        raise ValidationError("ACT prompt path differs from the trusted control record", code="TASK_SUBMISSION_TAMPERED")
    if sha256_file(act_path) != control.get("act_sha256"):
        raise ValidationError("ACT prompt changed after task creation", code="TASK_SUBMISSION_TAMPERED")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid ACT task manifest: {exc}") from exc
    if raw.get("task_id") != task_id:
        raise ValidationError("ACT task_id differs from its directory and trusted control", code="TASK_SUBMISSION_TAMPERED")
    if raw.get("task_fingerprint") != control.get("task_fingerprint"):
        raise ValidationError("ACT task fingerprint differs from trusted control", code="TASK_SUBMISSION_TAMPERED")
    identity = {
        key: value
        for key, value in raw.items()
        if key not in {"task_id", "task_root", "submit_commands", "task_fingerprint", "created_utc"}
    }
    recomputed = sha256_bytes(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    if recomputed != raw.get("task_fingerprint"):
        raise ValidationError("ACT task fingerprint cannot be recomputed from the manifest", code="TASK_SUBMISSION_TAMPERED")
    if raw.get("execution_mode") != "SAGE_GOVERNED_TASK_V1":
        raise ValidationError("ACT task execution_mode is not a supported governed task mode")
    if raw.get("workflow") != workflow or raw.get("operation") != control.get("operation"):
        raise ValidationError("ACT workflow or operation differs from trusted control", code="TASK_SUBMISSION_TAMPERED")
    if raw.get("schema_version") != "2.4":
        raise ValidationError("ACT task schema_version must be 2.4")
    expected_narrative_language = _narrative_language_contract(config)
    if raw.get("narrative_language") != expected_narrative_language:
        raise ValidationError(
            "ACT narrative language is missing or differs from the owning Job",
            code="ACT_REPORT_LANGUAGE_MISMATCH",
            next_action="Recreate the task from the current Job configuration.",
        )
    if raw.get("evidence_policy") != task_evidence_policy(workflow):
        raise ValidationError(
            "ACT task evidence policy is missing or differs from the canonical local-evidence boundary",
            code="ACT_EVIDENCE_POLICY_INVALID",
        )

    for field_name in ("governance_inputs", "allowed_reads"):
        for item in raw.get(field_name, []):
            if not isinstance(item, dict):
                raise ValidationError(f"ACT {field_name} contains a non-object entry")
            evidence_class = validate_read_class(item.get("evidence_class"))
            if field_name == "governance_inputs" and evidence_class != PROCESS_CONTROL:
                raise ValidationError("ACT governance input must use PROCESS_CONTROL evidence class")
            try:
                read_path = resolve_declared_path(config.root, str(item.get("path", "")), f"ACT {field_name} path")
            except StorageError as exc:
                raise ValidationError(str(exc), code="EXTERNAL_PATH_ESCAPE") from exc
            if not read_path.is_file():
                raise ValidationError(f"ACT input is missing: {item.get('path')}")
            if sha256_file(read_path) != item.get("sha256"):
                raise ValidationError(
                    f"ACT input changed after task creation: {item.get('path')}",
                    code="ACT_INPUT_STALE",
                    next_action="Use Restart active Run from the Job menu; the old Run will be preserved.",
                )

    for item in raw.get("conditional_reads", []):
        if not isinstance(item, dict):
            raise ValidationError("ACT conditional_reads contains a non-object entry")
        validate_read_class(item.get("evidence_class"))
        if item.get("condition") != "MATERIAL_SEMANTIC_RISK_LEVEL_2_WITH_TRIGGER":
            raise ValidationError("ACT conditional OL read has an unsupported condition")
        try:
            read_path = resolve_declared_path(config.root, str(item.get("path", "")), "ACT conditional input path")
        except StorageError as exc:
            raise ValidationError(str(exc), code="EXTERNAL_PATH_ESCAPE") from exc
        if not read_path.is_file():
            raise ValidationError(f"ACT conditional input is missing: {item.get('path')}")
        if sha256_file(read_path) != item.get("sha256"):
            raise ValidationError(
                f"ACT conditional input changed after task creation: {item.get('path')}",
                code="ACT_INPUT_STALE",
            )

    operation = str(raw.get("operation", ""))
    expected_writes = _expected_outputs(workflow, operation)
    allowed_writes = tuple(str(value) for value in control.get("allowed_writes", []))
    if allowed_writes != expected_writes:
        raise ValidationError("Trusted ACT control write allowlist is corrupt", code="TASK_SUBMISSION_TAMPERED")
    if tuple(raw.get("allowed_writes", [])) != expected_writes:
        raise ValidationError("ACT write allowlist differs from trusted control", code="TASK_SUBMISSION_TAMPERED")
    output_paths = {value: _safe_task_output(task_root, value) for value in allowed_writes}
    missing = [value for value, output_path in output_paths.items() if not output_path.is_file()]
    if missing:
        raise ValidationError("ACT output is incomplete: " + ", ".join(sorted(missing)))
    actual = {
        output_path.relative_to(task_root).as_posix()
        for output_path in (task_root / "output").rglob("*")
        if output_path.is_file()
    }
    unexpected = sorted(actual - set(allowed_writes))
    if unexpected:
        raise ValidationError("ACT task created unlisted outputs: " + ", ".join(unexpected))
    output_hashes = {
        relative: sha256_file(output_path)
        for relative, output_path in output_paths.items()
    }
    try:
        execution_route = execution_route_from_receipt(
            task_root,
            task_id=task_id,
            output_hashes=output_hashes,
        )
    except ValidationError as exc:
        if exc.code != "EXECUTION_RECEIPT_MISSING" or is_analysis_workflow(workflow):
            # RTC and STC output must come from a recorded provider route; only legacy BIC/NCA
            # fixtures may still be submitted without a receipt.
            raise
        # Pre-release preserved tasks and manually supplied Alpha fixtures may lack
        # a runtime receipt; record the absence without claiming a current route.
        execution_route = {
            "status": "UNRECORDED",
            "task_id": task_id,
            "skill_id": raw.get("skill_id"),
            "route_id": None,
            "provider": None,
            "model": None,
            "reasoning_effort": None,
            "routing_mode": None,
            "qualification_status": "UNVERIFIED",
            "receipt_path": None,
            "receipt_sha256": None,
        }
    return SealedSubmission(
        config=config,
        task_root=task_root,
        workflow_hint=workflow_hint,
        job_id=job_id,
        run_id=run_id,
        job_store=job_store,
        owning_job=owning_job,
        workflow=workflow,
        task_id=task_id,
        control_path=control_path,
        control=control,
        raw=raw,
        operation=operation,
        allowed_writes=allowed_writes,
        output_paths=output_paths,
        execution_route=execution_route,
    )


def submit_act_task(config: EcosystemConfig, task_manifest: Path) -> dict[str, Any]:
    """Validate immutable controls, exact reads, output grammar, and governed commit."""
    sealed = verify_sealed_submission(config, task_manifest)
    config = sealed.config
    task_root = sealed.task_root
    workflow_hint = sealed.workflow_hint
    job_id = sealed.job_id
    run_id = sealed.run_id
    job_store = sealed.job_store
    owning_job = sealed.owning_job
    workflow = sealed.workflow
    task_id = sealed.task_id
    control_path = sealed.control_path
    control = sealed.control
    raw = sealed.raw
    operation = sealed.operation
    allowed_writes = sealed.allowed_writes
    output_paths = sealed.output_paths
    execution_route = sealed.execution_route

    validation_details: dict[str, Any]
    commit: dict[str, Any] | None = None
    stc_publication: dict[str, Any] | None = None
    final_status: str
    conditional_ol_evidence_used = False
    if workflow == "nca" and operation == "numbers":
        from .nca import submit_nca_task

        _normalized, validation_details = submit_nca_task(
            raw, output_paths["output/model-evidence.json"]
        )
        final_status = "FINALIZED"
    elif workflow == "bic" and operation == "inspect":
        fingerprints = dict(raw.get("resource_fingerprints", {}))
        with provider_output_contract("BIC_OUTPUT_INVALID", affected_scope=str(raw["scope"])):
            normalized = validate_bic_inspect_output(
                output_paths["output/inspect-submission.json"],
                task_id=task_id,
                scope_value=str(raw["scope"]),
                resource_fingerprints=fingerprints,
            )
        commit = submit_inspect_transactionally(
            normalized,
            memory_root=_memory_root(config),
            transaction_root=config.workflow("bic").transaction_root,
            bic_job_id=str(raw.get("job_id") or "") or None,
        )
        dropped_items = list(normalized.get("dropped_items") or [])
        _record_salvage_exceptions(
            job_store.load_run(owning_job, run_id).root,
            workflow=workflow_hint,
            job_id=job_id,
            run_id=run_id,
            task_id=task_id,
            stage="INSPECT",
            scope=str(raw["scope"]),
            items=dropped_items,
        )
        validation_details = {
            "format": "BIC_INSPECT_1.0",
            "proposals": len(normalized["proposals"]),
            "challenges": len(normalized["challenges"]),
            "dropped_items": len(dropped_items),
        }
        final_status = "COMMITTED"
    elif workflow == "bic":
        target_reference_values = raw.get(
            "expected_output_references",
            raw["expected_references"],
        )
        if not isinstance(target_reference_values, list) or not target_reference_values:
            raise ValidationError(
                "BIC task has no sealed TARGET-local output references",
                code="BIC_TARGET_VRS_ALIGNMENT_REQUIRED",
                affected_scope=str(raw.get("scope") or ""),
            )
        target_scope_value = str(raw.get("target_scope") or raw["scope"])
        target_scope = parse_scope(target_scope_value)
        expected_refs = {
            VerseRef(ref.split()[0], int(ref.split()[1].split(":")[0]), int(ref.split(":")[1]))
            for ref in target_reference_values
        }
        expected_markers = tuple(raw["packets"]["contemporary_source"]["marker_sequence"])
        output_key = "output/rewrite.usfm" if operation == "rewrite" else "output/self-check.usfm"
        grammar = raw.get("project_grammar") or {}
        with provider_output_contract("BIC_OUTPUT_INVALID", affected_scope=str(raw["scope"])):
            usfm_validation = classify_bic_usfm_verses(
                output_paths[output_key],
                expected_book=target_scope.book,
                expected_references=expected_refs,
                source_marker_sequence=expected_markers,
                marker_policy=str(raw.get("marker_policy") or "SEMANTIC_STRUCTURE_V1"),
            )
            assessment = validate_grammar_assessment(
                output_paths["output/grammar-assessment.json"],
                task_id=task_id,
                scope_value=str(raw["scope"]),
                profile_id=str(grammar.get("profile_id", "")),
                profile_sha256=str(grammar.get("profile_sha256", "")),
                output_path=output_paths[output_key],
                required_rule_ids=list(grammar.get("rule_ids", [])),
            )
        failed_verses = list(usfm_validation.pop("failed_verses", []))
        usfm_validation.pop("passing_blocks", None)
        candidate_text = output_paths[output_key].read_text(encoding="utf-8")
        failed_keys = {
            (int(row["chapter"]), int(row["verse_start"]), int(row["verse_end"])) for row in failed_verses
        }
        # Never commit a kept verse joined to a failing neighbour's tail lines.
        committed_drop = expand_unsafe_drops(candidate_text, target_scope_value, failed_keys) if failed_keys else set()
        for chapter, verse_start, verse_end in sorted(committed_drop - failed_keys):
            label = f"{target_scope.book} {chapter}:{verse_start}" + (f"-{verse_end}" if verse_end != verse_start else "")
            failed_verses.append(
                {
                    "reference": label,
                    "chapter": chapter,
                    "verse_start": verse_start,
                    "verse_end": verse_end,
                    "code": "BIC_VERSE_SPLICE_RISK",
                    "message": f"{label} shares continuation lines with a failing neighbouring verse.",
                }
            )
        for row in failed_verses:
            row["message"] = f"{row['message']} The verse was not rewritten."
        _record_salvage_exceptions(
            job_store.load_run(owning_job, run_id).root,
            workflow=workflow_hint,
            job_id=job_id,
            run_id=run_id,
            task_id=task_id,
            stage=operation.upper(),
            scope=str(raw["scope"]),
            items=failed_verses,
            effect=NOT_ASSESSED,
        )
        challenge_document: dict[str, Any] | None = None
        if operation == "rewrite":
            inherited_path = task_root / "packet" / "translation-challenges.json"
            inherited_rows = json.loads(inherited_path.read_text(encoding="utf-8")) if inherited_path.is_file() else []
            inherited_ids = [str(row.get("challenge_id", "")).upper() for row in inherited_rows if isinstance(row, dict)]
            source_project = config.project(str(raw["contemporary_source"]))
            target_project = config.project(str(raw["output_project"]))
            with provider_output_contract("BIC_OUTPUT_INVALID", affected_scope=str(raw["scope"])):
                challenge_document = validate_rewrite_challenges(
                    output_paths["output/translation-challenges.json"],
                    task_id=task_id,
                    operation=operation,
                    scope_value=str(raw["scope"]),
                    output_path=output_paths[output_key],
                    inherited_challenge_ids=inherited_ids,
                    human_output=config.human_output,
                    source_language=source_project.language_code,
                    target_language=target_project.language_code,
                    ol_evidence_available=any(
                        str(item.get("path", "")).endswith("original-language.sfm")
                        for item in raw.get("conditional_reads", [])
                    ),
                    ol_checker=make_ol_checker(config.root, str(raw["scope"]).split(" ")[0])[0],
                )
            challenge_document["execution_route"] = execution_route
            _record_salvage_exceptions(
                job_store.load_run(owning_job, run_id).root,
                workflow=workflow_hint,
                job_id=job_id,
                run_id=run_id,
                task_id=task_id,
                stage="REWRITE",
                scope=str(raw["scope"]),
                items=challenge_document.get("salvage_records", []),
            )
            conditional_ol_evidence_used = any(
                bool((item.get("ol_referral") or {}).get("performed", False))
                for item in challenge_document.get("challenges", [])
                if isinstance(item, dict)
            )
            validation_root = task_root / "validation"
            atomic_write_json(validation_root / "normalized-translation-challenges.json", challenge_document)
            atomic_write_json(validation_root / "translation-challenge-ledger.json", challenge_document)
            atomic_write_text(
                validation_root / "TRANSLATION-CHALLENGES.md",
                render_rewrite_challenge_report(
                    challenge_document,
                    human_output=config.human_output,
                    source_language=source_project.language_code,
                    target_language=target_project.language_code,
                ),
            )
            from .local_assistive import maybe_write_report_executive_summary

            maybe_write_report_executive_summary(
                config.root,
                validation_root / "TRANSLATION-CHALLENGES.md",
                challenge_document,
            )
        validation_details = {
            "format": (
                "BOUNDED_USFM_GRAMMAR_AND_CHALLENGES_3.1"
                if operation == "rewrite"
                else "BOUNDED_USFM_AND_GRAMMAR_ASSESSMENT_2.0"
            ),
            "usfm": usfm_validation,
            "not_rewritten": [str(row["reference"]) for row in failed_verses],
            "grammar_assessment": {
                "rules": len(assessment["rules"]),
                "issues": assessment["issue_count"],
                "unresolved": len(assessment["unresolved"]),
            },
            "translation_challenges": (
                {
                    "count": len(challenge_document["challenges"]),
                    "material_count": len(
                        challenge_document["reporting"]["material_challenge_ids"]
                    ),
                    "minor_aggregated": challenge_document["reporting"]["minor_summary"]["total"],
                    "reporting_languages": challenge_document["reporting_languages"],
                    "highest_urgency": challenge_document["highest_urgency"],
                    "decision_required": False,
                    "decision_required_ids": [],
                    "attention": challenge_document["attention"],
                }
                if challenge_document is not None
                else None
            ),
        }
        if operation == "self_check":
            project = config.project(str(raw["output_project"]))
            source_project = config.project(str(raw["contemporary_source"]))
            source_file = _one_book_file(source_project, parse_scope(str(raw["scope"])).book)
            assert source_file is not None
            target_file = _one_book_file(project, target_scope.book, optional=True)
            if target_file is None:
                target_file = project.path / _target_book_filename(
                    project, target_scope.book
                )
            if project.external:
                if not project.external_writable_target:
                    raise ValidationError(
                        f"External BIC TARGET {project.project_id} is read-only",
                        code="EXTERNAL_TARGET_WRITE_PROHIBITED",
                    )
                target_file = validate_external_file(target_file, roots=(project.path,), write=True)
            before_text = target_file.read_text(encoding="utf-8") if target_file.is_file() else ""
            # Only verses that passed SELF-CHECK are committed; failing verses keep their existing TARGET text.
            commit_text = drop_verse_blocks(candidate_text, committed_drop) if committed_drop else candidate_text
            after_text = (
                merge_bounded_usfm(
                    before_text, commit_text, target_scope_value, keep_existing=committed_drop
                )
                if before_text.strip()
                else commit_text
            )
            lock_path = config.workflow("bic").lock_root / "self-check-commit.lock"
            with WorkspaceLock(lock_path, "BIC_SELF_CHECK_COMMIT"):
                transaction = FileTransaction(
                    config.workflow("bic").transaction_root,
                    operation="BIC_SELF_CHECK_COMMIT",
                    allowed_roots=(project.path,),
                )
                transaction.stage_bytes(target_file, after_text.encode("utf-8"))
                transaction.commit()
            job_id = str(raw.get("job_id") or "")
            run_id = str(raw.get("run_id") or "")
            if not job_id or not run_id:
                raise ValidationError("BIC commit requires Job and Run identity")
            job = JobStore(config.root, config.settings_path).load_job(job_id, tool="bic")
            history = record_target_commit(
                job_root=job.root,
                target_file=target_file,
                scope_value=target_scope_value,
                before_text=before_text,
                after_text=after_text,
                transaction_id=transaction.transaction_id,
                task_id=str(raw["task_id"]),
                run_id=run_id,
                created_utc=utc_now(),
            )
            commit = {
                "transaction_id": transaction.transaction_id,
                "target_file": str(target_file),
                "target_sha256": sha256_file(target_file),
                "bounded_scope": target_scope_value,
                "source_scope": str(raw["scope"]),
                "history": history,
                "not_committed": [str(row["reference"]) for row in failed_verses],
            }
            final_status = "COMMITTED"
        else:
            if challenge_document and challenge_document["challenges"]:
                final_status = "STAGED_VALIDATED_WITH_CHALLENGES"
            else:
                final_status = "STAGED_VALIDATED"
    elif is_analysis_workflow(workflow) and operation == "stc":
        sources = [
            dict(item)
            for item in raw.get("original_language_sources", [])
            if isinstance(item, dict)
        ]
        if len(sources) != 1:
            raise ValidationError(
                "STC task must bind exactly one primary original-language authority",
                code="STC_OL_AUTHORITY_MISMATCH",
            )
        authority_family = str(sources[0].get("authority_family") or "").strip().upper()
        if authority_family not in {"GRK", "HEB"} or str(sources[0].get("authority_role") or "").upper() != "PRIMARY":
            raise ValidationError(
                "STC task original-language authority identity is invalid",
                code="STC_OL_AUTHORITY_MISMATCH",
            )
        with provider_output_contract("STC_OUTPUT_INVALID", affected_scope=str(raw["scope"])):
            normalized = validate_stc_submission(
                output_paths["output/findings.json"],
                task_id=task_id,
                work_unit_id=str(raw.get("work_unit_id") or task_id),
                scope_value=str(raw["scope"]),
                expected_references=list(raw.get("expected_references", [])),
                authority_family=authority_family,
                task_fingerprint=str(raw.get("task_fingerprint", "")),
                narrative_language=str(dict(raw.get("narrative_language") or {}).get("tag") or ""),
                wip_text=_optional_text(task_root / "packet" / "wip.sfm"),
                ol_text=_optional_text(task_root / "packet" / "original-language.sfm"),
                expected_candidates=list(raw.get("deterministic_candidates") or []),
                ol_checker=make_ol_checker(
                    config.root,
                    str(raw["scope"]).split(" ")[0],
                    dict(raw.get("stc_alignment") or {}).get("verse_correspondence") or [],
                )[0],
            )
        stc_salvage = list(normalized.pop("salvage_records", []) or [])
        if stc_salvage:
            _record_salvage_exceptions(
                job_store.load_run(owning_job, run_id).root,
                workflow=workflow,
                job_id=job_id,
                run_id=run_id,
                task_id=task_id,
                stage="STC",
                scope=str(raw.get("scope") or ""),
                items=stc_salvage,
            )
        normalized_issues = unique_source_text_issues(
            dict(row)
            for row in raw.get("structural_issues", raw.get("source_text_issues", []))
            if isinstance(row, Mapping)
        )
        normalized.update(
            {
                "execution_route": execution_route,
                "job_id": job_id,
                "run_id": run_id,
                "parent_plan_id": raw.get("parent_plan_id"),
                "output_project": raw.get("output_project"),
                "contemporary_source": None,
                "primary_ol_authority": raw.get("primary_ol_authority"),
                "stc_planner_version": (
                    raw.get("stc_planner_version") or LEGACY_STC_PLANNER_VERSION
                ),
                "stc_alignment": raw.get("stc_alignment"),
                "resource_bindings": raw.get("resource_bindings", {}),
                "resource_display_names": raw.get("resource_display_names", {}),
                "resource_fingerprints": raw.get("resource_fingerprints", {}),
                "structural_issues": normalized_issues,
                "source_text_issues": normalized_issues,
            }
        )
        normalized["source_comparison_status"] = source_comparison_status(
            normalized["source_text_issues"]
        )
        # Text gaps found in code are findings too; the model only reviews the text both sides carry.
        known_ids = {str(row.get("finding_id")) for row in normalized["findings"]}
        normalized["findings"].extend(
            row
            for row in stc_gap_findings(
                normalized_issues,
                work_unit_id=str(raw.get("work_unit_id") or task_id),
                authority_family=authority_family,
            )
            if row["finding_id"] not in known_ids
        )
        normalized["finding_count"] = len(normalized["findings"])
        validation_root = task_root / "validation"
        atomic_write_json(validation_root / "normalized-findings.json", normalized)
        validation_details = {
            "format": "STC_FINDINGS_1.0",
            "finding_count": normalized["finding_count"],
            "coverage_count": len(normalized["primary_coverage"]),
            "analytical_completion": normalized["analytical_completion"]["status"],
        }
        if not raw.get("parent_plan_id"):
            canonical_artifacts = finalize_stc_run(
                run_id=run_id,
                planned_units=[
                    {
                        "work_unit_id": str(raw.get("work_unit_id") or task_id),
                        "primary_coverage": list(raw.get("expected_references", [])),
                        "scope": str(raw.get("scope") or ""),
                        "authority_family": authority_family,
                        "authority_role": "PRIMARY",
                    }
                ],
                accepted_results=[normalized],
                output_root=validation_root / "stc",
            )
            stc_publication = publish_stc_reports(
                config,
                job_id=job_id,
                run_id=run_id,
                requested_scope=str(raw.get("scope") or ""),
                results=[normalized],
            )
            validation_details["canonical_artifacts"] = {
                key: str(value) for key, value in canonical_artifacts.items()
            }
        final_status = "FINALIZED"
    else:
        grammar = raw.get("project_grammar") or {}
        if operation == "rtc" and raw.get("rtc_stage") == "SELECTIVE_OL_ADJUDICATION":
            sources = [
                dict(item)
                for item in raw.get("original_language_sources", [])
                if isinstance(item, dict)
            ]
            roles = [
                str(item.get("role") or "")
                for item in sources
                if str(item.get("role") or "") in {
                    "ORIGINAL_LANGUAGE_HEBREW", "ORIGINAL_LANGUAGE_GREEK"
                }
            ]
            packet_role = str(
                dict(dict(raw.get("packets") or {}).get("original_language") or {}).get(
                    "evidence_id" 
                )
                or ""
            )
            if (
                len(roles) != 1
                or packet_role != roles[0]
                or roles[0] not in set(raw.get("allowed_evidence_ids", []))
            ):
                raise ValidationError(
                    "Selective OL task evidence identity does not match its routed testament resource",
                    code=_analysis_code(workflow, "SAW_TASK_CONTRACT_INVALID"),
                    affected_scope=str(raw.get("scope") or ""),
                    next_action="Rebuild the affected selective OL stage from its inherited request ledger.",
                )
        with provider_output_contract(
            _analysis_code(workflow, "SAW_OUTPUT_INVALID"),
            affected_scope=str(raw.get("scope") or ""),
        ):
            normalized = validate_analysis_findings(
                output_paths["output/findings.json"],
                task_id=task_id,
                operation=operation,
                scope_value=str(raw["scope"]),
                focus=raw.get("focus"),
                check_type=raw.get("check_type"),
                expected_references=list(raw.get("expected_references", [])),
                structural_candidate_ids=list(raw.get("structural_candidate_ids", [])),
                grammar_rule_ids=list(grammar.get("rule_ids", [])),
                allowed_evidence_ids=list(raw.get("allowed_evidence_ids", [])),
                task_fingerprint=str(raw.get("task_fingerprint", "")),
                required_review_checks=list((raw.get("review_requirements") or {}).get("required_checks", [])),
                expected_work_unit_ids=list((raw.get("review_requirements") or {}).get("expected_work_unit_ids", [])),
                rtc_stage=raw.get("rtc_stage"),
                expected_ol_request_ids=list((raw.get("review_requirements") or {}).get("expected_ol_request_ids", [])),
                expected_ol_requests=list((raw.get("review_requirements") or {}).get("expected_ol_requests", [])),
                narrative_language=str(
                    dict(raw.get("narrative_language") or {}).get("tag") or ""
                ),
                ol_referral_contract=(
                    str(raw.get("ol_referral_contract"))
                    if raw.get("ol_referral_contract")
                    else None
                ),
                workflow=workflow,
                source_text_drift_adjudication=(
                    str(
                        dict(dict(raw.get("rtc_policy") or {}).get("original_language") or {}).get(
                            "source_text_drift_adjudication", "PROHIBITED"
                        )
                    )
                    if operation == "rtc"
                    else None
                ),
                rtc_policy=(
                    dict(raw["rtc_policy"])
                    if operation == "rtc" and isinstance(raw.get("rtc_policy"), Mapping)
                    else None
                ),
                expected_candidates=list(raw.get("deterministic_candidates") or []),
                ol_checker=(
                    make_ol_checker(config.root, str(raw["scope"]).split(" ")[0])[0]
                    if raw.get("rtc_stage") == "SELECTIVE_OL_ADJUDICATION" or operation == "ol"
                    else None
                ),
            )
        salvage_records = list(normalized.pop("salvage_records", []) or [])
        if salvage_records:
            _record_salvage_exceptions(
                job_store.load_run(owning_job, run_id).root,
                workflow=workflow,
                job_id=job_id,
                run_id=run_id,
                task_id=task_id,
                stage=str(normalized.get("stage") or operation.upper()),
                scope=str(raw.get("scope") or ""),
                items=salvage_records,
            )
        validation_details = {
            "format": (
                "SAW_FINDINGS_2.0"
                if legacy_saw_workflow(workflow)
                else f"{workflow.upper()}_FINDINGS_2.0"
            ),
            "stage": normalized["stage"],
            "finding_count": normalized["finding_count"],
            "coverage_count": len(normalized["coverage"]["reviewed_references"]),
            "review_receipt_count": len(normalized.get("review_receipts", [])),
            "structural_candidates_reconciled": len(normalized["structural_adjudications"]),
        }
        normalized_issues = unique_source_text_issues(
            dict(row)
            for row in raw.get("structural_issues", raw.get("source_text_issues", []))
            if isinstance(row, Mapping)
        )
        normalized.update(
            {
                "execution_route": execution_route,
                "job_id": job_id,
                "run_id": run_id,
                "parent_plan_id": raw.get("parent_plan_id"),
                "output_project": raw.get("output_project"),
                "contemporary_source": raw.get("contemporary_source"),
                "resource_bindings": raw.get("resource_bindings", {}),
                "resource_display_names": raw.get("resource_display_names", {}),
                "resource_fingerprints": raw.get("resource_fingerprints", {}),
                "structural_issues": normalized_issues,
                "source_text_issues": normalized_issues,
            }
        )
        normalized["source_comparison_status"] = source_comparison_status(
            normalized["source_text_issues"]
        )
        authority = report_language_authority(
            config.human_output.logs_and_reports,
            operator_language=config.human_output.operator_language,
        )
        if authority:
            normalized["language_authority"] = authority
        validation_root = task_root / "validation"
        atomic_write_text(validation_root / "ACTION-REPORT.md", render_action_report(normalized))
        atomic_write_text(validation_root / "OPERATOR-NOTE-TEXT.txt", render_operator_note_text(normalized))
        atomic_write_json(validation_root / "actions.json", {"findings": normalized["findings"]})
        atomic_write_json(validation_root / "normalized-findings.json", normalized)
        final_status = "FINALIZED"

    result = {
        "task_id": task_id,
        "status": final_status,
        "workflow": workflow,
        "operation": operation,
        "job_id": job_id,
        "run_id": run_id,
        "parent_plan_id": raw.get("parent_plan_id"),
        "resource_bindings": raw.get("resource_bindings", {}),
        "resource_display_names": raw.get("resource_display_names", {}),
        "resource_fingerprints": raw.get("resource_fingerprints", {}),
        "output_project": raw.get("output_project"),
        "contemporary_source": raw.get("contemporary_source"),
        "lexical_donor": raw.get("lexical_donor"),
        "original_language_sources": raw.get("original_language_sources", []),
        "conditional_ol_evidence_used": conditional_ol_evidence_used,
        "execution_route": execution_route,
        "scope": raw.get("scope"),
        "focus": raw.get("focus"),
        "check_type": raw.get("check_type"),
        "validation": validation_details,
        "decision_required": False,
        "commit": commit,
        "outputs": [
            {"path": value, "sha256": sha256_file(output_paths[value])}
            for value in sorted(allowed_writes)
        ],
        "validated_utc": utc_now(),
    }
    if stc_publication is not None:
        result.update(stc_publication)
    validation_root = task_root / "validation"
    atomic_write_json(validation_root / "submission.json", result)
    _update_control(
        control_path,
        {
            **control,
            "status": final_status,
            "validated_utc": result["validated_utc"],
            "submission_sha256": sha256_file(validation_root / "submission.json"),
        },
    )
    if workflow == "nca" and operation == "numbers":
        from .nca import finalize_nca_run

        finalized = finalize_nca_run(config, job_id=job_id, run_id=run_id)
        result.update(
            {
                "result_path": finalized["result_path"],
                "result_sha256": finalized["result_sha256"],
                "report_path": finalized["report_path"],
                "report_sha256": finalized["report_sha256"],
            }
        )
        for key in (
            "report_languages",
            "report_directory",
            "report_paths",
            "operator_note_text_paths",
            "job_summary_path",
            "diagnostics_path",
            "number_style_report_path",
            "reconstructed_style_profile_path",
        ):
            if key in finalized:
                result[key] = finalized[key]
        atomic_write_json(validation_root / "submission.json", result)
        _update_control(
            control_path,
            {
                **control,
                "status": final_status,
                "validated_utc": result["validated_utc"],
                "submission_sha256": sha256_file(validation_root / "submission.json"),
            },
        )
    return result

