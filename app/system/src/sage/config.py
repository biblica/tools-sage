"""Load SAGE YAML configuration with strict structural checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigurationError
from .storage import StorageError, resolve_declared_path


def load_yaml(path: Path) -> dict[str, Any]:
    """Load one UTF-8 YAML mapping and reject invalid or non-mapping documents."""
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConfigurationError(f"Configuration is not valid UTF-8: {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError(f"YAML root must be a mapping: {path}")
    return data


def load_json(path: Path) -> dict[str, Any]:
    """Load one UTF-8 JSON mapping and reject invalid or non-mapping documents."""
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConfigurationError(f"Configuration is not valid UTF-8: {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError(f"JSON root must be a mapping: {path}")
    return data


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    """Return a mapping or raise a configuration error with a useful label."""
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be a mapping")
    return value


def require_string(value: Any, label: str, *, allow_empty: bool = False) -> str:
    """Return a normalized string and reject absent values."""
    if not isinstance(value, str):
        raise ConfigurationError(f"{label} must be a string")
    result = value.strip()
    if not result and not allow_empty:
        raise ConfigurationError(f"{label} must not be empty")
    return result


def resolve_workspace_path(root: Path, value: str, label: str) -> Path:
    """Resolve a core or governed data path through the canonical storage contract."""
    try:
        return resolve_declared_path(root, value, label)
    except StorageError as exc:
        raise ConfigurationError(str(exc)) from exc
