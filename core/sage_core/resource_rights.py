"""Machine-readable Scripture resource provenance and rights validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .atomic import atomic_write_json, atomic_write_text
from .errors import ValidationError
from .registry import EcosystemConfig
from .state import utc_now

RIGHTS_STATUSES = {"CONFIRMED", "RESTRICTED", "NOT_APPLICABLE_GENERATED", "UNKNOWN"}
_REQUIRED_PROVENANCE = (
    "source_name",
    "source_version",
    "source_archive_sha256",
    "import_authority_id",
    "imported_utc",
)
_REQUIRED_RIGHTS = (
    "status",
    "copyright_holder",
    "license_identifier",
    "authority_record_id",
    "import_authorized",
    "redistribution_authorized",
    "distribution_scope",
    "reviewed_utc",
)


def _load_yaml_object(path: Path) -> dict[str, Any]:
    """Load one metadata document as a mapping."""
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValidationError(f"Invalid resource metadata {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"Resource metadata must contain one mapping: {path}")
    return dict(value)


def _missing_mapping_fields(value: Any, prefix: str, fields: tuple[str, ...]) -> list[str]:
    """Return required dotted fields missing from one mapping."""
    if not isinstance(value, dict):
        return [prefix]
    missing: list[str] = []
    for field in fields:
        item = value.get(field)
        if item is None or (isinstance(item, str) and not item.strip()):
            missing.append(f"{prefix}.{field}")
    return missing


def validate_resource_rights(
    config: EcosystemConfig,
    *,
    metadata_root: Path,
    write_report: bool = True,
) -> dict[str, Any]:
    """Validate exact per-project provenance and rights records without inventing authority."""
    root = metadata_root.expanduser().resolve()
    if not root.is_dir():
        raise ValidationError(f"Resource metadata directory does not exist: {root}")
    projects_root = root / "projects" if (root / "projects").is_dir() else root
    configured_ids = sorted(project_id for project_id, project in config.projects.items() if project.enabled)
    results: list[dict[str, Any]] = []
    blocking = 0
    warnings = 0
    for project_id in configured_ids:
        path = projects_root / f"{project_id}.yml"
        errors: list[dict[str, str]] = []
        project_warnings: list[dict[str, str]] = []
        record: dict[str, Any] = {}
        if not path.is_file():
            errors.append({"code": "RESOURCE_METADATA_MISSING", "field": "file"})
        else:
            record = _load_yaml_object(path)
            if record.get("schema_version") != "1.0":
                errors.append({"code": "RESOURCE_METADATA_SCHEMA_INVALID", "field": "schema_version"})
            if str(record.get("project_id", "")) != project_id:
                errors.append({"code": "RESOURCE_PROJECT_ID_MISMATCH", "field": "project_id"})
            for field in _missing_mapping_fields(record.get("provenance"), "provenance", _REQUIRED_PROVENANCE):
                errors.append({"code": "RESOURCE_PROVENANCE_FIELD_MISSING", "field": field})
            rights = record.get("rights")
            for field in _missing_mapping_fields(rights, "rights", _REQUIRED_RIGHTS):
                errors.append({"code": "RESOURCE_RIGHTS_FIELD_MISSING", "field": field})
            if isinstance(rights, dict):
                status = str(rights.get("status", "")).upper()
                if status and status not in RIGHTS_STATUSES:
                    errors.append({"code": "RESOURCE_RIGHTS_STATUS_INVALID", "field": "rights.status"})
                generated = config.project(project_id).kind == "GENERATED_SCRIPTURE"
                if generated:
                    if status != "NOT_APPLICABLE_GENERATED":
                        errors.append({"code": "GENERATED_RESOURCE_RIGHTS_STATUS_INVALID", "field": "rights.status"})
                    if not str(rights.get("generation_authority_record_id", "")).strip():
                        errors.append({"code": "GENERATION_AUTHORITY_MISSING", "field": "rights.generation_authority_record_id"})
                elif status == "NOT_APPLICABLE_GENERATED":
                    errors.append({"code": "RESOURCE_RIGHTS_STATUS_INVALID", "field": "rights.status"})
                if rights.get("import_authorized") is not True:
                    errors.append({"code": "RESOURCE_IMPORT_NOT_AUTHORIZED", "field": "rights.import_authorized"})
                if rights.get("redistribution_authorized") is not True:
                    errors.append({"code": "RESOURCE_REDISTRIBUTION_NOT_AUTHORIZED", "field": "rights.redistribution_authorized"})
                if status in {"UNKNOWN", "RESTRICTED"}:
                    project_warnings.append({"code": "RESOURCE_RIGHTS_ATTENTION", "field": "rights.status"})
        status = "BLOCKED" if errors else ("READY_WITH_WARNINGS" if project_warnings else "READY")
        blocking += int(bool(errors))
        warnings += len(project_warnings)
        results.append(
            {
                "project_id": project_id,
                "status": status,
                "metadata_path": str(path),
                "errors": errors,
                "warnings": project_warnings,
            }
        )
    extras = sorted(
        path.stem
        for path in projects_root.glob("*.yml")
        if path.stem not in configured_ids
    )
    report = {
        "schema_version": "1.0",
        "status": "BLOCKED" if blocking else ("READY_WITH_WARNINGS" if warnings else "READY"),
        "metadata_root": str(root),
        "configured_projects": len(configured_ids),
        "blocking_projects": blocking,
        "warning_count": warnings,
        "extra_metadata_projects": extras,
        "projects": results,
        "validated_utc": utc_now(),
    }
    if write_report:
        report_root = config.workspace_data_root / "sage" / "governance"
        json_path = report_root / "resource-rights-validation.json"
        md_path = report_root / "RESOURCE-RIGHTS-VALIDATION.md"
        atomic_write_json(json_path, report)
        lines = [
            "# Resource rights and provenance validation",
            "",
            f"- Status: `{report['status']}`",
            f"- Configured projects: `{report['configured_projects']}`",
            f"- Blocking projects: `{report['blocking_projects']}`",
            "",
            "| Project | Status | Errors | Warnings |",
            "|---|---:|---:|---:|",
        ]
        for row in results:
            lines.append(
                f"| `{row['project_id']}` | `{row['status']}` | `{len(row['errors'])}` | `{len(row['warnings'])}` |"
            )
        lines.append("")
        atomic_write_text(md_path, "\n".join(lines))
        report["report_path"] = str(json_path)
        report["human_report_path"] = str(md_path)
    return report
