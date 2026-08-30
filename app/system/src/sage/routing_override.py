"""Audited machine-local global route override with per-Skill fail-closed validation."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .atomic import atomic_write_json
from .errors import ConfigurationError, ValidationError
from .executors.base import ProviderStatus
from .model_policy import load_model_policy
from .skill_routing import SkillRoute, resolve_skill_route, resolve_specific_skill_route
from .storage import storage_layout


def _utc_now() -> datetime:
    """Return an aware UTC timestamp for override state and receipt identity."""
    return datetime.now(timezone.utc)


def _utc_text(value: datetime) -> str:
    """Render one UTC timestamp with deterministic Z notation."""
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def override_path(root: Path) -> Path:
    """Return the separate Operator-owned advanced override path."""
    return storage_layout(root).config_root / "model-routing-override.json"


def _receipt_root(root: Path) -> Path:
    """Return the immutable local audit-receipt directory."""
    return storage_layout(root).state_root / "model-routing-overrides"


def _selection(value: Mapping[str, Any]) -> dict[str, str]:
    """Normalize and validate one provider/model/capability/reasoning selection."""
    required = ("provider", "model_id", "capability_fingerprint", "reasoning_id")
    result = {field: str(value.get(field) or "").strip() for field in required}
    missing = [field for field, item in result.items() if not item]
    if missing:
        raise ConfigurationError("Routing override selection is missing: " + ", ".join(missing))
    return result


def load_global_override(root: Path) -> dict[str, Any] | None:
    """Load and validate active advanced override state when present."""
    path = override_path(root)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Invalid model routing override: {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise ConfigurationError("Model routing override must use schema_version 1.0")
    if value.get("routing_mode") != "GLOBAL_OVERRIDE":
        raise ConfigurationError("Model routing override routing_mode must be GLOBAL_OVERRIDE")
    value["selection"] = _selection(value.get("selection") or {})
    skills = value.get("qualified_skills")
    if not isinstance(skills, list) or any(not isinstance(item, str) for item in skills):
        raise ConfigurationError("Model routing override qualified_skills must be a list of Skill IDs")
    return value


def _qualified_skill_coverage(
    root: Path,
    selection: Mapping[str, str],
    statuses: Sequence[ProviderStatus],
) -> tuple[list[str], int]:
    """Return exact registered Skills currently qualified for one pinned route."""
    policy = load_model_policy(root)
    qualified: list[str] = []
    for skill_id in policy["skill_routes"]:
        try:
            resolve_specific_skill_route(
                root,
                skill_id,
                statuses,
                provider=selection["provider"],
                model_id=selection["model_id"],
                capability_fingerprint_value=selection["capability_fingerprint"],
                reasoning_id=selection["reasoning_id"],
            )
        except ValidationError:
            continue
        qualified.append(skill_id)
    return qualified, len(policy["skill_routes"])


def _write_receipt(root: Path, payload: dict[str, Any], when: datetime) -> Path:
    """Persist one immutable action receipt with collision-resistant identity."""
    receipt_root = _receipt_root(root)
    receipt_root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    stamp = when.strftime("%Y%m%dT%H%M%S%fZ")
    path = receipt_root / f"{stamp}-{str(payload['action']).lower()}-{digest}.json"
    atomic_write_json(path, payload)
    return path


def set_global_override(
    root: Path,
    *,
    selection: Mapping[str, Any],
    statuses: Sequence[ProviderStatus],
) -> dict[str, Any]:
    """Enable or change one exact override after measuring current Skill coverage."""
    normalized = _selection(selection)
    qualified, registered_count = _qualified_skill_coverage(root, normalized, statuses)
    if not qualified:
        raise ValidationError(
            "Selected route is not currently qualified for any registered Skill",
            code="GLOBAL_OVERRIDE_NO_QUALIFIED_SKILLS",
        )
    previous = load_global_override(root)
    now = _utc_now()
    payload = {
        "schema_version": "1.0",
        "routing_mode": "GLOBAL_OVERRIDE",
        "selection": normalized,
        "qualification_policy_version": str(
            load_model_policy(root).get("qualification_policy_version") or ""
        ),
        "qualified_skills": qualified,
        "qualified_skill_count": len(qualified),
        "registered_skill_count": registered_count,
        "created_utc": _utc_text(now),
    }
    path = override_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)
    receipt = {
        "schema_version": "1.0",
        "action": "CHANGE" if previous else "ENABLE",
        "previous_mode": "GLOBAL_OVERRIDE" if previous else "AUTOMATIC",
        "routing_mode": "GLOBAL_OVERRIDE",
        "selection": normalized,
        "qualified_skills": qualified,
        "qualified_skill_count": len(qualified),
        "registered_skill_count": registered_count,
        "qualification_policy_version": payload["qualification_policy_version"],
        "created_utc": payload["created_utc"],
    }
    receipt_path = _write_receipt(root, receipt, now)
    return {**payload, "override_path": str(path), "receipt_path": str(receipt_path)}


def clear_global_override(root: Path) -> dict[str, Any]:
    """Restore automatic routing while retaining an immutable audit receipt."""
    previous = load_global_override(root)
    path = override_path(root)
    path.unlink(missing_ok=True)
    now = _utc_now()
    receipt = {
        "schema_version": "1.0",
        "action": "CLEAR",
        "previous_mode": "GLOBAL_OVERRIDE" if previous else "AUTOMATIC",
        "routing_mode": "AUTOMATIC",
        "selection": previous.get("selection") if previous else None,
        "qualified_skills": previous.get("qualified_skills", []) if previous else [],
        "created_utc": _utc_text(now),
    }
    receipt_path = _write_receipt(root, receipt, now)
    return {
        "routing_mode": "AUTOMATIC",
        "override_path": str(path),
        "receipt_path": str(receipt_path),
    }


def resolve_routing_mode(
    root: Path,
    skill_id: str,
    statuses: Sequence[ProviderStatus],
) -> SkillRoute:
    """Resolve automatic routing or enforce the active exact override for one Skill."""
    override = load_global_override(root)
    if override is None:
        return resolve_skill_route(root, skill_id, statuses)
    selection = override["selection"]
    try:
        route = resolve_specific_skill_route(
            root,
            skill_id,
            statuses,
            provider=selection["provider"],
            model_id=selection["model_id"],
            capability_fingerprint_value=selection["capability_fingerprint"],
            reasoning_id=selection["reasoning_id"],
        )
    except ValidationError as exc:
        raise ValidationError(
            f"Global override route is not qualified for {skill_id}",
            code="GLOBAL_OVERRIDE_NOT_QUALIFIED_FOR_SKILL",
        ) from exc
    return replace(
        route,
        routing_mode="GLOBAL_OVERRIDE",
        selection_mode="USER_OVERRIDE",
    )
