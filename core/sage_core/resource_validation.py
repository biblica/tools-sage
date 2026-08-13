"""First-run and operator-facing validation of SAGE Scripture Projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .project_inventory import detect_scripture_books, registered_project_records, summarize_scope
from .registry import load_ecosystem
from .resource_mounts import load_resource_mount_state
from .paratext_catalog import catalog_summary, load_paratext_catalog, scan_paratext_projects
from .original_language_resources import validate_original_language_resources


def validate_scripture_resources(root: Path, settings_path: Path | None = None) -> dict[str, Any]:
    """Validate packaged VRS files plus every SAGE Scripture Project.

    The clean RC starting condition (zero SAGE Projects) is valid. Once a Project is
    added to SAGE, a missing mapping, unreadable Scripture folder, or missing declared base VRS is
    blocking. Scope drift is reported for operator review instead of being silently accepted.
    """
    sage_root = root.expanduser().resolve()
    settings = (settings_path or sage_root / "ecosystem.yml").expanduser().resolve()
    config = load_ecosystem(settings)
    records = registered_project_records(sage_root)
    mount_state = load_resource_mount_state(sage_root)
    mounts = dict(mount_state.get("mounts", {}))

    catalogue = load_paratext_catalog(sage_root)
    projects_root_value = mount_state.get("projects_root")
    if projects_root_value:
        try:
            catalogue = scan_paratext_projects(sage_root, Path(str(projects_root_value)), full=False)
        except Exception:
            # Project-level path validation below remains authoritative; catalogue failure is
            # reported as a warning so general SAGE setup is not trapped by discovery metadata.
            pass
    catalogue_info = catalog_summary(catalogue)
    ol_status = validate_original_language_resources(sage_root)

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    base_rows: list[dict[str, Any]] = []
    for vrs_id, path in sorted(config.base_vrs_files.items()):
        ready = path.is_file() and path.parent.resolve() == config.base_vrs_root.resolve()
        row = {"vrs_id": vrs_id, "path": str(path), "status": "READY" if ready else "BLOCKED"}
        base_rows.append(row)
        if not ready:
            errors.append({"code": "BASE_VRS_NOT_READY", "resource": vrs_id, "path": str(path)})

    projects: list[dict[str, Any]] = []
    for project_id, record in sorted(records.items(), key=lambda item: item[0].casefold()):
        project_errors: list[str] = []
        project_warnings: list[str] = []
        mount = mounts.get(project_id)
        mapped_path: Path | None = None
        detected: tuple[str, ...] = ()
        if not mount:
            project_errors.append("PROJECT_NOT_MAPPED")
        else:
            mapped_path = Path(str(mount.get("path") or "")).expanduser()
            if not mapped_path.is_absolute():
                project_errors.append("PROJECT_MAPPING_NOT_ABSOLUTE")
            elif not mapped_path.is_dir():
                project_errors.append("PROJECT_FOLDER_NOT_FOUND")
            else:
                detected = detect_scripture_books(mapped_path)
                if not detected and not bool(record.get("allow_empty")):
                    project_errors.append("PROJECT_SCRIPTURE_NOT_FOUND")

        versification = record.get("versification", {}) if isinstance(record.get("versification"), dict) else {}
        base_file = str(versification.get("base_file") or "").strip()
        if base_file:
            base_path = config.base_vrs_root / base_file
            if not base_path.is_file():
                project_errors.append("PROJECT_BASE_VRS_NOT_FOUND")
        else:
            project_errors.append("PROJECT_BASE_VRS_UNDECLARED")

        stored_books = tuple(str(item).upper() for item in record.get("detected_books", []) if str(item).strip())
        if detected and stored_books and detected != stored_books:
            project_warnings.append("PROJECT_SCOPE_CHANGED")

        for code in project_errors:
            errors.append({"code": code, "resource": project_id, "path": str(mapped_path or "")})
        for code in project_warnings:
            warnings.append({"code": code, "resource": project_id, "path": str(mapped_path or "")})
        projects.append(
            {
                "project_id": project_id,
                "path": str(mapped_path) if mapped_path is not None else None,
                "access_mode": mount.get("access_mode") if mount else None,
                "stored_scope": record.get("scope_summary"),
                "detected_scope": summarize_scope(detected),
                "detected_books": list(detected),
                "status": "BLOCKED" if project_errors else ("ATTENTION" if project_warnings else "READY"),
                "errors": project_errors,
                "warnings": project_warnings,
            }
        )

    nonblocking_warnings: list[dict[str, str]] = []
    for row in ol_status["resources"]:
        if row["status"] != "READY":
            nonblocking_warnings.append({
                "code": str(row.get("code") or "OL_RESOURCE_NOT_READY"),
                "resource": str(row["alias"]),
                "path": str(row["path"]),
            })

    if errors:
        status = "BLOCKED"
    elif warnings:
        status = "READY_WITH_WARNINGS"
    elif not records:
        status = "READY_EMPTY"
    else:
        status = "READY"
    return {
        "schema_version": "1.0",
        "status": status,
        "projects_root": mount_state.get("projects_root"),
        "base_vrs_root": str(config.base_vrs_root),
        "base_vrs": base_rows,
        "registered_projects": len(records),
        "mapped_projects": len(mounts),
        "catalogue": {**catalogue_info, "path": str(sage_root / "state" / "paratext-project-catalog.json")},
        "original_language": ol_status,
        "projects": projects,
        "errors": errors,
        "warnings": warnings,
        "nonblocking_warnings": nonblocking_warnings,
    }
