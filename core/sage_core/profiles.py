"""Workflow-profile loading, language-profile routing, evidence policies, and permissions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import load_yaml, require_mapping, require_string
from .errors import ConfigurationError, ValidationError
from .evidence import EvidencePolicy
from .grammar import load_grammar_profile
from .canon import PROJECT_ROLE_VALUES
from .registry import EcosystemConfig, LanguageProfileVariantSpec, WorkflowSpec

COMMON_STATES = {
    "NOT_RUN",
    "READY",
    "IN_PROGRESS",
    "COMPLETE",
    "STALE",
    "READY_WITH_ACTIONS",
    "READY_WITH_LIMITATIONS",
    "BLOCKED",
    "ERROR",
    "ABANDONED",
}
TARGET_PROFILE_BINDINGS = {"GENERATED_TARGET", "WIP"}
REQUIRED_LANGUAGE_PROFILE_ROLES = {
    "bic": {"CONTENT_SOURCE", "GENERATED_TARGET"},
    "saw": {"WIP"},
}

EXPECTED_PROCESS_STAGES = {
    "bic": ["INSPECT", "REWRITE", "SELF_CHECK", "TRANSACTIONAL_COMMIT"],
    "saw": [
        "DETERMINISTIC_PREFLIGHT",
        "STRUCTURAL_ADJUDICATION",
        "TRANSLATION_AND_MEANING_QA",
        "SELECTIVE_OL_ADJUDICATION",
        "COVERAGE_RECONCILIATION",
        "DETERMINISTIC_FINALISATION",
    ],
}

RESOURCE_ROLES = PROJECT_ROLE_VALUES
TRUSTED_INPUT_ROLES = {
    "CONTENT_SOURCE",
    "LEXICAL_DONOR",
    "REFERENCE",
    "ORIGINAL_LANGUAGE_GREEK",
    "ORIGINAL_LANGUAGE_HEBREW",
}



def _require_string_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    """Require one workflow-profile list containing only nonempty strings."""
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigurationError(f"{label} must be a list of nonempty strings")
    result = [item.strip() for item in value]
    if not result and not allow_empty:
        raise ConfigurationError(f"{label} must not be empty")
    return result


def _validate_workflow_profile_shape(raw: dict[str, Any], workflow_id: str) -> None:
    """Enforce the declared workflow-profile grammar before binding resolution."""
    section = require_mapping(raw.get("workflow"), f"{workflow_id} profile workflow")
    required_workflow = ("id", "name", "purpose", "qualification_status", "baseline_version", "execution_model")
    missing = [key for key in required_workflow if key not in section]
    if missing:
        raise ConfigurationError(f"{workflow_id} profile workflow is missing: {', '.join(missing)}")
    for key in required_workflow:
        require_string(section.get(key), f"{workflow_id} profile workflow.{key}")
    require_mapping(raw.get("bindings"), f"{workflow_id} profile bindings")
    require_mapping(raw.get("evidence_policies"), f"{workflow_id} profile evidence_policies")
    permissions = require_mapping(raw.get("permissions"), f"{workflow_id} profile permissions")
    if "may_write_projects" not in permissions:
        raise ConfigurationError(f"{workflow_id} profile permissions.may_write_projects is required")
    _require_string_list(permissions.get("may_write_projects"), f"{workflow_id}.permissions.may_write_projects", allow_empty=True)
    process = require_mapping(raw.get("process"), f"{workflow_id} profile process")
    stages = _require_string_list(process.get("stages"), f"{workflow_id}.process.stages")
    expected_stages = EXPECTED_PROCESS_STAGES.get(workflow_id)
    if expected_stages is not None and stages != expected_stages:
        raise ConfigurationError(
            f"{workflow_id}.process.stages must exactly match the current executable workflow grammar"
        )
    _require_string_list(process.get("rules"), f"{workflow_id}.process.rules")
    _require_string_list(raw.get("qualification_gates"), f"{workflow_id}.qualification_gates")
    if section.get("execution_model") != "SAGE_GOVERNED_TASK_V1":
        raise ConfigurationError(f"{workflow_id} workflow.execution_model must be SAGE_GOVERNED_TASK_V1")


@dataclass(frozen=True)
class WorkflowProfile:
    """Resolved workflow bindings, language contracts, limits, and permissions."""

    workflow_id: str
    name: str
    qualification_status: str
    bindings: dict[str, str]
    language_profile_bindings: dict[str, str]
    evidence_policies: dict[str, EvidencePolicy]
    may_write_projects: tuple[str, ...]
    publication_root: Path | None
    raw: dict[str, Any]
    path: Path

    def evidence_policy(self, operation: str) -> EvidencePolicy:
        """Return a named policy or the workflow default."""
        key = operation.strip().lower()
        if key in self.evidence_policies:
            return self.evidence_policies[key]
        if "default" in self.evidence_policies:
            return self.evidence_policies["default"]
        return EvidencePolicy()


def _parse_bindings(
    config: EcosystemConfig,
    workflow_id: str,
    raw: dict[str, Any],
    *,
    allow_unbound_template: bool = False,
) -> dict[str, str]:
    """Parse Job-role bindings, allowing an empty profile template before a Job is derived."""
    if allow_unbound_template and not raw:
        return {}
    bindings: dict[str, str] = {}
    for role, project_id in raw.items():
        normalized_role = str(role).strip().upper()
        if normalized_role not in RESOURCE_ROLES:
            raise ConfigurationError(f"Unknown resource role in {workflow_id}: {role}")
        project = require_string(project_id, f"{workflow_id}.bindings.{role}")
        if project not in config.projects:
            raise ConfigurationError(
                f"{workflow_id} binding {normalized_role} references unknown project {project!r}"
            )
        project_spec = config.project(project)
        if normalized_role not in project_spec.scope.roles:
            raise ConfigurationError(
                f"{workflow_id} binding {normalized_role}={project} is not authorised by "
                f"projects.{project}.scope.roles"
            )
        if normalized_role in TRUSTED_INPUT_ROLES and project_spec.content_state != "LOCKED":
            raise ConfigurationError(
                f"{workflow_id} binding {normalized_role}={project} requires content_state LOCKED"
            )
        if normalized_role == "GENERATED_TARGET" and project_spec.content_state != "UNDER_REVIEW":
            raise ConfigurationError(
                f"{workflow_id} generated target {project} must have content_state UNDER_REVIEW"
            )
        if normalized_role == "WIP" and project_spec.content_state != "UNDER_REVIEW":
            raise ConfigurationError(
                f"{workflow_id} WIP {project} must have content_state UNDER_REVIEW"
            )
        bindings[normalized_role] = project
    required_roles = {
        "bic": {"CONTENT_SOURCE", "LEXICAL_DONOR", "GENERATED_TARGET"},
        "saw": {"WIP", "REFERENCE"},
    }[workflow_id]
    optional_roles = {"ORIGINAL_LANGUAGE_GREEK", "ORIGINAL_LANGUAGE_HEBREW"}
    allowed_roles = required_roles | optional_roles
    missing_roles = sorted(required_roles - set(bindings))
    extra_roles = sorted(set(bindings) - allowed_roles)
    if missing_roles:
        raise ConfigurationError(
            f"{workflow_id} profile is missing required bindings: {', '.join(missing_roles)}"
        )
    if extra_roles:
        raise ConfigurationError(
            f"{workflow_id} profile declares unsupported workflow bindings: {', '.join(extra_roles)}"
        )
    return bindings


def _role_matches_profile(profile_role: str, binding_role: str) -> bool:
    """Return whether a project role is compatible with one language-profile variant."""
    return profile_role == binding_role or (
        profile_role == "TARGET" and binding_role in TARGET_PROFILE_BINDINGS
    )


def resolve_language_profile_variant(
    config: EcosystemConfig,
    project_id: str,
) -> LanguageProfileVariantSpec | None:
    """Resolve one project's optional role-specific language profile variant."""
    project = config.project(project_id)
    if not project.profile_variant:
        return None
    namespace = config.language_profile(project.language_profile)
    return namespace.variants[project.profile_variant]


def _resolve_language_profile_bindings(
    config: EcosystemConfig,
    workflow_id: str,
    bindings: dict[str, str],
    qualification_status: str,
) -> dict[str, str]:
    """Derive workflow language-profile bindings from the bound projects."""
    result: dict[str, str] = {}
    for role, project_id in bindings.items():
        project = config.project(project_id)
        variant = resolve_language_profile_variant(config, project_id)
        if variant is None:
            if (
                role in REQUIRED_LANGUAGE_PROFILE_ROLES[workflow_id]
                and qualification_status != "RESTRICTED"
            ):
                raise ConfigurationError(
                    f"Project {project_id} requires a language profile variant when bound as {role}; "
                    f"configure projects.{project_id}.language.variant"
                )
            continue
        if not _role_matches_profile(variant.role, role):
            if qualification_status == "RESTRICTED":
                continue
                raise ConfigurationError(
                    f"Language profile {project.profile_ref} role {variant.role} is not compatible "
                    f"with workflow binding role {role}"
                )
        namespace = config.language_profile(project.language_profile)
        load_grammar_profile(
            variant.path,
            expected_profile_id=variant.variant_id,
            expected_language=namespace.profile_language,
            expected_role=variant.role,
        )
        result[role] = project.profile_ref
    return result


def _parse_evidence_policies(workflow_id: str, raw: Any) -> dict[str, EvidencePolicy]:
    """Parse operation-specific evidence limits and routing requirements."""
    values = require_mapping(raw or {}, f"{workflow_id} profile evidence_policies")
    result: dict[str, EvidencePolicy] = {}
    for operation, mapping in values.items():
        if not isinstance(mapping, dict):
            raise ConfigurationError(
                f"{workflow_id}.evidence_policies.{operation} must be a mapping"
            )
        try:
            result[str(operation).strip().lower()] = EvidencePolicy.from_mapping(mapping)
        except ValidationError as exc:
            raise ConfigurationError(
                f"Invalid evidence policy {workflow_id}.{operation}: {exc}"
            ) from exc
    if not result:
        result["default"] = EvidencePolicy()
    return result


def load_workflow_profile(config: EcosystemConfig, workflow: WorkflowSpec) -> WorkflowProfile:
    """Load one profile and derive every language contract from project bindings."""
    raw = load_yaml(workflow.profile_path)
    _validate_workflow_profile_shape(raw, workflow.workflow_id)
    section = require_mapping(raw.get("workflow"), f"{workflow.workflow_id} profile workflow")
    declared_id = require_string(
        section.get("id"),
        f"{workflow.workflow_id} profile workflow.id",
    ).lower()
    if declared_id != workflow.workflow_id:
        raise ConfigurationError(
            f"Workflow profile ID {declared_id!r} does not match registry ID {workflow.workflow_id!r}"
        )
    if "grammar_bindings" in raw:
        raise ConfigurationError(
            f"{workflow.workflow_id} profile uses obsolete grammar_bindings; language profiles "
            "must be selected by the bound project"
        )
    qualification_status = require_string(
        section.get("qualification_status", "NOT_IMPLEMENTED"),
        f"{workflow.workflow_id} profile workflow.qualification_status",
    ).upper()
    if qualification_status not in {"NOT_IMPLEMENTED", "IN_PROGRESS", "VALIDATED", "RESTRICTED"}:
        raise ConfigurationError(
            f"Unsupported qualification status for {workflow.workflow_id}: {qualification_status}"
        )
    runtime_context = config.raw.get("runtime_context", {})
    inactive_job_workflow = (
        isinstance(runtime_context, dict)
        and runtime_context.get("kind") == "JOB"
        and str(runtime_context.get("tool", "")).strip().lower() != workflow.workflow_id
    )
    bindings = _parse_bindings(
        config,
        workflow.workflow_id,
        require_mapping(raw.get("bindings", {}), f"{workflow.workflow_id} profile bindings"),
        allow_unbound_template=not config.configured or inactive_job_workflow,
    )
    language_profile_bindings = _resolve_language_profile_bindings(
        config,
        workflow.workflow_id,
        bindings,
        qualification_status,
    )
    permissions = require_mapping(
        raw.get("permissions", {}),
        f"{workflow.workflow_id} profile permissions",
    )
    writable = permissions.get("may_write_projects", []) or []
    if not isinstance(writable, list) or any(not isinstance(item, str) for item in writable):
        raise ConfigurationError(
            f"{workflow.workflow_id}.permissions.may_write_projects must be a list"
        )
    may_write_projects = tuple(item.strip() for item in writable)
    if workflow.workflow_id == "saw" and may_write_projects:
        raise ConfigurationError("SAW must not have permission to write any Scripture project")
    for project_id in may_write_projects:
        if project_id not in config.projects:
            raise ConfigurationError(
                f"{workflow.workflow_id} write permission references unknown project {project_id!r}"
            )
        project = config.projects[project_id]
        if project.producer != workflow.workflow_id:
            raise ConfigurationError(
                f"{workflow.workflow_id} may write {project_id}, but that project producer is "
                f"{project.producer!r}"
            )
        if project.protected:
            raise ConfigurationError(
                f"{workflow.workflow_id} may not write protected project {project_id}"
            )
    if workflow.workflow_id == "bic" and may_write_projects and workflow.publication_root is None:
        raise ConfigurationError("BIC publication_root is required when it may write generated projects")
    return WorkflowProfile(
        workflow_id=workflow.workflow_id,
        name=require_string(section.get("name"), f"{workflow.workflow_id} profile workflow.name"),
        qualification_status=qualification_status,
        bindings=bindings,
        language_profile_bindings=language_profile_bindings,
        evidence_policies=_parse_evidence_policies(
            workflow.workflow_id,
            raw.get("evidence_policies", {}),
        ),
        may_write_projects=may_write_projects,
        publication_root=workflow.publication_root,
        raw=raw,
        path=workflow.profile_path,
    )


def validate_workflow_isolation(config: EcosystemConfig) -> list[str]:
    """Return errors when workflow state, locks, transactions, or outputs overlap."""
    errors: list[str] = []
    workflows = list(config.workflows.values())
    labels = ("state_root", "lock_root", "transaction_root", "output_root")
    for index, first in enumerate(workflows):
        for second in workflows[index + 1 :]:
            for first_label in labels:
                first_path = getattr(first, first_label).resolve()
                for second_label in labels:
                    second_path = getattr(second, second_label).resolve()
                    if first_path == second_path:
                        errors.append(
                            f"{first.workflow_id}.{first_label} collides with "
                            f"{second.workflow_id}.{second_label}: {first_path}"
                        )
                    else:
                        try:
                            first_path.relative_to(second_path)
                            errors.append(
                                f"{first.workflow_id}.{first_label} is nested inside "
                                f"{second.workflow_id}.{second_label}: {first_path}"
                            )
                        except ValueError:
                            pass
                        try:
                            second_path.relative_to(first_path)
                            errors.append(
                                f"{second.workflow_id}.{second_label} is nested inside "
                                f"{first.workflow_id}.{first_label}: {second_path}"
                            )
                        except ValueError:
                            pass
    return sorted(set(errors))
