"""Portable Job-to-Paratext rebinding for a cloned SAGE workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigurationError, ValidationError
from .external_access import EXTERNAL_ACCESS_MODES, READ_ONLY_SCRIPTURE
from .project_inventory import load_project_registry, write_project_registry
from .resource_mounts import set_project_root, set_resource_mount
from .storage import storage_layout


def _mapping_file(path: Path) -> dict[str, Any]:
    """Load one YAML mapping used as portable Job evidence."""
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Invalid portable Job record: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"Portable Job record must be a mapping: {path}")
    return dict(value)


def _bound_projects(root: Path) -> dict[str, str]:
    """Return external-access intent for every ordinary Project bound by a Job."""
    result: dict[str, str] = {}
    for manifest in sorted(storage_layout(root).jobs_root.glob("*/*/job.yml")):
        job = _mapping_file(manifest)
        bindings = job.get("bindings", {})
        if not isinstance(bindings, dict):
            raise ConfigurationError(f"Job bindings must be a mapping: {manifest}")
        for role, project_id in bindings.items():
            if str(role).startswith("original_language_"):
                continue
            value = str(project_id).strip()
            if not value:
                continue
            result.setdefault(value, READ_ONLY_SCRIPTURE)
    return result


def _runtime_project_records(root: Path) -> dict[str, dict[str, Any]]:
    """Recover Project metadata from preserved Job runtime snapshots."""
    result: dict[str, dict[str, Any]] = {}
    for runtime in sorted((storage_layout(root).system_root / "jobs").glob("*/*/runtime.yml")):
        projects = _mapping_file(runtime).get("projects", {})
        if not isinstance(projects, dict):
            continue
        for project_id, record in projects.items():
            if isinstance(project_id, str) and isinstance(record, dict):
                result.setdefault(project_id, dict(record))
    return result


def _direct_projects(projects_root: Path) -> dict[str, list[str]]:
    """Index Paratext subfolders case-insensitively without choosing ambiguous names."""
    from .paratext_catalog import parse_settings_xml

    result: dict[str, list[str]] = {}
    for child in sorted(projects_root.iterdir(), key=lambda item: item.name.casefold()):
        settings = child / "settings.xml"
        if not child.is_dir() or not settings.is_file():
            continue
        try:
            parse_settings_xml(settings)
        except ValidationError:
            continue
        result.setdefault(child.name.casefold(), []).append(child.name)
    return result


def _portable_folder_candidates(project_id: str, record: dict[str, Any]) -> tuple[str, ...]:
    """Return stable direct-subfolder candidates from prior Project evidence."""
    values: list[str] = []
    path_value = str(record.get("path") or "").strip()
    path = Path(path_value)
    if path_value and not path.is_absolute() and len(path.parts) == 1:
        values.append(path.name)
    external = str(record.get("external_path") or "").strip()
    if external:
        values.append(Path(external).name)
    values.append(project_id)
    return tuple(dict.fromkeys(value for value in values if value and value not in {".", ".."}))


def _internal_project_exists(root: Path, record: dict[str, Any]) -> bool:
    """Return whether a Project record intentionally points into portable workspace data."""
    if str(record.get("external_path") or "").strip():
        return False
    value = str(record.get("path") or "").strip()
    path = Path(value)
    if path.is_absolute() or not path.parts:
        return False
    layout = storage_layout(root)
    candidates = [layout.projects_root / path]
    for candidate in candidates:
        try:
            candidate.resolve().relative_to(layout.projects_root.resolve())
        except ValueError:
            continue
        if candidate.is_dir():
            return True
    return False


def rebind_new_host_projects(root: Path, projects_root: Path) -> dict[str, Any]:
    """Rebase preserved Jobs by matching their stable Paratext subfolder names.

    The parent Projects path is host-specific. Direct child names are portable identifiers.
    Every externally bound Job Project must match exactly one valid direct Paratext subfolder;
    missing or ambiguous matches block the operation before governed state is changed.
    """
    sage_root = root.resolve()
    new_root = projects_root.expanduser().resolve()
    if not new_root.is_dir():
        raise ValidationError(
            f"Paratext/PTLite Projects root not found: {new_root}",
            code="PROJECT_ROOT_NOT_FOUND",
        )
    bound = _bound_projects(sage_root)
    inventory = load_project_registry(sage_root)
    existing = {
        str(project_id): dict(record)
        for project_id, record in dict(inventory.get("projects", {})).items()
        if isinstance(record, dict)
    }
    recovered = _runtime_project_records(sage_root)
    folders = _direct_projects(new_root)
    resolved: dict[str, tuple[str, str]] = {}
    imported: dict[str, dict[str, Any]] = {}
    problems: list[str] = []

    for project_id, default_access in sorted(bound.items()):
        record = existing.get(project_id) or recovered.get(project_id)
        if record is None:
            problems.append(f"{project_id}: Project metadata is missing")
            continue
        if _internal_project_exists(sage_root, record):
            imported[project_id] = record
            continue
        matches: list[str] = []
        for candidate in _portable_folder_candidates(project_id, record):
            matches.extend(folders.get(candidate.casefold(), ()))
        matches = list(dict.fromkeys(matches))
        if len(matches) != 1:
            detail = "not found" if not matches else f"ambiguous ({', '.join(matches)})"
            problems.append(f"{project_id}: Paratext subfolder {detail}")
            continue
        portable = dict(record)
        access_mode = str(portable.pop("external_access_mode", default_access)).strip().upper()
        if access_mode not in EXTERNAL_ACCESS_MODES:
            problems.append(f"{project_id}: invalid external access mode {access_mode or 'EMPTY'}")
            continue
        portable.pop("external_path", None)
        portable.pop("consumers", None)
        portable["path"] = matches[0]
        imported[project_id] = portable
        resolved[project_id] = (matches[0], access_mode or default_access)

    if problems:
        raise ValidationError(
            "New-host Paratext rebinding failed: " + "; ".join(problems),
            code="NEW_HOST_PROJECT_SUBFOLDER_MISMATCH",
            details={"problems": problems, "projects_root": str(new_root)},
        )

    inventory["projects"] = {**existing, **imported}
    write_project_registry(sage_root, inventory)
    set_project_root(sage_root, project_root=new_root)
    for project_id, (folder, access_mode) in sorted(resolved.items()):
        set_resource_mount(
            sage_root,
            project_id=project_id,
            project_folder=folder,
            access_mode=access_mode,
        )
    return {
        "status": "READY",
        "projects_root": str(new_root),
        "job_projects": len(bound),
        "rebound_projects": len(resolved),
        "internal_projects": len(bound) - len(resolved),
        "subfolder_policy": "CASE_INSENSITIVE_SAME_DIRECT_SUBFOLDER",
    }
