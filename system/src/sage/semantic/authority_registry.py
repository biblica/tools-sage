"""Governed semantic-authority source registry loading and lookup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import load_json, require_mapping, require_string
from ..errors import ConfigurationError, ValidationError
from ..registry import EcosystemConfig


@dataclass(frozen=True)
class AuthoritySourceSpec:
    """One governed semantic classification or traversal authority source."""

    source_key: str
    authority_type: str
    selection_key: str
    storage_directory: str
    default_source_id: str
    content_file: str
    expected_format: str
    translation_authority: bool
    raw: dict[str, Any]


def load_authority_sources(config: EcosystemConfig) -> dict[str, AuthoritySourceSpec]:
    """Load and validate the canonical RWC authority-source registry."""
    path = config.root / "system" / "resources" / "rwc" / "authority" / "sources.json"
    raw = load_json(path)
    sources = require_mapping(raw.get("sources"), "authority sources")
    result: dict[str, AuthoritySourceSpec] = {}
    seen_types: set[str] = set()
    seen_selection_keys: set[str] = set()
    for source_key, value in sources.items():
        if not isinstance(source_key, str) or not source_key.strip():
            raise ConfigurationError("Authority source registry keys must be non-empty strings")
        item = require_mapping(value, f"authority sources[{source_key!r}]")
        authority_type = require_string(
            item.get("authority_type"), f"authority sources[{source_key!r}].authority_type"
        ).casefold()
        selection_key = require_string(
            item.get("selection_key"), f"authority sources[{source_key!r}].selection_key"
        )
        storage_directory = require_string(
            item.get("storage_directory"),
            f"authority sources[{source_key!r}].storage_directory",
        )
        default_source_id = require_string(
            item.get("default_source_id"),
            f"authority sources[{source_key!r}].default_source_id",
        )
        content_file = require_string(
            item.get("content_file"), f"authority sources[{source_key!r}].content_file"
        )
        expected_format = require_string(
            item.get("expected_format"), f"authority sources[{source_key!r}].expected_format"
        ).upper()
        translation_authority = item.get("translation_authority")
        if not isinstance(translation_authority, bool):
            raise ConfigurationError(
                f"authority sources[{source_key!r}].translation_authority must be a boolean"
            )
        if authority_type in seen_types:
            raise ConfigurationError(f"Duplicate authority_type in sources.json: {authority_type}")
        if selection_key in seen_selection_keys:
            raise ConfigurationError(f"Duplicate selection_key in sources.json: {selection_key}")
        if "/" in storage_directory or "\\" in storage_directory:
            raise ConfigurationError(
                f"Authority storage_directory must be one path component: {storage_directory}"
            )
        seen_types.add(authority_type)
        seen_selection_keys.add(selection_key)
        result[source_key] = AuthoritySourceSpec(
            source_key=source_key,
            authority_type=authority_type,
            selection_key=selection_key,
            storage_directory=storage_directory,
            default_source_id=default_source_id,
            content_file=content_file,
            expected_format=expected_format,
            translation_authority=translation_authority,
            raw=dict(item),
        )
    if not result:
        raise ConfigurationError("Authority source registry must not be empty")
    return result


def authority_source_for_type(
    config: EcosystemConfig,
    authority_type: str,
) -> AuthoritySourceSpec:
    """Resolve one unique authority source specification by operational type."""
    normalized = str(authority_type).strip().casefold()
    matches = [
        spec for spec in load_authority_sources(config).values() if spec.authority_type == normalized
    ]
    if len(matches) != 1:
        raise ValidationError(
            f"authority_type must resolve to exactly one governed source: {authority_type}"
        )
    return matches[0]
