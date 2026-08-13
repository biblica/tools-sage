"""Normative SAGE vocabulary and release metadata loader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import load_yaml, require_mapping, require_string
from .errors import ConfigurationError


@dataclass(frozen=True)
class SageStandard:
    """Machine-readable release identity and governed vocabularies."""

    version: str
    release_status: str
    operation_states: frozenset[str]
    capability_states: frozenset[str]
    resource_roles: frozenset[str]
    raw: dict[str, Any]


def load_standard(root: Path) -> SageStandard:
    """Load meta/sage.yml and ensure its release identity matches VERSION."""
    data = load_yaml(root / "meta" / "sage.yml")
    release = require_mapping(data.get("release"), "meta.sage.release")
    version = require_string(release.get("version"), "meta.sage.release.version")
    version_file = (root / "VERSION").read_text(encoding="utf-8").strip()
    if version != version_file:
        raise ConfigurationError(
            f"meta/sage.yml version {version!r} does not match VERSION {version_file!r}"
        )
    vocabularies = require_mapping(data.get("vocabularies"), "meta.sage.vocabularies")

    def values(name: str) -> frozenset[str]:
        """Return the governed standard values in declaration order."""
        raw = vocabularies.get(name)
        if not isinstance(raw, list) or not raw or any(not isinstance(item, str) for item in raw):
            raise ConfigurationError(f"meta.sage.vocabularies.{name} must be a nonempty string list")
        return frozenset(item.strip().upper() for item in raw)

    return SageStandard(
        version=version,
        release_status=require_string(
            release.get("status"),
            "meta.sage.release.status",
        ).upper(),
        operation_states=values("operation_states"),
        capability_states=values("capability_states"),
        resource_roles=values("resource_roles"),
        raw=data,
    )
