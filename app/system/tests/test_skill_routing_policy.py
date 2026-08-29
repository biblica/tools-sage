"""Execution-ownership and exact Skill-route policy contracts."""

from __future__ import annotations

import json
import importlib
import importlib.util
import shutil
from pathlib import Path

import yaml
import pytest

from sage.model_policy import load_model_policy, recommend_model
from sage.model_service import ModelService
from sage.schema_validation import validate_schema_contracts
from sage.errors import ValidationError
from sage.executors.base import ModelCapability, ProviderStatus, ReasoningEffortOption


REGISTERED_SKILLS = (
    "bic-inspect",
    "bic-rewrite",
    "bic-self-check",
    "saw-rtc",
    "saw-stc",
    "saw-focused-check",
    "saw-original-language-review",
)


def _write_yaml(path: Path, value: dict[str, object]) -> None:
    """Write one controlled YAML fixture."""
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _ownership_fixture() -> dict[str, object]:
    """Return a complete independently specified ownership registry."""
    return {
        "schema_version": "1.0",
        "policy_version": "alpha1-1",
        "deterministic_python": {
            "planning": {"justification": "bounded local planning"},
            "report-composition": {"justification": "deterministic projection"},
            "token-measurement": {"justification": "local byte and token measurement"},
        },
        "local_assistive": {
            "status-explanation": {"authority": "NON_AUTHORITATIVE_ASSISTIVE"},
        },
        "governed_skills": {
            skill_id: {"execution_class": "GOVERNED_SKILL"}
            for skill_id in REGISTERED_SKILLS
        },
        "governed_subtasks": {
            "secondary-language-rendering": {
                "execution_class": "GOVERNED_SKILL",
                "route_source": "ORIGINATING_SKILL",
                "isolation": "ONE_REPORTED_ITEM_PER_REQUEST",
                "authority": "ASSISTIVE_TRANSLATION_ONLY",
            }
        },
    }


def test_schema_gate_rejects_an_unowned_registered_skill(package_root: Path, tmp_path: Path) -> None:
    """Deleting one Skill owner must block execution-policy validation."""
    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    ownership = _ownership_fixture()
    del ownership["governed_skills"]["saw-stc"]  # type: ignore[index]
    _write_yaml(copy / "system/config/execution-ownership.yml", ownership)

    result = validate_schema_contracts(copy)

    assert result["status"] == "BLOCKED"
    assert "execution-ownership.yml missing registered Skill ownership: saw-stc" in result["errors"]


def test_schema_gate_rejects_model_routing_on_deterministic_work(package_root: Path, tmp_path: Path) -> None:
    """A Python-owned operation must not acquire a model route or token policy."""
    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    ownership = _ownership_fixture()
    ownership["deterministic_python"]["report-composition"]["model_route"] = "codex"  # type: ignore[index]
    _write_yaml(copy / "system/config/execution-ownership.yml", ownership)

    result = validate_schema_contracts(copy)

    assert result["status"] == "BLOCKED"
    assert "execution-ownership.yml deterministic_python.report-composition contains prohibited model_route" in result["errors"]


def test_schema_gate_requires_exact_registered_skill_route_keys(package_root: Path, tmp_path: Path) -> None:
    """Routing policy must neither omit nor invent a registered analytical Skill."""
    copy = tmp_path / "SAGE"
    shutil.copytree(package_root, copy)
    policy_path = copy / "system/config/model-policy.yml"
    policy = {
        "schema_version": "2.0",
        "qualification_policy_version": "alpha1-1",
        "unknown_route_status": "UNASSESSED",
        "accepted_operational_statuses": ["RECOMMENDED", "QUALIFIED"],
        "recommendation_order": [
            "hard_contracts",
            "cost_class",
            "provider_native_reasoning_order",
            "material_semantic_score",
            "release_preference",
        ],
        "skill_routes": {
            skill_id: {
                "suite_id": f"alpha1-{skill_id}",
                "execution_class": "GOVERNED_SKILL",
            }
            for skill_id in REGISTERED_SKILLS
            if skill_id != "saw-stc"
        },
    }
    _write_yaml(policy_path, policy)

    result = validate_schema_contracts(copy)

    assert result["status"] == "BLOCKED"
    assert "model-policy.yml missing registered Skill routes: saw-stc" in result["errors"]


def test_shipped_skill_route_keys_equal_the_registered_skill_inventory(package_root: Path) -> None:
    """The installed policy must route the exact governed Skill inventory."""
    skills = json.loads((package_root / "system/config/skills.json").read_text(encoding="utf-8"))
    policy = yaml.safe_load((package_root / "system/config/model-policy.yml").read_text(encoding="utf-8"))

    assert policy["schema_version"] == "2.0"
    assert set(policy["skill_routes"]) == set(skills["skills"])


def test_runtime_policy_loader_accepts_the_provider_neutral_contract(package_root: Path) -> None:
    """Runtime policy loading must return the same exact Skill-keyed contract."""
    policy = load_model_policy(package_root)

    assert policy["schema_version"] == "2.0"
    assert policy["qualification_policy_version"] == "alpha1-1"
    assert policy["accepted_operational_statuses"] == ["RECOMMENDED", "QUALIFIED"]


def _routing_module():
    """Load the routing API only after asserting that the production module exists."""
    assert importlib.util.find_spec("sage.skill_routing") is not None
    return importlib.import_module("sage.skill_routing")


def _route_workspace(package_root: Path, tmp_path: Path, skill_id: str) -> tuple[Path, str, str]:
    """Copy Core policy and bind one synthetic suite hash for a route test."""
    root = tmp_path / "SAGE" / "app"
    shutil.copytree(package_root, root)
    policy_path = root / "system/config/model-policy.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    suite_sha256 = "a" * 64
    policy["skill_routes"][skill_id]["suite_sha256"] = suite_sha256
    _write_yaml(policy_path, policy)
    skills = json.loads((root / "system/config/skills.json").read_text(encoding="utf-8"))
    return root, skills["skills"][skill_id]["adapted_sha256"], suite_sha256


def _capability(
    *,
    model: str = "gpt-5.6-sol",
    efforts: tuple[str, ...] = ("low", "medium", "high"),
    default: str | None = "medium",
    cost_class: str = "STANDARD",
) -> ModelCapability:
    """Return one complete live capability fixture with native effort order."""
    return ModelCapability(
        id=model,
        model=model,
        display_name=model,
        supported_reasoning_efforts=tuple(ReasoningEffortOption(value) for value in efforts),
        default_reasoning_effort=default,
        is_default=True,
        identity_strength="ALIASED",
        cost_class=cost_class,
    )


def _status(provider: str, *capabilities: ModelCapability, ready: bool = True) -> ProviderStatus:
    """Return one complete provider snapshot for deterministic resolution."""
    return ProviderStatus(
        provider=provider,
        available=True,
        ready=ready,
        auth_mode="CHATGPT" if provider == "codex" else "CONNECTED",
        version="1.2.3",
        model_capabilities=tuple(capabilities),
        diagnostic="ready" if ready else "temporarily unavailable",
    )


def _write_seed(
    root: Path,
    *,
    provider: str,
    capability: ModelCapability,
    fingerprint: str,
    reasoning_id: str,
    skill_id: str,
    skill_sha256: str,
    suite_sha256: str,
    status: str = "QUALIFIED",
    evidence_sha256: str = "b" * 64,
) -> None:
    """Write one independently specified exact qualification seed."""
    payload = {
        "schema_version": "1.0",
        "routes": [
            {
                "provider": provider,
                "model_id": capability.model,
                "capability_fingerprint": fingerprint,
                "reasoning_id": reasoning_id,
                "skill_id": skill_id,
                "skill_sha256": skill_sha256,
                "suite_id": f"alpha1-{skill_id}",
                "suite_sha256": suite_sha256,
                "policy_version": "alpha1-1",
                "qualification_status": status,
                "evidence_sha256": evidence_sha256,
                "cost_class": capability.cost_class,
                "semantic_score": 1.0,
                "semantic_score_material": False,
            }
        ],
    }
    (root / "system/config/model-qualification-seeds.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_model_capability_fingerprint_changes_with_native_effort_order() -> None:
    """Changing provider-native effort order must invalidate route capability identity."""
    routing = _routing_module()
    normal = _capability(efforts=("fast", "careful"), default="fast")
    reversed_order = _capability(efforts=("careful", "fast"), default="fast")

    assert routing.capability_fingerprint(normal) != routing.capability_fingerprint(reversed_order)


def test_resolver_returns_an_exact_qualified_skill_route(package_root: Path, tmp_path: Path) -> None:
    """Exact live capability and evidence identity must produce an operational route."""
    routing = _routing_module()
    root, skill_sha256, suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")
    capability = _capability()
    fingerprint = routing.capability_fingerprint(capability)
    _write_seed(
        root,
        provider="codex",
        capability=capability,
        fingerprint=fingerprint,
        reasoning_id="medium",
        skill_id="saw-rtc",
        skill_sha256=skill_sha256,
        suite_sha256=suite_sha256,
    )

    route = routing.resolve_skill_route(root, "saw-rtc", [_status("codex", capability)])

    assert route.identity.provider == "codex"
    assert route.identity.model_id == "gpt-5.6-sol"
    assert route.identity.reasoning_id == "medium"
    assert route.identity.skill_id == "saw-rtc"
    assert route.availability == "AVAILABLE"
    assert route.qualification == "RECOMMENDED"
    assert route.routing_mode == "AUTOMATIC"
    assert route.evidence_sha256 == "b" * 64


def test_resolver_marks_changed_skill_evidence_stale(package_root: Path, tmp_path: Path) -> None:
    """A seed bound to another Skill hash must not become an executable route."""
    routing = _routing_module()
    root, _skill_sha256, suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")
    capability = _capability()
    _write_seed(
        root,
        provider="codex",
        capability=capability,
        fingerprint=routing.capability_fingerprint(capability),
        reasoning_id="medium",
        skill_id="saw-rtc",
        skill_sha256="c" * 64,
        suite_sha256=suite_sha256,
    )

    with pytest.raises(ValidationError) as caught:
        routing.resolve_skill_route(root, "saw-rtc", [_status("codex", capability)])

    assert caught.value.code == "SKILL_ROUTE_EVIDENCE_STALE"


def test_resolver_rejects_a_qualified_but_unavailable_route(package_root: Path, tmp_path: Path) -> None:
    """Qualified evidence must not hide current provider unavailability."""
    routing = _routing_module()
    root, skill_sha256, suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")
    capability = _capability()
    _write_seed(
        root,
        provider="codex",
        capability=capability,
        fingerprint=routing.capability_fingerprint(capability),
        reasoning_id="medium",
        skill_id="saw-rtc",
        skill_sha256=skill_sha256,
        suite_sha256=suite_sha256,
    )

    with pytest.raises(ValidationError) as caught:
        routing.resolve_skill_route(root, "saw-rtc", [_status("codex", capability, ready=False)])

    assert caught.value.code == "PROVIDER_ROUTE_UNAVAILABLE"


def test_resolver_uses_provider_default_without_a_reasoning_control(package_root: Path, tmp_path: Path) -> None:
    """Providers with no effort control must expose one provider-default route candidate."""
    routing = _routing_module()
    root, skill_sha256, suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")
    capability = _capability(model="claude-fixture", efforts=(), default=None)
    _write_seed(
        root,
        provider="claude",
        capability=capability,
        fingerprint=routing.capability_fingerprint(capability),
        reasoning_id="provider-default",
        skill_id="saw-rtc",
        skill_sha256=skill_sha256,
        suite_sha256=suite_sha256,
    )

    route = routing.resolve_skill_route(root, "saw-rtc", [_status("claude", capability)])

    assert route.identity.reasoning_id == "provider-default"


def test_resolver_accepts_provider_native_non_sage_effort_names(package_root: Path, tmp_path: Path) -> None:
    """A future provider's native effort IDs must not be forced into the Codex scale."""
    routing = _routing_module()
    root, skill_sha256, suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")
    capability = _capability(model="grok-fixture", efforts=("fast", "deliberate"), default="fast")
    _write_seed(
        root,
        provider="grok",
        capability=capability,
        fingerprint=routing.capability_fingerprint(capability),
        reasoning_id="fast",
        skill_id="saw-rtc",
        skill_sha256=skill_sha256,
        suite_sha256=suite_sha256,
    )

    route = routing.resolve_skill_route(root, "saw-rtc", [_status("grok", capability)])

    assert route.identity.reasoning_id == "fast"


def test_resolver_rejects_an_unseen_model_as_unassessed(package_root: Path, tmp_path: Path) -> None:
    """A live model without exact qualification evidence must remain unroutable."""
    routing = _routing_module()
    root, _skill_sha256, _suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")

    with pytest.raises(ValidationError) as caught:
        routing.resolve_skill_route(root, "saw-rtc", [_status("codex", _capability())])

    assert caught.value.code == "NO_QUALIFIED_SKILL_ROUTE"


def test_legacy_workflow_recommendation_is_an_exact_skill_route_facade(
    package_root: Path, tmp_path: Path
) -> None:
    """Compatibility callers must receive evidence for the registered Skill, not a profile guess."""
    routing = _routing_module()
    root, skill_sha256, suite_sha256 = _route_workspace(package_root, tmp_path, "bic-inspect")
    capability = _capability(model="gpt-5.6-terra")
    _write_seed(
        root,
        provider="codex",
        capability=capability,
        fingerprint=routing.capability_fingerprint(capability),
        reasoning_id="medium",
        skill_id="bic-inspect",
        skill_sha256=skill_sha256,
        suite_sha256=suite_sha256,
    )

    recommendation = recommend_model(
        root=root,
        status=_status("codex", capability),
        workflow="bic",
        operation="inspect",
    )

    assert recommendation.task_profile == "bic-inspect"
    assert recommendation.model == "gpt-5.6-terra"
    assert recommendation.reasoning_effort == "medium"
    assert recommendation.qualification_status == "RECOMMENDED"
    assert recommendation.selection_basis == "exact_skill_qualification"


def test_model_service_exposes_recommendation_by_exact_skill(
    package_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Operator services must request a registered Skill rather than a workflow profile."""
    routing = _routing_module()
    root, skill_sha256, suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")
    capability = _capability()
    status = _status("codex", capability)
    _write_seed(
        root,
        provider="codex",
        capability=capability,
        fingerprint=routing.capability_fingerprint(capability),
        reasoning_id="medium",
        skill_id="saw-rtc",
        skill_sha256=skill_sha256,
        suite_sha256=suite_sha256,
    )
    service = ModelService(root)
    monkeypatch.setattr(service, "probe", lambda *_args, **_kwargs: (status, None))

    result = service.recommendation_for_skill("saw-rtc")

    assert result["status"] == "RECOMMENDED"
    assert result["skill_id"] == "saw-rtc"
    assert result["provider"] == "codex"
    assert result["model_id"] == "gpt-5.6-sol"
    assert result["reasoning_id"] == "medium"


def test_model_service_lists_blocked_and_recommended_skills_separately(
    package_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One qualified Skill must not make unrelated unassessed Skills appear ready."""
    routing = _routing_module()
    root, skill_sha256, suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")
    capability = _capability()
    status = _status("codex", capability)
    _write_seed(
        root,
        provider="codex",
        capability=capability,
        fingerprint=routing.capability_fingerprint(capability),
        reasoning_id="medium",
        skill_id="saw-rtc",
        skill_sha256=skill_sha256,
        suite_sha256=suite_sha256,
    )
    service = ModelService(root)
    monkeypatch.setattr(service, "probe", lambda *_args, **_kwargs: (status, None))

    result = service.skill_routes()
    rows = {row["skill_id"]: row for row in result["skills"]}

    assert result["status"] == "PARTIALLY_ROUTABLE"
    assert rows["saw-rtc"]["qualification"] == "RECOMMENDED"
    assert rows["saw-stc"]["qualification"] == "UNASSESSED"
    assert rows["saw-stc"]["reason_code"] == "NO_QUALIFIED_SKILL_ROUTE"


def test_available_model_catalog_lists_exact_qualified_skill_routes(
    package_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catalog rows must expose exact Skill/reasoning evidence without becoming a selector."""
    routing = _routing_module()
    root, skill_sha256, suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")
    capability = _capability()
    status = _status("codex", capability)
    _write_seed(
        root,
        provider="codex",
        capability=capability,
        fingerprint=routing.capability_fingerprint(capability),
        reasoning_id="medium",
        skill_id="saw-rtc",
        skill_sha256=skill_sha256,
        suite_sha256=suite_sha256,
    )
    service = ModelService(root)
    monkeypatch.setattr(service, "probe", lambda *_args, **_kwargs: (status, None))

    result = service.list_models("codex")

    assert result["selected_model"] is None
    assert result["models"][0]["qualified_skill_routes"] == [
        {
            "skill_id": "saw-rtc",
            "reasoning_id": "medium",
            "qualification": "RECOMMENDED",
            "evidence_sha256": "b" * 64,
        }
    ]


def test_release_provider_preference_breaks_only_otherwise_equal_route_ties(
    package_root: Path, tmp_path: Path
) -> None:
    """Changing the declared final tie-break must deterministically change an equal route choice."""
    routing = _routing_module()
    root, skill_sha256, suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")
    a_capability = _capability(model="a-model")
    z_capability = _capability(model="z-model")
    _write_seed(
        root,
        provider="z-provider",
        capability=z_capability,
        fingerprint=routing.capability_fingerprint(z_capability),
        reasoning_id="medium",
        skill_id="saw-rtc",
        skill_sha256=skill_sha256,
        suite_sha256=suite_sha256,
    )
    seed_path = root / "system/config/model-qualification-seeds.json"
    z_row = json.loads(seed_path.read_text(encoding="utf-8"))["routes"][0]
    _write_seed(
        root,
        provider="a-provider",
        capability=a_capability,
        fingerprint=routing.capability_fingerprint(a_capability),
        reasoning_id="medium",
        skill_id="saw-rtc",
        skill_sha256=skill_sha256,
        suite_sha256=suite_sha256,
    )
    seeds = json.loads(seed_path.read_text(encoding="utf-8"))
    seeds["routes"].append(z_row)
    seed_path.write_text(json.dumps(seeds, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    statuses = [_status("a-provider", a_capability), _status("z-provider", z_capability)]
    policy_path = root / "system/config/model-policy.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["release_preference"] = {"providers": ["z-provider", "a-provider"]}
    _write_yaml(policy_path, policy)

    first = routing.resolve_skill_route(root, "saw-rtc", statuses)
    policy["release_preference"] = {"providers": ["a-provider", "z-provider"]}
    _write_yaml(policy_path, policy)
    second = routing.resolve_skill_route(root, "saw-rtc", statuses)

    assert first.identity.provider == "z-provider"
    assert second.identity.provider == "a-provider"
