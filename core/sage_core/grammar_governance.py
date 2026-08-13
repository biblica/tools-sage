"""Operator-facing grammar-profile review registry bound to exact profile content."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .errors import ValidationError
from .grammar import GrammarProfile, load_grammar_profile
from .locking import WorkspaceLock
from .registry import EcosystemConfig
from .state import utc_now

GRAMMAR_REVIEW_DECISIONS = {"APPROVED", "RETURN_FOR_REVISION", "REJECTED"}


def grammar_review_registry_path(config: EcosystemConfig) -> Path:
    """Return the governed exact-profile review registry path."""
    return config.root / "state" / "grammar-profile-reviews.json"


def _read_registry(path: Path) -> list[dict[str, Any]]:
    """Read the review registry, returning an empty list only when absent."""
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid grammar review registry {path}: {exc}") from exc
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValidationError("Grammar review registry must contain a list of objects")
    return [dict(row) for row in value]


def configured_grammar_profiles(config: EcosystemConfig) -> dict[str, GrammarProfile]:
    """Load each unique configured profile under its language/profile selector."""
    result: dict[str, GrammarProfile] = {}
    for language, namespace in sorted(config.language_profiles.items()):
        for variant_id, spec in sorted(namespace.variants.items()):
            profile = load_grammar_profile(
                spec.path,
                expected_profile_id=variant_id,
                expected_language=namespace.profile_language,
                expected_role=spec.role,
            )
            key = f"{profile.language}/{profile.profile_id}"
            if key in result and result[key].path != profile.path:
                raise ValidationError(f"Duplicate configured grammar profile selector: {key}")
            result[key] = profile
    return result


def active_grammar_review(
    config: EcosystemConfig,
    profile: GrammarProfile,
) -> dict[str, Any] | None:
    """Return an active decision only when it binds the exact current profile hash."""
    key = f"{profile.language}/{profile.profile_id}"
    records = _read_registry(grammar_review_registry_path(config))
    for row in reversed(records):
        if (
            str(row.get("profile_key")) == key
            and str(row.get("profile_sha256")) == profile.sha256
            and str(row.get("status")) == "ACTIVE"
        ):
            return dict(row)
    return None


def grammar_review_by_decision_id(
    config: EcosystemConfig,
    profile: GrammarProfile,
    decision_id: str,
) -> dict[str, Any] | None:
    """Resolve one active decision ID only when it binds the exact current profile hash."""
    wanted = decision_id.strip()
    if not wanted:
        return None
    key = f"{profile.language}/{profile.profile_id}"
    for row in reversed(_read_registry(grammar_review_registry_path(config))):
        if (
            str(row.get("decision_id")) == wanted
            and str(row.get("profile_key")) == key
            and str(row.get("profile_sha256")) == profile.sha256
            and str(row.get("status")) == "ACTIVE"
        ):
            return dict(row)
    return None


def grammar_profile_is_approved(config: EcosystemConfig, profile: GrammarProfile) -> bool:
    """Return whether the profile is intrinsically active or exactly human-approved."""
    if profile.status == "ACTIVE":
        return True
    receipt = active_grammar_review(config, profile)
    return bool(receipt and receipt.get("decision") == "APPROVED")


def list_grammar_profile_reviews(config: EcosystemConfig) -> list[dict[str, Any]]:
    """List configured profiles with declared and exact-review effective status."""
    rows: list[dict[str, Any]] = []
    for key, profile in configured_grammar_profiles(config).items():
        review = active_grammar_review(config, profile)
        approved = grammar_profile_is_approved(config, profile)
        rows.append(
            {
                "profile_key": key,
                "profile_id": profile.profile_id,
                "language": profile.language,
                "role": profile.role,
                "declared_status": profile.status,
                "effective_status": "ACTIVE" if approved else profile.status,
                "profile_sha256": profile.sha256,
                "path": str(profile.path),
                "review": review,
            }
        )
    return rows


def record_grammar_profile_review(
    config: EcosystemConfig,
    *,
    profile_key: str,
    decision_id: str,
    operator: str,
    decision: str,
    notes: str = "",
) -> dict[str, Any]:
    """Record one exact-hash profile decision and supersede earlier active decisions."""
    selector = profile_key.strip()
    profiles = configured_grammar_profiles(config)
    if selector not in profiles:
        raise ValidationError(
            f"Unknown grammar profile selector: {profile_key}",
            code="GRAMMAR_PROFILE_NOT_FOUND",
            details={"available": sorted(profiles)},
        )
    profile = profiles[selector]
    normalized_decision = decision.strip().upper()
    if normalized_decision not in GRAMMAR_REVIEW_DECISIONS:
        raise ValidationError(f"Unsupported grammar review decision: {decision}")
    review_id = decision_id.strip()
    operator_id = operator.strip()
    if not review_id or not operator_id:
        raise ValidationError("Grammar review requires nonempty decision ID and operator")
    path = grammar_review_registry_path(config)
    lock_path = config.root / "state" / "locks" / "grammar-profile-review.lock"
    with WorkspaceLock(lock_path, "GRAMMAR_PROFILE_REVIEW"):
        records = _read_registry(path)
        if any(str(row.get("decision_id")) == review_id for row in records):
            raise ValidationError(
                f"Grammar review decision ID is already recorded: {review_id}",
                code="GRAMMAR_REVIEW_DECISION_ALREADY_RECORDED",
            )
        for index, row in enumerate(records):
            if str(row.get("profile_key")) == selector and str(row.get("status")) == "ACTIVE":
                records[index] = {
                    **row,
                    "status": "SUPERSEDED",
                    "superseded_by": review_id,
                    "superseded_utc": utc_now(),
                }
        receipt = {
            "schema_version": "1.0",
            "decision_id": review_id,
            "profile_key": selector,
            "profile_id": profile.profile_id,
            "language": profile.language,
            "role": profile.role,
            "profile_path": profile.path.resolve().relative_to(config.root.resolve()).as_posix(),
            "profile_sha256": profile.sha256,
            "declared_status": profile.status,
            "decision": normalized_decision,
            "operator": operator_id,
            "notes": notes.strip(),
            "status": "ACTIVE",
            "recorded_utc": utc_now(),
        }
        records.append(receipt)
        atomic_write_json(path, records)
    return {**receipt, "registry_path": str(path)}
