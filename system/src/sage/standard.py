"""Normative SAGE vocabulary and release metadata loader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import load_json, require_mapping, require_string
from .errors import ConfigurationError


@dataclass(frozen=True)
class SageStandard:
    """Machine-readable release identity and governed vocabularies."""

    version: str
    release_status: str
    public_release_ready: bool
    feature_classifications: dict[str, str]
    operation_states: frozenset[str]
    capability_states: frozenset[str]
    feature_maturity_states: frozenset[str]
    resource_roles: frozenset[str]
    raw: dict[str, Any]


def load_standard(root: Path) -> SageStandard:
    """Load system/config/sage-standard.json and ensure its release identity matches VERSION."""
    data = load_json(root / "system" / "config" / "sage-standard.json")
    release = require_mapping(data.get("release"), "config.sage.release")
    version = require_string(release.get("version"), "config.sage.release.version")
    version_file = (root / "VERSION").read_text(encoding="utf-8").strip()
    if version != version_file:
        raise ConfigurationError(
            f"system/config/sage-standard.json version {version!r} does not match VERSION {version_file!r}"
        )
    public_release_ready = release.get("public_release_ready")
    if not isinstance(public_release_ready, bool):
        raise ConfigurationError("config.sage.release.public_release_ready must be a boolean")
    vocabularies = require_mapping(data.get("vocabularies"), "config.sage.vocabularies")

    def values(name: str) -> frozenset[str]:
        """Return the governed standard values in declaration order."""
        raw = vocabularies.get(name)
        if not isinstance(raw, list) or not raw or any(not isinstance(item, str) for item in raw):
            raise ConfigurationError(f"config.sage.vocabularies.{name} must be a nonempty string list")
        return frozenset(item.strip().upper() for item in raw)

    feature_maturity_states = values("feature_maturity_states")
    raw_feature_classifications = require_mapping(
        release.get("feature_classifications"),
        "config.sage.release.feature_classifications",
    )
    feature_classifications = {
        require_string(name, "config.sage.release.feature_classifications key").strip().lower():
        require_string(value, f"config.sage.release.feature_classifications.{name}").upper()
        for name, value in raw_feature_classifications.items()
    }
    unsupported_classifications = sorted(set(feature_classifications.values()) - feature_maturity_states)
    if unsupported_classifications:
        raise ConfigurationError(
            "config.sage.release.feature_classifications contains unsupported states: "
            + ", ".join(unsupported_classifications)
        )

    return SageStandard(
        version=version,
        release_status=require_string(
            release.get("status"),
            "config.sage.release.status",
        ).upper(),
        public_release_ready=public_release_ready,
        feature_classifications=feature_classifications,
        operation_states=values("operation_states"),
        capability_states=values("capability_states"),
        feature_maturity_states=feature_maturity_states,
        resource_roles=values("resource_roles"),
        raw=data,
    )
