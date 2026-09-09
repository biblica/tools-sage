"""Adapt NCA domain evaluation to SAGE Jobs, Runs, and governed ACT tasks."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

import yaml

from .atomic import atomic_write_json, atomic_write_text
from .errors import ValidationError
from .hashing import sha256_bytes, sha256_file
from .job_snapshots import verify_wip_snapshot
from .jobs import Job, JobStore, Run
from .locking import WorkspaceLock
from .numbers.policy import (
    DEFAULT_CHECKS,
    build_nca_run_snapshot,
    load_nca_run_snapshot,
    validate_checks,
    validate_nca_job_prerequisites,
    write_nca_run_snapshot,
)
from .numbers.resources import resolve_reference_package
from .numbers.style import resolve_style_profile
from .references import parse_scope
from .registry import EcosystemConfig
from .runtime_paths import task_container
from .storage import StorageError, declare_governed_path, resolve_persisted_path
from .versification_service import VersificationService
from .workflow_identity import canonical_nca_job_id


def _store(config: EcosystemConfig) -> JobStore:
    """Return the shared lifecycle store for one resolved ecosystem."""
    return JobStore(config.root, config.settings_path)


def _utc_now() -> str:
    """Return one stable UTC timestamp for NCA lifecycle receipts."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _configured_nca_route(config: EcosystemConfig) -> dict[str, object]:
    """Resolve provider readiness once and normalize the exact NCA route snapshot."""
    from .numbers.model_tasks import NcaModelTasks

    tasks = NcaModelTasks(config)
    route = getattr(tasks, "route_snapshot", None)
    if not isinstance(route, Mapping):
        raise ValidationError(
            "NCA model task route cannot provide a complete persistence snapshot",
            code="NCA_MODEL_ROUTE_INVALID",
        )
    return {str(key): value for key, value in route.items()}


def create_nca_job(
    config: EcosystemConfig,
    *,
    wip: str,
    package_id: str,
    style_selector: str | None = None,
    display_name: str | None = None,
) -> Job:
    """Create one canonical NCA Job after package, style, and Project validation."""
    project = config.project(wip)
    namespace = config.language_profile(project.language_profile)
    bundle = resolve_reference_package(config, package_id)
    style = resolve_style_profile(
        config,
        style_selector,
        language=project.language_code,
        script=namespace.script,
        project=project.project_id,
    )
    store = _store(config)
    imported = store._analysis_import_time(wip, None)
    job_id = canonical_nca_job_id(wip, imported.strftime("%Y%m%d"))
    return store.create_job(
        tool="nca",
        job_id=job_id,
        display_name=display_name or f"NCA {wip}",
        bindings={"wip": wip},
        profiles={"number_style": style.selector},
        resources={
            "numbers_package": {
                "package_id": bundle.package_id,
                "sha256": bundle.sha256,
            }
        },
        defaults={"checks": dict(DEFAULT_CHECKS)},
        imported_at=imported,
    )


def create_nca_run(
    config: EcosystemConfig,
    *,
    job_id: str,
    scope_value: str,
    checks: Mapping[str, object] | None = None,
) -> Run:
    """Atomically seal one NCA policy, WIP, package, style, and route snapshot."""
    store = _store(config)
    job = store.load_job(job_id, tool="nca")
    active = store.active_run(job)
    if active is not None:
        raise ValidationError(
            f"NCA Job already has an active Run: {active.run_id}",
            code="NCA_RUN_ALREADY_ACTIVE",
            next_action="Continue, complete, or abandon the active Run before starting another.",
        )
    validate_nca_job_prerequisites(config, job)
    defaults = job.defaults.get("checks")
    if not isinstance(defaults, Mapping):
        raise ValidationError("NCA Job check defaults are missing", code="NCA_CHECK_POLICY_INVALID")
    merged = dict(defaults)
    if checks is not None:
        unknown = set(checks) - set(DEFAULT_CHECKS)
        if unknown:
            raise ValidationError("NCA Run contains unknown check settings", code="NCA_CHECK_POLICY_INVALID")
        merged.update(checks)
    exact_checks = validate_checks(merged)
    route = _configured_nca_route(config)

    def initialize(root: Path) -> None:
        """Write every NCA-owned Run artifact inside JobStore's rollback boundary."""
        snapshot = build_nca_run_snapshot(config, job, checks=exact_checks, route=route)
        resolved = validate_nca_job_prerequisites(config, job)
        write_nca_run_snapshot(root, snapshot, style_bytes=resolved.style.content_bytes)

    return store.create_run(
        job,
        operation="numbers",
        scope=scope_value,
        initialize_run=initialize,
    )


def restart_nca_run(config: EcosystemConfig, *, job: Job, run: Run) -> Run:
    """Abandon one open NCA Run after atomically creating its fresh replacement."""
    if job.tool != "nca" or run.tool != "nca" or run.job_id != job.job_id:
        raise ValidationError("NCA restart requires an owning Job and Run", code="NCA_TASK_BINDING_INVALID")
    if run.status in {"COMPLETE", "ARCHIVED", "ABANDONED"}:
        raise ValidationError(f"Cannot restart a {run.status.lower()} NCA Run")
    validate_nca_job_prerequisites(config, job)
    defaults = job.defaults.get("checks")
    exact_checks = validate_checks(defaults if isinstance(defaults, Mapping) else None)
    route = _configured_nca_route(config)
    store = _store(config)

    def initialize(root: Path) -> None:
        """Seal current Job defaults and resources in the replacement Run."""
        snapshot = build_nca_run_snapshot(config, job, checks=exact_checks, route=route)
        resolved = validate_nca_job_prerequisites(config, job)
        write_nca_run_snapshot(root, snapshot, style_bytes=resolved.style.content_bytes)

    replacement = store.create_run(
        job,
        operation="numbers",
        scope=run.scope,
        initialize_run=initialize,
        replace_active_run_id=run.run_id,
    )
    store.update_run(run, status="ABANDONED", current_stage="ABANDONED")
    store.set_active_run(job, replacement.run_id)
    return replacement


def create_nca_task(
    config: EcosystemConfig,
    *,
    job_id: str,
    run_id: str,
    scope_value: str,
) -> Mapping[str, object]:
    """Create or return one governed NCA ACT task for an exact Run scope."""
    store = _store(config)
    job = store.load_job(job_id, tool="nca")
    run = store.load_run(job, run_id)
    if run.operation != "numbers" or run.scope != parse_scope(scope_value).label():
        raise ValidationError(
            "NCA task scope must equal its sealed Run request",
            code="NCA_TASK_SCOPE_MISMATCH",
        )
    policy = load_nca_run_snapshot(run.root)
    runtime_config = _runtime_config(store, job)
    projected, headings, expected_ids, expected_refs = _sealed_units(
        runtime_config, job=job, run=run, policy=policy
    )
    del projected, headings

    # The Run ledger is the idempotency authority: its one exact coverage task
    # survives menu/CLI retries and completed-result resume without re-creation.
    for persisted in run.task_manifests:
        existing = Path(persisted).resolve()
        try:
            raw = json.loads(existing.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            raw.get("workflow") == "nca"
            and raw.get("operation") == "numbers"
            and raw.get("scope") == run.scope
            and raw.get("expected_unit_ids") == list(expected_ids)
        ):
            return _created_task_result(existing, raw)
    if run.task_manifests:
        raise ValidationError(
            "NCA Run already owns a different governed task",
            code="NCA_TASK_COVERAGE_CONFLICT",
        )

    from .act_tasks import load_skill_registry
    from .evidence_policy import PROCESS_CONTROL, SUBJECT_TEXT, task_evidence_policy

    skill = load_skill_registry(runtime_config.root)[("nca", "numbers")]
    policy_path = run.root / "check-policy.json"
    style_path = run.root / "profiles/number-style.yml"
    snapshot = verify_wip_snapshot(run.root / "snapshot", require_file_inventory=True)
    package = policy["reference_package"]
    package_root = _package_root(runtime_config, str(package["package_id"]))
    reads = [
        {
            "path": _relative(runtime_config.root, run.root / "snapshot" / relative),
            "sha256": digest,
            "evidence_class": SUBJECT_TEXT,
        }
        for relative, digest in sorted(snapshot["files"].items())
    ]
    reads.extend(
        {
            "path": _relative(runtime_config.root, package_root / relative),
            "sha256": digest,
            "evidence_class": PROCESS_CONTROL,
        }
        for relative, digest in sorted(package["files"].items())
    )
    reads.append(
        {
            "path": _relative(runtime_config.root, style_path),
            "sha256": sha256_file(style_path),
            "evidence_class": PROCESS_CONTROL,
        }
    )
    governance = [
        {
            "path": _relative(runtime_config.root, policy_path),
            "sha256": sha256_file(policy_path),
            "evidence_class": PROCESS_CONTROL,
        },
        {
            "path": _relative(runtime_config.root, skill.path),
            "sha256": sha256_file(skill.path),
            "evidence_class": PROCESS_CONTROL,
        },
    ]
    seed = sha256_bytes(
        json.dumps(
            {
                "job_id": job.job_id,
                "run_id": run.run_id,
                "scope": run.scope,
                "expected_unit_ids": expected_ids,
                "policy_sha256": sha256_file(policy_path),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    task_id = f"nca-numbers-{parse_scope(run.scope).book.lower()}-{seed[:12]}"
    task_root = task_container(runtime_config.workflow("nca"), run.run_id) / task_id
    manifest_path = task_root / "task-manifest.json"
    control_path = runtime_config.workflow("nca").state_root / "act-tasks" / f"{task_id}.json"
    task_root.mkdir(parents=True, exist_ok=False)
    (task_root / "output").mkdir()
    try:
        project = runtime_config.project(job.bindings["wip"])
        identity: dict[str, object] = {
            "schema_version": "2.4",
            "execution_mode": "SAGE_GOVERNED_TASK_V1",
            "workflow": "nca",
            "operation": "numbers",
            "skill_id": skill.skill_id,
            "job_id": job.job_id,
            "run_id": run.run_id,
            "resource_bindings": {
                "WIP": project.project_id,
                "NUMBERS_PACKAGE": package["package_id"],
                "NUMBER_STYLE": policy["number_style"]["selector"],
            },
            "resource_display_names": {},
            "output_project": project.project_id,
            "output_content_state": project.content_state,
            "contemporary_source": None,
            "original_language_sources": [],
            "scope": run.scope,
            "focus": None,
            "check_type": "NUMBERS",
            "skill": {
                "id": skill.skill_id,
                "entrypoint": _relative(runtime_config.root, skill.path),
                "source_system": skill.source_system,
                "source_version": skill.source_version,
                "original_sha256": skill.original_sha256,
                "adapted_sha256": skill.adapted_sha256,
                "qualification_status": skill.qualification_status,
            },
            "project_grammar": None,
            "linguistic_profile_bindings": {},
            "evidence_policy": task_evidence_policy("nca"),
            "packets": {
                "wip_snapshot": _relative(runtime_config.root, run.root / "snapshot"),
                "reference_package": str(package["package_id"]),
                "number_style": _relative(runtime_config.root, style_path),
            },
            "resource_fingerprints": {
                "settings": sha256_file(runtime_config.settings_path),
                "check_policy": sha256_file(policy_path),
                "wip": str(policy["wip"]["inventory_sha256"]),
                "reference_package": str(package["inventory_sha256"]),
                "number_style": str(policy["number_style"]["sha256"]),
                "model_route": str(policy["model_route"]["route_id"]),
            },
            "expected_references": list(expected_refs),
            "expected_unit_ids": list(expected_ids),
            "coverage": {"expected_unit_ids": list(expected_ids)},
            "structural_candidate_ids": [],
            "allowed_evidence_ids": sorted(str(value) for value in _bundle(runtime_config, policy).provenance),
            "governance_inputs": governance,
            "allowed_reads": reads,
            "conditional_reads": [],
            "allowed_writes": ["output/model-evidence.json"],
            "output_grammar": "NCA_MODEL_EVIDENCE_1.0",
            "narrative_language": {
                "tag": job.primary_report_language,
                "authority": "CANONICAL_REPORT_NARRATIVE",
            },
            "human_output": {
                "logs_and_reports": {
                    "primary_language": job.primary_report_language,
                    "secondary_language": job.secondary_report_language,
                    "bilingual": job.secondary_report_language is not None,
                }
            },
            "forbidden_actions": [
                "broaden_scope",
                "read_unlisted_files",
                "use_external_content_evidence",
                "modify_scripture",
                "create_unlisted_outputs",
            ],
        }
        fingerprint = _fingerprint(identity)
        manifest = {
            **identity,
            "task_id": task_id,
            "task_root": _relative(runtime_config.root, task_root),
            "submit_commands": {},
            "task_fingerprint": fingerprint,
            "created_utc": _utc_now(),
        }
        act_path = task_root / "ACT.md"
        atomic_write_json(manifest_path, manifest)
        atomic_write_text(
            act_path,
            "\n".join(
                [
                    f"# SAGE ACT Task: {task_id}",
                    "",
                    "SAGE EXECUTION MODE: GOVERNED TASK V1",
                    "",
                    "Execute the sealed Number Consistency & Accuracy task.",
                    f"- WIP: `{project.project_id}`",
                    f"- Scope: `{run.scope}`",
                    "- Write only `output/model-evidence.json` through the SAGE executor.",
                    "",
                ]
            ),
        )
        control = {
            "schema_version": "2.0",
            "task_id": task_id,
            "workflow": "nca",
            "operation": "numbers",
            "job_id": job.job_id,
            "run_id": run.run_id,
            "task_root": _relative(runtime_config.root, task_root),
            "manifest_path": _relative(runtime_config.root, manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
            "act_path": _relative(runtime_config.root, act_path),
            "act_sha256": sha256_file(act_path),
            "task_fingerprint": fingerprint,
            "settings_sha256": sha256_file(runtime_config.settings_path),
            "allowed_writes": ["output/model-evidence.json"],
            "status": "CREATED",
            "created_utc": _utc_now(),
        }
        atomic_write_json(control_path, control)
        for immutable in (manifest_path, act_path, control_path):
            try:
                os.chmod(immutable, 0o444)
            except OSError:
                pass
        store.update_run(
            run,
            status="ACTIVE",
            current_stage="MODEL_INTERPRETATION",
            task_manifests=(str(manifest_path.resolve()),),
        )
        return _created_task_result(manifest_path, manifest)
    except Exception:
        import shutil

        shutil.rmtree(task_root, ignore_errors=True)
        control_path.unlink(missing_ok=True)
        raise


def execute_nca_task(
    config: EcosystemConfig,
    task_manifest: Path,
    *,
    timeout_seconds: int = 600,
    dry_run: bool = False,
) -> Mapping[str, object]:
    """Execute phased model interpretation against one sealed NCA task."""
    path = task_manifest.expanduser().resolve()
    with WorkspaceLock(path.parent / "locks" / "execution.lock", "NCA_TASK_EXECUTION"):
        return _execute_nca_task_locked(
            config,
            path,
            timeout_seconds=timeout_seconds,
            dry_run=dry_run,
        )


def _execute_nca_task_locked(
    config: EcosystemConfig,
    task_manifest: Path,
    *,
    timeout_seconds: int,
    dry_run: bool,
) -> Mapping[str, object]:
    """Validate, execute, and publish one NCA task while holding its task lock."""
    manifest_path, manifest, runtime_config, job, run, policy = _validate_task(
        config, task_manifest
    )
    output_path = manifest_path.parent / "output/model-evidence.json"
    receipt_path = manifest_path.parent / "validation/llm-execution-receipt.json"
    if output_path.is_file() and receipt_path.is_file():
        receipt = _load_json(receipt_path, "NCA execution receipt")
        if receipt.get("output_sha256") != {"output/model-evidence.json": sha256_file(output_path)}:
            raise ValidationError("Existing NCA output differs from its execution receipt", code="EXECUTION_RECEIPT_OUTPUT_MISMATCH")
        return {**receipt, "status": "EXECUTED", "receipt_path": str(receipt_path)}
    if output_path.exists() or receipt_path.exists():
        raise ValidationError("NCA task has partial execution artifacts", code="LLM_TASK_OUTPUT_NOT_EMPTY")

    route = policy["model_route"]
    if dry_run:
        return {
            "status": "READY_TO_EXECUTE",
            "task_id": manifest["task_id"],
            "skill_id": "nca-numbers",
            "route_id": route["route_id"],
            "provider": route["provider"],
            "model": route["model"],
            "reasoning_effort": route["reasoning_effort"],
            "allowed_writes": ["output/model-evidence.json"],
        }

    from .numbers.engine import evaluate_run
    from .numbers.model_tasks import NcaModelTasks
    from .numbers.results import numbers_result_document, validate_numbers_result

    projected, headings, expected_ids, _expected_refs = _sealed_units(
        runtime_config, job=job, run=run, policy=policy
    )
    style_document = yaml.safe_load((run.root / "profiles/number-style.yml").read_text(encoding="utf-8"))
    tasks = NcaModelTasks(
        runtime_config,
        expected_route_id=str(route["route_id"]),
        timeout_seconds=timeout_seconds,
    )
    live_route = getattr(tasks, "route_snapshot", None)
    if not isinstance(live_route, Mapping) or dict(live_route) != dict(route):
        raise ValidationError(
            "Resolved NCA model route differs from the sealed Run route",
            code="NCA_MODEL_ROUTE_CHANGED",
        )
    recording = _RecordingModelTasks(tasks)
    started = _utc_now()
    # The engine receives only sealed target/style/package data. The proxy records
    # successful phase receipts while keeping provider payload boundaries in model_tasks.
    result = evaluate_run(
        projected,
        bundle=_bundle(runtime_config, policy),
        language=str(policy["wip"]["language"]),
        language_profile={
            "language": policy["wip"]["language"],
            "script": policy["wip"]["script"],
        },
        style_profile=style_document,
        check_policy=policy,
        run_id=run.run_id,
        expected_unit_ids=expected_ids,
        model_tasks=recording,
        coverage_restrictions=_reference_restrictions(policy),
        style_units=headings,
    )
    if expected_ids and not any(recording.receipts.values()):
        raise ValidationError(
            "NCA model execution produced no validated phase evidence",
            code="NCA_MODEL_PROVIDER_FAILED",
        )
    document = numbers_result_document(
        result,
        provenance=_provenance(job, run, policy),
        check_policy=policy,
        model_receipts=recording.receipts,
    )
    validate_numbers_result(
        document,
        expected_unit_ids=expected_ids,
        allowed_evidence_ids=tuple(manifest["allowed_evidence_ids"]),
    )
    atomic_write_json(output_path, document)
    route_identity = dict(getattr(tasks, "route_identity", {}))
    receipt = _execution_receipt(
        manifest,
        route_identity=route_identity,
        receipts=recording.receipts,
        output_path=output_path,
        started=started,
    )
    atomic_write_json(receipt_path, receipt)
    return {**receipt, "status": "EXECUTED", "receipt_path": str(receipt_path)}


def finalize_nca_run(
    config: EcosystemConfig,
    *,
    job_id: str,
    run_id: str,
) -> Mapping[str, object]:
    """Reconcile accepted task coverage and publish one deterministic NCA report."""
    store = _store(config)
    job = store.load_job(job_id, tool="nca")
    run = store.load_run(job, run_id)
    result_path = run.root / "validation/numbers-result.json"
    report_path = run.root / "reports/NUMBER-CONSISTENCY-ACCURACY.md"
    if not run.task_manifests:
        raise ValidationError("NCA Run has no governed task", code="NCA_RESULT_COVERAGE_INVALID")
    # Finalization reads accepted task-local results only and publishes after the
    # complete expected-unit ledger reconciles, so a write failure cannot mark DONE.
    documents: list[dict[str, object]] = []
    expected: list[str] = []
    report_languages: list[tuple[str, str | None]] = []
    runtime = _runtime_config(store, job)
    for persisted in run.task_manifests:
        document, ids, sealed_languages = _validated_finalized_task(
            config,
            runtime=runtime,
            job=job,
            run=run,
            persisted_manifest=persisted,
        )
        documents.append(document)
        expected.extend(ids)
        report_languages.append(sealed_languages)
    if (
        len(documents) != 1
        or len(expected) != len(set(expected))
        or len(set(report_languages)) != 1
    ):
        raise ValidationError(
            "NCA Run task coverage does not reconcile exactly once",
            code="NCA_RESULT_COVERAGE_INVALID",
        )
    document = documents[0]
    from .nca_reporting import render_nca_report

    primary_language, secondary_language = report_languages[0]
    report = render_nca_report(document, language=primary_language)
    secondary_report = (
        render_nca_report(document, language=secondary_language)
        if secondary_language is not None
        else None
    )
    secondary_report_path = (
        run.root
        / "reports"
        / f"NUMBER-CONSISTENCY-ACCURACY.{secondary_language}.md"
        if secondary_language is not None
        else None
    )
    atomic_write_json(result_path, document)
    atomic_write_text(report_path, report)
    if secondary_report_path is not None and secondary_report is not None:
        atomic_write_text(secondary_report_path, secondary_report)
    if run.status != "COMPLETE" or run.result != "DONE":
        store.update_run(
            run,
            status="COMPLETE",
            current_stage="DETERMINISTIC_FINALISATION",
            result="DONE",
        )
    published = {
        "status": "COMPLETE",
        "job_id": job.job_id,
        "run_id": run.run_id,
        "result_path": str(result_path),
        "result_sha256": sha256_file(result_path),
        "report_path": str(report_path),
        "report_sha256": sha256_file(report_path),
    }
    if secondary_report_path is not None:
        published.update(
            {
                "secondary_report_path": str(secondary_report_path),
                "secondary_report_sha256": sha256_file(secondary_report_path),
                "secondary_report_language": secondary_language,
            }
        )
    return published


def _validated_finalized_task(
    config: EcosystemConfig,
    *,
    runtime: EcosystemConfig,
    job: Job,
    run: Run,
    persisted_manifest: str,
) -> tuple[dict[str, object], tuple[str, ...], tuple[str, str | None]]:
    """Reconcile one finalized task against its control, receipt, and original output."""
    manifest_path = resolve_persisted_path(
        runtime.root,
        persisted_manifest,
        "NCA finalized task manifest",
    )
    path, manifest, reopened_runtime, reopened_job, reopened_run, _policy = _validate_task(
        config,
        manifest_path,
    )
    if (
        reopened_runtime.root != runtime.root
        or reopened_job.job_id != job.job_id
        or reopened_run.run_id != run.run_id
    ):
        raise ValidationError(
            "NCA finalized task belongs to another Run",
            code="NCA_TASK_BINDING_INVALID",
        )
    control_path = (
        runtime.workflow("nca").state_root
        / "act-tasks"
        / f"{manifest.get('task_id')}.json"
    )
    control = _load_json(control_path, "NCA trusted task control")
    submission_path = path.parent / "validation/submission.json"
    submission = _load_json(submission_path, "NCA submission")
    if control.get("status") != "FINALIZED" or submission.get("status") != "FINALIZED":
        raise ValidationError(
            "NCA Run contains an unfinished task",
            code="WORK_UNIT_NOT_FINALIZED",
        )
    if control.get("submission_sha256") != sha256_file(submission_path):
        raise ValidationError(
            "NCA submission differs from its trusted control",
            code="ACT_INPUT_STALE",
        )
    expected_submission = {
        "task_id": manifest.get("task_id"),
        "workflow": "nca",
        "operation": "numbers",
        "job_id": job.job_id,
        "run_id": run.run_id,
    }
    if any(submission.get(key) != value for key, value in expected_submission.items()):
        raise ValidationError(
            "NCA submission identity differs from its sealed task",
            code="NCA_TASK_BINDING_INVALID",
        )
    narrative = manifest.get("narrative_language")
    if not isinstance(narrative, Mapping) or not isinstance(narrative.get("tag"), str):
        raise ValidationError(
            "NCA task has no sealed report language",
            code="NCA_TASK_BINDING_INVALID",
        )
    narrative_language = str(narrative["tag"]).strip()
    if not narrative_language:
        raise ValidationError(
            "NCA task has no sealed report language",
            code="NCA_TASK_BINDING_INVALID",
        )
    human_output = manifest.get("human_output")
    logs = human_output.get("logs_and_reports") if isinstance(human_output, Mapping) else None
    if not isinstance(logs, Mapping) or logs.get("primary_language") != narrative_language:
        raise ValidationError(
            "NCA sealed report-language settings are inconsistent",
            code="NCA_TASK_BINDING_INVALID",
        )
    secondary_value = logs.get("secondary_language")
    secondary_language = (
        str(secondary_value).strip()
        if isinstance(secondary_value, str) and secondary_value.strip()
        else None
    )
    if bool(logs.get("bilingual")) != (secondary_language is not None) or (
        secondary_language is not None and secondary_language == narrative_language
    ):
        raise ValidationError(
            "NCA sealed bilingual report settings are inconsistent",
            code="NCA_TASK_BINDING_INVALID",
        )

    output_path = path.parent / "output/model-evidence.json"
    from .act_outputs import execution_route_from_receipt
    from .numbers.results import validate_numbers_result

    if not output_path.is_file():
        raise ValidationError(
            "NCA receipt-bound model evidence is missing",
            code="EXECUTION_RECEIPT_OUTPUT_MISMATCH",
        )
    execution_route_from_receipt(
        path.parent,
        task_id=str(manifest["task_id"]),
        output_hashes={"output/model-evidence.json": sha256_file(output_path)},
    )
    ids = tuple(str(item) for item in manifest.get("expected_unit_ids", []))
    evidence_ids = tuple(str(item) for item in manifest.get("allowed_evidence_ids", []))
    original = validate_numbers_result(
        _load_json(output_path, "NCA model evidence"),
        expected_unit_ids=ids,
        allowed_evidence_ids=evidence_ids,
    )
    accepted = validate_numbers_result(
        _load_json(path.parent / "validation/numbers-result.json", "NCA task result"),
        expected_unit_ids=ids,
        allowed_evidence_ids=evidence_ids,
    )
    if accepted != original:
        raise ValidationError(
            "NCA accepted result differs from its receipt-bound model evidence",
            code="ACT_INPUT_STALE",
        )
    return original, ids, (narrative_language, secondary_language)


def submit_nca_task(
    manifest: Mapping[str, object], output_path: Path
) -> tuple[dict[str, object], dict[str, object]]:
    """Validate controller-written model evidence and persist task-local canonical result."""
    from .numbers.results import validate_numbers_result

    document = _load_json(output_path, "NCA model evidence")
    normalized = validate_numbers_result(
        document,
        expected_unit_ids=tuple(str(item) for item in manifest.get("expected_unit_ids", [])),
        allowed_evidence_ids=tuple(str(item) for item in manifest.get("allowed_evidence_ids", [])),
    )
    destination = output_path.parent.parent / "validation/numbers-result.json"
    atomic_write_json(destination, normalized)
    return normalized, {
        "format": "NCA_NUMBERS_RESULT_1.0",
        "unit_count": len(normalized["units"]),
        "finding_count": len(normalized["findings"]),
        "coverage": normalized["coverage"]["coverage"],
    }


class _RecordingModelTasks:
    """Forward model phases while collecting only their validated receipts."""

    def __init__(self, tasks: object) -> None:
        """Initialize empty phase ledgers around one pinned task router."""
        self._tasks = tasks
        self.receipts: dict[str, list[dict[str, object]]] = {
            "EXTRACTION": [],
            "CORRESPONDENCE": [],
            "FOOTNOTE": [],
        }

    def _call(self, method: str, *args: object, **kwargs: object) -> object:
        """Invoke one phase and append its exact provider receipt."""
        result = getattr(self._tasks, method)(*args, **kwargs)
        receipt = getattr(result, "receipt", None)
        phase = str(getattr(receipt, "phase", ""))
        if phase not in self.receipts or not callable(getattr(receipt, "to_dict", None)):
            raise ValidationError("NCA model phase lacks a validated receipt", code="NCA_MODEL_RECEIPT_INVALID")
        self.receipts[phase].append(receipt.to_dict())
        return result

    def extract(self, *args: object, **kwargs: object) -> object:
        """Execute and record one target extraction phase."""
        return self._call("extract", *args, **kwargs)

    def correspond(self, *args: object, **kwargs: object) -> object:
        """Execute and record one source correspondence phase."""
        return self._call("correspond", *args, **kwargs)

    def assess_footnote(self, *args: object, **kwargs: object) -> object:
        """Execute and record one target-footnote phase."""
        return self._call("assess_footnote", *args, **kwargs)


def _runtime_config(store: JobStore, job: Job) -> EcosystemConfig:
    """Load the Job-owned runtime settings used by shared ACT controls."""
    from .registry import load_ecosystem

    path = job.runtime_settings_path
    if not path.is_file():
        path = store.ensure_runtime_files(job)
    return load_ecosystem(path)


def _relative(root: Path, path: Path) -> str:
    """Declare one governed path relative to the workspace root."""
    try:
        return declare_governed_path(root, path, "NCA governed path")
    except StorageError as exc:
        raise ValidationError("NCA governed path escapes the workspace", code="EXTERNAL_PATH_ESCAPE") from exc


def _fingerprint(identity: Mapping[str, object]) -> str:
    """Hash the immutable task identity using shared ACT canonical JSON."""
    return sha256_bytes(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _load_json(path: Path, label: str) -> dict[str, Any]:
    """Load one required JSON object with a stable validation error."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{label} is missing or invalid", code="NCA_TASK_INVALID") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object", code="NCA_TASK_INVALID")
    return value


def _package_root(config: EcosystemConfig, package_id: str) -> Path:
    """Return one confined imported numbers package directory."""
    from .storage import storage_layout

    root = storage_layout(config.root).resources_root / "numbers"
    path = (root / package_id).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValidationError("NCA package path escapes its resource root", code="EXTERNAL_PATH_ESCAPE") from exc
    return path


def _bundle(config: EcosystemConfig, policy: Mapping[str, object]):
    """Requalify the exact package sealed by the Run and reject identity drift."""
    raw = policy.get("reference_package")
    if not isinstance(raw, Mapping):
        raise ValidationError("NCA Run reference identity is missing", code="NCA_RUN_SNAPSHOT_INVALID")
    bundle = resolve_reference_package(config, str(raw.get("package_id") or ""))
    if bundle.sha256 != raw.get("sha256"):
        raise ValidationError("NCA reference package changed after Run creation", code="NCA_REFERENCE_PACKAGE_STALE")
    files: dict[str, str] = {}
    root = _package_root(config, bundle.package_id)
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            files[path.relative_to(root).as_posix()] = sha256_file(path)
    inventory = sha256_bytes(json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if files != raw.get("files") or inventory != raw.get("inventory_sha256"):
        raise ValidationError("NCA reference package inventory changed after Run creation", code="NCA_REFERENCE_PACKAGE_STALE")
    return bundle


def _sealed_units(
    config: EcosystemConfig,
    *,
    job: Job,
    run: Run,
    policy: Mapping[str, object],
):
    """Project numeric body units and independent heading style streams from sealed USJ."""
    from .numbers.scope import project_scope
    from .numbers.target import extract_heading_units, target_units

    scope = parse_scope(run.scope)
    receipt = verify_wip_snapshot(run.root / "snapshot", require_file_inventory=True)
    body = []
    headings = []
    for relative, digest in sorted(receipt["files"].items()):
        path = run.root / "snapshot" / relative
        raw = _load_json(path, "NCA sealed USJ")
        body.extend(
            unit
            for unit in target_units(raw, source_sha256=digest)
        )
        headings.extend(
            unit
            for unit in extract_heading_units(raw, source_sha256=digest)
            if any(scope.contains(ref) for ref in unit.target_references)
        )
    bundle = _bundle(config, policy)
    service = VersificationService(config)
    all_projected, expected_refs = project_scope(
        tuple(body),
        scope=scope,
        target_schema=service.project_schema(job.bindings["wip"]),
        western_schema=service.base_schema("eng.vrs"),
        bundle=bundle,
        mapping_path=_package_root(config, bundle.package_id) / 'reference/eng_org_map_rules.txt',
    )
    # Keep every scoped target stream so extraction can surface target-added
    # numbers at Western coordinates absent from the authoritative index.
    projected = tuple(all_projected)
    heading_values = tuple(headings)
    expected_ids = tuple(unit.target.unit_id for unit in projected) + tuple(
        unit.unit_id for unit in heading_values
    )
    if len(expected_ids) != len(set(expected_ids)):
        raise ValidationError("NCA projected unit identities overlap", code="NCA_RESULT_COVERAGE_INVALID")
    return projected, heading_values, expected_ids, tuple(ref.label() for ref in expected_refs)


def _created_task_result(path: Path, manifest: Mapping[str, object]) -> dict[str, object]:
    """Return the stable task-create result consumed by CLI and menu controllers."""
    return {
        **manifest,
        "task_manifest": str(path.resolve()),
        "task_manifest_path": str(path.resolve()),
        "manifest_path": str(path.resolve()),
        "manifest_sha256": sha256_file(path),
    }


def _validate_task(
    config: EcosystemConfig, task_manifest: Path
) -> tuple[Path, dict[str, Any], EcosystemConfig, Job, Run, Mapping[str, object]]:
    """Revalidate trusted ACT control, manifest, inputs, and sealed Run identities."""
    path = task_manifest.expanduser().resolve()
    manifest = _load_json(path, "NCA task manifest")
    if manifest.get("workflow") != "nca" or manifest.get("operation") != "numbers":
        raise ValidationError("Task is not an NCA NUMBERS task", code="NCA_TASK_INVALID")
    store = _store(config)
    job = store.load_job(str(manifest.get("job_id") or ""), tool="nca")
    runtime = _runtime_config(store, job)
    run = store.load_run(job, str(manifest.get("run_id") or ""))
    if run.status != "COMPLETE":
        active = store.active_run(job)
        if active is None or active.run_id != run.run_id:
            raise ValidationError(
                "NCA task does not belong to the Job's active Run",
                code="NCA_RUN_NOT_ACTIVE",
            )
    control_path = runtime.workflow("nca").state_root / "act-tasks" / f"{manifest.get('task_id')}.json"
    control = _load_json(control_path, "NCA trusted task control")
    if control.get("status") not in {"CREATED", "FINALIZED"}:
        raise ValidationError("NCA task is not open or finalized", code="NCA_TASK_INVALID")
    if control.get("settings_sha256") != sha256_file(runtime.settings_path):
        raise ValidationError("NCA runtime settings changed after task creation", code="ACT_INPUT_STALE")
    if resolve_persisted_path(runtime.root, str(control.get("manifest_path") or ""), "NCA task manifest") != path:
        raise ValidationError("NCA task manifest path differs from trusted control", code="NCA_TASK_INVALID")
    if control.get("manifest_sha256") != sha256_file(path):
        raise ValidationError("NCA task manifest changed after creation", code="ACT_INPUT_STALE")
    identity = {key: value for key, value in manifest.items() if key not in {"task_id", "task_root", "submit_commands", "task_fingerprint", "created_utc"}}
    if manifest.get("task_fingerprint") != control.get("task_fingerprint") or _fingerprint(identity) != manifest.get("task_fingerprint"):
        raise ValidationError("NCA task fingerprint is invalid", code="ACT_INPUT_STALE")
    for field in ("governance_inputs", "allowed_reads"):
        for item in manifest.get(field, []):
            if not isinstance(item, Mapping):
                raise ValidationError("NCA task input allowlist is invalid", code="NCA_TASK_INVALID")
            input_path = resolve_persisted_path(runtime.root, str(item.get("path") or ""), "NCA task input")
            if not input_path.is_file() or sha256_file(input_path) != item.get("sha256"):
                raise ValidationError("NCA task input changed after creation", code="ACT_INPUT_STALE")
    policy = load_nca_run_snapshot(run.root)
    _bundle(runtime, policy)
    model_contract = policy.get("model_contract")
    if not isinstance(model_contract, Mapping):
        raise ValidationError("NCA model contract is missing", code="NCA_RUN_SNAPSHOT_INVALID")
    if sha256_file(runtime.root / "system/skills/nca-numbers/SKILL.md") != model_contract.get("skill_sha256") or sha256_file(runtime.root / "system/config/schemas/nca-extraction.schema.yml") != model_contract.get("structured_response_schema_sha256"):
        raise ValidationError("NCA model contract changed after Run creation", code="NCA_MODEL_ROUTE_CHANGED")
    return path, manifest, runtime, job, run, policy


def _provenance(job: Job, run: Run, policy: Mapping[str, object]) -> dict[str, object]:
    """Project exact Run identities into the canonical NCA result contract."""
    return {
        "run_id": run.run_id,
        "job_id": job.job_id,
        "style_profile": {
            "selector": policy["number_style"]["selector"],
            "sha256": policy["number_style"]["sha256"],
        },
        "reference_package": {
            "package_id": policy["reference_package"]["package_id"],
            "sha256": policy["reference_package"]["sha256"],
        },
        "wip": {
            "identity": policy["wip"]["project_id"],
            "sha256": policy["wip"]["content_fingerprint"],
        },
    }


def _reference_restrictions(policy: Mapping[str, object]) -> tuple[str, ...]:
    """Retain nonblocking package diagnostics as explicit Run coverage limits."""
    diagnostics = policy["reference_package"].get("diagnostics", [])
    return tuple(
        str(item.get("code"))
        for item in diagnostics
        if isinstance(item, Mapping) and str(item.get("code") or "")
    )


def _execution_receipt(
    manifest: Mapping[str, object],
    *,
    route_identity: Mapping[str, object],
    receipts: Mapping[str, list[dict[str, object]]],
    output_path: Path,
    started: str,
) -> dict[str, object]:
    """Build the shared schema-2.0 execution receipt from actual NCA phase calls."""
    phases = [row for name in ("EXTRACTION", "CORRESPONDENCE", "FOOTNOTE") for row in receipts[name]]
    canonical = json.dumps(receipts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": "2.0",
        "task_id": manifest["task_id"],
        "skill_id": "nca-numbers",
        "execution_mode": "SAGE_GOVERNED_TASK_V1",
        "route_id": route_identity.get("route_id"),
        "routing_mode": route_identity.get("routing_mode"),
        "qualification_status": route_identity.get("qualification"),
        "qualification_evidence_sha256": route_identity.get("evidence_sha256"),
        "routing_basis_sha256": route_identity.get("routing_basis_sha256"),
        "routing_policy_version": route_identity.get("policy_version"),
        "provider_runtime_version": route_identity.get("provider_runtime_version"),
        "model_identity_strength": route_identity.get("model_identity_strength"),
        "capability_fingerprint": route_identity.get("capability_fingerprint"),
        "provider": route_identity.get("provider"),
        "model": route_identity.get("model_id"),
        "reasoning_effort": route_identity.get("reasoning_id"),
        "selection_mode": route_identity.get("selection_mode"),
        "operator_policy_override": route_identity.get("routing_mode") == "GLOBAL_OVERRIDE",
        "started_utc": started,
        "completed_utc": _utc_now(),
        "phase_count": len(phases),
        "phase_reasoning_efforts": [row.get("reasoning_effort") for row in phases],
        "conditional_evidence_used": False,
        "conditional_ol_micro_scopes": [],
        "report_language": manifest["narrative_language"]["tag"],
        "language_retry_count": 0,
        "language_retry_reason": None,
        "prompt_sha256": sha256_bytes(canonical),
        "final_prompt_sha256": sha256_bytes(canonical),
        "handoff_measurements": [],
        "response_sha256": sha256_bytes(canonical),
        "provider_response_sha256": [str(row["response_sha256"]) for row in phases],
        "output_sha256": {"output/model-evidence.json": sha256_file(output_path)},
        "provider_metadata": {"phase_receipts": len(phases)},
        "model_policy": dict(route_identity),
        "policy": {
            "openai_api_keys": "PROHIBITED",
            "sealed_transport": True,
            "sage_workspace_exposed_as_provider_cwd": False,
            "filesystem_writes_by_provider": False,
            "live_provider_catalog_required": True,
        },
    }
