"""Load SAGE YAML configuration with strict structural checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigurationError


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


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    """Return a mapping or raise a configuration error with a useful label."""
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be a mapping")
    return value


def require_string(value: Any, label: str, *, allow_empty: bool = False) -> str:
    """Return a normalised string and reject absent values."""
    if not isinstance(value, str):
        raise ConfigurationError(f"{label} must be a string")
    result = value.strip()
    if not result and not allow_empty:
        raise ConfigurationError(f"{label} must not be empty")
    return result


def resolve_workspace_path(root: Path, value: str, label: str) -> Path:
    """Resolve a workspace path and require it to remain under the SAGE root."""
    raw = Path(value)
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ConfigurationError(f"{label} must remain inside the SAGE workspace: {value}") from exc
    return candidate
