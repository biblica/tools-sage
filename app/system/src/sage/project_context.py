"""Immutable Project identity resolution for sealed tasks and human reports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .errors import ValidationError
from .generations import project_validation_fingerprint
from .project_inventory import project_import_date, registered_project_records
from .registry import ProjectSpec

_ROLE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ProjectIdentity:
    """One role-bound Project identity sealed from inventory and compiled inputs."""

    role: str
    project_id: str
    display_name: str
    imported_date: str | None
    content_fingerprint: str | None
    vrs_schema_id: str | None
    effective_vrs_sha256: str | None


def resolve_project_identity(
    root: Path,
    role: str,
    project: ProjectSpec,
    compiled: Mapping[str, Any],
) -> ProjectIdentity:
    """Resolve and validate one Project's sealed role, display, and provenance identity."""
    normalized_role = str(role).strip().upper()
    if not _ROLE_RE.fullmatch(normalized_role):
        raise ValidationError(
            "Project identity role must be a non-empty uppercase machine role",
            code="PROJECT_IDENTITY_ROLE_INVALID",
        )
    compiled_project_id = str(compiled.get("project_id") or "").strip()
    if compiled_project_id != project.project_id:
        raise ValidationError(
            f"Compiled Project identity does not match {project.project_id}",
            code="PROJECT_IDENTITY_PROJECT_MISMATCH",
        )
    effective_vrs_value = compiled.get("effective_vrs")
    if not isinstance(effective_vrs_value, Mapping):
        raise ValidationError(
            f"Project {project.project_id} has no effective VRS identity",
            code="PROJECT_IDENTITY_VRS_MISSING",
        )
    effective_vrs = dict(effective_vrs_value)
    vrs_schema_id = str(effective_vrs.get("schema_id") or "").strip()
    effective_vrs_sha256 = str(effective_vrs.get("effective_sha256") or "").strip().lower()
    if not vrs_schema_id:
        raise ValidationError(
            f"Project {project.project_id} has no effective VRS schema ID",
            code="PROJECT_IDENTITY_VRS_MISSING",
        )
    if not _SHA256_RE.fullmatch(effective_vrs_sha256):
        raise ValidationError(
            f"Project {project.project_id} effective VRS hash is invalid",
            code="PROJECT_IDENTITY_VRS_HASH_INVALID",
        )
    content_fingerprint = project_validation_fingerprint(compiled)
    if not _SHA256_RE.fullmatch(content_fingerprint):
        raise ValidationError(
            f"Project {project.project_id} content fingerprint is invalid",
            code="PROJECT_IDENTITY_CONTENT_HASH_INVALID",
        )
    inventory = registered_project_records(root).get(project.project_id, {})
    display_name = str(inventory.get("display_name") or "").strip() or project.project_id
    return ProjectIdentity(
        role=normalized_role,
        project_id=project.project_id,
        display_name=display_name,
        imported_date=project_import_date(inventory),
        content_fingerprint=content_fingerprint,
        vrs_schema_id=vrs_schema_id,
        effective_vrs_sha256=effective_vrs_sha256,
    )


def resolve_project_identities(
    root: Path,
    bindings: Mapping[str, str],
    projects: Mapping[str, ProjectSpec],
    compiled: Mapping[str, Mapping[str, Any]],
) -> dict[str, ProjectIdentity]:
    """Resolve every role binding without permitting missing or duplicate normalized roles."""
    identities: dict[str, ProjectIdentity] = {}
    for role, project_id in bindings.items():
        normalized_role = str(role).strip().upper()
        if normalized_role in identities:
            raise ValidationError(
                f"Duplicate normalized Project identity role: {normalized_role}",
                code="PROJECT_IDENTITY_ROLE_DUPLICATE",
            )
        try:
            project = projects[project_id]
        except KeyError as exc:
            raise ValidationError(
                f"Project identity inputs are incomplete for {normalized_role or role}: {project_id}",
                code="PROJECT_IDENTITY_INPUT_MISSING",
            ) from exc
        project_result = compiled.get(project_id)
        if (
            project_result is not None
            and str(project_result.get("status")) != "NOT_GENERATED"
        ):
            identities[normalized_role] = resolve_project_identity(
                root,
                normalized_role,
                project,
                project_result,
            )
            continue
        if not _ROLE_RE.fullmatch(normalized_role):
            raise ValidationError(
                "Project identity role must be a non-empty uppercase machine role",
                code="PROJECT_IDENTITY_ROLE_INVALID",
            )
        inventory = registered_project_records(root).get(project.project_id, {})
        display_name = (
            str(inventory.get("display_name") or "").strip() or project.project_id
        )
        identities[normalized_role] = ProjectIdentity(
            role=normalized_role,
            project_id=project.project_id,
            display_name=display_name,
            imported_date=project_import_date(inventory),
            content_fingerprint=None,
            vrs_schema_id=None,
            effective_vrs_sha256=None,
        )
    return identities


def identity_bindings(identities: Mapping[str, ProjectIdentity]) -> dict[str, str]:
    """Project sealed identities into a fresh canonical role-to-Project-ID mapping."""
    return {role: identity.project_id for role, identity in identities.items()}


def identity_display_names(
    identities: Mapping[str, ProjectIdentity],
) -> dict[str, str]:
    """Project sealed identities into a fresh canonical role-to-display-name mapping."""
    return {role: identity.display_name for role, identity in identities.items()}
