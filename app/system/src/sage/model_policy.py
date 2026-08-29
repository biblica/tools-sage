"""SAGE model qualification, reasoning policy, live catalog caching, and recommendations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from .atomic import atomic_write_json
from .errors import ConfigurationError, ValidationError
from .storage import storage_layout
from .executors.base import (
    SAGE_SUPPORTED_REASONING_EFFORTS,
    ModelCapability,
    ProviderStatus,
    sage_supports_reasoning_effort,
)


_KNOWN_EFFORT_RANK = {
    "none": 0,
    "minimal": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "xhigh": 5,
}
_COMPLEXITY_RANK = {"R1": 1, "R2": 2, "R3": 3, "R4": 4}
_COMPLEXITY_EFFORT = {"R1": "low", "R2": "medium", "R3": "high", "R4": "xhigh"}


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


def task_profile_key(workflow: str, operation: str) -> str:
    """Return the canonical policy key for one governed SAGE operation."""
    return f"{workflow.strip().lower()}.{operation.strip().lower()}"


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


def qualification_for(policy: dict[str, Any], model: str, profile: str) -> dict[str, Any]:
    """Return model qualification metadata for one workflow profile."""
    row = policy.get("qualification", {}).get(model)
    if not isinstance(row, dict):
        return {
            "qualified": False,
            "status": str(policy.get("global", {}).get("unknown_models", "UNQUALIFIED")),
            "basis": "Model is not listed in the release-governed SAGE qualification table.",
        }
    workflows = row.get("workflows", [])
    qualified = isinstance(workflows, list) and profile in workflows
    return {
        "qualified": qualified,
        "status": str(row.get("status", "UNQUALIFIED")),
        "basis": str(row.get("basis", "")),
    }


def _effort_allowed(policy: dict[str, Any], effort: str | None) -> bool:
    """Return whether an effort is inside the hard SAGE ceiling and release allowlist."""
    if effort is None:
        return True
    effort = effort.strip().lower()
    if not sage_supports_reasoning_effort(effort):
        return False
    allowed = policy.get("global", {}).get("allowed_reasoning_efforts", [])
    if isinstance(allowed, list) and allowed:
        return effort in {str(value).strip().lower() for value in allowed}
    return effort in SAGE_SUPPORTED_REASONING_EFFORTS


def ensure_reasoning_effort_supported(policy: dict[str, Any], effort: str | None) -> str | None:
    """Normalize one explicit effort and reject anything above SAGE's XHigh ceiling."""
    if effort is None:
        return None
    normalized = effort.strip().lower()
    if not _effort_allowed(policy, normalized):
        raise ValidationError(
            f"Reasoning effort {effort} is unsupported by SAGE; highest supported reasoning level is xhigh",
            code="MODEL_REASONING_UNSUPPORTED",
        )
    return normalized


def _rank(value: str | None) -> int | None:
    """Return the canonical rank for known reasoning effort names."""
    return _KNOWN_EFFORT_RANK.get(value or "")


def _within_effort_bounds(effort: str, minimum: str | None, maximum: str | None) -> bool:
    """Check known effort bounds while failing closed on unknown ranked values."""
    effort_rank = _rank(effort)
    minimum_rank = _rank(minimum)
    maximum_rank = _rank(maximum)
    if effort_rank is None:
        return effort == minimum == maximum
    if minimum_rank is not None and effort_rank < minimum_rank:
        return False
    if maximum_rank is not None and effort_rank > maximum_rank:
        return False
    return True


def choose_reasoning_effort(
    model: ModelCapability,
    *,
    target: str | None,
    minimum: str | None,
    maximum: str | None,
    policy: dict[str, Any],
) -> str | None:
    """Choose target or the nearest higher provider-advertised effort within SAGE bounds."""
    efforts = [value for value in model.reasoning_efforts if _effort_allowed(policy, value)]
    if not efforts:
        return None
    if target in efforts and target is not None and _within_effort_bounds(target, minimum, maximum):
        return target
    target_rank = _rank(target)
    if target_rank is not None:
        higher = [
            value for value in efforts
            if (_rank(value) is not None and _rank(value) >= target_rank and _within_effort_bounds(value, minimum, maximum))
        ]
        if higher:
            return higher[0]
        lower = [value for value in efforts if _within_effort_bounds(value, minimum, maximum)]
        if lower:
            return lower[-1]
    default = model.default_reasoning_effort
    if default in efforts and default is not None and _within_effort_bounds(default, minimum, maximum):
        return default
    bounded = [value for value in efforts if _within_effort_bounds(value, minimum, maximum)]
    return bounded[0] if bounded else None


def classify_task_complexity(manifest: dict[str, Any], profile: dict[str, Any]) -> str:
    """Classify a governed task using task type plus bounded scope/candidate size signals."""
    base = str(profile.get("base_complexity", "R2"))
    rank = _COMPLEXITY_RANK.get(base, 2)
    expected = manifest.get("expected_references", [])
    candidates = manifest.get("structural_candidate_ids", [])
    expected_count = len(expected) if isinstance(expected, list) else 0
    candidate_count = len(candidates) if isinstance(candidates, list) else 0
    if expected_count > 100 or candidate_count > 25:
        rank = min(4, rank + 1)
    return f"R{rank}"


def _effective_target(profile: dict[str, Any], complexity: str) -> str | None:
    """Escalate the profile target when deterministic task complexity requires it."""
    configured = str(profile.get("target_reasoning_effort") or "").strip() or None
    complexity_effort = _COMPLEXITY_EFFORT.get(complexity)
    if configured is None:
        return complexity_effort
    configured_rank = _rank(configured)
    complexity_rank = _rank(complexity_effort)
    if configured_rank is not None and complexity_rank is not None and complexity_rank > configured_rank:
        return complexity_effort
    return configured


def _model_lookup(models: Iterable[ModelCapability]) -> dict[str, ModelCapability]:
    """Index live models by executable model slug and catalog id."""
    result: dict[str, ModelCapability] = {}
    for item in models:
        result.setdefault(item.model, item)
        result.setdefault(item.id, item)
    return result


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


def validate_explicit_selection(
    *,
    root: Path,
    status: ProviderStatus,
    workflow: str,
    operation: str,
    model: str,
    reasoning_effort: str | None,
    allow_unqualified: bool = False,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an Operator-selected live model/effort against SAGE policy and record override state."""
    policy = load_model_policy(root)
    key = task_profile_key(workflow, operation)
    profile = policy.get("task_profiles", {}).get(key)
    if not isinstance(profile, dict):
        raise ValidationError(f"No SAGE model policy exists for {key}", code="MODEL_POLICY_PROFILE_MISSING")
    lookup = _model_lookup(status.model_capabilities)
    item = lookup.get(model)
    if item is None:
        raise ValidationError(f"Codex model is not available to the current ChatGPT workspace: {model}", code="MODEL_NOT_AVAILABLE")
    qualification = qualification_for(policy, item.model, key)
    override = False
    if not qualification["qualified"]:
        if not allow_unqualified:
            raise ValidationError(
                f"Model {item.model} is available but not SAGE-qualified for {key}; use --policy-override only after Operator review",
                code="MODEL_NOT_QUALIFIED",
            )
        override = True
    complexity = classify_task_complexity(manifest or {}, profile)
    minimum = str(profile.get("minimum_reasoning_effort") or "").strip() or None
    maximum = str(profile.get("maximum_reasoning_effort") or "").strip() or None
    if reasoning_effort is None:
        selected_effort = choose_reasoning_effort(
            item,
            target=_effective_target(profile, complexity),
            minimum=minimum,
            maximum=maximum,
            policy=policy,
        )
        if item.reasoning_efforts and selected_effort is None:
            raise ValidationError(
                f"No advertised reasoning effort for {item.model} satisfies SAGE policy for {key}",
                code="MODEL_REASONING_NOT_AVAILABLE",
            )
    else:
        selected_effort = ensure_reasoning_effort_supported(policy, reasoning_effort)
    conditional_second_effort = selected_effort
    if reasoning_effort is None:
        second_target = str(profile.get("conditional_second_pass_reasoning_effort") or "").strip() or None
        if second_target:
            conditional_second_effort = choose_reasoning_effort(
                item,
                target=second_target,
                minimum=minimum,
                maximum=maximum,
                policy=policy,
            ) or selected_effort
    if selected_effort:
        if selected_effort not in item.reasoning_efforts:
            raise ValidationError(
                f"Reasoning effort {selected_effort} is not advertised for {item.model}; supported={list(item.reasoning_efforts)}",
                code="MODEL_REASONING_NOT_AVAILABLE",
            )
        ensure_reasoning_effort_supported(policy, selected_effort)
        if not _within_effort_bounds(selected_effort, minimum, maximum):
            if not allow_unqualified:
                raise ValidationError(
                    f"Reasoning effort {selected_effort} is outside SAGE bounds for {key}: {minimum}..{maximum}",
                    code="MODEL_REASONING_OUTSIDE_POLICY",
                )
            override = True
    return {
        "model": item.model,
        "display_name": item.display_name,
        "reasoning_effort": selected_effort,
        "conditional_second_pass_reasoning_effort": conditional_second_effort,
        "qualification_status": qualification["status"],
        "qualification_basis": qualification["basis"],
        "operator_policy_override": override,
        "task_profile": key,
        "complexity": complexity,
        "selection_basis": "operator_selected + live_available + policy_validated",
    }
