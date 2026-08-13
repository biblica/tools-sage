"""Governed grammar-profile loading and compact evidence-contract compilation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .config import load_yaml, require_mapping, require_string
from .errors import ConfigurationError
from .hashing import sha256_bytes, sha256_file


GRAMMAR_STATUS_VALUES = {"ACTIVE", "PROJECT_REVIEW_REQUIRED", "AI_DRAFTED", "INACTIVE"}
_TARGET_ROLES = {"TARGET", "WIP"}
_PROFILE_REQUIRED = (
    "schema_version", "id", "language", "script", "role", "status",
    "purpose", "owner_role", "last_reviewed",
)
_SCRIPT_RE = re.compile(r"^[A-Z][a-z]{3}$")


@dataclass(frozen=True)
class GrammarProfile:
    """Represent one grammar profile bound to a language and project role."""

    profile_id: str
    language: str
    role: str
    status: str
    purpose: str
    checks: tuple[dict[str, str], ...]
    project_decisions: tuple[dict[str, Any], ...]
    approved_exceptions: tuple[dict[str, Any], ...]
    path: Path
    sha256: str
    raw: dict[str, Any]

    def contract(self) -> dict[str, Any]:
        """Return the complete governed contract routed to relevant analysis tasks."""
        profile = dict(self.raw["profile"])
        return {
            "schema_version": "2.0",
            "profile_id": self.profile_id,
            "language": self.language,
            "script": profile["script"],
            "role": self.role,
            "status": self.status,
            "purpose": self.purpose,
            "owner_role": profile["owner_role"],
            "last_reviewed": profile["last_reviewed"],
            "provenance": dict(self.raw.get("provenance", {})),
            "profile_sha256": self.sha256,
            "governance": dict(self.raw.get("governance", {})),
            "evidence_priority": list(self.raw.get("evidence_priority", [])),
            "normalization": dict(self.raw.get("normalization", {})),
            "rules": list(self.checks),
            "usage": dict(self.raw.get("usage", {})),
            "finding_requirements": list(self.raw.get("finding_requirements", [])),
            "restrictions": list(self.raw.get("restrictions", [])),
            "project_decisions": list(self.project_decisions),
            "approved_exceptions": list(self.approved_exceptions),
            "finding_requirement": (
                "A project-grammar finding must cite one or more rule IDs. "
                "A general meaning finding must identify its non-grammar category explicitly."
            ),
        }


def _list_of_mappings(value: Any, label: str) -> tuple[dict[str, Any], ...]:
    """Require a list of mapping objects for one grammar-profile section."""
    if value in (None, ""):
        return ()
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ConfigurationError(f"{label} must be a list of mappings")
    return tuple(dict(item) for item in value)


def _string_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    """Require one list containing only nonempty strings."""
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigurationError(f"{label} must be a list of nonempty strings")
    result = [item.strip() for item in value]
    if not result and not allow_empty:
        raise ConfigurationError(f"{label} must not be empty")
    return result


def _validate_profile_shape(raw: dict[str, Any], path: Path) -> dict[str, Any]:
    """Enforce the executable grammar-profile schema before semantic compilation."""
    profile = require_mapping(raw.get("profile"), f"grammar profile {path}.profile")
    missing = [key for key in _PROFILE_REQUIRED if key not in profile]
    if missing:
        raise ConfigurationError(
            f"Grammar profile {path} is missing required profile fields: {', '.join(missing)}"
        )
    for key in _PROFILE_REQUIRED:
        if key == "last_reviewed":
            value = profile.get(key)
            if value is not None:
                reviewed = require_string(value, f"grammar profile {path}.profile.{key}")
                try:
                    date.fromisoformat(reviewed)
                except ValueError as exc:
                    raise ConfigurationError(
                        f"Grammar profile {path}.profile.last_reviewed must be a valid ISO calendar date YYYY-MM-DD"
                    ) from exc
            continue
        require_string(profile.get(key), f"grammar profile {path}.profile.{key}")
    if profile["schema_version"] != "2.0":
        raise ConfigurationError(
            f"Grammar profile {path} schema_version must be '2.0'"
        )
    if not _SCRIPT_RE.fullmatch(profile["script"]):
        raise ConfigurationError(
            f"Grammar profile {path}.profile.script must be one ISO 15924-style four-letter code"
        )
    checks = raw.get("checks")
    if not isinstance(checks, list):
        raise ConfigurationError(f"Grammar profile {path}.checks must be a list")
    if "normalization" in raw and not isinstance(raw["normalization"], dict):
        raise ConfigurationError(f"Grammar profile {path}.normalization must be a mapping")
    for key in ("project_decisions", "approved_exceptions"):
        if key in raw:
            _list_of_mappings(raw[key], f"grammar profile {path}.{key}")
    status = str(profile["status"]).upper()
    if status == "AI_DRAFTED":
        provenance = require_mapping(raw.get("provenance"), f"grammar profile {path}.provenance")
        if require_string(provenance.get("type"), f"grammar profile {path}.provenance.type") != "LLM_GENERAL_LANGUAGE_KNOWLEDGE":
            raise ConfigurationError(
                f"AI_DRAFTED grammar profile {path} provenance.type must be LLM_GENERAL_LANGUAGE_KNOWLEDGE"
            )
        require_string(provenance.get("provider"), f"grammar profile {path}.provenance.provider")
        if "model" in provenance and provenance["model"] not in (None, ""):
            require_string(provenance.get("model"), f"grammar profile {path}.provenance.model")
        if provenance.get("project_validated") is not False:
            raise ConfigurationError(
                f"AI_DRAFTED grammar profile {path} provenance.project_validated must be false"
            )
    elif "provenance" in raw and not isinstance(raw["provenance"], dict):
        raise ConfigurationError(f"Grammar profile {path}.provenance must be a mapping")
    return dict(profile)


def load_grammar_profile(
    path: Path,
    *,
    expected_profile_id: str | None = None,
    expected_language: str | None = None,
    expected_role: str | None = None,
) -> GrammarProfile:
    """Load one normalised SAGE grammar profile and validate its full executable schema."""
    raw = load_yaml(path)
    profile = _validate_profile_shape(raw, path)
    profile_id = require_string(profile.get("id"), f"grammar profile {path}.profile.id")
    language = require_string(profile.get("language"), f"grammar profile {path}.profile.language")
    role = require_string(profile.get("role"), f"grammar profile {path}.profile.role").upper()
    status = require_string(profile.get("status"), f"grammar profile {path}.profile.status").upper()
    if status not in GRAMMAR_STATUS_VALUES:
        raise ConfigurationError(f"Grammar profile {profile_id} has unsupported status {status!r}")
    if expected_profile_id and profile_id != expected_profile_id:
        raise ConfigurationError(
            f"Grammar profile ID {profile_id!r} does not match registry ID {expected_profile_id!r}"
        )
    if expected_language and language.casefold() != expected_language.casefold():
        raise ConfigurationError(
            f"Grammar profile {profile_id} language {language!r} does not match project language {expected_language!r}"
        )
    if expected_role and role != expected_role.upper():
        raise ConfigurationError(
            f"Grammar profile {profile_id} role {role!r} does not match binding role {expected_role.upper()!r}"
        )
    checks_raw = raw["checks"]
    if any(not isinstance(item, dict) for item in checks_raw):
        raise ConfigurationError(f"Grammar profile {profile_id}.checks must be a list of mappings")
    checks: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(checks_raw, start=1):
        rule_id = require_string(item.get("id"), f"{profile_id}.checks[{index}].id")
        if rule_id in seen_ids:
            raise ConfigurationError(f"Duplicate grammar rule ID in {profile_id}: {rule_id}")
        seen_ids.add(rule_id)
        checks.append({
            "rule_id": rule_id,
            "dimension": require_string(item.get("dimension"), f"{profile_id}.checks[{index}].dimension"),
            "review": require_string(item.get("review"), f"{profile_id}.checks[{index}].review"),
            "caution": require_string(item.get("caution"), f"{profile_id}.checks[{index}].caution"),
        })
    if not checks:
        raise ConfigurationError(f"Grammar profile {profile_id} has no checks")
    if role in _TARGET_ROLES:
        if len(checks) < 8:
            raise ConfigurationError(f"Target grammar profile {profile_id} must contain at least 8 substantive checks")
        governance = require_mapping(raw.get("governance"), f"{profile_id}.governance")
        if not governance:
            raise ConfigurationError(f"Target grammar profile {profile_id}.governance must not be empty")
        _string_list(raw.get("evidence_priority"), f"{profile_id}.evidence_priority")
        usage = require_mapping(raw.get("usage"), f"{profile_id}.usage")
        if not usage:
            raise ConfigurationError(f"Target grammar profile {profile_id}.usage must not be empty")
        _string_list(raw.get("finding_requirements"), f"{profile_id}.finding_requirements")
        _string_list(raw.get("restrictions"), f"{profile_id}.restrictions")
    else:
        for key in ("evidence_priority", "finding_requirements", "restrictions"):
            if key in raw:
                _string_list(raw[key], f"{profile_id}.{key}", allow_empty=True)
        for key in ("governance", "usage"):
            if key in raw and not isinstance(raw[key], dict):
                raise ConfigurationError(f"{profile_id}.{key} must be a mapping")
    return GrammarProfile(
        profile_id=profile_id,
        language=language,
        role=role,
        status=status,
        purpose=require_string(profile.get("purpose"), f"grammar profile {profile_id}.profile.purpose"),
        checks=tuple(checks),
        project_decisions=_list_of_mappings(raw.get("project_decisions"), f"{profile_id}.project_decisions"),
        approved_exceptions=_list_of_mappings(raw.get("approved_exceptions"), f"{profile_id}.approved_exceptions"),
        path=path.resolve(),
        sha256=sha256_file(path),
        raw=raw,
    )


def compile_grammar_contract(profile: GrammarProfile, cache_root: Path) -> dict[str, Any]:
    """Write and return a content-addressed compact grammar contract."""
    contract = profile.contract()
    key = sha256_bytes((profile.sha256 + "\0" + profile.profile_id + "\0" + profile.language + "\0" + profile.role).encode("utf-8"))[:24]
    path = cache_root / "grammar" / f"{profile.profile_id}-{key}.contract.json"
    if not path.exists():
        atomic_write_json(path, contract)
    return {**contract, "cache": str(path)}
