"""Shared SAGE Project Inventory, language-profile namespace, and workflow model for SAGE."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canon import (
    CANON_VALUES,
    TESTAMENT_VALUES,
    PROJECT_ROLE_VALUES,
    ProjectScopeSpec,
    normalize_book_list,
    normalize_roles,
    validate_scope_compatibility,
)
from .config import load_yaml, require_mapping, require_string, resolve_workspace_path
from .errors import ConfigurationError
from .external_access import EXTERNAL_ACCESS_MODES, READ_ONLY_SCRIPTURE, READ_WRITE_SCRIPTURE, READ_WRITE_TARGET
from .language_codes import canonical_language_tag, canonical_script_code
from .human_output import HumanOutputSpec, parse_human_output
from .operator_overrides import load_effective_settings
from .resource_mounts import apply_resource_mounts
from .project_inventory import merge_registered_projects
from .original_language_resources import apply_original_language_resources

SUPPORTED_SCHEMA = "0.04"
PROJECT_FORMATS = {"USFM"}
PROJECT_KINDS = {"SCRIPTURE", "GENERATED_SCRIPTURE"}
WORKFLOW_IDS = {"bic", "saw"}
PROFILE_ROLES = PROJECT_ROLE_VALUES | {"TARGET"}
CONTENT_STATES = {"LOCKED", "UNDER_REVIEW"}
VARIANT_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass(frozen=True)
class VersificationSpec:
    """Effective VRS filename declaration for one Paratext project."""

    base_file: str
    custom_file: str

    @property
    def base(self) -> str:
        """Canonical short property used by the VRS compiler."""
        return self.base_file

    @property
    def custom(self) -> str:
        """Canonical short property used by the VRS compiler."""
        return self.custom_file


@dataclass(frozen=True)
class LanguageProfileVariantSpec:
    """One role-specific variant inside a language-code profile namespace."""

    variant_id: str
    path: Path
    role: str


@dataclass(frozen=True)
class LanguageProfileSpec:
    """Represent one canonical namespace for language-code profile selection."""

    language_code: str
    script: str
    variants: dict[str, LanguageProfileVariantSpec]
    profile_language: str
    profile_alias: str | None


@dataclass(frozen=True)
class ProjectSpec:
    """One Scripture Project available to SAGE, with Job-effective runtime metadata."""

    project_id: str
    path: Path
    enabled: bool
    language_code: str
    language_profile: str
    profile_variant: str | None
    format: str
    kind: str
    content_state: str
    producer: str | None
    consumers: tuple[str, ...]
    versification: VersificationSpec
    scope: ProjectScopeSpec
    coverage_policy: str
    allow_empty: bool
    external_access_mode: str | None

    @property
    def protected(self) -> bool:
        """LOCKED projects are immutable inputs; UNDER_REVIEW resources remain workflow-governed."""
        return self.content_state == "LOCKED"

    @property
    def external_readonly(self) -> bool:
        """Return whether a project is mounted externally without write permission."""
        return self.external_access_mode == READ_ONLY_SCRIPTURE

    @property
    def external(self) -> bool:
        """Return whether this project is mapped to a Paratext/PTLite project folder."""
        return self.external_access_mode is not None

    @property
    def external_write_capable(self) -> bool:
        """Return whether the effective Job runtime permits .SFM writes for this Project."""
        return self.external_access_mode in {READ_WRITE_SCRIPTURE, READ_WRITE_TARGET}

    @property
    def external_writable_target(self) -> bool:
        """Return whether the Project inventory capability permits a BIC TARGET write binding."""
        return self.external_write_capable

    @property
    def language(self) -> str:
        """Return the canonical language code for display and provenance."""
        return self.language_code

    @property
    def profile_ref(self) -> str:
        """Return the stable language-profile reference used in reports and provenance."""
        if self.profile_variant:
            return f"{self.language_profile}/{self.profile_variant}"
        return self.language_profile


@dataclass(frozen=True)
class EvaluationEntrySpec:
    """Represent one isolated evaluation task and its governed defaults."""

    output_project: str
    contemporary_source: str


@dataclass(frozen=True)
class EvaluationSetSpec:
    """A sequential set that expands into one-project ACT tasks."""

    set_id: str
    execution_mode: str
    entries: tuple[EvaluationEntrySpec, ...]


@dataclass(frozen=True)
class WorkflowSpec:
    """One independently governed BIC or SAW workflow profile."""

    workflow_id: str
    profile_path: Path
    state_root: Path
    lock_root: Path
    transaction_root: Path
    output_root: Path
    publication_root: Path | None
    memory_root: Path | None


@dataclass(frozen=True)
class EcosystemConfig:
    """Resolved SAGE configuration and governed resource settings."""

    root: Path
    settings_path: Path
    schema_version: str
    ecosystem_id: str
    name: str
    configured: bool
    projects_root: Path
    cache_root: Path
    workspace_data_root: Path
    canonical_versification: str
    base_vrs_root: Path
    base_vrs_files: dict[str, Path]
    custom_vrs_filename: str
    language_profiles: dict[str, LanguageProfileSpec]
    projects: dict[str, ProjectSpec]
    evaluation_sets: dict[str, EvaluationSetSpec]
    workflows: dict[str, WorkflowSpec]
    raw: dict[str, Any]
    operator_overrides_path: Path | None
    operator_resolutions: tuple[dict[str, Any], ...]
    human_output: HumanOutputSpec

    def project(self, project_id: str) -> ProjectSpec:
        """Return one project by its stable registry ID."""
        try:
            return self.projects[project_id]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown project ID: {project_id}") from exc

    def workflow(self, workflow_id: str) -> WorkflowSpec:
        """Return one workflow by ID."""
        try:
            return self.workflows[workflow_id]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown workflow ID: {workflow_id}") from exc

    def language_profile(self, language_code: str) -> LanguageProfileSpec:
        """Return one canonical language-profile namespace."""
        try:
            return self.language_profiles[language_code]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown language profile: {language_code}") from exc


def _resolve_projects_root(root: Path, value: str) -> Path:
    """Resolve the configured projects root and require it to remain inside the workspace."""
    raw = Path(value)
    return raw.resolve() if raw.is_absolute() else (root / raw).resolve()


def _project_path(projects_root: Path, project_id: str, value: str) -> Path:
    """Resolve one project directory beneath the governed internal projects root."""
    raw = Path(value)
    if raw.is_absolute():
        raise ConfigurationError(
            f"projects.{project_id}.path must be relative to paths.projects_root; "
            "use external_path for a locked external Paratext/PTLite source"
        )
    candidate = (projects_root / raw).resolve()
    try:
        candidate.relative_to(projects_root.resolve())
    except ValueError as exc:
        raise ConfigurationError(f"projects.{project_id}.path escapes paths.projects_root: {value}") from exc
    return candidate


def _external_project_path(
    project_id: str,
    value: str,
    *,
    kind: str,
    content_state: str,
    roles: frozenset[str],
    producer: str | None,
    access_mode: str,
) -> Path:
    """Resolve one explicit Paratext/PTLite project mount under role-specific access rules."""
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise ConfigurationError(f"projects.{project_id}.external_path must be absolute")
    if kind not in PROJECT_KINDS or content_state not in CONTENT_STATES:
        raise ConfigurationError(f"projects.{project_id}.external_path is not valid for this project type/state")
    mode = access_mode.strip().upper()
    if mode not in EXTERNAL_ACCESS_MODES:
        raise ConfigurationError(f"projects.{project_id}.external_access_mode is invalid: {access_mode}")
    if mode == READ_WRITE_SCRIPTURE and content_state != "UNDER_REVIEW":
        raise ConfigurationError(
            f"projects.{project_id}.external_access_mode READ_WRITE_SCRIPTURE requires content_state UNDER_REVIEW"
        )
    if mode == READ_WRITE_TARGET and not (
        kind == "GENERATED_SCRIPTURE" and producer == "bic" and "GENERATED_TARGET" in roles
    ):
        raise ConfigurationError(
            f"projects.{project_id}.external_access_mode READ_WRITE_TARGET is a effective mode allowed only for a BIC GENERATED_TARGET"
        )
    return raw.resolve()


def _parse_language_profiles(data: dict[str, Any], root: Path) -> dict[str, LanguageProfileSpec]:
    """Parse concrete profile namespaces, then explicit ISO-to-profile aliases."""
    concrete: dict[str, LanguageProfileSpec] = {}
    aliases: dict[str, tuple[str, str]] = {}
    for raw_code, raw_value in data.items():
        code = canonical_language_tag(str(raw_code), f"language_profiles.{raw_code}")
        if code != str(raw_code):
            raise ConfigurationError(
                f"language_profiles key {raw_code!r} must use canonical form {code!r}"
            )
        item = require_mapping(raw_value, f"language_profiles.{code}")
        script = canonical_script_code(
            require_string(item.get("script"), f"language_profiles.{code}.script"),
            f"language_profiles.{code}.script",
        )
        alias_raw = item.get("profile_alias")
        if alias_raw not in (None, ""):
            alias = canonical_language_tag(
                require_string(alias_raw, f"language_profiles.{code}.profile_alias"),
                f"language_profiles.{code}.profile_alias",
            )
            if alias == code:
                raise ConfigurationError(f"language_profiles.{code}.profile_alias cannot refer to itself")
            if require_mapping(item.get("variants", {}), f"language_profiles.{code}.variants"):
                raise ConfigurationError(
                    f"language_profiles.{code} cannot define variants as well as profile_alias"
                )
            aliases[code] = (script, alias)
            continue
        variants_raw = require_mapping(
            item.get("variants", {}),
            f"language_profiles.{code}.variants",
        )
        variants: dict[str, LanguageProfileVariantSpec] = {}
        for raw_variant, raw_variant_value in variants_raw.items():
            variant_id = str(raw_variant).strip().lower()
            if not VARIANT_ID_RE.fullmatch(variant_id) or variant_id != str(raw_variant):
                raise ConfigurationError(
                    f"language_profiles.{code}.variants key {raw_variant!r} must be lowercase "
                    "letters, digits, and hyphens"
                )
            variant = require_mapping(
                raw_variant_value,
                f"language_profiles.{code}.variants.{variant_id}",
            )
            role = require_string(
                variant.get("role"),
                f"language_profiles.{code}.variants.{variant_id}.role",
            ).upper()
            if role not in PROFILE_ROLES:
                raise ConfigurationError(
                    f"Unsupported profile role for {code}/{variant_id}: {role}"
                )
            variants[variant_id] = LanguageProfileVariantSpec(
                variant_id=variant_id,
                path=resolve_workspace_path(
                    root,
                    require_string(
                        variant.get("file"),
                        f"language_profiles.{code}.variants.{variant_id}.file",
                    ),
                    f"language_profiles.{code}.variants.{variant_id}.file",
                ),
                role=role,
            )
        concrete[code] = LanguageProfileSpec(
            language_code=code,
            script=script,
            variants=variants,
            profile_language=code,
            profile_alias=None,
        )
    if not concrete:
        raise ConfigurationError("language_profiles must register at least one language code")

    result = dict(concrete)

    def resolve_alias(code: str, trail: tuple[str, ...] = ()) -> LanguageProfileSpec:
        """Resolve one alias chain while rejecting unknown targets and cycles."""
        if code in result:
            return result[code]
        if code in trail:
            chain = " -> ".join((*trail, code))
            raise ConfigurationError(f"Circular language profile alias: {chain}")
        try:
            script, target_code = aliases[code]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown language profile alias target: {code}") from exc
        if target_code not in concrete and target_code not in aliases:
            raise ConfigurationError(
                f"language_profiles.{code}.profile_alias references unknown namespace {target_code!r}"
            )
        target = resolve_alias(target_code, (*trail, code))
        if script != target.script:
            raise ConfigurationError(
                f"language_profiles.{code}.script {script!r} must match aliased profile "
                f"{target_code!r} script {target.script!r}"
            )
        result[code] = LanguageProfileSpec(
            language_code=code,
            script=script,
            variants=dict(target.variants),
            profile_language=target.profile_language,
            profile_alias=target_code,
        )
        return result[code]

    for alias_code in aliases:
        resolve_alias(alias_code)
    return result


def _parse_project_language(
    item: dict[str, Any],
    project_id: str,
    language_profiles: dict[str, LanguageProfileSpec],
) -> tuple[str, str, str | None]:
    """Parse and cross-check project language, script, and profile identity."""
    raw = require_mapping(item.get("language"), f"projects.{project_id}.language")
    code = canonical_language_tag(
        require_string(raw.get("code"), f"projects.{project_id}.language.code"),
        f"projects.{project_id}.language.code",
    )
    profile_code = canonical_language_tag(
        require_string(raw.get("profile"), f"projects.{project_id}.language.profile"),
        f"projects.{project_id}.language.profile",
    )
    if code != profile_code:
        raise ConfigurationError(
            f"Project {project_id} language code {code!r} must match its profile namespace "
            f"{profile_code!r}"
        )
    variant_raw = raw.get("variant")
    if variant_raw in (None, ""):
        # A SAGE Project may be added before a language-specific grammar profile exists.
        # Grammar availability is enforced later, when the Project is assigned to a Job role
        # whose operation requires that profile.
        return code, profile_code, None
    try:
        profile = language_profiles[profile_code]
    except KeyError as exc:
        raise ConfigurationError(
            f"Project {project_id} uses language-profile variant metadata but no "
            f"SAGE language profile namespace exists for {profile_code!r}"
        ) from exc
    variant = require_string(
        variant_raw,
        f"projects.{project_id}.language.variant",
    ).lower()
    if not VARIANT_ID_RE.fullmatch(variant):
        raise ConfigurationError(
            f"projects.{project_id}.language.variant must use lowercase letters, digits, and hyphens"
        )
    if variant not in profile.variants:
        raise ConfigurationError(
            f"Project {project_id} references unknown language profile variant "
            f"{profile_code}/{variant}"
        )
    return code, profile_code, variant


def _parse_projects(
    data: dict[str, Any],
    projects_root: Path,
    language_profiles: dict[str, LanguageProfileSpec],
) -> dict[str, ProjectSpec]:
    """Parse every SAGE Project with state, VRS, and path validation."""
    # Resolve project paths and roles before applying cross-project compatibility checks.
    result: dict[str, ProjectSpec] = {}
    for registry_id, raw_value in data.items():
        item = require_mapping(raw_value, f"projects.{registry_id}")
        project_id = require_string(item.get("project_id", registry_id), f"projects.{registry_id}.project_id")
        if project_id != registry_id:
            raise ConfigurationError(
                f"SAGE Project Inventory key {registry_id!r} must match project_id {project_id!r}"
            )
        path_value = require_string(item.get("path", project_id), f"projects.{project_id}.path")
        language_code, language_profile, profile_variant = _parse_project_language(
            item,
            project_id,
            language_profiles,
        )
        project_format = require_string(item.get("format", "USFM"), f"projects.{project_id}.format").upper()
        if project_format not in PROJECT_FORMATS:
            raise ConfigurationError(f"Unsupported project format for {project_id}: {project_format}")
        kind = require_string(item.get("kind", "SCRIPTURE"), f"projects.{project_id}.kind").upper()
        if kind not in PROJECT_KINDS:
            raise ConfigurationError(f"Unsupported project kind for {project_id}: {kind}")
        producer_raw = item.get("producer")
        producer = require_string(producer_raw, f"projects.{project_id}.producer") if producer_raw else None
        if producer and producer not in WORKFLOW_IDS:
            raise ConfigurationError(f"Unsupported producer for {project_id}: {producer}")
        consumers_raw = item.get("consumers", []) or []
        if not isinstance(consumers_raw, list) or any(not isinstance(value, str) for value in consumers_raw):
            raise ConfigurationError(f"projects.{project_id}.consumers must be a list of workflow IDs")
        consumers = tuple(value.strip().lower() for value in consumers_raw)
        invalid_consumers = sorted(set(consumers) - WORKFLOW_IDS)
        if invalid_consumers:
            raise ConfigurationError(f"Unsupported consumers for {project_id}: {', '.join(invalid_consumers)}")
        scope_raw = require_mapping(item.get("scope"), f"projects.{project_id}.scope")
        testament = require_string(
            scope_raw.get("testament"),
            f"projects.{project_id}.scope.testament",
        ).upper()
        if testament not in TESTAMENT_VALUES:
            raise ConfigurationError(
                f"Unsupported testament scope for {project_id}: {testament}"
            )
        canon = require_string(
            scope_raw.get("canon"),
            f"projects.{project_id}.scope.canon",
        ).upper()
        if canon not in CANON_VALUES:
            raise ConfigurationError(f"Unsupported canon for {project_id}: {canon}")
        expected_raw = scope_raw.get("expected_books")
        if isinstance(expected_raw, str):
            if expected_raw.strip().lower() != "auto":
                raise ConfigurationError(
                    f"projects.{project_id}.scope.expected_books must be auto or a list"
                )
            expected_books: str | tuple[str, ...] = "auto"
        elif isinstance(expected_raw, list):
            expected_books = normalize_book_list(
                expected_raw,
                f"projects.{project_id}.scope.expected_books",
            )
        else:
            raise ConfigurationError(
                f"projects.{project_id}.scope.expected_books must be auto or a list"
            )
        roles_raw = scope_raw.get("roles")
        if not isinstance(roles_raw, list):
            raise ConfigurationError(
                f"projects.{project_id}.scope.roles must be an explicit list"
            )
        roles = normalize_roles(roles_raw, f"projects.{project_id}.scope.roles")
        if "GENERATED_TARGET" in roles and "WIP" in roles:
            raise ConfigurationError(
                f"Project {project_id} cannot be both BIC GENERATED_TARGET and SAW WIP; "
                "configure independent workflow resources even when they map to the same external folder"
            )
        scope = ProjectScopeSpec(
            testament=testament,
            canon=canon,
            expected_books=expected_books,
            roles=roles,
        )
        validate_scope_compatibility(scope)
        coverage_policy = require_string(
            item.get("coverage_policy", "CONFIGURED_BOOKS_COMPLETE"),
            f"projects.{project_id}.coverage_policy",
        ).upper()
        if coverage_policy not in {"CONFIGURED_BOOKS_COMPLETE", "PRESENT_CHAPTERS_ONLY"}:
            raise ConfigurationError(
                f"Unsupported coverage policy for {project_id}: {coverage_policy}"
            )
        if "protected" in item:
            raise ConfigurationError(
                f"projects.{project_id}.protected is obsolete; use content_state: LOCKED|UNDER_REVIEW"
            )
        content_state = require_string(
            item.get("content_state"),
            f"projects.{project_id}.content_state",
        ).upper()
        if content_state not in CONTENT_STATES:
            raise ConfigurationError(
                f"Unsupported content_state for {project_id}: {content_state}"
            )
        vrs = require_mapping(item.get("versification", {}), f"projects.{project_id}.versification")
        if "base" in vrs or "custom" in vrs:
            raise ConfigurationError(
                f"projects.{project_id}.versification uses obsolete base/custom keys; "
                "use base_file/custom_file with complete .vrs filenames"
            )
        base_file = require_string(
            vrs.get("base_file"),
            f"projects.{project_id}.versification.base_file",
        )
        base_path = Path(base_file)
        if base_path.is_absolute() or len(base_path.parts) != 1 or base_path.suffix.lower() != ".vrs":
            raise ConfigurationError(
                f"projects.{project_id}.versification.base_file must be one .vrs filename"
            )
        custom_file = require_string(
            str(vrs.get("custom_file", "auto")),
            f"projects.{project_id}.versification.custom_file",
        )
        if custom_file.lower() not in {"auto", "none"}:
            custom_path = Path(custom_file)
            if custom_path.is_absolute() or len(custom_path.parts) != 1 or custom_path.suffix.lower() != ".vrs":
                raise ConfigurationError(
                    f"projects.{project_id}.versification.custom_file must be auto, none, or one .vrs filename"
                )
        external_value = item.get("external_path")
        external_access_mode: str | None = None
        if external_value not in (None, ""):
            external_access_mode = require_string(
                item.get("external_access_mode", READ_ONLY_SCRIPTURE),
                f"projects.{project_id}.external_access_mode",
            ).upper()
            resolved_path = _external_project_path(
                project_id,
                require_string(external_value, f"projects.{project_id}.external_path"),
                kind=kind,
                content_state=content_state,
                roles=scope.roles,
                producer=producer,
                access_mode=external_access_mode,
            )
        else:
            resolved_path = _project_path(projects_root, project_id, path_value)
        result[project_id] = ProjectSpec(
            project_id=project_id,
            path=resolved_path,
            enabled=bool(item.get("enabled", True)),
            language_code=language_code,
            language_profile=language_profile,
            profile_variant=profile_variant,
            format=project_format,
            kind=kind,
            content_state=content_state,
            producer=producer,
            consumers=consumers,
            versification=VersificationSpec(base_file=base_file, custom_file=custom_file),
            scope=scope,
            coverage_policy=coverage_policy,
            allow_empty=bool(item.get("allow_empty", kind == "GENERATED_SCRIPTURE")),
            external_access_mode=external_access_mode,
        )
    return result


def _parse_evaluation_sets(
    data: dict[str, Any],
    projects: dict[str, ProjectSpec],
) -> dict[str, EvaluationSetSpec]:
    """Parse sequential evaluation sets without combining projects in one task."""
    result: dict[str, EvaluationSetSpec] = {}
    contemporary_roles = {"REFERENCE"}
    for raw_id, raw_value in data.items():
        set_id = str(raw_id).strip().lower()
        if not VARIANT_ID_RE.fullmatch(set_id) or set_id != str(raw_id):
            raise ConfigurationError(
                f"evaluation_sets key {raw_id!r} must use lowercase letters, digits, and hyphens"
            )
        item = require_mapping(raw_value, f"evaluation_sets.{set_id}")
        execution_mode = require_string(
            item.get("execution_mode", "SEQUENTIAL"),
            f"evaluation_sets.{set_id}.execution_mode",
        ).upper()
        if execution_mode != "SEQUENTIAL":
            raise ConfigurationError(
                f"evaluation_sets.{set_id}.execution_mode must be SEQUENTIAL"
            )
        entries_raw = item.get("entries")
        if not isinstance(entries_raw, list) or not entries_raw:
            raise ConfigurationError(f"evaluation_sets.{set_id}.entries must be a non-empty list")
        entries: list[EvaluationEntrySpec] = []
        seen_outputs: set[str] = set()
        for index, raw_entry in enumerate(entries_raw):
            entry = require_mapping(raw_entry, f"evaluation_sets.{set_id}.entries[{index}]")
            output_project = require_string(
                entry.get("output_project"),
                f"evaluation_sets.{set_id}.entries[{index}].output_project",
            )
            contemporary_source = require_string(
                entry.get("contemporary_source"),
                f"evaluation_sets.{set_id}.entries[{index}].contemporary_source",
            )
            if output_project not in projects or contemporary_source not in projects:
                raise ConfigurationError(
                    f"evaluation_sets.{set_id}.entries[{index}] references an unknown project"
                )
            target = projects[output_project]
            source = projects[contemporary_source]
            if "WIP" not in target.scope.roles:
                raise ConfigurationError(
                    f"Evaluation output {output_project} lacks WIP in scope.roles"
                )
            if not contemporary_roles.intersection(source.scope.roles):
                raise ConfigurationError(
                    f"Evaluation source {contemporary_source} lacks an authorised contemporary role"
                )
            if source.content_state != "LOCKED":
                raise ConfigurationError(
                    f"Evaluation source {contemporary_source} must have content_state LOCKED"
                )
            if output_project in seen_outputs:
                raise ConfigurationError(
                    f"evaluation_sets.{set_id} repeats output project {output_project}"
                )
            seen_outputs.add(output_project)
            entries.append(
                EvaluationEntrySpec(
                    output_project=output_project,
                    contemporary_source=contemporary_source,
                )
            )
        result[set_id] = EvaluationSetSpec(
            set_id=set_id,
            execution_mode=execution_mode,
            entries=tuple(entries),
        )
    return result


def _parse_workflows(data: dict[str, Any], root: Path) -> dict[str, WorkflowSpec]:
    """Parse isolated workflow roots, limits, permissions, and evaluation bindings."""
    result: dict[str, WorkflowSpec] = {}
    for workflow_id, raw_value in data.items():
        normalized = workflow_id.strip().lower()
        if normalized not in WORKFLOW_IDS:
            raise ConfigurationError(f"Unsupported workflow ID: {workflow_id}")
        item = require_mapping(raw_value, f"workflows.{workflow_id}")
        result[normalized] = WorkflowSpec(
            workflow_id=normalized,
            profile_path=resolve_workspace_path(
                root,
                require_string(item.get("profile"), f"workflows.{workflow_id}.profile"),
                f"workflows.{workflow_id}.profile",
            ),
            state_root=resolve_workspace_path(
                root,
                require_string(item.get("state_root"), f"workflows.{workflow_id}.state_root"),
                f"workflows.{workflow_id}.state_root",
            ),
            lock_root=resolve_workspace_path(
                root,
                require_string(item.get("lock_root"), f"workflows.{workflow_id}.lock_root"),
                f"workflows.{workflow_id}.lock_root",
            ),
            transaction_root=resolve_workspace_path(
                root,
                require_string(item.get("transaction_root"), f"workflows.{workflow_id}.transaction_root"),
                f"workflows.{workflow_id}.transaction_root",
            ),
            output_root=resolve_workspace_path(
                root,
                require_string(item.get("output_root"), f"workflows.{workflow_id}.output_root"),
                f"workflows.{workflow_id}.output_root",
            ),
            publication_root=(
                resolve_workspace_path(
                    root,
                    require_string(
                        item.get("publication_root"),
                        f"workflows.{workflow_id}.publication_root",
                    ),
                    f"workflows.{workflow_id}.publication_root",
                )
                if item.get("publication_root")
                else None
            ),
            memory_root=(
                resolve_workspace_path(
                    root,
                    require_string(
                        item.get("memory_root"),
                        f"workflows.{workflow_id}.memory_root",
                    ),
                    f"workflows.{workflow_id}.memory_root",
                )
                if item.get("memory_root")
                else None
            ),
        )
    missing = WORKFLOW_IDS - set(result)
    if missing:
        raise ConfigurationError(f"Missing workflow configuration: {', '.join(sorted(missing))}")
    return result


def load_ecosystem(settings_path: Path) -> EcosystemConfig:
    """Load and fully resolve ecosystem, language profile, project, and workflow paths."""
    settings_path = settings_path.resolve()
    raw, operator_overrides_path, operator_resolutions = load_effective_settings(settings_path)
    paths = require_mapping(raw.get("paths"), "paths")
    root_value = paths.get("sage_root")
    if root_value in (None, ""):
        root = settings_path.parent
    else:
        raw_root = Path(require_string(root_value, "paths.sage_root")).expanduser()
        root = (
            raw_root.resolve()
            if raw_root.is_absolute()
            else (settings_path.parent / raw_root).resolve()
        )
        if not root.is_dir():
            raise ConfigurationError(f"paths.sage_root is not an existing directory: {root}")
    # Operator-owned SAGE Project Inventory entries are merged before machine-local path mounts.
    raw = merge_registered_projects(raw, root)
    raw = apply_original_language_resources(raw, root)
    raw = apply_resource_mounts(raw, root)
    ecosystem = require_mapping(raw.get("ecosystem"), "ecosystem")
    schema_version = require_string(ecosystem.get("schema_version"), "ecosystem.schema_version")
    if schema_version != SUPPORTED_SCHEMA:
        raise ConfigurationError(
            f"Unsupported ecosystem schema {schema_version!r}; expected {SUPPORTED_SCHEMA!r}"
        )
    ecosystem_id = require_string(ecosystem.get("id"), "ecosystem.id")
    if ecosystem_id != "sage":
        raise ConfigurationError("ecosystem.id must be 'sage'")
    internal_root_value = paths.get("internal_scripture_root", paths.get("projects_root"))
    projects_root = _resolve_projects_root(
        root,
        require_string(internal_root_value, "paths.internal_scripture_root"),
    )
    cache_root = resolve_workspace_path(
        root,
        require_string(paths.get("cache_root", "cache"), "paths.cache_root"),
        "paths.cache_root",
    )
    workspace_data_root = resolve_workspace_path(
        root,
        require_string(paths.get("workspace_data_root", "workspace-data"), "paths.workspace_data_root"),
        "paths.workspace_data_root",
    )
    versification = require_mapping(raw.get("versification"), "versification")
    base_root_value = require_string(
        paths.get("base_vrs_root", paths.get("internal_scripture_root", paths.get("projects_root"))),
        "paths.base_vrs_root",
    )
    base_root_raw = Path(base_root_value).expanduser()
    base_vrs_root = base_root_raw.resolve() if base_root_raw.is_absolute() else (root / base_root_raw).resolve()
    base_values = versification.get("base_files")
    if not isinstance(base_values, list) or not base_values:
        raise ConfigurationError("versification.base_files must be a non-empty list of .vrs filenames")
    base_vrs_files: dict[str, Path] = {}
    for index, value in enumerate(base_values):
        filename = require_string(value, f"versification.base_files[{index}]")
        raw_path = Path(filename)
        if raw_path.is_absolute() or len(raw_path.parts) != 1 or raw_path.suffix.lower() != ".vrs":
            raise ConfigurationError(
                f"versification.base_files[{index}] must be one .vrs filename, not {filename!r}"
            )
        key = filename.casefold()
        if key in base_vrs_files:
            raise ConfigurationError(f"Duplicate base VRS filename: {filename}")
        base_vrs_files[key] = (base_vrs_root / raw_path).resolve()
    canonical_file = require_string(
        versification.get("canonical_file"),
        "versification.canonical_file",
    )
    if Path(canonical_file).suffix.lower() != ".vrs" or len(Path(canonical_file).parts) != 1:
        raise ConfigurationError("versification.canonical_file must be one .vrs filename")
    custom_default = require_string(
        versification.get("custom_file_default"),
        "versification.custom_file_default",
    )
    if Path(custom_default).suffix.lower() != ".vrs" or len(Path(custom_default).parts) != 1:
        raise ConfigurationError("versification.custom_file_default must be one .vrs filename")
    language_profiles = _parse_language_profiles(
        require_mapping(raw.get("language_profiles"), "language_profiles"),
        root,
    )
    projects = _parse_projects(
        require_mapping(raw.get("projects", {}), "projects"),
        projects_root,
        language_profiles,
    )
    evaluation_sets = _parse_evaluation_sets(
        require_mapping(raw.get("evaluation_sets", {}), "evaluation_sets"),
        projects,
    )
    workflows = _parse_workflows(require_mapping(raw.get("workflows"), "workflows"), root)
    return EcosystemConfig(
        root=root,
        settings_path=settings_path,
        schema_version=schema_version,
        ecosystem_id=ecosystem_id,
        name=require_string(ecosystem.get("name"), "ecosystem.name"),
        configured=bool(ecosystem.get("configured", False)),
        projects_root=projects_root,
        cache_root=cache_root,
        workspace_data_root=workspace_data_root,
        canonical_versification=require_string(
            versification.get("canonical_file"),
            "versification.canonical_file",
        ),
        base_vrs_root=base_vrs_root,
        base_vrs_files=base_vrs_files,
        custom_vrs_filename=require_string(
            versification.get("custom_file_default"),
            "versification.custom_file_default",
        ),
        language_profiles=language_profiles,
        projects=projects,
        evaluation_sets=evaluation_sets,
        workflows=workflows,
        raw=raw,
        operator_overrides_path=operator_overrides_path,
        operator_resolutions=operator_resolutions,
        human_output=parse_human_output(raw.get("human_output", {})),
    )
