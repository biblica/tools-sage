"""SAGE model qualification, reasoning policy, live catalog caching, and recommendations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .atomic import atomic_write_json
from .errors import ConfigurationError, ValidationError
from .storage import storage_layout
from .executors.base import ProviderStatus


@dataclass(frozen=True)
class ModelRecommendation:
    """One deterministic SAGE model/reasoning recommendation."""

    workflow: str
    operation: str
    task_profile: str
    complexity: str
    model: str
    display_name: str
    reasoning_effort: str | None
    conditional_second_pass_reasoning_effort: str | None
    qualification_status: str
    qualification_basis: str
    account_plan_type: str | None
    selection_basis: str

    def to_dict(self) -> dict[str, Any]:
        """Render the recommendation for CLI output and execution receipts."""
        return {
            "workflow": self.workflow,
            "operation": self.operation,
            "task_profile": self.task_profile,
            "complexity": self.complexity,
            "model": self.model,
            "display_name": self.display_name,
            "reasoning_effort": self.reasoning_effort,
            "conditional_second_pass_reasoning_effort": self.conditional_second_pass_reasoning_effort,
            "qualification_status": self.qualification_status,
            "qualification_basis": self.qualification_basis,
            "account_plan_type": self.account_plan_type,
            "selection_basis": self.selection_basis,
        }


def _utc_now() -> str:
    """Return a stable UTC timestamp for non-secret model-catalog provenance."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def model_policy_path(root: Path) -> Path:
    """Return the release-governed model policy path."""
    return root.resolve() / "system" / "config" / "model-policy.yml"


def load_model_policy(root: Path) -> dict[str, Any]:
    """Load and minimally validate the release-governed model policy."""
    path = model_policy_path(root)
    if not path.is_file():
        raise ConfigurationError(f"Missing SAGE model policy: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Invalid SAGE model policy: {path}: {exc}") from exc
    if not isinstance(value, dict) or str(value.get("schema_version")) != "2.0":
        raise ConfigurationError("SAGE model policy must be schema_version 2.0")
    required = (
        "qualification_policy_version",
        "unknown_route_status",
        "accepted_operational_statuses",
        "recommendation_order",
        "skill_routes",
    )
    missing = [field for field in required if field not in value]
    if missing:
        raise ConfigurationError("SAGE model policy is missing: " + ", ".join(missing))
    if value.get("unknown_route_status") != "UNASSESSED":
        raise ConfigurationError("SAGE model policy unknown_route_status must be UNASSESSED")
    if value.get("accepted_operational_statuses") != ["RECOMMENDED", "QUALIFIED"]:
        raise ConfigurationError(
            "SAGE model policy accepted_operational_statuses must be RECOMMENDED, QUALIFIED"
        )
    routes = value.get("skill_routes")
    if not isinstance(routes, dict) or not routes:
        raise ConfigurationError("SAGE model policy skill_routes must be a non-empty object")
    registry_path = root.resolve() / "system" / "config" / "skills.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Invalid SAGE Skill registry: {registry_path}: {exc}") from exc
    registered = set((registry.get("skills") or {}).keys()) if isinstance(registry, dict) else set()
    if set(routes) != registered:
        raise ConfigurationError("SAGE model policy routes must exactly match the registered Skill IDs")
    return value


def catalog_cache_path(root: Path, provider: str = "codex") -> Path:
    """Return the operator-state path for one non-secret provider capability snapshot."""
    return storage_layout(root).state_root / "model-catalog" / f"{provider}.json"


def cache_provider_catalog(root: Path, status: ProviderStatus) -> Path:
    """Persist a non-secret provider capability snapshot for diagnostics and audit."""
    path = catalog_cache_path(root, status.provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "queried_utc": _utc_now(),
        "provider": status.provider,
        "auth_mode": status.auth_mode,
        "account_plan_type": status.account_plan_type,
        "ready": status.ready,
        "selected_model": status.selected_model,
        "selected_reasoning_effort": status.selected_reasoning_effort,
        "models": [item.to_dict() for item in status.model_capabilities],
        "diagnostic": status.diagnostic,
    }
    atomic_write_json(path, payload)
    return path


def load_cached_catalog(root: Path, provider: str = "codex") -> dict[str, Any] | None:
    """Load a previously cached non-secret catalog snapshot when present."""
    path = catalog_cache_path(root, provider)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def skill_id_for_operation(root: Path, workflow: str, operation: str) -> str:
    """Resolve a legacy workflow/operation caller to one exact registered Skill ID."""
    registry_path = root.resolve() / "system" / "config" / "skills.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Invalid SAGE Skill registry: {registry_path}: {exc}") from exc
    matches = [
        str(skill_id)
        for skill_id, record in (registry.get("skills") or {}).items()
        if isinstance(record, dict)
        and str(record.get("workflow") or "").strip().lower() == workflow.strip().lower()
        and str(record.get("operation") or "").strip().lower() == operation.strip().lower()
    ]
    if len(matches) != 1:
        raise ValidationError(
            f"No unique registered Skill exists for {workflow}/{operation}",
            code="NO_QUALIFIED_SKILL_ROUTE",
        )
    return matches[0]


def recommend_model(
    *,
    root: Path,
    status: ProviderStatus,
    workflow: str,
    operation: str,
    manifest: dict[str, Any] | None = None,
) -> ModelRecommendation:
    """Adapt a legacy workflow caller to exact registered-Skill route resolution."""
    del manifest  # Complexity cannot replace exact per-Skill qualification.
    from .skill_routing import resolve_skill_route

    skill_id = skill_id_for_operation(root, workflow, operation)
    route = resolve_skill_route(root, skill_id, [status])
    capability = next(
        (
            item
            for item in status.model_capabilities
            if item.model == route.identity.model_id or item.id == route.identity.model_id
        ),
        None,
    )
    display_name = capability.display_name if capability is not None else route.identity.model_id
    reasoning = (
        None if route.identity.reasoning_id == "provider-default" else route.identity.reasoning_id
    )
    return ModelRecommendation(
        workflow=workflow,
        operation=operation,
        task_profile=skill_id,
        complexity="EVIDENCE_QUALIFIED",
        model=route.identity.model_id,
        display_name=display_name,
        reasoning_effort=reasoning,
        conditional_second_pass_reasoning_effort=reasoning,
        qualification_status=route.qualification,
        qualification_basis=f"qualification evidence {route.evidence_sha256}",
        account_plan_type=status.account_plan_type,
        selection_basis="exact_skill_qualification",
    )
