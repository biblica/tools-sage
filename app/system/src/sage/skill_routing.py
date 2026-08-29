"""Provider-neutral, evidence-bound route identity and deterministic Skill resolution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .errors import ConfigurationError, ValidationError
from .executors.base import ModelCapability, ProviderStatus
from .model_policy import load_model_policy
from .storage import storage_layout


_COST_RANK = {"LOW": 0, "STANDARD": 1, "HIGH": 2, "UNKNOWN": 3}


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    """Hash one canonical JSON mapping for stable route identity."""
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def capability_fingerprint(capability: ModelCapability) -> str:
    """Bind the provider-reported capability fields that can affect route behavior."""
    return _canonical_sha256(
        {
            "id": capability.id,
            "model": capability.model,
            "reasoning_efforts": list(capability.reasoning_efforts),
            "default_reasoning_effort": capability.default_reasoning_effort,
            "input_modalities": list(capability.input_modalities),
            "supports_personality": capability.supports_personality,
            "model_specialty": capability.model_specialty,
            "service_tiers": list(capability.service_tiers),
            "default_service_tier": capability.default_service_tier,
            "identity_strength": capability.identity_strength,
            "cost_class": capability.cost_class,
        }
    )


@dataclass(frozen=True)
class RouteIdentity:
    """Exact provider, model capability, Skill, suite, and policy identity."""

    provider: str
    model_id: str
    capability_fingerprint: str
    reasoning_id: str
    skill_id: str
    skill_sha256: str
    suite_id: str
    suite_sha256: str
    policy_version: str

    @property
    def route_id(self) -> str:
        """Return the stable SHA-256 ID for the complete route identity."""
        return _canonical_sha256(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        """Render the route identity for receipts and status views."""
        return {**asdict(self), "route_id": self.route_id}


@dataclass(frozen=True)
class SkillRoute:
    """One currently executable route plus its qualification provenance."""

    identity: RouteIdentity
    availability: str
    qualification: str
    routing_mode: str
    evidence_sha256: str
    provider_runtime_version: str | None
    model_identity_strength: str
    cost_class: str

    def to_dict(self) -> dict[str, Any]:
        """Render one route without losing exact identity fields."""
        return {
            **self.identity.to_dict(),
            "availability": self.availability,
            "qualification": self.qualification,
            "routing_mode": self.routing_mode,
            "evidence_sha256": self.evidence_sha256,
            "provider_runtime_version": self.provider_runtime_version,
            "model_identity_strength": self.model_identity_strength,
            "cost_class": self.cost_class,
        }


def _load_object(path: Path) -> dict[str, Any] | None:
    """Load one optional JSON evidence object, ignoring no malformed evidence."""
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Invalid model qualification evidence: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"Model qualification evidence must be an object: {path}")
    return value


class QualificationEvidenceRepository(Protocol):
    """Replaceable local API for already verified qualification evidence."""

    def records_for_skill(self, skill_id: str) -> Sequence[Mapping[str, Any]]:
        """Return qualification records bounded to one exact registered Skill."""
        ...


@dataclass(frozen=True)
class LocalQualificationEvidenceRepository:
    """Read bundled seeds and machine-local receipts through the repository contract."""

    root: Path

    def records_for_skill(self, skill_id: str) -> list[dict[str, Any]]:
        """Load one Skill's Core seeds and immutable local receipts in stable path order."""
        root = self.root.expanduser().resolve()
        rows: list[dict[str, Any]] = []
        seed = _load_object(root / "system/config/model-qualification-seeds.json")
        if seed is not None:
            raw_routes = seed.get("routes")
            if not isinstance(raw_routes, list):
                raise ConfigurationError("model-qualification-seeds.json routes must be a list")
            rows.extend(dict(item) for item in raw_routes if isinstance(item, dict))

        receipt_root = storage_layout(root).state_root / "model-qualification"
        if receipt_root.is_dir():
            for path in sorted(receipt_root.rglob("*.json")):
                receipt = _load_object(path)
                if receipt is None:
                    continue
                raw_routes = receipt.get("routes")
                if isinstance(raw_routes, list):
                    rows.extend(dict(item) for item in raw_routes if isinstance(item, dict))
                elif receipt.get("skill_id"):
                    rows.append(dict(receipt))
        return [row for row in rows if str(row.get("skill_id") or "") == skill_id]


def qualification_evidence_repository(root: Path) -> QualificationEvidenceRepository:
    """Return the default repository behind the resolver's replaceable local API seam."""
    return LocalQualificationEvidenceRepository(root)


def _skill_identity(root: Path, skill_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Return the exact adapted Skill hash, policy, and per-Skill route policy."""
    policy = load_model_policy(root)
    route_policy = policy["skill_routes"].get(skill_id)
    if not isinstance(route_policy, dict):
        raise ValidationError(
            f"No routing policy exists for registered Skill {skill_id}",
            code="NO_QUALIFIED_SKILL_ROUTE",
        )
    registry_path = root / "system/config/skills.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Invalid SAGE Skill registry: {registry_path}: {exc}") from exc
    skill = (registry.get("skills") or {}).get(skill_id) if isinstance(registry, dict) else None
    if not isinstance(skill, dict) or not str(skill.get("adapted_sha256") or ""):
        raise ValidationError(
            f"Registered Skill identity is unavailable: {skill_id}",
            code="NO_QUALIFIED_SKILL_ROUTE",
        )
    return str(skill["adapted_sha256"]), policy, route_policy


def _capability_rows(
    statuses: Sequence[ProviderStatus],
) -> Iterable[tuple[ProviderStatus, ModelCapability, str]]:
    """Yield every live advertised capability with its exact fingerprint."""
    for status in statuses:
        for capability in status.model_capabilities:
            yield status, capability, capability_fingerprint(capability)


def _reasoning_index(capability: ModelCapability, reasoning_id: str) -> int | None:
    """Return provider-native reasoning order or the sole provider-default position."""
    if not capability.reasoning_efforts:
        return 0 if reasoning_id == "provider-default" else None
    try:
        return capability.reasoning_efforts.index(reasoning_id)
    except ValueError:
        return None


def _record_identity_matches(
    row: Mapping[str, Any],
    *,
    provider: str,
    capability: ModelCapability,
    fingerprint: str,
    reasoning_id: str,
    skill_id: str,
    skill_sha256: str,
    suite_id: str,
    suite_sha256: str,
    policy_version: str,
) -> bool:
    """Compare all evidence-bound identity fields without aliases or fallback."""
    expected = {
        "provider": provider,
        "model_id": capability.model,
        "capability_fingerprint": fingerprint,
        "reasoning_id": reasoning_id,
        "skill_id": skill_id,
        "skill_sha256": skill_sha256,
        "suite_id": suite_id,
        "suite_sha256": suite_sha256,
        "policy_version": policy_version,
    }
    return all(str(row.get(key) or "") == str(value) for key, value in expected.items())


def _candidate_skill_routes(
    root: Path,
    skill_id: str,
    statuses: Sequence[ProviderStatus],
    *,
    evidence_repository: QualificationEvidenceRepository | None = None,
) -> tuple[list[SkillRoute], bool, bool]:
    """Return sorted exact candidates plus unavailable and stale evidence state."""
    root = root.expanduser().resolve()
    skill_sha256, policy, route_policy = _skill_identity(root, skill_id)
    suite_id = str(route_policy.get("suite_id") or "")
    suite_sha256 = str(route_policy.get("suite_sha256") or "")
    policy_version = str(policy.get("qualification_policy_version") or "")
    accepted = {str(value) for value in policy.get("accepted_operational_statuses", [])}
    release_preference = policy.get("release_preference")
    release_preference = release_preference if isinstance(release_preference, dict) else {}
    preferred_providers = [str(value) for value in release_preference.get("providers", [])]
    preferred_models = release_preference.get("models")
    preferred_models = preferred_models if isinstance(preferred_models, dict) else {}
    repository = evidence_repository or qualification_evidence_repository(root)
    evidence = [
        dict(row)
        for row in repository.records_for_skill(skill_id)
        if str(row.get("skill_id") or "") == skill_id
    ]
    candidates: list[tuple[tuple[Any, ...], SkillRoute]] = []
    exact_but_unavailable = False
    stale_observed = False

    # Keep evidence matching and recommendation ordering in one pass so no
    # status view can accidentally apply weaker identity rules than execution.
    for status, capability, fingerprint in _capability_rows(statuses):
        reasoning_ids = capability.reasoning_efforts or ("provider-default",)
        for reasoning_id in reasoning_ids:
            native_index = _reasoning_index(capability, reasoning_id)
            if native_index is None:
                continue
            related = [
                row
                for row in evidence
                if str(row.get("provider") or "") == status.provider
                and str(row.get("model_id") or "") == capability.model
                and str(row.get("reasoning_id") or "") == reasoning_id
            ]
            exact = [
                row
                for row in related
                if _record_identity_matches(
                    row,
                    provider=status.provider,
                    capability=capability,
                    fingerprint=fingerprint,
                    reasoning_id=reasoning_id,
                    skill_id=skill_id,
                    skill_sha256=skill_sha256,
                    suite_id=suite_id,
                    suite_sha256=suite_sha256,
                    policy_version=policy_version,
                )
            ]
            if related and not exact:
                stale_observed = True
            for row in exact:
                qualification = str(row.get("qualification_status") or "")
                if qualification not in accepted:
                    continue
                if not status.available or not status.ready:
                    exact_but_unavailable = True
                    continue
                identity = RouteIdentity(
                    provider=status.provider,
                    model_id=capability.model,
                    capability_fingerprint=fingerprint,
                    reasoning_id=reasoning_id,
                    skill_id=skill_id,
                    skill_sha256=skill_sha256,
                    suite_id=suite_id,
                    suite_sha256=suite_sha256,
                    policy_version=policy_version,
                )
                route = SkillRoute(
                    identity=identity,
                    availability="AVAILABLE",
                    qualification="QUALIFIED",
                    routing_mode="AUTOMATIC",
                    evidence_sha256=str(row.get("evidence_sha256") or ""),
                    provider_runtime_version=status.version,
                    model_identity_strength=capability.identity_strength,
                    cost_class=str(row.get("cost_class") or capability.cost_class or "UNKNOWN"),
                )
                score = float(row.get("semantic_score") or 0.0)
                material_score = score if bool(row.get("semantic_score_material")) else 0.0
                cost_rank = _COST_RANK.get(route.cost_class.upper(), _COST_RANK["UNKNOWN"])
                provider_rank = (
                    preferred_providers.index(status.provider)
                    if status.provider in preferred_providers
                    else len(preferred_providers)
                )
                provider_models = [str(value) for value in preferred_models.get(status.provider, [])]
                model_rank = (
                    provider_models.index(capability.model)
                    if capability.model in provider_models
                    else len(provider_models)
                )
                candidates.append(
                    (
                        (
                            cost_rank,
                            native_index,
                            -material_score,
                            provider_rank,
                            model_rank,
                            identity.route_id,
                        ),
                        route,
                    )
                )

    candidates.sort(key=lambda item: item[0])
    return [route for _rank, route in candidates], exact_but_unavailable, stale_observed


def _raise_unresolved_skill_route(
    skill_id: str,
    *,
    exact_but_unavailable: bool,
    stale_observed: bool,
) -> None:
    """Raise the most specific fail-closed route resolution error."""
    if exact_but_unavailable:
        raise ValidationError(
            f"Qualified route for {skill_id} is not currently available",
            code="PROVIDER_ROUTE_UNAVAILABLE",
        )
    if stale_observed:
        raise ValidationError(
            f"Qualification evidence for {skill_id} does not match current route identity",
            code="SKILL_ROUTE_EVIDENCE_STALE",
        )
    raise ValidationError(
        f"No enabled, available route is qualified for {skill_id}",
        code="NO_QUALIFIED_SKILL_ROUTE",
    )


def qualified_skill_routes(
    root: Path,
    skill_id: str,
    statuses: Sequence[ProviderStatus],
    *,
    evidence_repository: QualificationEvidenceRepository | None = None,
) -> tuple[SkillRoute, ...]:
    """Return every available qualified route in deterministic recommendation order."""
    routes, exact_but_unavailable, stale_observed = _candidate_skill_routes(
        root,
        skill_id,
        statuses,
        evidence_repository=evidence_repository,
    )
    if not routes:
        _raise_unresolved_skill_route(
            skill_id,
            exact_but_unavailable=exact_but_unavailable,
            stale_observed=stale_observed,
        )
    return tuple(
        replace(route, qualification="RECOMMENDED" if index == 0 else "QUALIFIED")
        for index, route in enumerate(routes)
    )


def resolve_skill_route(
    root: Path,
    skill_id: str,
    statuses: Sequence[ProviderStatus],
    *,
    evidence_repository: QualificationEvidenceRepository | None = None,
) -> SkillRoute:
    """Resolve the recommended available exact route for one registered Skill."""
    return qualified_skill_routes(
        root,
        skill_id,
        statuses,
        evidence_repository=evidence_repository,
    )[0]


def resolve_specific_skill_route(
    root: Path,
    skill_id: str,
    statuses: Sequence[ProviderStatus],
    *,
    provider: str,
    model_id: str,
    capability_fingerprint_value: str,
    reasoning_id: str,
    evidence_repository: QualificationEvidenceRepository | None = None,
) -> SkillRoute:
    """Resolve one exact qualified route selection without substituting another candidate."""
    routes = qualified_skill_routes(
        root,
        skill_id,
        statuses,
        evidence_repository=evidence_repository,
    )
    for route in routes:
        identity = route.identity
        if (
            identity.provider == provider
            and identity.model_id == model_id
            and identity.capability_fingerprint == capability_fingerprint_value
            and identity.reasoning_id == reasoning_id
        ):
            return route
    raise ValidationError(
        f"Selected route is not qualified for {skill_id}",
        code="NO_QUALIFIED_SKILL_ROUTE",
    )
