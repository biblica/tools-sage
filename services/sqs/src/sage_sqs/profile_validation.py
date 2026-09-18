"""Validation helpers for deterministic SQS language evaluation identities."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

PROFILE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))$")
SCRIPT_RE = re.compile(r"^[A-Z][a-z]{3}$")
REGION_RE = re.compile(r"^(?:[A-Z]{2}|[0-9]{3})$")


@dataclass(frozen=True)
class ProfileIssue:
    code: str
    message: str


def validate_profile_id(profile_id: str) -> list[ProfileIssue]:
    if PROFILE_RE.fullmatch(profile_id):
        return []
    return [ProfileIssue("INVALID_PROFILE_ID", f"Unsupported profile identity: {profile_id}")]


def _id_parts(profile_id: str) -> tuple[str | None, str | None]:
    parts = profile_id.split("-")
    if len(parts) == 2:
        return None, parts[1]
    if len(parts) == 3:
        return parts[1], parts[2]
    return None, None


def validate_profile(seed: dict[str, Any]) -> list[ProfileIssue]:
    issues = list(validate_profile_id(str(seed.get("profile_id", ""))))
    identity = seed.get("identity") or {}
    script = str(identity.get("script", ""))
    region = str(identity.get("region", ""))
    if not SCRIPT_RE.fullmatch(script):
        issues.append(ProfileIssue("INVALID_SCRIPT", f"Unsupported script: {script}"))
    if not REGION_RE.fullmatch(region):
        issues.append(ProfileIssue("INVALID_REGION", f"Unsupported region: {region}"))

    id_script, id_region = _id_parts(str(seed.get("profile_id", "")))
    if id_script is not None and id_script != script:
        issues.append(ProfileIssue("PROFILE_SCRIPT_MISMATCH", f"Profile ID script {id_script} != identity script {script}"))
    if id_region is not None and id_region != region:
        issues.append(ProfileIssue("PROFILE_REGION_MISMATCH", f"Profile ID region {id_region} != identity region {region}"))

    tier = seed.get("tier")
    if tier not in (1, 2, 3):
        issues.append(ProfileIssue("INVALID_TIER", f"Unsupported tier: {tier}"))
    if not str(seed.get("cluster", "")).strip():
        issues.append(ProfileIssue("MISSING_CLUSTER", "Profile cluster is required"))

    capabilities = set(seed.get("capabilities") or [])
    expected = {"GRAMMAR_ANALYSIS", "SEMANTIC_REWRITE"}
    if capabilities != expected:
        issues.append(ProfileIssue("INVALID_CAPABILITY_SET", "Profiles must declare both governed capabilities"))
    return issues
