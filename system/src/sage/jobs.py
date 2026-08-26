"""Persistent BIC/SAW Jobs, active selections, Runs, and derived runtime configs."""

from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from .atomic import atomic_write_json, atomic_write_text
from .config import load_json, load_yaml, require_mapping, require_string
from .errors import ConfigurationError, ValidationError
from .registry import EcosystemConfig, load_ecosystem
from .resource_mounts import apply_resource_mounts
from .project_inventory import merge_registered_projects, registered_project_records
from .original_language_resources import apply_original_language_resources, active_ol_provenance
from .operator_overrides import load_effective_settings
from .external_access import READ_ONLY_SCRIPTURE, READ_WRITE_SCRIPTURE, READ_WRITE_TARGET
from .language_codes import canonical_language_tag
from .runtime_paths import validate_context_id
from .state import append_event
from .progress import DEFAULT_JOB_PROGRESS_POLICY, validate_job_progress_policy
from .storage import resolve_declared_path, storage_layout

TOOL_IDS = ("bic", "saw")
JOB_SCHEMA_VERSION = "1.0"
RUN_SCHEMA_VERSION = "1.0"
RUN_CLOSED_STATUSES = frozenset({"COMPLETE", "ARCHIVED", "ABANDONED"})
_JOB_ID_RE = re.compile(r"^(BIC|SAW)_[A-Za-z0-9][A-Za-z0-9._-]{1,190}$")


@dataclass(frozen=True)
class Job:
    """One persistent BIC or SAW Job with fixed SAGE Project bindings."""

    job_id: str
    tool: str
    display_name: str
    status: str
    bindings: dict[str, str]
    profiles: dict[str, str]
    defaults: dict[str, Any]
    progress_quantifier: dict[str, Any]
    secondary_report_language: str | None
    configuration_revision: int
    root: Path
    manifest_path: Path
    controller_root: Path

    @property
    def runtime_settings_path(self) -> Path:
        """Return the controller-owned Job runtime settings outside operator-facing Job data."""
        return self.controller_root / "runtime.yml"

    @property
    def runtime_profile_path(self) -> Path:
        """Return the controller-owned Job workflow profile."""
        return self.controller_root / "profile.yml"

    @property
    def controller_state_root(self) -> Path:
        """Return the hidden controller state root for this Job."""
        return self.controller_root / "state"

    @property
    def output_project(self) -> str:
        """Manage `output project` for Job-scoped state and storage."""
        key = "generated_target" if self.tool == "bic" else "wip"
        return self.bindings[key]

    @property
    def contemporary_source(self) -> str:
        """Return the BIC SOURCE or SAW REFERENCE binding for Job-scoped state."""
        key = "content_source" if self.tool == "bic" else "reference"
        return self.bindings[key]

    @property
    def lexical_donor(self) -> str | None:
        """Return the BIC lexical-donor resource when this is a BIC project."""
        return self.bindings.get("lexical_donor") if self.tool == "bic" else None


@dataclass(frozen=True)
class Run:
    """One bounded operator execution owned by exactly one Job."""

    run_id: str
    tool: str
    job_id: str
    operation: str
    scope: str
    focus: str | None
    check_type: str | None
    status: str
    current_stage: str
    result: str | None
    result_reason: str | None
    task_manifests: tuple[str, ...]
    plan_path: str | None
    approved_work_plan_path: str | None
    created_utc: str
    updated_utc: str
    root: Path

    @property
    def manifest_path(self) -> Path:
        """Return the governed Run manifest."""
        return self.root / "run.json"

    @property
    def status_path(self) -> Path:
        """Manage `status path` for Job-scoped state and storage."""
        return self.root / "status.json"


def _utc_now() -> str:
    """Manage ` utc now` for Job-scoped state and storage."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_yaml(value: dict[str, Any]) -> str:
    """Manage ` safe yaml` for Job-scoped state and storage."""
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)


def _validate_bound_code(value: str, label: str) -> str:
    """Validate one SAGE Project code before embedding it in a Job identity."""
    code = str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", code):
        raise ValidationError(f"{label} project code is not cross-platform safe: {value}")
    return code


def default_job_name(
    tool: str,
    output_project: str,
    source_project: str,
    lexical_donor: str | None = None,
) -> str:
    """Return the canonical binding-derived Job name."""
    normalized = tool.strip().lower()
    if normalized not in TOOL_IDS:
        raise ValidationError(f"Unsupported tool: {tool}")
    output = _validate_bound_code(output_project, "Output")
    source = _validate_bound_code(source_project, "Source")
    if normalized == "bic":
        if not lexical_donor:
            raise ValidationError("BIC Job identity requires one bound DONOR")
        donor = _validate_bound_code(lexical_donor, "Donor")
        return f"BIC_{source}-{donor}-{output}"
    return f"SAW_{output}-{source}"



def _resource_slug(project_id: str) -> str:
    """Display slug helper; never use this to construct Job identity."""
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", project_id).strip("-")
    return normalized or project_id

def _relative_from(path: Path, target: Path) -> str:
    """Manage ` relative from` for Job-scoped state and storage."""
    return Path(os.path.relpath(target.resolve(), path.resolve())).as_posix()


class JobStore:
    """Manage Job manifests, active pointers, Runs, and derived configs."""

    def __init__(self, sage_root: Path, settings_path: Path | None = None) -> None:
        """Manage `  init  ` for Job-scoped state and storage."""
        self.sage_root = sage_root.expanduser().resolve()
        self.settings_path = (settings_path or self.sage_root / "ecosystem.yml").expanduser().resolve()
        self.storage = storage_layout(self.sage_root, create=True)
        self.jobs_root = self.storage.jobs_root
        self.state_root = self.storage.state_root
        self.controller_jobs_root = self.storage.system_root / "jobs"
        self.active_jobs_path = self.state_root / "active-jobs.json"
        self.last_run_path = self.state_root / "last-run.json"
        self.setup_state_path = self.state_root / "setup-state.json"
        self.operator_cues_path = self.state_root / "operator-cues.jsonl"

    def tool_root(self, tool: str) -> Path:
        """Manage `tool root` for Job-scoped state and storage."""
        normalized = tool.strip().lower()
        if normalized not in TOOL_IDS:
            raise ValidationError(f"Unsupported tool: {tool}")
        return self.jobs_root / normalized

    def job_root(self, tool: str, job_id: str) -> Path:
        """Return the canonical directory for one Job."""
        job = validate_context_id(job_id, "job_id")
        assert job is not None
        return self.tool_root(tool) / job

    def discover(self, tool: str | None = None, *, include_archived: bool = False) -> list[Job]:
        """Load current Jobs in stable canonical-name order."""
        tools: Iterable[str] = (tool.strip().lower(),) if tool else TOOL_IDS
        result: list[Job] = []
        for tool_id in tools:
            for manifest in sorted(self.tool_root(tool_id).glob("*/job.yml")):
                job = self.load_job(manifest.parent.name, tool=tool_id)
                if include_archived or job.status != "ARCHIVED":
                    result.append(job)
        return sorted(result, key=lambda item: (item.tool, item.job_id.casefold()))

    def load_job(self, job_id: str, *, tool: str | None = None) -> Job:
        """Load and validate one current Job."""
        job_id = validate_context_id(job_id, "job_id")
        assert job_id is not None
        tools = (tool.strip().lower(),) if tool else TOOL_IDS
        existing = [self.job_root(tool_id, job_id) / "job.yml" for tool_id in tools]
        existing = [path for path in existing if path.is_file()]
        if len(existing) != 1:
            if not existing:
                raise ConfigurationError(f"Job not found: {job_id}")
            raise ConfigurationError(f"Job ID is ambiguous across workflow containers: {job_id}")
        path = existing[0]
        raw = load_yaml(path)
        required_fields = {
            "schema_version", "job_id", "tool", "display_name", "status",
            "bindings", "profiles", "defaults", "configuration_revision",
        }
        missing_fields = sorted(required_fields - set(raw))
        if missing_fields:
            raise ConfigurationError(
                f"Job {path.parent.name} is missing required fields: {', '.join(missing_fields)}"
            )
        schema = require_string(raw.get("schema_version"), "job schema_version")
        if schema != JOB_SCHEMA_VERSION:
            raise ConfigurationError(f"Unsupported Job schema {schema!r}; expected {JOB_SCHEMA_VERSION!r}")
        manifest_job_id = require_string(raw.get("job_id"), "job job_id")
        job_tool = require_string(raw.get("tool"), "job tool").lower()
        if manifest_job_id != path.parent.name or not _JOB_ID_RE.fullmatch(manifest_job_id):
            raise ConfigurationError(f"Invalid or mismatched Job ID: {manifest_job_id}")
        if job_tool not in TOOL_IDS or path.parent.parent.name != job_tool:
            raise ConfigurationError(f"Invalid or mismatched Job workflow: {job_tool}")
        bindings = {
            str(key): require_string(value, f"job bindings.{key}")
            for key, value in require_mapping(raw.get("bindings"), "job bindings").items()
        }
        required = (
            {"content_source", "lexical_donor", "generated_target"}
            if job_tool == "bic" else {"wip", "reference"}
        )
        optional = {"original_language_greek", "original_language_hebrew"}
        allowed = required | optional
        missing = sorted(required - set(bindings))
        extra = sorted(set(bindings) - allowed)
        if missing:
            raise ConfigurationError(f"Job {manifest_job_id} is missing bindings: {', '.join(missing)}")
        if extra:
            raise ConfigurationError(f"Job {manifest_job_id} has unsupported bindings: {', '.join(extra)}")
        if job_tool == "bic":
            trio = [bindings["content_source"], bindings["lexical_donor"], bindings["generated_target"]]
            if len(set(trio)) != 3:
                raise ConfigurationError(
                    "BIC Job requires exactly_one SOURCE, DONOR, and TARGET; the three bindings must be distinct"
                )
        expected_job_id = default_job_name(
            job_tool,
            bindings["generated_target"] if job_tool == "bic" else bindings["wip"],
            bindings["content_source"] if job_tool == "bic" else bindings["reference"],
            bindings.get("lexical_donor"),
        )
        if manifest_job_id != expected_job_id:
            raise ConfigurationError(
                f"Job {manifest_job_id} canonical identity does not match bindings; expected {expected_job_id}"
            )
        profiles = {
            str(key): require_string(value, f"job profiles.{key}")
            for key, value in require_mapping(raw.get("profiles"), "job profiles").items()
        }
        defaults = dict(require_mapping(raw.get("defaults"), "job defaults"))
        try:
            progress_quantifier = validate_job_progress_policy(
                require_mapping(raw.get("progress_quantifier", {}), "job progress_quantifier")
            ).to_dict()
        except ValueError as exc:
            raise ConfigurationError(f"Job {manifest_job_id} has invalid progress quantifier: {exc}") from exc
        reporting = require_mapping(raw.get("reporting", {}), "job reporting")
        unsupported_reporting = sorted(set(reporting) - {"secondary_language"})
        if unsupported_reporting:
            raise ConfigurationError(
                f"Job {manifest_job_id} has unsupported reporting fields: "
                + ", ".join(unsupported_reporting)
            )
        secondary_value = reporting.get("secondary_language")
        secondary_report_language = (
            None
            if secondary_value in (None, "")
            else canonical_language_tag(
                str(secondary_value),
                "job reporting secondary_language",
            )
        )
        status = require_string(raw.get("status"), "job status").upper()
        if status not in {"ACTIVE", "INACTIVE", "ARCHIVED"}:
            raise ConfigurationError(f"Unsupported Job status: {status}")
        revision = raw.get("configuration_revision", 1)
        if not isinstance(revision, int) or revision < 1:
            raise ConfigurationError("Job configuration_revision must be a positive integer")
        try:
            canonical_profiles = self._validate_project_bindings(
                tool=job_tool, job_id=manifest_job_id, bindings=bindings, profiles=profiles,
            )
        except ValidationError as exc:
            raise ConfigurationError(f"Job {manifest_job_id} has invalid semantic bindings: {exc}") from exc
        if canonical_profiles != profiles:
            raise ConfigurationError(f"Job {manifest_job_id} profile bindings do not match its bound resources")
        return Job(
            job_id=manifest_job_id, tool=job_tool,
            display_name=require_string(raw.get("display_name", manifest_job_id), "job display_name"),
            status=status, bindings=bindings, profiles=profiles, defaults=defaults,
            progress_quantifier=progress_quantifier,
            secondary_report_language=secondary_report_language,
            configuration_revision=revision, root=path.parent, manifest_path=path,
            controller_root=self.controller_jobs_root / job_tool / manifest_job_id,
        )


    def _validate_project_bindings(
        self,
        *,
        tool: str,
        job_id: str,
        bindings: dict[str, str],
        profiles: dict[str, str] | None,
    ) -> dict[str, str]:
        """Resolve Job bindings and derive role-specific grammar profiles at Job scope."""
        # Project inventory stays role-neutral here; all semantic authority below is Job-scoped.
        config = load_ecosystem(self.settings_path)

        def bound(key: str, role: str):
            """Resolve one SAGE Project; ``role`` exists only in this Job binding."""
            resource_id = bindings[key]
            try:
                return config.project(resource_id)
            except ConfigurationError as exc:
                raise ValidationError(
                    f"Job {job_id} binding {key} references a Project that is not in SAGE: {resource_id}",
                    code="PROJECT_BINDING_MISMATCH",
                ) from exc

        def profile_candidates(project: Any, role: str) -> tuple[str, ...]:
            """Return role-compatible grammar profile references without mutating Project metadata."""
            namespace = config.language_profiles.get(project.language_code)
            if namespace is None:
                return ()
            wanted = {
                "CONTENT_SOURCE": {"CONTENT_SOURCE"},
                "GENERATED_TARGET": {"GENERATED_TARGET", "TARGET"},
                "WIP": {"WIP", "TARGET"},
            }.get(role, {role})
            values = tuple(
                f"{project.language_code}/{variant.variant_id}"
                for variant in namespace.variants.values()
                if variant.role in wanted
            )
            if project.profile_variant:
                preferred = f"{project.language_code}/{project.profile_variant}"
                if preferred in values:
                    return (preferred,) + tuple(value for value in values if value != preferred)
            return values

        def resolve_profile(project: Any, role: str, key: str) -> str:
            """Resolve one required Job grammar binding or return an actionable configuration error."""
            candidates = profile_candidates(project, role)
            requested = supplied.get(key)
            if requested is not None:
                if requested not in candidates:
                    raise ValidationError(
                        f"Job {job_id} profile {key}={requested} is not compatible with "
                        f"{project.project_id} as {role}",
                        code="LANGUAGE_PROFILE_ROLE_NOT_CONFIGURED",
                        details={"project": project.project_id, "role": role, "candidates": list(candidates)},
                    )
                return requested
            if len(candidates) == 1:
                return candidates[0]
            if not candidates:
                raise ValidationError(
                    f"Grammar Profile required for {project.language_code}. No compatible SAGE grammar "
                    f"profile is configured for {project.project_id} as {role}.",
                    code="LANGUAGE_PROFILE_NOT_CONFIGURED",
                    next_action=(
                        f"Open Maintain grammar profiles for {project.language_code}/{role}; choose a compatible "
                        "profile from the existing list or add a validated grammar-profile YAML file, then retry. "
                        "The Project remains available in SAGE."
                    ),
                    details={
                        "project": project.project_id,
                        "language": project.language_code,
                        "role": role,
                    },
                )
            raise ValidationError(
                f"More than one grammar profile is available for {project.project_id} as {role}",
                code="LANGUAGE_PROFILE_SELECTION_REQUIRED",
                next_action="Select the grammar profile to use for this Job binding.",
                details={"project": project.project_id, "role": role, "candidates": list(candidates)},
            )

        def optional_bound(key: str, role: str):
            """Resolve one optional original-language binding when configured."""
            if key not in bindings:
                return None
            return bound(key, role)

        supplied = dict(profiles or {})
        if tool == "bic":
            source = bound("content_source", "CONTENT_SOURCE")
            donor = bound("lexical_donor", "LEXICAL_DONOR")
            target = bound("generated_target", "GENERATED_TARGET")
            greek = optional_bound("original_language_greek", "ORIGINAL_LANGUAGE_GREEK")
            hebrew = optional_bound("original_language_hebrew", "ORIGINAL_LANGUAGE_HEBREW")
            for resource in (greek, hebrew):
                if resource is not None and resource.content_state != "LOCKED":
                    raise ValidationError(
                        f"BIC original-language resource {resource.project_id} must be LOCKED",
                        code="PROJECT_BINDING_MISMATCH",
                    )
            if donor.language_code != target.language_code:
                raise ValidationError(
                    f"BIC DONOR language {donor.language_code} must match TARGET language {target.language_code}",
                    code="PROJECT_BINDING_MISMATCH",
                )
            expected_profiles = {
                "source_grammar": resolve_profile(source, "CONTENT_SOURCE", "source_grammar"),
                "target_grammar": resolve_profile(target, "GENERATED_TARGET", "target_grammar"),
            }
        else:
            wip = bound("wip", "WIP")
            reference = bound("reference", "REFERENCE")
            greek = optional_bound("original_language_greek", "ORIGINAL_LANGUAGE_GREEK")
            hebrew = optional_bound("original_language_hebrew", "ORIGINAL_LANGUAGE_HEBREW")
            for resource in (reference, greek, hebrew):
                if resource is not None and resource.content_state != "LOCKED":
                    raise ValidationError(
                        f"SAW authority resource {resource.project_id} must be LOCKED",
                        code="PROJECT_BINDING_MISMATCH",
                    )
            expected_profiles = {
                "target_grammar": resolve_profile(wip, "WIP", "target_grammar")
            }
        unknown_profiles = sorted(set(supplied) - set(expected_profiles))
        if unknown_profiles:
            raise ValidationError(
                f"Job {job_id} has unsupported profile bindings: {', '.join(unknown_profiles)}",
                code="PROJECT_BINDING_MISMATCH",
            )
        for key, expected in expected_profiles.items():
            supplied[key] = expected
        return supplied

    def create_job(
        self,
        *,
        tool: str,
        job_id: str,
        display_name: str,
        bindings: dict[str, str],
        profiles: dict[str, str] | None = None,
        defaults: dict[str, Any] | None = None,
        secondary_report_language: str | None = None,
        overwrite: bool = False,
    ) -> Job:
        """Create one canonical Job from fixed SAGE Project bindings."""
        # Keep validation, runtime isolation, and receipt creation in this one transaction.
        normalized_tool = tool.strip().lower()
        if normalized_tool not in TOOL_IDS:
            raise ValidationError(f"Unsupported tool: {tool}")
        required_bindings = (
            {"content_source", "lexical_donor", "generated_target"}
            if normalized_tool == "bic"
            else {"wip", "reference"}
        )
        optional_bindings = {"original_language_greek", "original_language_hebrew"}
        allowed_bindings = required_bindings | optional_bindings
        binding_keys = set(bindings)
        missing_bindings = sorted(required_bindings - binding_keys)
        extra_bindings = sorted(binding_keys - allowed_bindings)
        if missing_bindings:
            raise ValidationError(
                f"Job is missing required bindings: {', '.join(missing_bindings)}",
                code="PROJECT_BINDING_MISMATCH",
            )
        if extra_bindings:
            raise ValidationError(
                f"Job has unsupported bindings: {', '.join(extra_bindings)}",
                code="PROJECT_BINDING_MISMATCH",
            )
        requested_id = job_id.strip()
        expected_id = default_job_name(
            normalized_tool,
            bindings["generated_target"] if normalized_tool == "bic" else bindings["wip"],
            bindings["content_source"] if normalized_tool == "bic" else bindings["reference"],
            bindings.get("lexical_donor"),
        )
        normalized_id = requested_id or expected_id
        if normalized_id != expected_id:
            raise ValidationError(
                f"Job name must be canonical binding-derived name {expected_id}: {job_id}",
                code="JOB_ID_MISMATCH",
            )
        if not _JOB_ID_RE.fullmatch(normalized_id):
            raise ValidationError(f"Invalid canonical Job name: {normalized_id}", code="JOB_ID_INVALID")
        if normalized_tool == "bic":
            trio = [bindings["content_source"], bindings["lexical_donor"], bindings["generated_target"]]
            if len(set(trio)) != 3:
                raise ValidationError(
                    "BIC Job requires one bound SOURCE resource, one bound DONOR resource, and one bound TARGET resource; the three bindings must be distinct",
                    code="PROJECT_BINDING_MISMATCH",
                )
        canonical_profiles = self._validate_project_bindings(
            tool=normalized_tool,
            job_id=normalized_id,
            bindings=bindings,
            profiles=profiles,
        )
        canonical_secondary = (
            canonical_language_tag(
                secondary_report_language,
                "job reporting secondary_language",
            )
            if secondary_report_language
            else None
        )
        operator_language = load_ecosystem(self.settings_path).human_output.operator_language
        if canonical_secondary == operator_language:
            raise ValidationError(
                "Job secondary reporting language must differ from the global Operator language",
                code="JOB_REPORTING_LANGUAGE_CONFLICT",
            )
        root = self.job_root(normalized_tool, normalized_id)
        if root.exists() and not overwrite:
            existing = self.load_job(normalized_id, tool=normalized_tool)
            if existing.bindings != bindings:
                raise ValidationError(
                    f"Job {normalized_id} already exists with different resource bindings",
                    code="PROJECT_BINDING_MISMATCH",
                    details={"existing": existing.bindings, "requested": bindings},
                )
            return existing
        root.mkdir(parents=True, exist_ok=True)
        for relative in ("runs", "diagnostics", "exports"):
            (root / relative).mkdir(parents=True, exist_ok=True)
        controller_root = self.controller_jobs_root / normalized_tool / normalized_id
        for relative in ("state", "locks", "transactions", "indexes", "cache"):
            (controller_root / relative).mkdir(parents=True, exist_ok=True)
        if normalized_tool == "bic":
            for relative in ("memory", "generations", "target-history"):
                (root / relative).mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": JOB_SCHEMA_VERSION,
            "job_id": normalized_id,
            "tool": normalized_tool,
            "display_name": display_name.strip() or normalized_id,
            "status": "ACTIVE",
            "bindings": bindings,
            "profiles": canonical_profiles,
            "defaults": defaults or {},
            "progress_quantifier": DEFAULT_JOB_PROGRESS_POLICY.to_dict(),
            "reporting": {
                "secondary_language": canonical_secondary,
            },
            "configuration_revision": 1,
        }
        atomic_write_text(root / "job.yml", _safe_yaml(payload))
        atomic_write_text(root / "README.md", self._render_project_readme(payload))
        project = self.load_job(normalized_id, tool=normalized_tool)
        self.write_runtime_files(project)
        return project

    def revise_job(
        self,
        project: Job,
        *,
        display_name: str | None = None,
        defaults: dict[str, Any] | None = None,
        reporting: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> Job:
        """Apply a bounded manifest revision and rebuild derived runtime files."""
        raw = load_yaml(project.manifest_path)
        if display_name is not None:
            normalized_name = display_name.strip()
            if not normalized_name:
                raise ValidationError("Job display name cannot be blank")
            raw["display_name"] = normalized_name
        if defaults is not None:
            raw["defaults"] = dict(defaults)
        if reporting is not None:
            unsupported_reporting = sorted(set(reporting) - {"secondary_language"})
            if unsupported_reporting:
                raise ValidationError(
                    "Job reporting accepts only secondary_language",
                    code="JOB_REPORTING_FIELD_INVALID",
                    details={"unsupported": unsupported_reporting},
                )
            secondary = reporting.get("secondary_language")
            canonical_secondary = (
                canonical_language_tag(
                    str(secondary),
                    "job reporting secondary_language",
                )
                if secondary not in (None, "")
                else None
            )
            operator_language = load_ecosystem(self.settings_path).human_output.operator_language
            if canonical_secondary == operator_language:
                raise ValidationError(
                    "Job secondary reporting language must differ from the global Operator language",
                    code="JOB_REPORTING_LANGUAGE_CONFLICT",
                )
            raw["reporting"] = {"secondary_language": canonical_secondary}
        if status is not None:
            normalized_status = status.strip().upper()
            if normalized_status not in {"ACTIVE", "INACTIVE", "ARCHIVED"}:
                raise ValidationError(f"Unsupported Job status: {status}")
            raw["status"] = normalized_status
        revision = raw.get("configuration_revision", project.configuration_revision)
        if not isinstance(revision, int) or revision < 1:
            raise ConfigurationError("Job configuration_revision must be a positive integer")
        raw["configuration_revision"] = revision + 1
        raw["revised_utc"] = _utc_now()
        atomic_write_text(project.manifest_path, _safe_yaml(raw))
        updated = self.load_job(project.job_id, tool=project.tool)
        atomic_write_text(updated.root / "README.md", self._render_project_readme(raw))
        self.write_runtime_files(updated)
        return self.load_job(project.job_id, tool=project.tool)

    def remove_job(self, project: Job) -> None:
        """Remove one Job directory without touching Projects or root-level published reports."""
        current = self.load_job(project.job_id, tool=project.tool)
        if self.active_jobs().get(current.tool) == current.job_id:
            self.set_active_job(current.tool, None)
        if self.last_run_path.is_file():
            try:
                last = json.loads(self.last_run_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                last = {}
            if isinstance(last, dict) and last.get("job_id") == current.job_id and last.get("tool") == current.tool:
                self.last_run_path.unlink(missing_ok=True)
        shutil.rmtree(current.root)
        if current.controller_root.exists():
            shutil.rmtree(current.controller_root)
        inactive = self.controller_jobs_root / "inactive" / current.tool / current.job_id
        if inactive.exists():
            shutil.rmtree(inactive)

    @staticmethod
    def _exportable_project_files(project: Job, destination: Path) -> list[Path]:
        """Return stable project-owned files while excluding regenerable runtime clutter."""
        excluded_roots = {
            project.root / ".sage" / "cache",  # legacy package residue; excluded if encountered
            project.root / ".sage" / "workspace_data",
            project.root / ".sage" / "locks",
        }
        files: list[Path] = []
        for path in sorted(project.root.rglob("*")):
            if not path.is_file() or path.resolve() == destination.resolve():
                continue
            if any(path.is_relative_to(root) for root in excluded_roots):
                continue
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            files.append(path)
        return files

    def export_job(self, project: Job, destination: Path | None = None) -> Path:
        """Create one deterministic portable ZIP containing only this Job."""
        target = destination or project.root / "exports" / f"{project.job_id}-backup.zip"
        target = target.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        files = self._exportable_project_files(project, target)
        manifest = {
            "schema_version": "1.0",
            "export_type": "SAGE_JOB",
            "job_id": project.job_id,
            "tool": project.tool,
            "configuration_revision": project.configuration_revision,
            "file_count": len(files),
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            info = zipfile.ZipInfo("EXPORT-MANIFEST.json", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            for path in files:
                relative = path.relative_to(project.root).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
        return target

    def export_run(
        self,
        project: Job,
        run: Run,
        destination: Path | None = None,
    ) -> Path:
        """Create a deterministic project-labeled bundle for one bounded run."""
        if run.job_id != project.job_id:
            raise ValidationError("Run does not belong to the selected project")
        target = destination or project.root / "exports" / f"{run.run_id}.zip"
        target = target.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        files = [path for path in sorted(run.root.rglob("*")) if path.is_file()]
        manifest = {
            "schema_version": "1.0",
            "export_type": "SAGE_RUN",
            "job_id": project.job_id,
            "tool": project.tool,
            "run_id": run.run_id,
            "status": run.status,
            "file_count": len(files),
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            info = zipfile.ZipInfo("EXPORT-MANIFEST.json", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            for path in files:
                relative = path.relative_to(run.root).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
        return target

    def _render_project_readme(self, payload: dict[str, Any]) -> str:
        """Render one human-facing project summary using canonical binding terminology."""
        bindings = dict(payload["bindings"])
        profiles = dict(payload.get("profiles", {}))
        lines = [
            f"# {payload['display_name']}",
            "",
            f"- Tool: `{str(payload['tool']).upper()}`",
            f"- Job: `{payload.get('job_id')}`",
            f"- Status: `{payload['status']}`",
            f"- Secondary report language: `{dict(payload.get('reporting') or {}).get('secondary_language') or 'NONE'}`",
            "",
            "When a secondary report language is configured, the primary Operator-language rendering governs interpretation. The secondary rendering is assistive, has lower unverified translation confidence, and must be checked against the primary before action. It adds model usage and report compilation time and requires more human review than a single-language report. Canonical machine evidence remains authoritative.",
            "",
            "## Bound resources",
            "",
        ]
        if str(payload["tool"]).lower() == "bic":
            lines.extend([
                f"- SOURCE — one bound resource: `{bindings['content_source']}`",
                f"- DONOR — one bound resource: `{bindings['lexical_donor']}`",
                f"- TARGET — one bound resource: `{bindings['generated_target']}`",
                f"- Configured Greek resource: `{bindings.get('original_language_greek') or 'NOT_CONFIGURED'}`",
                f"- Configured Hebrew resource: `{bindings.get('original_language_hebrew') or 'NOT_CONFIGURED'}`",
                f"- Selected SOURCE grammar profile: `{profiles.get('source_grammar') or 'NOT_CONFIGURED'}`",
                f"- Selected TARGET grammar profile: `{profiles.get('target_grammar') or 'NOT_CONFIGURED'}`",
            ])
        else:
            lines.extend([
                f"- WIP — one bound resource: `{bindings['wip']}`",
                f"- REFERENCE — one bound resource: `{bindings['reference']}`",
                f"- Configured Greek resource: `{bindings.get('original_language_greek') or 'NOT_CONFIGURED'}`",
                f"- Configured Hebrew resource: `{bindings.get('original_language_hebrew') or 'NOT_CONFIGURED'}`",
                f"- Selected WIP grammar profile: `{profiles.get('target_grammar') or 'NOT_CONFIGURED'}`",
            ])
        lines.extend(
            [
                "",
                "## Directory use",
                "",
                "- `runs/`: bounded operator Runs and immutable governed tasks.",
                "- `diagnostics/`: Job-local technical execution and validation diagnostics; finalized Operator reports are published only under root `reports/<job-id>/`.",
                "- `exports/`: portable Job and Run export archives.",
                "- Controller-owned runtime state is stored outside this folder under `SAGEdata/.system/jobs/`.",
                "- BIC `memory/` and `generations/` belong only to that BIC Job; SAW has no generation-handoff state.",
                "",
            ]
        )
        return "\n".join(lines)

    def _base_raw(self) -> dict[str, Any]:
        """Load effective Core + local settings plus operator-owned resource registrations."""
        raw, _override_path, _resolutions = load_effective_settings(self.settings_path)
        raw = merge_registered_projects(raw, self.sage_root)
        raw = apply_original_language_resources(raw, self.sage_root)
        return apply_resource_mounts(raw, self.sage_root)

    def _base_profile(self, tool: str, raw: dict[str, Any]) -> dict[str, Any]:
        """Manage ` base profile` for Job-scoped state and storage."""
        workflow = require_mapping(require_mapping(raw.get("workflows"), "workflows").get(tool), f"workflows.{tool}")
        profile_value = require_string(workflow.get("profile"), f"workflows.{tool}.profile")
        profile_path = resolve_declared_path(self.sage_root, profile_value, f"workflows.{tool}.profile")
        return load_yaml(profile_path)

    def write_runtime_files(self, project: Job) -> Path:
        """Derive a stable Job-scoped ecosystem settings file and workflow profile."""
        raw = self._base_raw()
        project_profile = self._base_profile(project.tool, raw)
        if project.tool == "bic":
            role_bindings = {
                "CONTENT_SOURCE": project.bindings["content_source"],
                "LEXICAL_DONOR": project.bindings["lexical_donor"],
                "GENERATED_TARGET": project.bindings["generated_target"],
            }
        else:
            role_bindings = {
                "WIP": project.bindings["wip"],
                "REFERENCE": project.bindings["reference"],
            }
        if project.bindings.get("original_language_greek"):
            role_bindings["ORIGINAL_LANGUAGE_GREEK"] = project.bindings["original_language_greek"]
        if project.bindings.get("original_language_hebrew"):
            role_bindings["ORIGINAL_LANGUAGE_HEBREW"] = project.bindings["original_language_hebrew"]
        project_profile["bindings"] = role_bindings
        if project.tool == "bic":
            permissions = dict(require_mapping(project_profile.get("permissions", {}), "BIC permissions"))
            permissions["may_write_projects"] = [project.bindings["generated_target"]]
            project_profile["permissions"] = permissions
        else:
            permissions = dict(require_mapping(project_profile.get("permissions", {}), "SAW permissions"))
            permissions["may_write_projects"] = []
            project_profile["permissions"] = permissions
        atomic_write_text(project.runtime_profile_path, _safe_yaml(project_profile))

        ecosystem = dict(require_mapping(raw.get("ecosystem"), "ecosystem"))
        ecosystem["configured"] = True
        raw["ecosystem"] = ecosystem
        paths = dict(require_mapping(raw.get("paths"), "paths"))
        paths["sage_root"] = str(self.sage_root)
        controller_token = f"@system/jobs/{project.tool}/{project.job_id}"
        paths["cache_root"] = f"{controller_token}/cache"
        paths["runtime_state_root"] = controller_token
        raw["paths"] = paths

        registered = require_mapping(raw.get("projects", {}), "projects")
        bound_ids = set(role_bindings.values())
        # BIC and SAW projects are independent; enable only this project's bound resources.
        required_resource_ids = bound_ids
        projects_root = self.storage.projects_root
        custom_default = str(
            require_mapping(raw.get("versification", {}), "versification").get(
                "custom_file_default", "custom.vrs"
            )
        )
        effective_roles: dict[str, list[str]] = {}
        for role, resource_id in role_bindings.items():
            effective_roles.setdefault(resource_id, []).append(role)
        grammar_variants: dict[str, str] = {}
        if project.tool == "bic":
            grammar_variants[project.bindings["content_source"]] = project.profiles["source_grammar"].split("/", 1)[-1]
            grammar_variants[project.bindings["generated_target"]] = project.profiles["target_grammar"].split("/", 1)[-1]
        else:
            grammar_variants[project.bindings["wip"]] = project.profiles["target_grammar"].split("/", 1)[-1]
        for resource_id, value in registered.items():
            item = dict(require_mapping(value, f"projects.{resource_id}"))
            resource_path = Path(str(item.get("path", resource_id)))
            external_value = item.get("external_path")
            resource_root = (
                Path(str(external_value)).expanduser().resolve()
                if external_value not in (None, "")
                else (projects_root / resource_path).resolve()
            )
            present = resource_root.is_dir()
            item["enabled"] = bool(resource_id in required_resource_ids and present)
            scope = dict(require_mapping(item.get("scope", {}), f"projects.{resource_id}.scope"))
            roles = sorted(effective_roles.get(resource_id, []))
            scope["roles"] = roles
            item["scope"] = scope
            language = dict(require_mapping(item.get("language", {}), f"projects.{resource_id}.language"))
            if resource_id in grammar_variants:
                language["variant"] = grammar_variants[resource_id]
            else:
                language.pop("variant", None)
            item["language"] = language
            # Project inventory is role-neutral. Runtime state/content/writer semantics are
            # derived solely from the active Job binding.
            if "GENERATED_TARGET" in roles:
                item["kind"] = "GENERATED_SCRIPTURE"
                item["content_state"] = "UNDER_REVIEW"
                item["producer"] = "bic"
                item["consumers"] = []
                item["coverage_policy"] = "PRESENT_CHAPTERS_ONLY"
            elif "WIP" in roles:
                item["kind"] = "SCRIPTURE"
                item["content_state"] = "UNDER_REVIEW"
                item.pop("producer", None)
                item["consumers"] = ["saw"]
            else:
                item["kind"] = "SCRIPTURE"
                item["content_state"] = "LOCKED"
                item.pop("producer", None)
            if external_value not in (None, ""):
                target_id = project.bindings.get("generated_target") if project.tool == "bic" else None
                if resource_id == target_id:
                    item["external_access_mode"] = READ_WRITE_TARGET
                else:
                    item["external_access_mode"] = READ_ONLY_SCRIPTURE
            versification = dict(
                require_mapping(item.get("versification", {}), f"projects.{resource_id}.versification")
            )
            if str(versification.get("custom_file", "")).strip().lower() == "auto":
                candidate = resource_root / custom_default
                versification["custom_file"] = custom_default if candidate.is_file() else "none"
                item["versification"] = versification
            registered[resource_id] = item
        raw["projects"] = registered

        workflow_data = require_mapping(raw.get("workflows"), "workflows")
        for workflow_id in TOOL_IDS:
            entry = dict(require_mapping(workflow_data.get(workflow_id), f"workflows.{workflow_id}"))
            if workflow_id == project.tool:
                controller_token = f"@system/jobs/{project.tool}/{project.job_id}"
                job_token = f"@jobs/{project.tool}/{project.job_id}"
                entry["profile"] = f"{controller_token}/profile.yml"
                entry["state_root"] = f"{controller_token}/state"
                entry["lock_root"] = f"{controller_token}/locks"
                entry["transaction_root"] = f"{controller_token}/transactions"
                entry["output_root"] = job_token
                if workflow_id == "bic":
                    entry["memory_root"] = f"{job_token}/memory"
                    entry["publication_root"] = f"{job_token}/generations"
                else:
                    entry.pop("memory_root", None)
                    entry.pop("publication_root", None)
            else:
                inactive_token = f"@system/jobs/inactive/{project.tool}/{project.job_id}/{workflow_id}"
                entry["state_root"] = f"{inactive_token}/state"
                entry["lock_root"] = f"{inactive_token}/locks"
                entry["transaction_root"] = f"{inactive_token}/transactions"
                entry["output_root"] = f"{inactive_token}/output"
                if workflow_id == "bic":
                    entry["memory_root"] = f"{inactive_token}/memory"
                    entry["publication_root"] = f"{inactive_token}/generations"
                else:
                    entry.pop("memory_root", None)
                    entry.pop("publication_root", None)
            workflow_data[workflow_id] = entry
        raw["workflows"] = workflow_data

        # The global Operator language is always primary. Each Job may add one secondary
        # reporting language without changing Project identity or global interface settings.
        reporting_project_id = (
            project.bindings.get("generated_target") if project.tool == "bic" else project.bindings.get("wip")
        )
        human = dict(require_mapping(raw.get("human_output", {}), "human_output"))
        primary = str(human.get("operator_language") or "en")
        secondary = project.secondary_report_language
        bilingual = bool(secondary and secondary != primary)
        logs = dict(require_mapping(human.get("logs_and_reports", {}), "human_output.logs_and_reports"))
        logs.update({"primary_language": primary, "secondary_language": secondary, "bilingual": bilingual})
        human["logs_and_reports"] = logs
        challenges = dict(require_mapping(human.get("translation_challenges", {}), "human_output.translation_challenges"))
        challenges.update({"primary_language": primary, "secondary_language": secondary, "bilingual": bilingual})
        human["translation_challenges"] = challenges
        human["operator_language"] = primary
        raw["human_output"] = human

        raw["runtime_context"] = {
            "kind": "JOB",
            "job_id": project.job_id,
            "tool": project.tool,
            "configuration_revision": project.configuration_revision,
            "original_language_resources": active_ol_provenance(self.sage_root),
            "reporting_project": reporting_project_id,
            "secondary_report_language": secondary,
        }
        atomic_write_text(project.runtime_settings_path, _safe_yaml(raw))
        # Validate immediately so a broken project cannot become active silently.
        load_ecosystem(project.runtime_settings_path)
        return project.runtime_settings_path

    def ensure_runtime_files(self, project: Job) -> Path:
        """Refresh and validate derived Job runtime files against current SAGE configuration."""
        return self.write_runtime_files(project)

    def active_jobs(self) -> dict[str, str | None]:
        """Return active Job selections."""
        value: dict[str, Any] = {}
        if self.active_jobs_path.is_file():
            try:
                loaded = json.loads(self.active_jobs_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    value = loaded
            except (OSError, json.JSONDecodeError):
                value = {}
        return {tool: value.get(tool) if isinstance(value.get(tool), str) else None for tool in TOOL_IDS}

    def set_active_job(self, tool: str, job_id: str | None) -> dict[str, str | None]:
        """Set the active Job for one workflow."""
        normalized = tool.strip().lower()
        if normalized not in TOOL_IDS:
            raise ValidationError(f"Unsupported tool: {tool}")
        state = self.active_jobs()
        if job_id is not None:
            project = self.load_job(job_id, tool=normalized)
            if project.status != "ACTIVE":
                raise ValidationError(f"Cannot activate {project.status.lower()} Job: {job_id}")
            self.ensure_runtime_files(project)
            state[normalized] = project.job_id
        else:
            state[normalized] = None
        atomic_write_json(
            self.active_jobs_path,
            {"schema_version": "1.0", **state, "updated_utc": _utc_now()},
        )
        return state

    def active_job(self, tool: str) -> Job | None:
        """Return the active Job for one workflow."""
        job_id = self.active_jobs().get(tool.strip().lower())
        return self.load_job(job_id, tool=tool) if job_id else None

    def create_run(
        self,
        project: Job,
        *,
        operation: str,
        scope: str,
        focus: str | None = None,
        check_type: str | None = None,
    ) -> Run:
        """Create one deterministic Run and make it current for the selected Job."""
        date = datetime.now(timezone.utc).strftime("%Y%m%d")
        prefix = f"{project.job_id}-{date}-"
        run_root = project.root / "runs"
        existing = [path.name for path in run_root.glob(f"{prefix}*") if path.is_dir()]
        sequences: list[int] = []
        for value in existing:
            try:
                sequences.append(int(value.rsplit("-", 1)[1]))
            except (ValueError, IndexError):
                continue
        run_id = f"{prefix}{(max(sequences, default=0) + 1):03d}"
        root = run_root / run_id
        for relative in ("tasks", "plans", "diagnostics"):
            (root / relative).mkdir(parents=True, exist_ok=True)
        now = _utc_now()
        payload = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "tool": project.tool,
            "job_id": project.job_id,
            "operation": operation.strip().lower(),
            "scope": scope.strip(),
            "focus": focus.strip() if isinstance(focus, str) and focus.strip() else None,
            "check_type": check_type.strip().upper() if isinstance(check_type, str) and check_type.strip() else None,
            "status": "NEW",
            "current_stage": "NEW",
            "result": None,
            "result_reason": None,
            "task_manifests": [],
            "plan_path": None,
            "approved_work_plan_path": None,
            "created_utc": now,
            "updated_utc": now,
        }
        atomic_write_json(root / "run.json", payload)
        atomic_write_json(root / "status.json", payload)
        atomic_write_json(
            project.controller_state_root / "active-run.json",
            {
                "schema_version": "1.0",
                "tool": project.tool,
                "job_id": project.job_id,
                "run_id": run_id,
                "updated_utc": now,
            },
        )
        self.set_last_run(project.tool, project.job_id, run_id)
        return self.load_run(project, run_id)

    def restart_bic_scope(self, project: Job, *, scope: str) -> Run:
        """Abandon incomplete BIC analytical Runs for one scope and create a clean replacement."""
        if project.tool != "bic":
            raise ValidationError("Restart Scope is a BIC-only analytical operation")
        for run in self.list_runs(project, include_archived=False):
            if run.operation == "bic" and run.scope == scope and run.status not in {"COMPLETE", "ARCHIVED", "ABANDONED"}:
                self.update_run(run, status="ABANDONED", current_stage="ABANDONED")
        return self.create_run(project, operation="bic", scope=scope)

    def restart_run(self, project: Job, run: Run) -> Run:
        """Preserve an incomplete Run as abandoned and recreate its operator request."""
        if run.job_id != project.job_id or run.tool != project.tool:
            raise ValidationError("Run restart requires its owning Job")
        if run.status in {"COMPLETE", "ARCHIVED", "ABANDONED"}:
            raise ValidationError(
                f"Cannot restart a {run.status.lower()} Run; start a new task instead"
            )
        replacement = self.create_run(
            project,
            operation=run.operation,
            scope=run.scope,
            focus=run.focus,
            check_type=run.check_type,
        )
        self.update_run(run, status="ABANDONED", current_stage="ABANDONED")
        self.set_active_run(project, replacement.run_id)
        self.set_last_run(project.tool, project.job_id, replacement.run_id)
        return replacement

    def _run_location(self, project: Job, run_id: str) -> tuple[Path, Path]:
        """Return the current Run root and manifest path after existence validation."""
        root = project.root / "runs" / run_id
        manifest = root / "run.json"
        if not manifest.is_file():
            raise ConfigurationError(f"Run not found: {run_id}")
        return root, manifest

    def load_run(self, project: Job, run_id: str) -> Run:
        """Load one current Run."""
        run = validate_context_id(run_id, "run_id")
        assert run is not None
        root, manifest = self._run_location(project, run)
        raw = load_json(manifest)
        if require_string(raw.get("run_id"), "run run_id") != run:
            raise ConfigurationError(f"Run manifest identity mismatch: {run}")
        if require_string(raw.get("job_id"), "run job_id") != project.job_id:
            raise ConfigurationError(f"Run belongs to another Job: {run}")
        task_values = raw.get("task_manifests", []) or []
        if not isinstance(task_values, list) or any(not isinstance(item, str) for item in task_values):
            raise ConfigurationError("run task_manifests must be a list of paths")
        result_value = str(raw.get("result") or "").upper() or None
        result_reason = str(raw.get("result_reason") or "").upper() or None
        if result_value and result_value not in {"DONE", "FAILED", "BLOCKED", "CANCELLED"}:
            raise ConfigurationError(f"Unsupported Run result: {result_value}")
        if result_value == "BLOCKED" and not result_reason:
            raise ConfigurationError("BLOCKED Run result requires result_reason")
        return Run(
            run_id=run,
            tool=require_string(raw.get("tool"), "run tool").lower(),
            job_id=project.job_id,
            operation=require_string(raw.get("operation"), "run operation").lower(),
            scope=require_string(raw.get("scope"), "run scope"),
            focus=str(raw["focus"]) if raw.get("focus") else None,
            check_type=str(raw["check_type"]) if raw.get("check_type") else None,
            status=require_string(raw.get("status", "NEW"), "run status").upper(),
            current_stage=require_string(raw.get("current_stage", "NEW"), "run current_stage").upper(),
            result=result_value,
            result_reason=result_reason,
            task_manifests=tuple(task_values),
            plan_path=str(raw["plan_path"]) if raw.get("plan_path") else None,
            approved_work_plan_path=(
                str(raw["approved_work_plan_path"])
                if raw.get("approved_work_plan_path")
                else None
            ),
            created_utc=require_string(raw.get("created_utc"), "run created_utc"),
            updated_utc=require_string(raw.get("updated_utc"), "run updated_utc"),
            root=root,
        )

    def update_run(self, run: Run, **changes: Any) -> Run:
        """Update bounded Run state."""
        raw = load_json(run.manifest_path)
        allowed = {
            "status", "current_stage", "result", "result_reason", "task_manifests",
            "plan_path", "approved_work_plan_path", "focus", "check_type", "notes",
        }
        unknown = sorted(set(changes) - allowed)
        if unknown:
            raise ValidationError(f"Unsupported Run updates: {', '.join(unknown)}")
        for key, value in changes.items():
            raw[key] = list(value) if key == "task_manifests" and isinstance(value, tuple) else value
        status = str(raw.get("status") or "").upper()
        explicit_result = str(raw.get("result") or "").upper()
        if not explicit_result:
            if status == "COMPLETE":
                raw["result"] = "DONE"
            elif status == "ABANDONED":
                raw["result"] = "CANCELLED"
            elif status == "FAILED":
                raw["result"] = "FAILED"
            elif status == "BLOCKED":
                raw["result"] = "BLOCKED"
        result = str(raw.get("result") or "").upper()
        if result and result not in {"DONE", "FAILED", "BLOCKED", "CANCELLED"}:
            raise ValidationError(f"Unsupported Run result: {result}")
        if result == "BLOCKED" and not str(raw.get("result_reason") or "").strip():
            raise ValidationError("BLOCKED Run result requires result_reason")
        raw["updated_utc"] = _utc_now()
        atomic_write_json(run.manifest_path, raw)
        atomic_write_json(run.status_path, raw)
        project = self.load_job(run.job_id, tool=run.tool)
        if status in RUN_CLOSED_STATUSES:
            # Completion may occur outside the menu. Reconcile the Job-local
            # pointer here so every caller observes the same lifecycle state.
            self.active_run(project)
        self.set_last_run(run.tool, run.job_id, run.run_id)
        return self.load_run(project, run.run_id)

    def list_runs(self, project: Job, *, include_archived: bool = True) -> list[Run]:
        """List current Runs for one Job."""
        result: list[Run] = []
        for path in sorted((project.root / "runs").glob("*/run.json"), reverse=True):
            run = self.load_run(project, path.parent.name)
            if include_archived or run.status not in {"ARCHIVED", "ABANDONED"}:
                result.append(run)
        return result

    def active_run(self, project: Job) -> Run | None:
        """Return the active non-closed Run for one Job and discard stale pointers."""
        path = project.controller_state_root / "active-run.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        run_id = value.get("run_id") if isinstance(value, dict) else None
        if not isinstance(run_id, str):
            return None
        try:
            run = self.load_run(project, run_id)
        except (ConfigurationError, ValidationError):
            return None
        if run.status in RUN_CLOSED_STATUSES:
            path.unlink(missing_ok=True)
            return None
        return run

    def set_active_run(self, project: Job, run_id: str | None) -> None:
        """Set or clear the Job-local active Run pointer."""
        path = project.controller_state_root / "active-run.json"
        if run_id is None:
            path.unlink(missing_ok=True)
            return
        run = self.load_run(project, run_id)
        if run.status in RUN_CLOSED_STATUSES:
            raise ValidationError(
                f"Cannot make a {run.status.lower()} Run active; open it from Run history instead"
            )
        atomic_write_json(
            path,
            {"schema_version": "1.0", "tool": project.tool, "job_id": project.job_id, "run_id": run.run_id, "updated_utc": _utc_now()},
        )
        self.set_last_run(project.tool, project.job_id, run.run_id)

    def set_last_run(self, tool: str, job_id: str, run_id: str) -> None:
        """Persist the global resume pointer for one current Job/Run pair."""
        atomic_write_json(
            self.last_run_path,
            {"schema_version": "1.0", "tool": tool, "job_id": job_id, "run_id": run_id, "updated_utc": _utc_now()},
        )

    def last_run(self) -> tuple[Job, Run] | None:
        """Return the most recent Run."""
        path = self.last_run_path
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict):
            return None
        try:
            project = self.load_job(str(value["job_id"]), tool=str(value["tool"]))
            run = self.load_run(project, str(value["run_id"]))
        except (KeyError, ConfigurationError, ValidationError):
            return None
        return project, run


    def bootstrap_default_jobs(self) -> list[Job]:
        """Create deterministic Jobs from the configured workflow bindings and evaluation set."""
        config = load_ecosystem(self.settings_path)
        created: list[Job] = []
        bic_profile = self._base_profile("bic", config.raw)
        bic_bindings = require_mapping(bic_profile.get("bindings"), "BIC bindings")
        bic_output = require_string(bic_bindings.get("GENERATED_TARGET"), "BIC GENERATED_TARGET")
        bic_source = require_string(bic_bindings.get("CONTENT_SOURCE"), "BIC CONTENT_SOURCE")
        bic_donor = require_string(bic_bindings.get("LEXICAL_DONOR"), "BIC LEXICAL_DONOR")
        bic_id = default_job_name("bic", bic_output, bic_source, bic_donor)
        created.append(
            self.create_job(
                tool="bic",
                job_id=bic_id,
                display_name=f"{_resource_slug(bic_source).upper()} to {_resource_slug(bic_output).upper()}",
                bindings={
                    "content_source": bic_source,
                    "lexical_donor": bic_donor,
                    "generated_target": bic_output,
                    **({"original_language_greek": str(bic_bindings["ORIGINAL_LANGUAGE_GREEK"])} if bic_bindings.get("ORIGINAL_LANGUAGE_GREEK") else {}),
                    **({"original_language_hebrew": str(bic_bindings["ORIGINAL_LANGUAGE_HEBREW"])} if bic_bindings.get("ORIGINAL_LANGUAGE_HEBREW") else {}),
                },
                profiles={
                    "source_grammar": config.project(bic_source).profile_ref,
                    "target_grammar": config.project(bic_output).profile_ref,
                },
                defaults={
                    "challenge_language": config.human_output.translation_challenges.primary_language,
                    "report_language": config.human_output.logs_and_reports.primary_language,
                    "publication_enabled": True,
                },
            )
        )

        saw_profile = self._base_profile("saw", config.raw)
        saw_bindings = require_mapping(saw_profile.get("bindings"), "SAW bindings")
        greek = str(saw_bindings["ORIGINAL_LANGUAGE_GREEK"]) if saw_bindings.get("ORIGINAL_LANGUAGE_GREEK") else None
        hebrew = str(saw_bindings["ORIGINAL_LANGUAGE_HEBREW"]) if saw_bindings.get("ORIGINAL_LANGUAGE_HEBREW") else None
        pairs: list[tuple[str, str]] = [
            (
                require_string(saw_bindings.get("WIP"), "SAW WIP"),
                require_string(saw_bindings.get("REFERENCE"), "SAW REFERENCE"),
            )
        ]
        for evaluation_set in config.evaluation_sets.values():
            pairs.extend((entry.output_project, entry.contemporary_source) for entry in evaluation_set.entries)
        seen: set[tuple[str, str]] = set()
        for output, source in pairs:
            if (output, source) in seen:
                continue
            seen.add((output, source))
            job_id = default_job_name("saw", output, source)
            created.append(
                self.create_job(
                    tool="saw",
                    job_id=job_id,
                    display_name=f"{_resource_slug(output).upper()} reviewed against {_resource_slug(source).upper()}",
                    bindings={
                        "wip": output,
                        "reference": source,
                        **({"original_language_greek": greek} if greek else {}),
                        **({"original_language_hebrew": hebrew} if hebrew else {}),
                    },
                    profiles={"target_grammar": config.project(output).profile_ref},
                    defaults={
                        "report_language": config.human_output.logs_and_reports.primary_language,
                    },
                )
            )
        active = self.active_jobs()
        for tool in TOOL_IDS:
            if not active.get(tool):
                candidates = [project for project in created if project.tool == tool]
                if candidates:
                    self.set_active_job(tool, candidates[0].job_id)
        for project in created:
            self.write_runtime_files(project)
        return created

    def write_setup_state(self, payload: dict[str, Any]) -> None:
        """Manage `write setup state` for Job-scoped state and storage."""
        atomic_write_json(
            self.setup_state_path,
            {"schema_version": "1.0", **payload, "updated_utc": _utc_now()},
        )

    def record_cue(self, event: str, **payload: Any) -> None:
        """Append one high-level operator cue without duplicating workflow transaction journals."""
        append_event(
            self.operator_cues_path,
            {
                "schema_version": "1.0",
                "event": event.strip().upper(),
                "updated_utc": _utc_now(),
                **payload,
            },
        )

    def setup_state(self) -> dict[str, Any] | None:
        """Manage `setup state` for Job-scoped state and storage."""
        if not self.setup_state_path.is_file():
            return None
        try:
            value = json.loads(self.setup_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return dict(value) if isinstance(value, dict) else None
