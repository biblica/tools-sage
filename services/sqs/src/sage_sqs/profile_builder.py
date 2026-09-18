"""Load SQS language seeds and build review-required evaluation identities."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .domain import LanguageProfile
from .profile_validation import ProfileIssue, validate_profile


@dataclass(frozen=True)
class ProfileDraft:
    profile: LanguageProfile
    issues: tuple[ProfileIssue, ...]

    def __getattr__(self, name: str) -> Any:
        return getattr(self.profile, name)


def build_profile(seed: dict[str, Any], sage_source: object | None = None) -> ProfileDraft:
    del sage_source  # reserved for a future direct SAGE-source correlation pass
    identity = seed.get("identity") or {}
    issues = list(validate_profile(seed))
    build = seed.get("profile_build") or {}
    if not build.get("sage_profile_available_in_reference_snapshot", False):
        issues.append(ProfileIssue(
            "SAGE_0.02ALPHA1_GRAMMAR_PROFILE_ABSENT",
            "No exact SAGE 0.02a1 grammar profile was present in the reference snapshot",
        ))
    if build.get("evaluation_pack_state") not in {"READY", "BUILD_REQUIRED"}:
        issues.append(ProfileIssue("INVALID_EVALUATION_PACK_STATE", "Unsupported evaluation pack state"))
    if build.get("evaluation_pack_state") == "BUILD_REQUIRED":
        issues.append(ProfileIssue("EVALUATION_PACK_BUILD_REQUIRED", "Exact evaluation pack still requires build/review"))

    for raw in (seed.get("admin_review") or {}).get("issues") or []:
        if isinstance(raw, dict):
            issues.append(ProfileIssue(str(raw.get("code", "SEED_REVIEW_ISSUE")), str(raw.get("message", "Seed review issue"))))
        else:
            issues.append(ProfileIssue("SEED_REVIEW_ISSUE", str(raw)))

    profile = LanguageProfile(
        profile_id=str(seed["profile_id"]),
        display_name=str(seed.get("display_name") or seed["profile_id"]),
        status="REVIEW_REQUIRED",
        revision=int(seed.get("revision", 1)),
        tier=int(seed["tier"]),
        cluster=str(seed["cluster"]),
        iso_639_1=str(identity.get("iso_639_1", "")),
        iso_639_3=str(identity.get("iso_639_3", "")),
        script=str(identity.get("script", "")),
        region=str(identity.get("region", "")),
    )
    return ProfileDraft(profile=profile, issues=tuple(issues))


def load_seed_profiles(path: str | Path) -> list[ProfileDraft]:
    root = Path(path)
    rows = [build_profile(yaml.safe_load(file.read_text(encoding="utf-8"))) for file in sorted(root.glob("*.yml"))]
    ids = [row.profile_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate profile_id in SQS seed catalog")
    identities = [row.evaluation_identity_sha256 for row in rows]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate SQS evaluation identity in seed catalog")
    return rows
