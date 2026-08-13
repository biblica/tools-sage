"""Operator-owned Paratext/PTLite Projects root, per-project mounts, and base-VRS configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from .atomic import atomic_write_json
from .errors import ConfigurationError, ValidationError
from .external_access import EXTERNAL_ACCESS_MODES, READ_ONLY_SCRIPTURE

SCHEMA_VERSION = "2.0"


def mounts_path(root: Path) -> Path:
    """Return the operator-state file used for external Scripture-project locations."""
    return root.resolve() / "state" / "resource-mounts.json"


def normalize_operator_path(value: str) -> str:
    """Normalise a path pasted from a shell without requiring shell quoting rules."""
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    if os.name != "nt":
        text = text.replace(r"\ ", " ")
    return text


def interpret_operator_project_location(project_id: str, value: str) -> tuple[Path, Path | None, str | None]:
    """Interpret a pasted project path, also accepting the parent Projects root.

    Returns ``(project_path, inferred_projects_root, inferred_project_folder)``. If the
    operator pasted the parent Projects root and it contains a direct child whose name
    matches the selected project code case-insensitively, that child is selected.
    Surrounding shell quotes and escaped Unix spaces are normalised first.
    """
    path = Path(normalize_operator_path(value)).expanduser()
    if not path.is_absolute():
        raise ValidationError(
            "External Scripture project path must be absolute",
            code="RESOURCE_MOUNT_PATH_INVALID",
        )
    resolved = path.resolve()
    if not resolved.is_dir():
        raise ValidationError(
            f"External Scripture project directory not found: {resolved}",
            code="RESOURCE_MOUNT_NOT_FOUND",
        )
    wanted = str(project_id).casefold()
    try:
        children = [child for child in resolved.iterdir() if child.is_dir()]
    except OSError:
        children = []
    matches = [child for child in children if child.name.casefold() == wanted]
    if len(matches) == 1:
        child = matches[0].resolve()
        return child, resolved, matches[0].name
    return resolved, None, None


def _absolute_directory(value: str, label: str, *, require_exists: bool = False) -> str:
    """Normalise one configured external directory and optionally require it to exist."""
    path = Path(normalize_operator_path(value)).expanduser()
    if not path.is_absolute():
        raise ConfigurationError(f"{label} must be absolute: {value}")
    resolved = path.resolve()
    if require_exists and not resolved.is_dir():
        raise ValidationError(f"Directory not found: {resolved}", code="RESOURCE_MOUNT_NOT_FOUND")
    return str(resolved)


def _resolve_mount(
    *,
    project_id: str,
    value: dict[str, Any],
    projects_root: str | None,
) -> tuple[str, dict[str, str]]:
    """Resolve one root-relative project subfolder or explicit <Other location> binding."""
    access_mode = str(value.get("access_mode", READ_ONLY_SCRIPTURE)).strip().upper()
    if access_mode not in EXTERNAL_ACCESS_MODES:
        raise ConfigurationError(f"Unsupported external access mode for {project_id}: {access_mode}")
    project_folder = str(value.get("project_folder") or "").strip()
    explicit_path = str(value.get("path") or "").strip()
    if project_folder:
        if explicit_path:
            raise ConfigurationError(f"Resource mount {project_id} cannot contain both project_folder and path")
        if not projects_root:
            raise ConfigurationError(f"Resource mount {project_id} requires the configured Paratext Projects root")
        folder = Path(project_folder)
        if folder.is_absolute() or len(folder.parts) != 1 or folder.name in {".", ".."}:
            raise ConfigurationError(f"Resource mount {project_id} project_folder must be one direct subfolder name")
        resolved = (Path(projects_root) / folder).resolve()
        return str(resolved), {
            "path": str(resolved),
            "project_folder": project_folder,
            "access_mode": access_mode,
        }
    if not explicit_path:
        raise ConfigurationError(f"Resource mount {project_id} requires project_folder or path")
    mount_path = _absolute_directory(explicit_path, f"resource mount for {project_id}")
    return mount_path, {"path": mount_path, "access_mode": access_mode}


def load_resource_mount_state(root: Path) -> dict[str, Any]:
    """Load the one Projects root, project mounts, and optional machine-local base-VRS root."""
    path = mounts_path(root)
    if not path.is_file():
        return {
            "schema_version": SCHEMA_VERSION,
            "projects_root": None,
            "mounts": {},
            "base_vrs_root": None,
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Invalid resource mounts file: {path}: {exc}") from exc
    if not isinstance(raw, dict) or str(raw.get("schema_version")) != SCHEMA_VERSION:
        raise ConfigurationError(f"Unsupported resource mounts file: {path}")

    root_value = raw.get("projects_root")
    projects_root = None if root_value in (None, "") else _absolute_directory(str(root_value), "projects_root")
    mounts = raw.get("mounts", {})
    if not isinstance(mounts, dict):
        raise ConfigurationError("resource mounts must be a mapping")
    result: dict[str, dict[str, str]] = {}
    for project_id, value in mounts.items():
        if not isinstance(project_id, str) or not isinstance(value, dict):
            raise ConfigurationError("resource mount entries must be project-ID mappings")
        _resolved, normalized = _resolve_mount(
            project_id=project_id,
            value=value,
            projects_root=projects_root,
        )
        result[project_id] = normalized
    base = raw.get("base_vrs_root")
    base_value = None if base in (None, "") else _absolute_directory(str(base), "base_vrs_root")
    return {
        "schema_version": SCHEMA_VERSION,
        "projects_root": projects_root,
        "mounts": result,
        "base_vrs_root": base_value,
    }


def load_resource_mounts(root: Path) -> dict[str, dict[str, str]]:
    """Return external project mappings with resolved absolute paths and access modes."""
    return dict(load_resource_mount_state(root)["mounts"])


def configured_projects_root(root: Path) -> str | None:
    """Return the one configured Paratext/PTLite Projects root, if present."""
    return load_resource_mount_state(root).get("projects_root")


def discover_project_folders(project_root: Path) -> tuple[str, ...]:
    """Return immediate subfolders containing a valid Paratext ``settings.xml`` sentinel."""
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise ValidationError(f"Paratext/PTLite project root not found: {root}", code="PROJECT_ROOT_NOT_FOUND")
    found: list[str] = []
    from .paratext_catalog import parse_settings_xml

    for child in sorted((item for item in root.iterdir() if item.is_dir()), key=lambda item: item.name.casefold()):
        settings = child / "settings.xml"
        if not settings.is_file():
            continue
        try:
            parse_settings_xml(settings)
        except ValidationError:
            continue
        found.append(child.name)
    return tuple(found)


def apply_resource_mounts(raw: dict[str, Any], root: Path) -> dict[str, Any]:
    """Overlay machine-local project locations and permissions onto parsed settings in memory."""
    state = load_resource_mount_state(root)
    projects = raw.get("projects")
    if isinstance(projects, dict):
        for project_id, mount in state["mounts"].items():
            item = projects.get(project_id)
            if isinstance(item, dict):
                item["external_path"] = mount["path"]
                item["external_access_mode"] = mount["access_mode"]
    paths = raw.get("paths")
    if isinstance(paths, dict):
        if state.get("base_vrs_root"):
            paths["base_vrs_root"] = state["base_vrs_root"]
        elif state.get("projects_root"):
            # The Paratext Projects root is the machine-local default base-VRS root. An explicit
            # base_vrs_root override remains independent and is never overwritten by root changes.
            paths["base_vrs_root"] = state["projects_root"]
    return raw


def _persisted_state(state: dict[str, Any]) -> dict[str, Any]:
    """Remove resolved root-relative paths before persisting machine-local bindings."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "projects_root": state.get("projects_root"),
        "mounts": {},
        "base_vrs_root": state.get("base_vrs_root"),
    }
    for project_id, mount in dict(state.get("mounts", {})).items():
        item = dict(mount)
        if item.get("project_folder"):
            payload["mounts"][project_id] = {
                "project_folder": item["project_folder"],
                "access_mode": item["access_mode"],
            }
        else:
            payload["mounts"][project_id] = {
                "path": item["path"],
                "access_mode": item["access_mode"],
            }
    return payload


def _write_state(root: Path, state: dict[str, Any]) -> Path:
    """Persist machine-local project locations and invalidate derived Job runtime settings."""
    destination = mounts_path(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, _persisted_state(state))
    invalidate_runtime_settings(root)
    return destination


def set_project_root(
    root: Path,
    *,
    project_root: Path,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Persist the one absolute Paratext/PTLite Projects root and refresh its catalogue."""
    value = Path(normalize_operator_path(str(project_root))).expanduser()
    if not value.is_absolute():
        raise ValidationError("Paratext/PTLite Projects root must be absolute", code="PROJECT_ROOT_PATH_INVALID")
    value = value.resolve()
    if not value.is_dir():
        raise ValidationError(f"Paratext/PTLite Projects root not found: {value}", code="PROJECT_ROOT_NOT_FOUND")
    state = load_resource_mount_state(root)
    state["projects_root"] = str(value)
    destination = _write_state(root, state)
    # Selecting a Projects root immediately builds the persistent discovery catalogue.
    from .paratext_catalog import scan_paratext_projects
    scan_paratext_projects(root, value, full=True, progress=progress)
    return destination


def clear_project_root(root: Path) -> Path:
    """Clear the Projects root only when no root-relative SAGE Project mount depends on it."""
    state = load_resource_mount_state(root)
    dependents = sorted(
        project_id
        for project_id, mount in state["mounts"].items()
        if mount.get("project_folder")
    )
    if dependents:
        raise ValidationError(
            f"Projects root is still used by: {', '.join(dependents)}",
            code="PROJECT_ROOT_IN_USE",
        )
    state["projects_root"] = None
    destination = _write_state(root, state)
    from .paratext_catalog import clear_paratext_catalog
    clear_paratext_catalog(root)
    return destination


def set_resource_mount(
    root: Path,
    *,
    project_id: str,
    external_path: Path | None = None,
    access_mode: str = READ_ONLY_SCRIPTURE,
    project_folder: str | None = None,
) -> Path:
    """Persist one project location using the configured root or explicit <Other location>."""
    mode = access_mode.strip().upper()
    if mode not in EXTERNAL_ACCESS_MODES:
        raise ValidationError(f"Unsupported external access mode: {access_mode}", code="RESOURCE_ACCESS_MODE_INVALID")
    state = load_resource_mount_state(root)
    if project_folder:
        folder = str(project_folder).strip()
        if not state.get("projects_root"):
            raise ValidationError("Paratext/PTLite Projects root is not configured", code="PROJECT_ROOT_NOT_FOUND")
        folder_path = Path(folder)
        if folder_path.is_absolute() or len(folder_path.parts) != 1 or folder in {".", ".."}:
            raise ValidationError("Project folder must be one direct subfolder name", code="RESOURCE_MOUNT_PATH_INVALID")
        resolved = (Path(state["projects_root"]) / folder).resolve()
        if not resolved.is_dir():
            raise ValidationError(f"External Scripture project directory not found: {resolved}", code="RESOURCE_MOUNT_NOT_FOUND")
        state["mounts"][project_id] = {
            "path": str(resolved),
            "project_folder": folder,
            "access_mode": mode,
        }
        return _write_state(root, state)
    if external_path is None:
        raise ValidationError("External Scripture project path is required", code="RESOURCE_MOUNT_PATH_INVALID")
    path_value = Path(normalize_operator_path(str(external_path))).expanduser()
    if not path_value.is_absolute():
        raise ValidationError("External Scripture project path must be absolute", code="RESOURCE_MOUNT_PATH_INVALID")
    path_value = path_value.resolve()
    if not path_value.is_dir():
        raise ValidationError(f"External Scripture project directory not found: {path_value}", code="RESOURCE_MOUNT_NOT_FOUND")
    state["mounts"][project_id] = {"path": str(path_value), "access_mode": mode}
    return _write_state(root, state)


def remove_resource_mount(root: Path, *, project_id: str) -> Path:
    """Remove one operator project mapping and invalidate derived Job runtime settings."""
    state = load_resource_mount_state(root)
    state["mounts"].pop(project_id, None)
    return _write_state(root, state)


def set_base_vrs_root(root: Path, *, base_vrs_root: Path) -> Path:
    """Persist the absolute root from which configured base VRS files may be read."""
    value = Path(normalize_operator_path(str(base_vrs_root))).expanduser()
    if not value.is_absolute():
        raise ValidationError("Base VRS root must be absolute", code="BASE_VRS_ROOT_INVALID")
    value = value.resolve()
    if not value.is_dir():
        raise ValidationError(f"Base VRS root directory not found: {value}", code="BASE_VRS_ROOT_NOT_FOUND")
    state = load_resource_mount_state(root)
    state["base_vrs_root"] = str(value)
    return _write_state(root, state)


def clear_base_vrs_root(root: Path) -> Path:
    """Remove the machine-local base-VRS-root override."""
    state = load_resource_mount_state(root)
    state["base_vrs_root"] = None
    return _write_state(root, state)


def invalidate_runtime_settings(root: Path) -> int:
    """Remove derived Job runtime settings so the next controller call rebuilds them."""
    count = 0
    job_state_root = root.resolve() / "jobs"
    for pattern in ("*/*/.sage/runtime.yml", "*/*/.sage/runtime-ecosystem.yml"):
        for path in job_state_root.glob(pattern):
            if path.is_file():
                path.unlink()
                count += 1
    return count
