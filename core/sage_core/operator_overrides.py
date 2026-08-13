"""Governed Operator overrides produced by interactive INIT remediation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

import yaml

from .atomic import atomic_write_text
from .config import load_yaml, require_mapping
from .errors import ConfigurationError
from .hashing import sha256_file

OVERRIDE_SCHEMA_VERSION = "1.0"
OVERRIDE_FILENAME = "operator-overrides.yml"

_ALLOWED_PROJECT_FIELDS = {
    "enabled",
    "content_state",
    "language",
    "scope",
    "versification",
}
_ALLOWED_LANGUAGE_FIELDS = {"code", "profile", "variant"}
_ALLOWED_SCOPE_FIELDS = {"testament", "canon", "expected_books", "roles"}
_ALLOWED_VRS_FIELDS = {"base_file", "custom_file"}


def operator_override_path(settings_path: Path, raw: dict[str, Any] | None = None) -> Path:
    """Return the deterministic sidecar path for one settings file."""
    settings_path = settings_path.resolve()
    data = raw if raw is not None else load_yaml(settings_path)
    paths = data.get("paths", {}) if isinstance(data, dict) else {}
    value = paths.get("workspace_data_root", "workspace-data") if isinstance(paths, dict) else "workspace-data"
    root = Path(str(value))
    if not root.is_absolute():
        root = settings_path.parent / root
    return root.resolve() / "sage" / "init" / OVERRIDE_FILENAME


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge confirmed effective settings while preserving unrelated source values."""
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _reject_unknown_fields(value: dict[str, Any], allowed: set[str], label: str) -> None:
    """Reject sidecar keys outside the explicit Operator-remediation allowlist."""
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ConfigurationError(
            f"Operator overrides contain unsupported {label} fields: {', '.join(unknown)}",
            code="OPERATOR_OVERRIDE_FIELD_NOT_ALLOWED",
        )


def validate_override_tree(base: dict[str, Any], overrides: dict[str, Any]) -> None:
    """Restrict INIT overrides to explicit, Operator-reviewable settings."""
    _reject_unknown_fields(overrides, {"ecosystem", "projects"}, "top-level")
    ecosystem = overrides.get("ecosystem", {})
    if ecosystem:
        ecosystem = require_mapping(ecosystem, "operator overrides ecosystem")
        _reject_unknown_fields(ecosystem, {"configured"}, "ecosystem")
        if "configured" in ecosystem and not isinstance(ecosystem["configured"], bool):
            raise ConfigurationError(
                "operator overrides ecosystem.configured must be boolean",
                code="OPERATOR_OVERRIDE_INVALID_VALUE",
            )
    projects = overrides.get("projects", {})
    if not projects:
        return
    projects = require_mapping(projects, "operator overrides projects")
    base_projects = require_mapping(base.get("projects", {}), "projects")
    unknown_projects = sorted(set(projects) - set(base_projects))
    if unknown_projects:
        raise ConfigurationError(
            "Operator overrides reference unknown projects: " + ", ".join(unknown_projects),
            code="OPERATOR_OVERRIDE_UNKNOWN_PROJECT",
        )
    for project_id, raw_project in projects.items():
        project = require_mapping(raw_project, f"operator overrides projects.{project_id}")
        _reject_unknown_fields(project, _ALLOWED_PROJECT_FIELDS, f"projects.{project_id}")
        if "enabled" in project and not isinstance(project["enabled"], bool):
            raise ConfigurationError(
                f"operator overrides projects.{project_id}.enabled must be boolean",
                code="OPERATOR_OVERRIDE_INVALID_VALUE",
            )
        if "content_state" in project and not isinstance(project["content_state"], str):
            raise ConfigurationError(
                f"operator overrides projects.{project_id}.content_state must be a string",
                code="OPERATOR_OVERRIDE_INVALID_VALUE",
            )
        for key, allowed in (
            ("language", _ALLOWED_LANGUAGE_FIELDS),
            ("scope", _ALLOWED_SCOPE_FIELDS),
            ("versification", _ALLOWED_VRS_FIELDS),
        ):
            if key in project:
                nested = require_mapping(project[key], f"operator overrides projects.{project_id}.{key}")
                _reject_unknown_fields(nested, allowed, f"projects.{project_id}.{key}")


def load_effective_settings(
    settings_path: Path,
) -> tuple[dict[str, Any], Path | None, tuple[dict[str, Any], ...]]:
    """Load source settings plus a fresh, governed INIT sidecar when present."""
    settings_path = settings_path.resolve()
    source = load_yaml(settings_path)
    sidecar = operator_override_path(settings_path, source)
    if not sidecar.is_file():
        return source, None, ()
    payload = load_yaml(sidecar)
    schema = str(payload.get("schema_version", "")).strip()
    if schema != OVERRIDE_SCHEMA_VERSION:
        raise ConfigurationError(
            f"Unsupported operator override schema {schema!r}; expected {OVERRIDE_SCHEMA_VERSION!r}",
            code="OPERATOR_OVERRIDE_SCHEMA_UNSUPPORTED",
        )
    expected_hash = str(payload.get("source_settings_sha256", "")).strip()
    actual_hash = sha256_file(settings_path)
    if expected_hash != actual_hash:
        raise ConfigurationError(
            "Operator overrides are stale because the selected settings file changed",
            code="OPERATOR_OVERRIDE_STALE",
            next_action="Run `./sage project init` to review and regenerate operator overrides.",
            details={
                "override_path": str(sidecar),
                "expected_source_sha256": expected_hash,
                "actual_source_sha256": actual_hash,
            },
        )
    overrides = require_mapping(payload.get("overrides", {}), "operator overrides")
    validate_override_tree(source, overrides)
    resolutions_raw = payload.get("operator_resolutions", []) or []
    if not isinstance(resolutions_raw, list) or any(not isinstance(item, dict) for item in resolutions_raw):
        raise ConfigurationError(
            "operator_resolutions must be a list of mappings",
            code="OPERATOR_OVERRIDE_INVALID_HISTORY",
        )
    return _merge(source, overrides), sidecar, tuple(deepcopy(resolutions_raw))


def write_operator_overrides(
    settings_path: Path,
    overrides: dict[str, Any],
    resolutions: Iterable[dict[str, Any]],
) -> Path:
    """Persist explicit Operator choices without rewriting source settings."""
    settings_path = settings_path.resolve()
    source = load_yaml(settings_path)
    validate_override_tree(source, overrides)
    path = operator_override_path(settings_path, source)
    payload = {
        "schema_version": OVERRIDE_SCHEMA_VERSION,
        "source_settings": str(settings_path),
        "source_settings_sha256": sha256_file(settings_path),
        "overrides": overrides,
        "operator_resolutions": list(resolutions),
    }
    atomic_write_text(
        path,
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
    )
    return path


def clear_operator_overrides(settings_path: Path) -> Path | None:
    """Remove only the governed INIT sidecar, preserving source settings."""
    settings_path = settings_path.resolve()
    source = load_yaml(settings_path)
    path = operator_override_path(settings_path, source)
    if path.exists():
        path.unlink()
        return path
    return None
