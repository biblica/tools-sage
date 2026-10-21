"""Shared ACT task helpers: constants, Job/Run and Project resolution, scope helpers, and Skill loading.

Split from act_tasks.py, which re-exports every name defined here.
"""

from __future__ import annotations

from .bic_memory import inspect_completion_and_review_status
from .bic_output import is_generated_target_folder
from .canon import BOOK_ORDER
from .canon import NT_27
from .canon import OT_39
from .canon import resolve_expected_books
from .config import load_json
from .config import require_mapping
from .config import require_string
from .errors import ConfigurationError
from .errors import InputRequiredError
from .errors import ValidationError
from .evidence import EvidencePolicy
from .external_access import validate_external_file
from .hashing import sha256_file
from .jobs import JobStore
from .jobs import RUN_CLOSED_STATUSES
from .jobs import default_job_name
from .language_codes import canonical_language_tag
from .llm_settings import load_llm_settings
from .paratext_filenames import paratext_book_digits
from .paratext_filenames import template_book_filename
from .platform_commands import render_sage_command
from .profiles import load_workflow_profile
from .project_inventory import require_project_imported_at
from .references import AnalysisScope
from .references import ScriptureScope
from .references import ScriptureScopeSet
from .references import atomic_reference_labels
from .references import expand_reference_atoms
from .references import parse_scope
from .references import parse_scope_set
from .references import scripture_scopes_equal
from .references import validate_scripture_scope
from .registry import EcosystemConfig
from .registry import ProjectSpec
from .registry import load_ecosystem
from .rtc_planner import LEGACY_RTC_PLANNER_VERSION
from .rtc_planner import RTC_HANDOFF_CONTRACT_VERSION
from .rtc_planner import RTC_PLANNER_VERSION
from .rtc_planner import rtc_prompt_schema_projection_version
from .runtime_paths import task_container
from .runtime_paths import workflow_memory_root
from .scripture import compile_project_scope
from .scripture import discover_book_ids
from .state import ecosystem_state_path
from .state import read_state
from .storage import StorageError
from .storage import declare_governed_path
from .storage import resolve_persisted_path
from .transactions import incomplete_transactions
from .vocabulary import CANONICAL_TARGET_TEXT_OPERATION
from .vocabulary import require_canonical_target_text_vocabulary
from .vrs import VerseRef
from .work_units import records_from_project_result
from .work_units import select_records_for_scope
from .workflow_identity import analysis_reason_code
from .workflow_identity import canonical_analysis_job_id
from .workflow_identity import is_analysis_workflow
from .workflow_identity import legacy_saw_workflow
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Iterable
from typing import Mapping
from typing import Sequence
import json
import os
import re


ACT_OPERATIONS = {
    "bic": {"inspect", CANONICAL_TARGET_TEXT_OPERATION, "self_check"},
    "rtc": {"rtc"},
    "stc": {"stc"},
    "nca": {"numbers"},
    "saw": {"rtc", "stc", "focused", "ol"},
}

CONTEMPORARY_ROLES = {"REFERENCE"}

READY_RESOURCE_STATES = {"READY", "READY_WITH_WARNINGS"}

RTC_STAGES = {
    "STRUCTURAL_ADJUDICATION",
    "REFERENCE_TEXT_COMPARISON",
    "SELECTIVE_OL_ADJUDICATION",
}

LEGACY_TARGETED_CHECK_TYPES = {
    "DIVINE_NAME_MARKUP",
    "DIVINE_NAME_CORRELATION",
    "VERSE_BRIDGE_MAPPING",
    "VERSE_BRIDGE_CONTENT",
    "TEXTUAL_VARIANT_COORDINATE",
    "PROPER_NAME_CONSISTENCY",
    "KEY_TERM_CONSISTENCY",
    "PARTICIPANT_REFERENCE",
    "QUOTATION_STRUCTURE",
    "GRAMMATICAL_RELATIONSHIP",
    "MEANING_EQUIVALENCE",
    "CUSTOM_BOUNDED_CHECK",
}

_SAFE_OUTPUT_RE = re.compile(r"^output/[A-Za-z0-9][A-Za-z0-9._-]*$")


def _analysis_identity(workflow: str) -> str:
    """Return a current workflow label or an explicit legacy compatibility label."""
    return "legacy analysis" if legacy_saw_workflow(workflow) else workflow.upper()


def _analysis_code(workflow: str, legacy_code: str) -> str:
    """Preserve stored legacy codes while emitting canonical current-workflow codes."""
    return (
        legacy_code
        if legacy_saw_workflow(workflow)
        else analysis_reason_code(legacy_code, workflow)
    )


def _narrative_language_contract(config: EcosystemConfig) -> dict[str, str]:
    """Return the required concrete Job-owned language contract for generated narrative."""
    value = str(config.human_output.logs_and_reports.primary_language or "").strip()
    if value.upper() == "OPERATOR_LANGUAGE":
        value = config.human_output.operator_language
    try:
        tag = canonical_language_tag(value, "ACT narrative report language")
    except ConfigurationError as exc:
        raise ValidationError(
            "ACT creation requires one resolved Job-owned primary report language",
            code="ACT_REPORT_LANGUAGE_MISSING",
            next_action="Set the Job primary reporting language and recreate the task.",
        ) from exc
    return {
        "tag": tag,
        "authority": "CANONICAL_REPORT_NARRATIVE",
    }


@dataclass(frozen=True)
class SkillBinding:
    """Describe one registered operation Skill and its routed entrypoint."""

    skill_id: str
    workflow: str
    operation: str
    path: Path
    source_system: str
    source_version: str
    original_file: Path
    original_sha256: str
    adapted_sha256: str
    qualification_status: str
    shared_references: tuple[Path, ...] = ()


def _relative(root: Path, path: Path) -> str:
    """Return a portable governed Core/localdata path reference."""
    try:
        return declare_governed_path(root, path, "ACT task path")
    except StorageError as exc:
        raise ValidationError(str(exc), code="EXTERNAL_PATH_ESCAPE") from exc


def _vrs_provenance_reference(
    config: EcosystemConfig,
    project: ProjectSpec,
    path: Path,
    *,
    custom: bool,
) -> str:
    """Label one authorized VRS source without exposing it as a model-readable task path."""
    try:
        return _relative(config.root, path)
    except ValidationError:
        pass
    resolved = path.resolve()
    try:
        resolved.relative_to(project.path.resolve())
    except ValueError:
        if custom:
            raise ValidationError(
                f"Project custom VRS is outside its authorized Project root: {path}",
                code="EXTERNAL_PATH_ESCAPE",
            )
        validate_external_file(resolved, roots=(config.base_vrs_root,), write=False)
        return f"@BASE_VRS/{resolved.name}"
    validate_external_file(resolved, roots=(project.path,), write=False)
    return f"@PROJECT/{project.project_id}/{resolved.name}"


def _safe_task_output(task_root: Path, value: str) -> Path:
    """Resolve one fixed task output without allowing path traversal."""
    if not _SAFE_OUTPUT_RE.fullmatch(value):
        raise ValidationError(f"Unsafe ACT output path: {value}")
    path = (task_root / value).resolve()
    try:
        path.relative_to((task_root / "output").resolve())
    except ValueError as exc:
        raise ValidationError(f"ACT output path escapes output/: {value}") from exc
    return path


def load_skill_registry(root: Path) -> dict[tuple[str, str], SkillBinding]:
    """Load the operation-to-Skill registry and validate explicit file paths."""
    path = root / "system" / "config" / "skills.json"
    raw = load_json(path)
    items = raw.get("skills")
    if not isinstance(items, dict) or not items:
        raise ConfigurationError("system/config/skills.json must contain a non-empty skills mapping")
    result: dict[tuple[str, str], SkillBinding] = {}
    for skill_id, raw_item in items.items():
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise ConfigurationError("Skill registry keys must be non-empty strings")
        item = require_mapping(raw_item, f"skills[{skill_id!r}]")
        skill_id = skill_id.strip()
        workflow = require_string(item.get("workflow"), f"skills[{skill_id!r}].workflow").lower()
        operation = require_string(item.get("operation"), f"skills[{skill_id!r}].operation").lower()
        file_value = require_string(item.get("file"), f"skills[{skill_id!r}].file")
        skill_path = (root / file_value).resolve()
        if Path(file_value).suffix.lower() != ".md":
            raise ConfigurationError(f"Skill file must include its .md extension: {file_value}")
        try:
            skill_path.relative_to(root.resolve())
        except ValueError as exc:
            raise ConfigurationError(f"Skill file escapes the workspace: {file_value}") from exc
        if not skill_path.is_file():
            raise ConfigurationError(f"Registered Skill file is missing: {file_value}")
        if workflow not in ACT_OPERATIONS or operation not in ACT_OPERATIONS[workflow]:
            raise ConfigurationError(
                f"Skill {skill_id} has unsupported operation {workflow}/{operation}"
            )
        key = (workflow, operation)
        if key in result:
            raise ConfigurationError(f"Duplicate Skill binding for {workflow}/{operation}")
        shared_references: list[Path] = []
        shared_items = item.get("shared_references", [])
        if not isinstance(shared_items, list):
            raise ConfigurationError(f"Skill {skill_id} shared_references must be a list")
        for shared_item in shared_items:
            shared_item = require_mapping(shared_item, f"Skill {skill_id} shared reference")
            shared_path = (root / require_string(shared_item.get("file"), "shared reference file")).resolve()
            try:
                shared_path.relative_to(root.resolve())
                shared_path.relative_to((root / "system/skills/global/references").resolve())
            except ValueError as exc:
                raise ConfigurationError(f"Skill {skill_id} shared reference escapes global references") from exc
            if not shared_path.is_file() or sha256_file(shared_path) != shared_item.get("sha256"):
                raise ConfigurationError(f"Skill {skill_id} shared reference is missing or its hash does not match")
            if shared_path in shared_references:
                raise ConfigurationError(f"Skill {skill_id} contains a duplicate shared reference")
            shared_references.append(shared_path)
        binding = SkillBinding(
            skill_id=skill_id,
            workflow=workflow,
            operation=operation,
            path=skill_path,
            source_system=require_string(
                item.get("source_system"), f"skills[{skill_id!r}].source_system"
            ),
            source_version=require_string(
                item.get("source_version"), f"skills[{skill_id!r}].source_version"
            ),
            original_file=(root / require_string(
                item.get("original_file"), f"skills[{skill_id!r}].original_file"
            )).resolve(),
            original_sha256=require_string(
                item.get("original_sha256"), f"skills[{skill_id!r}].original_sha256"
            ).lower(),
            adapted_sha256=require_string(
                item.get("adapted_sha256"), f"skills[{skill_id!r}].adapted_sha256"
            ).lower(),
            qualification_status=require_string(
                item.get("qualification_status"), f"skills[{skill_id!r}].qualification_status"
            ).upper(),
            shared_references=tuple(shared_references),
        )
        try:
            binding.original_file.relative_to(root.resolve())
        except ValueError as exc:
            raise ConfigurationError(
                f"Skill {skill_id} original_file escapes the workspace"
            ) from exc
        if not binding.original_file.is_file():
            raise ConfigurationError(
                f"Skill {skill_id} original_file is missing: {binding.original_file}"
            )
        if sha256_file(binding.original_file) != binding.original_sha256:
            raise ConfigurationError(f"Skill {skill_id} original source hash does not match")
        if sha256_file(binding.path) != binding.adapted_sha256:
            raise ConfigurationError(f"Skill {skill_id} adapted Skill hash does not match")
        routed_texts = _skill_files(binding)
        forbidden_contracts = {
            "system/tools/bic.py": "obsolete BIC script command",
            "./saw run": "obsolete SAW controller command",
            "Cline": "provider-specific Cline instruction in provider-neutral model context",
            "SWITCH TO ACT MODE": "obsolete Cline mode-switch instruction",
            "Guided Operator input": "controller-only guided-input instruction in model context",
            "Natural-language command mapping": "controller-only natural-language routing instruction in model context",
        }
        for routed_path in routed_texts:
            text = routed_path.read_text(encoding="utf-8")
            require_canonical_target_text_vocabulary(
                text, surface=f"routed Skill file {routed_path.name}"
            )
            for token, label in forbidden_contracts.items():
                if token in text:
                    raise ConfigurationError(
                        f"Skill {skill_id} contains {label} in routed file {routed_path.name}"
                    )
            if "preflight.json" in text and "saw-preflight.json" not in text:
                raise ConfigurationError(
                    f"Skill {skill_id} uses non-canonical preflight.json in {routed_path.name}"
                )
        if binding.qualification_status != "VALIDATED":
            raise ConfigurationError(f"Skill {skill_id} qualification_status is not VALIDATED")
        result[key] = binding

    # Persisted SAW Jobs use the current owning contracts, not duplicate Skills.
    for operation in ("rtc", "stc"):
        if (operation, operation) in result:
            result[("saw", operation)] = result[(operation, operation)]

    missing = {
        (workflow, operation)
        for workflow, operations in ACT_OPERATIONS.items()
        for operation in operations
    } - set(result)
    if missing:
        formatted = ", ".join(f"{workflow}/{operation}" for workflow, operation in sorted(missing))
        raise ConfigurationError(f"Missing operation Skills: {formatted}")
    return result


def _skill_files(skill: SkillBinding) -> list[Path]:
    """Return only the canonical Skill contract files routed into ACT context."""
    files = [skill.path]
    references = skill.path.parent / "references"
    if references.is_dir():
        files.extend(
            path for path in sorted(references.iterdir())
            if path.is_file()
            and not path.name.upper().startswith("ORIGINAL-")
            and not path.name.upper().startswith("LEGACY-")
            and path.name.upper() != "RUN-RTC.MD"
        )
    files.extend(skill.shared_references)
    return files


def _load_bic_protected_rewrite_contract(config: EcosystemConfig) -> dict[str, Any]:
    """Validate the pinned BIC 4 protected REWRITE contract and every active mirror."""
    pin_path = config.root / "system" / "config" / "bic-protected-rewrite-pin.json"
    raw = load_json(pin_path)
    contract = require_mapping(raw.get("contract"), "BIC protected rewrite contract")
    contract_id = require_string(contract.get("id"), "BIC protected rewrite contract.id")
    baseline = require_string(contract.get("baseline"), "BIC protected rewrite contract.baseline")
    expected_sha256 = require_string(
        contract.get("sha256"), "BIC protected rewrite contract.sha256"
    ).lower()
    canonical_value = require_string(
        contract.get("canonical_file"), "BIC protected rewrite contract.canonical_file"
    )
    mirror_values = contract.get("mirror_files", []) or []
    if not isinstance(mirror_values, list) or any(not isinstance(item, str) for item in mirror_values):
        raise ConfigurationError("BIC protected rewrite contract.mirror_files must be a list")
    file_values = [canonical_value, *mirror_values]
    verified_files: list[dict[str, str]] = []
    for value in file_values:
        path = (config.root / value).resolve()
        try:
            path.relative_to(config.root.resolve())
        except ValueError as exc:
            raise ConfigurationError(
                f"BIC protected rewrite contract path escapes the workspace: {value}"
            ) from exc
        if not path.is_file():
            raise ConfigurationError(f"BIC protected rewrite contract file is missing: {value}")
        actual_sha256 = sha256_file(path)
        if actual_sha256 != expected_sha256:
            raise ConfigurationError(
                f"BIC protected rewrite contract hash mismatch: {value}; "
                f"expected {expected_sha256}, received {actual_sha256}"
            )
        require_canonical_target_text_vocabulary(
            path.read_text(encoding="utf-8"),
            surface=f"BIC protected rewrite contract {value}",
        )
        verified_files.append({"path": value, "sha256": actual_sha256})
    return {
        "id": contract_id,
        "baseline": baseline,
        "sha256": expected_sha256,
        "canonical_file": canonical_value,
        "verified_files": verified_files,
    }


def _load_bic_protected_verb_selection_contract(config: EcosystemConfig) -> dict[str, Any]:
    """Validate the pinned BIC verb-selection policy without pinning Python implementation."""
    pin_path = config.root / "system" / "config" / "bic-protected-verb-selection-pin.json"
    raw = load_json(pin_path)
    contract = require_mapping(raw.get("contract"), "BIC protected verb-selection contract")
    contract_id = require_string(contract.get("id"), "BIC protected verb-selection contract.id")
    baseline = require_string(contract.get("baseline"), "BIC protected verb-selection contract.baseline")
    expected_sha256 = require_string(
        contract.get("sha256"), "BIC protected verb-selection contract.sha256"
    ).lower()
    canonical_value = require_string(
        contract.get("canonical_file"), "BIC protected verb-selection contract.canonical_file"
    )
    path = (config.root / canonical_value).resolve()
    try:
        path.relative_to(config.root.resolve())
    except ValueError as exc:
        raise ConfigurationError(
            f"BIC protected verb-selection contract path escapes the workspace: {canonical_value}"
        ) from exc
    if not path.is_file():
        raise ConfigurationError(
            f"BIC protected verb-selection contract file is missing: {canonical_value}"
        )
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ConfigurationError(
            f"BIC protected verb-selection contract hash mismatch: {canonical_value}; "
            f"expected {expected_sha256}, received {actual_sha256}"
        )
    return {
        "id": contract_id,
        "baseline": baseline,
        "sha256": expected_sha256,
        "canonical_file": canonical_value,
    }


def _assert_project_scope(project: ProjectSpec, scope: AnalysisScope, label: str) -> None:
    """Require the selected project to declare the requested book in its effective scope."""
    books = set(resolve_expected_books(project.scope))
    if scope.book not in books:
        raise ValidationError(
            f"{label} project {project.project_id} does not authorize book {scope.book}"
        )


def _assert_enabled(project: ProjectSpec, label: str) -> None:
    """Require the selected project to be enabled before task evidence is routed."""
    if not project.enabled:
        raise ValidationError(f"{label} project is disabled: {project.project_id}")
    if not project.path.is_dir():
        raise ValidationError(f"{label} project folder is missing: {project.path}")


def _one_book_file(project: ProjectSpec, book: str, *, optional: bool = False) -> Path | None:
    """Select the single Scripture file for the requested book and reject duplicates or absence."""
    path = discover_book_ids(project.path).get(book)
    if path is not None and project.external:
        path = validate_external_file(path, roots=(project.path,), write=False)
    if path is None and not optional:
        raise ValidationError(
            f"Project {project.project_id} has no USFM file for task book {book}"
        )
    return path


def _select_ol_project(
    config: EcosystemConfig,
    scope: AnalysisScope,
    *,
    required: bool,
    workflow: str,
    job_id: str | None,
) -> tuple[str, ProjectSpec | None]:
    """Resolve the configured applicable original-language resource for this Job."""
    if scope.book in NT_27:
        role = "ORIGINAL_LANGUAGE_GREEK"
        binding_key = "original_language_greek"
    elif scope.book in OT_39:
        role = "ORIGINAL_LANGUAGE_HEBREW"
        binding_key = "original_language_hebrew"
    else:
        raise ValidationError(f"Cannot determine original-language source for {scope.book}")
    project_id: str | None = None
    if job_id:
        job = _load_owning_job(config, job_id, workflow)
        project_id = job.bindings.get(binding_key)
    if not project_id:
        profile = load_workflow_profile(config, config.workflow(workflow))
        project_id = profile.bindings.get(role)
    if not project_id:
        if required:
            raise ValidationError(f"Job has no configured {role} binding")
        return role, None
    project = config.project(project_id)
    if role not in project.scope.roles:
        raise ValidationError(
            f"Configured OL project {project.project_id} lacks required role {role}"
        )
    if not project.enabled or not project.path.is_dir() or project.content_state != "LOCKED":
        if required:
            raise ValidationError(f"Configured OL project {project.project_id} is not usable")
        return role, None
    try:
        _assert_project_scope(project, scope, "Original-language")
    except ValidationError:
        if required:
            raise
        return role, None
    return role, project


def _load_owning_job(
    config: EcosystemConfig,
    job_id: str,
    runtime_workflow: str,
):
    """Resolve an Operator Job through its governed runtime adapter."""
    job = JobStore(config.root, config.settings_path).load_job(job_id)
    if job.runtime_tool != runtime_workflow:
        raise ValidationError(
            f"Job {job.job_id} does not use the {runtime_workflow.upper()} runtime adapter",
            code="PROJECT_BINDING_MISMATCH",
        )
    return job


def _validate_task_projects(
    config: EcosystemConfig,
    workflow: str,
    output_project_id: str,
    contemporary_source_id: str,
    scope: AnalysisScope,
    *,
    operation: str | None = None,
    job_id: str | None = None,
    rtc_stage: str | None = None,
) -> tuple[ProjectSpec, ProjectSpec, str, ProjectSpec | None]:
    """Validate required projects and resolve optional passage-relevant OL evidence."""
    output = config.project(output_project_id)
    source = config.project(contemporary_source_id)
    output_label = "BIC TARGET" if workflow == "bic" else f"{workflow.upper()} WIP"
    source_label = "BIC SOURCE" if workflow == "bic" else f"{workflow.upper()} REFERENCE"
    _assert_enabled(output, output_label)
    _assert_enabled(source, source_label)
    if workflow != "bic":
        _assert_project_scope(output, scope, output_label)
    _assert_project_scope(source, scope, source_label)
    if output.project_id == source.project_id:
        raise ValidationError(f"{output_label} and {source_label} must be different projects")
    if source.content_state != "LOCKED":
        raise ValidationError(f"{source_label} {source.project_id} must be LOCKED")
    if workflow == "bic":
        if "GENERATED_TARGET" not in output.scope.roles:
            raise ValidationError(f"BIC output {output.project_id} lacks GENERATED_TARGET role")
        if output.content_state != "UNDER_REVIEW":
            raise ValidationError(f"BIC output {output.project_id} must be UNDER_REVIEW")
        if "CONTENT_SOURCE" not in source.scope.roles:
            raise ValidationError(f"BIC source {source.project_id} lacks CONTENT_SOURCE role")
    else:
        if "WIP" not in output.scope.roles:
            raise ValidationError(f"{workflow.upper()} output {output.project_id} lacks WIP role")
        if "REFERENCE" not in source.scope.roles:
            raise ValidationError(f"{workflow.upper()} REFERENCE {source.project_id} lacks REFERENCE role")
        if output.content_state != "UNDER_REVIEW":
            raise ValidationError(f"{workflow.upper()} WIP {output.project_id} must be UNDER_REVIEW")
    ol_role, ol_project = _select_ol_project(
        config,
        scope,
        required=(is_analysis_workflow(workflow) and (operation == "ol" or rtc_stage == "SELECTIVE_OL_ADJUDICATION")),
        workflow=workflow,
        job_id=job_id,
    )
    return output, source, ol_role, ol_project


def _resolve_bic_lexical_donor(
    config: EcosystemConfig,
    *,
    donor_project_id: str | None,
    output: ProjectSpec,
    source: ProjectSpec,
    scope: ScriptureScope,
) -> ProjectSpec:
    """Resolve and validate the BIC DONOR without granting it content authority."""
    if not donor_project_id:
        profile = load_workflow_profile(config, config.workflow("bic"))
        donor_project_id = profile.bindings.get("LEXICAL_DONOR")
    if not donor_project_id:
        raise ValidationError("BIC requires one LEXICAL_DONOR binding")
    donor = config.project(donor_project_id)
    _assert_enabled(donor, "Lexical donor")
    _assert_project_scope(donor, scope, "Lexical donor")
    if "LEXICAL_DONOR" not in donor.scope.roles:
        raise ValidationError(f"BIC donor {donor.project_id} lacks LEXICAL_DONOR role")
    if donor.content_state != "LOCKED":
        raise ValidationError(f"BIC donor {donor.project_id} must be LOCKED")
    if donor.project_id in {output.project_id, source.project_id}:
        raise ValidationError("BIC SOURCE, DONOR, and TARGET must be three distinct projects")
    if donor.language_code != output.language_code:
        raise ValidationError(
            f"BIC DONOR language {donor.language_code} must match TARGET language {output.language_code}",
            code="BIC_DONOR_TARGET_LANGUAGE_MISMATCH",
        )
    return donor


def _assert_initialized_and_ready(
    config: EcosystemConfig,
    workflow: str,
    projects: Iterable[tuple[str, ProjectSpec]],
    scope: AnalysisScope,
) -> dict[str, Any]:
    """Require fresh initialization and exact-scope resource readiness."""
    # Readiness belongs to the exact effective settings used to create the ACT. A Job
    # runtime has its own bindings, hashes, caches, and state receipt; consulting the
    # root ecosystem here would discard the Job initialization performed by the menu.
    receipt_config = config
    state_path = ecosystem_state_path(config.runtime_state_root)
    state = read_state(state_path)
    runtime_context = config.raw.get("runtime_context")
    if not state and isinstance(runtime_context, Mapping) and runtime_context.get("kind") == "JOB":
        # Direct API/CLI callers historically initialize the root configuration before
        # SAGE derives the owning Job. Preserve that route when no Job receipt exists;
        # an explicitly initialized Job receipt always takes precedence.
        base_config = load_ecosystem(config.root / "ecosystem.yml")
        base_state = read_state(ecosystem_state_path(base_config.runtime_state_root))
        if base_state:
            receipt_config = base_config
            state = base_state
    if not state:
        raise InputRequiredError(
            f"Run `{render_sage_command(['workspace', 'initialize'])}` before creating analytical ACT tasks",
            code="WORKSPACE_INITIALIZATION_INPUT_REQUIRED",
            received="NOT_RUN",
            suggestions=[
                {
                    "value": "sage workspace initialize",
                    "label": "Run guided workspace initialization",
                    "score": 1.0,
                    "confidence": "AUTHORITATIVE",
                }
            ],
            next_action=f"Run `{render_sage_command(['workspace', 'initialize'])}` and retry the exact scope.",
            affected_scope=scope.label(),
        )
    if state.get("state") not in {"READY", "READY_WITH_ACTIONS", "READY_WITH_LIMITATIONS"}:
        raise ValidationError(
            "The last workspace initialization is not executable; use guided remediation and rerun initialization",
            code="WORKSPACE_INITIALIZATION_BLOCKED",
            affected_scope=scope.label(),
        )
    current_override_hash = (
        sha256_file(receipt_config.operator_overrides_path)
        if receipt_config.operator_overrides_path and receipt_config.operator_overrides_path.is_file()
        else None
    )
    if (
        state.get("settings_sha256") != sha256_file(receipt_config.settings_path)
        or state.get("operator_overrides_sha256") != current_override_hash
    ):
        raise InputRequiredError(
            f"Effective settings changed after initialization; rerun `{render_sage_command(['workspace', 'initialize'])}`",
            code="WORKSPACE_INITIALIZATION_INPUT_REQUIRED",
            received="STALE",
            suggestions=[
                {
                    "value": "sage workspace initialize",
                    "label": "Rerun guided workspace initialization",
                    "score": 1.0,
                    "confidence": "AUTHORITATIVE",
                }
            ],
            affected_scope=scope.label(),
            next_action="Rerun workspace initialization and recreate the task.",
        )
    workflow_state = (state.get("workflows", {}) or {}).get(workflow, {})
    if workflow_state.get("qualification_status") != "VALIDATED":
        raise ValidationError(
            f"{workflow.upper()} analytical qualification is not VALIDATED; ACT creation is blocked",
            code="WORKFLOW_QUALIFICATION_NOT_VALIDATED",
            affected_scope=scope.label(),
        )
    if workflow_state.get("controller_available") is False:
        raise ValidationError(
            f"{workflow.upper()} controller is unavailable according to the last initialization",
            code="WORKFLOW_CONTROLLER_UNAVAILABLE",
            affected_scope=scope.label(),
        )
    if int(workflow_state.get("pending_transactions", 0) or 0) != 0 or incomplete_transactions(
        config.workflow(workflow).transaction_root
    ):
        raise ValidationError(
            f"{workflow.upper()} has incomplete transactions; recover them first",
            code="INCOMPLETE_TRANSACTION",
            next_action=f"Run `{render_sage_command(['transaction', 'recover', '--workflow', workflow])}`.",
            affected_scope=scope.label(),
        )
    compiled: dict[str, Any] = {}
    for label, project in projects:
        result = compile_project_scope(config, project, scope)
        status = str(result.get("status", "BLOCKED"))
        acceptable = set(READY_RESOURCE_STATES)
        issue_codes = sorted({str(item.get("code", "UNKNOWN")) for item in result.get("issues", [])})
        if workflow == "bic" and label in {"Output", "BIC TARGET"} and project.allow_empty:
            acceptable.add("NOT_GENERATED")
            if status == "BLOCKED" and set(issue_codes) <= {"REQUESTED_BOOKS_MISSING"}:
                result = {**result, "status": "NOT_GENERATED", "generation_candidate": True}
                status = "NOT_GENERATED"
        if status not in acceptable:
            raise ValidationError(
                f"{label} project {project.project_id} is {status} for {scope.label()}; "
                "only defects intersecting the requested scope can block this task",
                code="REQUESTED_SCOPE_BLOCKED",
                affected_scope=scope.label(),
                next_action="Correct the listed in-scope resource defects, then rerun task creation.",
                details={
                    "project_id": project.project_id,
                    "resource_role": label,
                    "issue_codes": issue_codes,
                    "blocking_issues": [
                        {
                            "code": str(item.get("code", "UNKNOWN")),
                            "reference": str(item.get("reference", "") or scope.label()),
                            "message": str(item.get("message", "Resource validation failed.")),
                        }
                        for item in result.get("issues", [])
                    ],
                    "out_of_scope_issue_count": len(result.get("out_of_scope_issues", [])),
                },
            )
        compiled[project.project_id] = result
    return compiled


def _scope_is_contained(parent: AnalysisScope, child: ScriptureScope) -> bool:
    """Return whether one governed child work-unit scope is contained by its Run scope."""
    if isinstance(parent, ScriptureScopeSet):
        return any(_scope_is_contained(portion, child) for portion in parent.portions)
    if child.book != parent.book:
        return False
    if child.start_chapter is None:
        return isinstance(parent, ScriptureScope) and parent.start_chapter is None
    if child.start_verse is None:
        end_chapter = child.end_chapter or child.start_chapter
        return all(
            parent.contains(VerseRef(parent.book, chapter, verse))
            for chapter in (child.start_chapter, end_chapter)
            for verse in (1, 999999)
        )
    return all(
        parent.contains(VerseRef(parent.book, chapter, verse))
        for chapter, verse in (
            (child.start_chapter, child.start_verse),
            (child.end_chapter or child.start_chapter, child.end_verse or child.start_verse),
        )
    )


def _ensure_task_context(
    config: EcosystemConfig,
    *,
    workflow: str,
    operation: str,
    output_project_id: str,
    contemporary_source_id: str | None,
    lexical_donor_id: str | None,
    scope: AnalysisScope,
    focus: str | None,
    check_type: str | None,
    job_id: str | None,
    run_id: str | None,
    allow_run_subscope: bool = False,
) -> tuple[str, str, str | None]:
    """Require one persisted Job and Run for every governed task."""
    if bool(job_id) != bool(run_id):
        raise ValidationError("job_id and run_id must be supplied together")
    source_id = str(contemporary_source_id or "").strip() or None
    if source_id is None and not (is_analysis_workflow(workflow) and operation == "stc"):
        raise ValidationError(
            f"{workflow.upper()} {operation.upper()} requires a source/reference Project"
        )
    store = JobStore(config.root, config.settings_path)
    if not job_id and workflow == "rtc":
        # Only the legacy SAW shortcut may still mint a Job; an RTC task belongs to an existing RTC Job.
        raise ValidationError(
            "RTC tasks require an existing RTC Job and Run",
            code="RTC_JOB_REQUIRED",
            next_action="Create the RTC Job from the Main Menu, then pass --job-id and --run-id.",
        )
    if not job_id:
        profile = load_workflow_profile(config, config.workflow(workflow))
        if workflow == "bic":
            assert source_id is not None
            donor_id = lexical_donor_id or profile.bindings.get("LEXICAL_DONOR")
            if not donor_id:
                raise ValidationError("BIC task context requires one lexical DONOR")
            project_id = default_job_name(
                "bic", output_project_id, source_id, donor_id
            )
            output = config.project(output_project_id)
            source = config.project(source_id)
            job = store.create_job(
                tool="bic",
                job_id=project_id,
                display_name=f"{source_id} via {donor_id} to {output_project_id}",
                bindings={
                    "content_source": source_id,
                    "lexical_donor": donor_id,
                    "generated_target": output_project_id,
                    **({"original_language_greek": profile.bindings["ORIGINAL_LANGUAGE_GREEK"]} if profile.bindings.get("ORIGINAL_LANGUAGE_GREEK") else {}),
                    **({"original_language_hebrew": profile.bindings["ORIGINAL_LANGUAGE_HEBREW"]} if profile.bindings.get("ORIGINAL_LANGUAGE_HEBREW") else {}),
                },
                # Without an explicit TARGET variant the Job resolves TARGET grammar from DONOR language data.
                profiles={
                    "source_grammar": source.profile_ref,
                    **({"target_grammar": output.profile_ref} if output.profile_variant else {}),
                },
                defaults={},
            )
            lexical_donor_id = donor_id
            run_operation = "bic"
        elif operation == "stc":
            snapshot_time = require_project_imported_at(
                config.root,
                output_project_id,
            )
            project_id = canonical_analysis_job_id(
                "stc", output_project_id, snapshot_time.astimezone(timezone.utc).strftime("%Y%m%d")
            )
            output = config.project(output_project_id)
            job = store.create_job(
                tool="stc",
                job_id=project_id,
                display_name=f"{output_project_id} analyzed against GRK/HEB",
                bindings={"wip": output_project_id},
                profiles={"target_grammar": output.profile_ref},
                defaults={},
                imported_at=snapshot_time,
            )
            run_operation = "stc"
        else:
            assert source_id is not None
            project_id = default_job_name(
                "saw", output_project_id, source_id
            )
            output = config.project(output_project_id)
            job = store.create_job(
                tool="saw",
                job_id=project_id,
                display_name=f"{output_project_id} analyzed against {source_id}",
                bindings={
                    "wip": output_project_id,
                    "reference": source_id,
                    **({"original_language_greek": profile.bindings["ORIGINAL_LANGUAGE_GREEK"]} if profile.bindings.get("ORIGINAL_LANGUAGE_GREEK") else {}),
                    **({"original_language_hebrew": profile.bindings["ORIGINAL_LANGUAGE_HEBREW"]} if profile.bindings.get("ORIGINAL_LANGUAGE_HEBREW") else {}),
                },
                profiles={"target_grammar": output.profile_ref},
                defaults={},
            )
            run_operation = operation
        # Reuse one active scope-owned Run so direct shortcuts obey the same Project/Job/Run grammar as the Control Center.
        reusable = None
        for candidate in store.list_runs(job, include_archived=False):
            if candidate.status in RUN_CLOSED_STATUSES:
                continue
            if candidate.operation != run_operation or not scripture_scopes_equal(
                candidate.scope, scope.label(), workflow=workflow, operation=run_operation,
            ):
                continue
            if is_analysis_workflow(workflow) and (candidate.focus != focus or candidate.check_type != check_type):
                continue
            reusable = candidate
            break
        run = reusable or store.create_run(
            job,
            operation=run_operation,
            scope=scope.label(),
            focus=focus,
            check_type=check_type,
        )
        return job.job_id, run.run_id, lexical_donor_id

    job = _load_owning_job(config, job_id, workflow)
    run = store.load_run(job, run_id)
    if job.status != "ACTIVE":
        raise ValidationError(f"Job {job.job_id} is not ACTIVE")
    if not scripture_scopes_equal(run.scope, scope.label(), workflow=workflow, operation=run.operation):
        run_scope = validate_scripture_scope(run.scope, workflow=workflow, operation=run.operation)
        if not (allow_run_subscope and _scope_is_contained(run_scope, scope)):
            raise ValidationError("Task scope does not match the owning Run scope")
    if workflow == "bic":
        if run.operation != "bic":
            raise ValidationError("BIC tasks must belong to one BIC Run")
        expected = {
            "content_source": source_id,
            "generated_target": output_project_id,
        }
        donor_id = lexical_donor_id or job.bindings["lexical_donor"]
        expected["lexical_donor"] = donor_id
        lexical_donor_id = donor_id
    else:
        if run.operation != operation:
            raise ValidationError(
                f"{_analysis_identity(workflow)} task operation {operation} does not match Run operation {run.operation}"
            )
        expected = {"wip": output_project_id}
        if operation != "stc":
            expected["reference"] = source_id
        if run.focus != focus:
            raise ValidationError("Analysis task focus does not match the owning Run")
        if run.check_type != check_type:
            raise ValidationError("Analysis task check type does not match the owning Run")
    mismatches = {
        key: {"job": job.bindings.get(key), "task": value}
        for key, value in expected.items()
        if job.bindings.get(key) != value
    }
    if mismatches:
        raise ValidationError(
            "Task resource bindings do not match the owning Job",
            code="PROJECT_BINDING_MISMATCH",
            details=mismatches,
        )
    return job.job_id, run.run_id, lexical_donor_id


def _load_list(path: Path) -> list[dict[str, Any]]:
    """Load a JSON list from governed storage and reject any other top-level shape."""
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid governed list {path}: {exc}") from exc
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValidationError(f"Governed list must contain JSON objects: {path}")
    return [dict(row) for row in value]


def _memory_root(config: EcosystemConfig) -> Path:
    """Return the BIC memory-governance directory beneath the configured workflow state root."""
    return workflow_memory_root(config.workflow("bic"))


def _require_inspect_complete(
    config: EcosystemConfig,
    scope: ScriptureScope,
    *,
    bic_job_id: str | None,
) -> dict[str, Any]:
    """Require committed INSPECT for the same BIC project and return its evidence receipt."""
    return inspect_completion_and_review_status(
        _memory_root(config), scope.label(), bic_job_id=bic_job_id
    )


def _expected_outputs(workflow: str, operation: str) -> tuple[str, ...]:
    """Return the exact output allowlist for one workflow operation."""
    if workflow == "nca" and operation == "numbers":
        return ("output/model-evidence.json",)
    if workflow == "bic" and operation == "inspect":
        return ("output/inspect-submission.json",)
    if workflow == "bic" and operation == "rewrite":
        return (
            "output/rewrite.usfm",
            "output/grammar-assessment.json",
            "output/translation-challenges.json",
        )
    if workflow == "bic" and operation == "self_check":
        return ("output/self-check.usfm", "output/grammar-assessment.json")
    return ("output/findings.json",)


def _load_predecessor(
    config: EcosystemConfig,
    predecessor_task: str | None,
    *,
    output_project: str,
    contemporary_source: str,
    lexical_donor: str,
    scope: str,
) -> dict[str, Any]:
    """Load and validate the immutable predecessor task required by a chained BIC operation."""
    if not predecessor_task:
        raise ValidationError("BIC SELF-CHECK requires --predecessor-task for a validated REWRITE task")
    path = Path(predecessor_task)
    if not path.is_absolute():
        path = (config.root / path).resolve()
    try:
        path.relative_to(config.workflow("bic").output_root.resolve())
    except ValueError as exc:
        raise ValidationError("SELF-CHECK predecessor must be inside the BIC output root") from exc
    submission_path = path.parent / "validation" / "submission.json"
    if not submission_path.is_file():
        raise ValidationError("SELF-CHECK predecessor has not been submitted and validated")
    submission = json.loads(submission_path.read_text(encoding="utf-8"))
    accepted_statuses = {"STAGED_VALIDATED", "STAGED_VALIDATED_WITH_CHALLENGES"}
    if submission.get("status") not in accepted_statuses or submission.get("operation") != "rewrite":
        raise ValidationError(
            "SELF-CHECK predecessor must be a validated BIC REWRITE task"
        )
    if submission.get("output_project") != output_project:
        raise ValidationError("SELF-CHECK predecessor output project differs from this task")
    if submission.get("contemporary_source") != contemporary_source:
        raise ValidationError("SELF-CHECK predecessor SOURCE differs from this task")
    if submission.get("lexical_donor") != lexical_donor:
        raise ValidationError("SELF-CHECK predecessor DONOR differs from this task")
    if submission.get("scope") != scope:
        raise ValidationError("SELF-CHECK predecessor scope differs from this task")
    challenge_path = path.parent / "validation" / "translation-challenge-ledger.json"
    if not challenge_path.is_file():
        challenge_path = path.parent / "validation" / "normalized-translation-challenges.json"
    rewrite_path = path.parent / "output" / "rewrite.usfm"
    if not rewrite_path.is_file():
        raise ValidationError("SELF-CHECK predecessor rewrite.usfm is missing")
    try:
        predecessor_manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid predecessor manifest: {path}: {exc}") from exc
    if not isinstance(predecessor_manifest, dict):
        raise ValidationError("SELF-CHECK predecessor manifest must be a JSON object")
    predecessor_fingerprints = dict(predecessor_manifest.get("resource_fingerprints", {}))
    cohort_sha256 = str(predecessor_fingerprints.get("bic.evidence_cohort", ""))
    if not cohort_sha256:
        raise ValidationError(
            "SELF-CHECK predecessor lacks the immutable BIC evidence cohort",
            code="BIC_EVIDENCE_COHORT_MISSING",
        )
    ol_used = bool(submission.get("conditional_ol_evidence_used", False))
    inherited_ol: dict[str, Any] | None = None
    if ol_used:
        ol_path = path.parent / "packet" / "original-language.sfm"
        authority_profile_path = path.parent / "packet" / "ol-authority-profile.yml"
        vrs_path = path.parent / "packet" / "conditional-ol-vrs-evidence.json"
        if not ol_path.is_file() or not authority_profile_path.is_file() or not vrs_path.is_file():
            raise ValidationError(
                "REWRITE reports OL use but its exact conditional OL evidence/profile is missing",
                code="BIC_PREDECESSOR_OL_EVIDENCE_MISSING",
            )
        conditional = {
            str(item.get("path")): str(item.get("sha256", ""))
            for item in predecessor_manifest.get("conditional_reads", [])
            if isinstance(item, dict)
        }
        for evidence_path in (ol_path, authority_profile_path, vrs_path):
            relative = _relative(config.root, evidence_path)
            expected = conditional.get(relative)
            actual = sha256_file(evidence_path)
            if not expected or expected != actual:
                raise ValidationError(
                    f"Predecessor OL evidence fingerprint mismatch: {relative}",
                    code="BIC_PREDECESSOR_OL_EVIDENCE_CHANGED",
                )
        inherited_ol = {
            "sfm_path": ol_path,
            "sfm_sha256": sha256_file(ol_path),
            "authority_profile_path": authority_profile_path,
            "authority_profile_sha256": sha256_file(authority_profile_path),
            "vrs_path": vrs_path,
            "vrs_sha256": sha256_file(vrs_path),
            "sources": list(predecessor_manifest.get("original_language_sources", [])),
        }
    return {
        "manifest_path": path,
        "manifest_sha256": sha256_file(path),
        "submission_path": submission_path,
        "submission_sha256": sha256_file(submission_path),
        "rewrite_path": rewrite_path,
        "rewrite_sha256": sha256_file(rewrite_path),
        "task_id": submission.get("task_id"),
        "challenge_path": challenge_path if challenge_path.is_file() else None,
        "evidence_cohort_sha256": cohort_sha256,
        "conditional_ol_evidence_used": ol_used,
        "inherited_ol": inherited_ol,
    }


def _target_book_filename(project: ProjectSpec, book: str) -> str:
    """Generate a target-owned Paratext filename without inheriting source identity."""
    book_number = BOOK_ORDER.get(book)
    if book_number is None:
        raise ValidationError(
            f"BIC TARGET filename cannot resolve the canonical book number for {book}",
            code="TARGET_BOOK_FILENAME_UNSUPPORTED",
        )
    declared_filename = template_book_filename(project.path, book)
    if declared_filename is not None:
        return declared_filename
    conventions: set[tuple[str, str]] = set()
    for path in sorted(discover_book_ids(project.path).values()):
        match = re.match(r"^\d{2}[A-Za-z0-9]{3}(?P<suffix>.*)$", path.stem)
        if match:
            conventions.add((match.group("suffix"), path.suffix or ".SFM"))
    if len(conventions) > 1:
        raise ValidationError(
            f"BIC TARGET project {project.project_id} has inconsistent Scripture filename conventions",
            code="TARGET_BOOK_FILENAME_AMBIGUOUS",
        )
    # A SAGE-created localdata TARGET uses plain {NN}{BOOK}.SFM names for a clean Paratext import.
    suffix, extension = (
        next(iter(conventions))
        if conventions
        else ("" if is_generated_target_folder(project.path) else project.project_id, ".SFM")
    )
    return f"{paratext_book_digits(book)}{book}{suffix}{extension}"


def _required_review_checks(
    operation: str,
    check_type: str | None,
    rtc_stage: str | None = None,
    rtc_policy: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return exact review checks for one analysis task or composite RTC stage."""
    if operation == "rtc":
        if rtc_stage == "STRUCTURAL_ADJUDICATION":
            return ["STRUCTURAL_ADJUDICATION"]
        if rtc_stage == "SELECTIVE_OL_ADJUDICATION":
            return ["WIP_REFERENCE_SOURCE_ADJUDICATION"]
        checks = dict((rtc_policy or {}).get("checks") or {})
        if not checks:
            return [
                "MEANING_EQUIVALENCE",
                "GRAMMAR",
                "TERMINOLOGY",
                "PARTICIPANT_REFERENCE",
                "QUOTATION_STRUCTURE",
                "CROSS_REFERENCE",
            ]
        required: list[str] = []
        if checks.get("translation_meaning", True):
            required.extend(["MEANING_EQUIVALENCE", "VERSE_BRIDGE_CONTENT"])
        if checks.get("language_readability", True):
            required.append("GRAMMAR")
        if checks.get("consistency", True):
            required.extend(["TERMINOLOGY", "PARTICIPANT_REFERENCE"])
        if checks.get("structure_completeness", True):
            # VERSE_BRIDGE_MAPPING is decided in code from the WIP↔REFERENCE alignment, not by the model.
            required.append("QUOTATION_STRUCTURE")
        required.append("CROSS_REFERENCE")
        return required
    if operation == "focused":
        return [check_type or "CUSTOM_BOUNDED_CHECK"]
    return ["ORIGINAL_LANGUAGE_COMPARISON"]


def _scope_intersects(scope: ScriptureScope, reference: str) -> bool:
    """Return whether a bounded reference set intersects one child Scripture scope."""
    try:
        portions = parse_scope_set(str(reference))
    except ValidationError:
        return False
    if scope.start_chapter is None:
        return any(part.book == scope.book for part in portions)
    scope_start = (scope.start_chapter, scope.start_verse or 0)
    scope_end = (scope.end_chapter or scope.start_chapter, scope.end_verse if scope.start_verse is not None else 10**9)
    for part in portions:
        if part.book != scope.book or part.start_chapter is None:
            continue
        part_start = (part.start_chapter, part.start_verse or 0)
        part_end = (part.end_chapter or part.start_chapter, part.end_verse if part.start_verse is not None else 10**9)
        if part_start <= scope_end and scope_start <= part_end:
            return True
    return False


def _approved_rtc_work_plan(
    config: EcosystemConfig,
    *,
    workflow: str,
    job_id: str,
    run_id: str,
    output_project_id: str,
    scope: AnalysisScope,
) -> dict[str, Any] | None:
    """Load and revalidate the Operator-approved RTC work-unit plan for one Run."""
    identity = _analysis_identity(workflow)
    store = JobStore(config.root, config.settings_path)
    job = _load_owning_job(config, job_id, workflow)
    run = store.load_run(job, run_id)
    if not run.approved_work_plan_path:
        return None
    plan_path = resolve_persisted_path(
        config.root, run.approved_work_plan_path, "approved RTC work plan"
    )
    try:
        plan_path.relative_to(run.root.resolve())
    except ValueError as exc:
        raise ValidationError(
            f"Approved {identity} work plan is outside its owning Run",
            code=_analysis_code(workflow, "SAW_APPROVED_PLAN_INVALID"),
        ) from exc
    if not plan_path.is_file():
        raise ValidationError(
            f"Approved {identity} work plan is missing",
            code=_analysis_code(workflow, "SAW_APPROVED_PLAN_STALE"),
            affected_scope=scope.label(),
            next_action=f"Rebuild and approve the affected {identity} Run plan.",
        )
    plan = load_json(plan_path)
    expected_identity = {
        "workflow_id": workflow,
        "operation": "rtc",
        "operator_scope": scope.label(),
        "project_id": output_project_id,
        "approved_job_id": job_id,
        "approved_run_id": run_id,
        "approval_status": "OPERATOR_APPROVED",
    }
    for key, expected in expected_identity.items():
        if str(plan.get(key) or "") != expected:
            raise ValidationError(
                f"Approved {identity} work plan {key} does not match its Run",
                code=_analysis_code(workflow, "SAW_APPROVED_PLAN_INVALID"),
                affected_scope=scope.label(),
                next_action=f"Rebuild and approve the affected {identity} Run plan.",
            )
    units = plan.get("units")
    if not isinstance(units, list) or not units or any(not isinstance(item, dict) for item in units):
        raise ValidationError(
            f"Approved {identity} work plan has no valid work-unit inventory",
            code=_analysis_code(workflow, "SAW_APPROVED_PLAN_INVALID"),
            affected_scope=scope.label(),
        )

    # Approval freezes boundaries, not stale content: recompile and reconcile every
    # primary coordinate before any child task can inherit the approved unit IDs.
    output = config.project(output_project_id)
    compiled = compile_project_scope(config, output, scope)
    if compiled.get("status") not in READY_RESOURCE_STATES:
        raise ValidationError(
            f"{identity} WIP is no longer ready for the approved work plan",
            code=_analysis_code(workflow, "SAW_APPROVED_PLAN_STALE"),
            affected_scope=scope.label(),
            next_action="Correct the WIP resource, then rebuild and approve the Run plan.",
        )
    hashes = dict(plan.get("shared_hashes") or {})
    current_hashes = {
        "resource_sha256": str(compiled.get("resource_sha256") or ""),
        "compiled_files_sha256": str(compiled.get("compiled_files_sha256") or ""),
        "effective_vrs_sha256": str(
            dict(compiled.get("effective_vrs") or {}).get("effective_sha256") or ""
        ),
        "structure_policy_sha256": str(
            dict(compiled.get("structure_policy") or {}).get("effective_sha256") or ""
        ),
    }
    changed = [
        key for key, value in current_hashes.items()
        if hashes.get(key) and str(hashes.get(key)) != value
    ]
    if changed:
        raise ValidationError(
            f"{identity} WIP changed after work-unit approval: " + ", ".join(changed),
            code=_analysis_code(workflow, "SAW_APPROVED_PLAN_STALE"),
            affected_scope=scope.label(),
            next_action=f"Rebuild and approve the affected {identity} Run plan.",
        )

    rtc_plan_schema = str(plan.get("schema_version") or "") in {"1.3", "1.4"}
    rtc_sizing_contract = None
    if rtc_plan_schema:
        profile = load_workflow_profile(config, config.workflow(workflow))
        reference_project_id = str(plan.get("reference_project_id") or "")
        if reference_project_id != str(profile.bindings.get("REFERENCE") or ""):
            raise ValidationError(
                f"{identity} REFERENCE binding changed after work-unit approval",
                code=_analysis_code(workflow, "SAW_APPROVED_PLAN_STALE"),
                affected_scope=scope.label(),
                next_action=f"Rebuild and approve the affected {identity} Run plan.",
            )
        sizing = profile.require_rtc_sizing()
        rtc_sizing_contract = sizing
        sizing.validate_active_provider(
            str(load_llm_settings(config.root).get("selected_provider") or "")
        )
        if dict(plan.get("rtc_sizing") or {}) != sizing.to_dict():
            raise ValidationError(
                f"{identity} RTC sizing policy changed after work-unit approval",
                code=_analysis_code(workflow, "SAW_APPROVED_PLAN_STALE"),
                affected_scope=scope.label(),
                next_action=f"Rebuild and approve the affected {identity} Run plan.",
            )
        persisted_planner = dict(plan.get("rtc_planner") or {})
        persisted_planner_version = str(
            persisted_planner.get("version") or LEGACY_RTC_PLANNER_VERSION
        )
        if persisted_planner_version not in {
            RTC_PLANNER_VERSION,
            LEGACY_RTC_PLANNER_VERSION,
        }:
            raise ValidationError(
                f"Unsupported persisted RTC planner version: {persisted_planner_version}",
                code="RTC_PLANNER_VERSION_UNSUPPORTED",
                affected_scope=scope.label(),
                next_action="Resume with a supported SAGE release or rebuild and approve the Run plan.",
            )
        expected_planner = {
            "version": persisted_planner_version,
            "handoff_contract_version": RTC_HANDOFF_CONTRACT_VERSION,
            "prompt_schema_projection_version": rtc_prompt_schema_projection_version(workflow),
            "slicing_stream": "WIP",
            "boundary_streams": ["WIP", "REFERENCE"],
            "reference_correlation": (
                "CANONICAL_PROJECT_VRS"
                if persisted_planner_version == RTC_PLANNER_VERSION
                else "EXACT_WIP_SCRIPTURE_RANGE"
            ),
        }
        if persisted_planner != expected_planner:
            raise ValidationError(
                f"{identity} RTC planner/prompt/schema contract changed after work-unit approval",
                code=_analysis_code(workflow, "SAW_APPROVED_PLAN_STALE"),
                affected_scope=scope.label(),
                next_action=f"Rebuild and approve the affected {identity} Run plan.",
            )
        reference = config.project(reference_project_id)
        reference_compiled = compile_project_scope(config, reference, scope)
        if reference_compiled.get("status") not in READY_RESOURCE_STATES:
            raise ValidationError(
                f"{identity} REFERENCE is no longer ready for the approved work plan",
                code=_analysis_code(workflow, "SAW_APPROVED_PLAN_STALE"),
                affected_scope=scope.label(),
                next_action="Correct the REFERENCE resource, then rebuild and approve the Run plan.",
            )
        reference_hashes = {
            "reference_resource_sha256": str(reference_compiled.get("resource_sha256") or ""),
            "reference_compiled_files_sha256": str(
                reference_compiled.get("compiled_files_sha256") or ""
            ),
            "reference_effective_vrs_sha256": str(
                dict(reference_compiled.get("effective_vrs") or {}).get("effective_sha256") or ""
            ),
            "reference_structure_policy_sha256": str(
                dict(reference_compiled.get("structure_policy") or {}).get("effective_sha256") or ""
            ),
        }
        missing_reference_hashes = [
            key for key in reference_hashes if not str(hashes.get(key) or "")
        ]
        changed_reference_hashes = [
            key
            for key, value in reference_hashes.items()
            if str(hashes.get(key) or "") != value
        ]
        if missing_reference_hashes or changed_reference_hashes:
            raise ValidationError(
                f"{identity} REFERENCE or its planning contract changed after work-unit approval: "
                + ", ".join(sorted(set(missing_reference_hashes + changed_reference_hashes))),
                code=_analysis_code(workflow, "SAW_APPROVED_PLAN_STALE"),
                affected_scope=scope.label(),
                next_action=f"Rebuild and approve the affected {identity} Run plan.",
            )

    records = records_from_project_result(
        output_project_id,
        compiled,
        resource_role="WIP",
    )
    selected = select_records_for_scope(records, scope)
    expected_refs = [ref for record in selected for ref in sorted(record.refs)]
    observed_refs: list[VerseRef] = []
    seen_unit_ids: set[str] = set()
    for index, unit in enumerate(units, start=1):
        unit_id = str(unit.get("unit_id") or "").strip()
        primary_scope = str(unit.get("primary_scope") or "").strip()
        refs = [str(value) for value in unit.get("primary_references", [])]
        if not unit_id or unit_id in seen_unit_ids or not primary_scope or not refs:
            raise ValidationError(
                f"Approved {identity} work unit {index} has an invalid identity or primary inventory",
                code=_analysis_code(workflow, "SAW_APPROVED_PLAN_INVALID"),
                affected_scope=scope.label(),
            )
        if rtc_plan_schema:
            package = unit.get("rtc_package")
            if not isinstance(package, Mapping) or rtc_sizing_contract is None:
                raise ValidationError(
                    f"Approved {identity} work unit {unit_id} lacks its RTC package projection",
                    code=_analysis_code(workflow, "SAW_APPROVED_PLAN_INVALID"),
                    affected_scope=primary_scope,
                    next_action=f"Rebuild and approve the affected {identity} Run plan.",
                )
            try:
                wip_tokens = int(dict(package.get("wip") or {})["estimated_tokens"])
                route_tokens = int(dict(package.get("route") or {})["estimated_tokens"])
                route_bytes = int(dict(package.get("route") or {})["serialized_bytes"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValidationError(
                    f"Approved {identity} work unit {unit_id} has an invalid RTC package projection",
                    code=_analysis_code(workflow, "SAW_APPROVED_PLAN_INVALID"),
                    affected_scope=primary_scope,
                ) from exc
            if str(package.get("projection") or "") != persisted_planner_version:
                raise ValidationError(
                    f"Approved {identity} work unit {unit_id} uses a different RTC planner projection",
                    code=_analysis_code(workflow, "SAW_APPROVED_PLAN_INVALID"),
                    affected_scope=primary_scope,
                )
            if persisted_planner_version == RTC_PLANNER_VERSION:
                alignment = package.get("alignment")
                required_alignment_keys = {
                    "primary_local_atoms",
                    "canonical_atoms",
                    "reference_local_spans",
                    "missing_canonical_atoms",
                }
                if not isinstance(alignment, Mapping) or set(alignment) != required_alignment_keys:
                    raise ValidationError(
                        f"Approved {identity} work unit {unit_id} lacks canonical RTC alignment metadata",
                        code=_analysis_code(workflow, "SAW_APPROVED_PLAN_INVALID"),
                        affected_scope=primary_scope,
                    )
            if (
                wip_tokens >= rtc_sizing_contract.wip_hard_exclusive_tokens
                or route_tokens > rtc_sizing_contract.route_hard_max_tokens
                or route_bytes > rtc_sizing_contract.route_hard_serialized_bytes
            ):
                raise ValidationError(
                    f"Approved {identity} work unit {unit_id} no longer fits RTC sizing limits",
                    code=_analysis_code(workflow, "SAW_APPROVED_PLAN_STALE"),
                    affected_scope=primary_scope,
                    next_action=f"Rebuild and approve the affected {identity} Run plan.",
                )
        seen_unit_ids.add(unit_id)
        parsed_unit = parse_scope(primary_scope)
        try:
            unit_refs = list(expand_reference_atoms(refs))
        except ValidationError as exc:
            raise ValidationError(
                f"Approved {identity} work unit {unit_id} has an invalid primary inventory",
                code=_analysis_code(workflow, "SAW_APPROVED_PLAN_INVALID"),
                affected_scope=primary_scope,
            ) from exc
        refs_inside_unit = all(parsed_unit.contains(ref) for ref in unit_refs)
        declared_atoms = unit.get("primary_coverage_atoms")
        if declared_atoms is not None:
            if not isinstance(declared_atoms, list) or atomic_reference_labels(
                str(value) for value in declared_atoms
            ) != tuple(ref.label() for ref in unit_refs):
                raise ValidationError(
                    f"Approved {identity} work unit {unit_id} has inconsistent canonical coverage atoms",
                    code=_analysis_code(workflow, "SAW_APPROVED_PLAN_INVALID"),
                    affected_scope=primary_scope,
                )
        if parsed_unit.book != scope.book or not refs_inside_unit:
            raise ValidationError(
                f"Approved {identity} work unit {unit_id} has references outside {primary_scope}",
                code=_analysis_code(workflow, "SAW_APPROVED_PLAN_INVALID"),
                affected_scope=primary_scope,
            )
        observed_refs.extend(unit_refs)
    if observed_refs != expected_refs or len(observed_refs) != len(set(observed_refs)):
        expected_set = set(expected_refs)
        observed_set = set(observed_refs)
        raise ValidationError(
            f"Approved {identity} work units no longer reconcile exact WIP coordinates",
            code=_analysis_code(workflow, "SAW_APPROVED_PLAN_STALE"),
            affected_scope=scope.label(),
            next_action=f"Rebuild and approve the affected {identity} Run plan.",
            details={
                "missing_coordinates": [
                    ref.label() for ref in sorted(expected_set - observed_set)
                ],
                "extra_coordinates": [
                    ref.label() for ref in sorted(observed_set - expected_set)
                ],
                "duplicate_coordinates": sorted({
                    ref.label() for ref in observed_refs if observed_refs.count(ref) > 1
                }),
            },
        )
    portion_total = len(units)
    for index, unit in enumerate(units, start=1):
        unit["review_portion_id"] = str(unit["unit_id"])
        unit["review_portion_index"] = index
        unit["review_portion_total"] = portion_total
        unit["review_portion_scope"] = str(unit["primary_scope"])
    plan["units"] = units
    return {**plan, "approved_manifest_path": str(plan_path)}


def _rollback_unregistered_stage_tasks(
    config: EcosystemConfig,
    workflow_id: str,
    run_id: str,
    tasks: Sequence[Mapping[str, Any]],
) -> None:
    """Remove only child tasks created by an RTC stage that failed before publication."""
    import shutil

    workflow = config.workflow(workflow_id)
    expected_task_parent = task_container(workflow, run_id).resolve()
    expected_control_parent = (workflow.state_root / "act-tasks").resolve()
    for task in reversed(tasks):
        manifest_path = Path(str(task.get("manifest_path") or "")).resolve()
        task_root = manifest_path.parent
        control_path = Path(str(task.get("control_path") or "")).resolve()
        if task_root.parent != expected_task_parent:
            raise ValidationError(
                "Refusing to roll back an RTC stage task outside its current Run",
                code=_analysis_code(workflow_id, "SAW_TASK_ROLLBACK_BOUNDARY_VIOLATION"),
            )
        if control_path.parent != expected_control_parent:
            raise ValidationError(
                "Refusing to roll back an RTC stage control outside its governed state",
                code=_analysis_code(workflow_id, "SAW_TASK_ROLLBACK_BOUNDARY_VIOLATION"),
            )
        if control_path.is_file():
            try:
                os.chmod(control_path, 0o600)
            except OSError:
                pass
            control_path.unlink()
        if task_root.is_dir():
            for path in task_root.rglob("*"):
                try:
                    os.chmod(path, 0o700 if path.is_dir() else 0o600)
                except OSError:
                    pass
            try:
                os.chmod(task_root, 0o700)
            except OSError:
                pass
            shutil.rmtree(task_root)


def _scope_project_predecessor(document: Mapping[str, Any], scope: ScriptureScope) -> dict[str, Any]:
    """Project inherited RTC evidence to one child scope without mutating its governed source result."""
    result = dict(document)
    result["scope"] = scope.label()
    coverage = dict(result.get("coverage") or {})
    coverage["reviewed_references"] = [str(v) for v in coverage.get("reviewed_references", []) if _scope_intersects(scope, str(v))]
    result["coverage"] = coverage
    for key in ("findings", "ol_review_requests", "ol_resolutions"):
        result[key] = [dict(row) for row in result.get(key, []) if isinstance(row, Mapping) and _scope_intersects(scope, str(row.get("target_reference") or ""))]
    result["resolved_ol_request_ids"] = [str(row.get("request_id") or "") for row in result.get("ol_resolutions", []) if str(row.get("request_id") or "").strip()]
    receipts = []
    for row in result.get("review_receipts", []):
        if not isinstance(row, Mapping):
            continue
        refs = [str(v) for v in row.get("reviewed_references", []) if _scope_intersects(scope, str(v))]
        if refs:
            item = dict(row)
            item["reviewed_references"] = refs
            receipts.append(item)
    result["review_receipts"] = receipts
    result["work_units"] = [dict(row) for row in result.get("work_units", []) if isinstance(row, Mapping) and _scope_intersects(scope, str(row.get("scope") or ""))]
    return result


def _partition_evidence_policy(
    workflow: str,
    operation: str,
    policy: EvidencePolicy,
) -> EvidencePolicy:
    """Preserve the configured routed-SFM targets and hard limits exactly."""
    del workflow, operation
    return EvidencePolicy(
        target_estimated_tokens=policy.target_estimated_tokens,
        hard_estimated_tokens=policy.hard_estimated_tokens,
        hard_serialized_bytes=policy.hard_serialized_bytes,
        minimum_target_tokens=policy.minimum_target_tokens,
        preferred_max_estimated_tokens=policy.preferred_max_estimated_tokens,
        maximum_primary_verse_units=min(policy.maximum_primary_verse_units, 80),
        maximum_primary_discourse_units=policy.maximum_primary_discourse_units,
        preferred_primary_discourse_units=policy.preferred_primary_discourse_units,
        context_before_verses=policy.context_before_verses,
        context_after_verses=policy.context_after_verses,
        allow_cross_chapter_units=policy.allow_cross_chapter_units,
    )


def _scope_for_case_atoms(atoms: Sequence[VerseRef]) -> ScriptureScope:
    """Return the smallest contiguous authorization scope containing one OL case."""
    ordered = sorted(set(atoms))
    if not ordered:
        raise ValidationError("Selective OL case has no Scripture coordinates")
    if any(ref.book != ordered[0].book for ref in ordered):
        raise ValidationError("Selective OL case cannot cross Scripture books")
    first = ordered[0]
    last = ordered[-1]
    return ScriptureScope(
        book=first.book,
        start_chapter=first.chapter,
        start_verse=first.verse,
        end_chapter=last.chapter,
        end_verse=last.verse,
    )


def _scope_contains_scope(container: ScriptureScope, candidate: ScriptureScope) -> bool:
    """Return whether one normalized Scripture scope wholly contains another."""
    if container.book != candidate.book:
        return False
    if container.start_chapter is None:
        return True
    if candidate.start_chapter is None:
        return False

    def bounds(value: ScriptureScope) -> tuple[tuple[int, int], tuple[int, int]]:
        """Return inclusive comparable bounds without requiring chapter maxima."""
        assert value.start_chapter is not None
        start_verse = value.start_verse if value.start_verse is not None else -1
        end_chapter = value.end_chapter or value.start_chapter
        if value.start_verse is None:
            end_verse = 2**31 - 1
        else:
            end_verse = (
                value.end_verse
                if value.end_verse is not None
                else value.start_verse
            )
        return (value.start_chapter, start_verse), (end_chapter, end_verse)

    container_start, container_end = bounds(container)
    candidate_start, candidate_end = bounds(candidate)
    return container_start <= candidate_start and candidate_end <= container_end


def _review_portion_for_reference(
    review_portions: Sequence[Mapping[str, Any]],
    target_reference: str,
    *,
    workflow: str = "saw",
) -> dict[str, Any]:
    """Resolve one stage case to exactly one immutable review portion."""
    case_atoms = tuple(expand_reference_atoms(target_reference))
    matches: list[dict[str, Any]] = []
    for raw in review_portions:
        portion = dict(raw)
        portion_scope_value = str(
            portion.get("review_portion_scope")
            or portion.get("primary_scope")
            or ""
        ).strip()
        if not portion_scope_value:
            continue
        portion_scope = parse_scope(portion_scope_value)
        if case_atoms and all(portion_scope.contains(ref) for ref in case_atoms):
            matches.append(portion)
    if len(matches) != 1:
        raise ValidationError(
            "Stage case must belong wholly to exactly one approved review portion",
            code=_analysis_code(workflow, "SAW_STAGE_CASE_PORTION_MISMATCH"),
            affected_scope=target_reference,
            details={
                "matching_review_portion_ids": [
                    str(row.get("review_portion_id") or row.get("unit_id") or "")
                    for row in matches
                ]
            },
        )
    match = matches[0]
    return {
        "review_portion_id": str(
            match.get("review_portion_id") or match.get("unit_id") or ""
        ),
        "review_portion_index": int(match["review_portion_index"]),
        "review_portion_total": int(match["review_portion_total"]),
        "review_portion_scope": str(
            match.get("review_portion_scope") or match.get("primary_scope") or ""
        ),
    }


def _stage_record(result: Mapping[str, Any], stage: str) -> dict[str, Any]:
    """Normalize one task or partitioned-plan result into a composite RTC stage record."""
    if result.get("status") == "PARTITIONED":
        return {
            "stage": stage,
            "kind": "PARTITIONED_PLAN",
            "plan_path": str(result["plan_path"]),
            "task_manifests": [str(item["manifest_path"]) for item in result.get("work_units", [])],
        }
    return {
        "stage": stage,
        "kind": "TASK",
        "manifest_path": str(result["manifest_path"]),
        "task_manifests": [str(result["manifest_path"])],
    }


# Public names for other modules; the private spellings remain for existing callers.
one_book_file = _one_book_file
review_portion_for_reference = _review_portion_for_reference
stage_record = _stage_record
