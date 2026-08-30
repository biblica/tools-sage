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


def test_runtime_policy_declares_universal_no_data_provisional_routing(package_root: Path) -> None:
    """Adding a release-phase gate must not restrict the universal no-data fallback."""
    policy = load_model_policy(package_root)

    assert policy["provisional_routing"] == {
        "no_data_qualification_status": "PROVISIONAL_UNQUALIFIED",
        "default_reasoning_by_provider": {"codex": "medium"},
        "prohibited_reasoning_by_provider": {"codex": ["none", "minimal", "low"]},
        "known_negative_effect": "BLOCK",
        "stale_evidence_effect": "BLOCK",
    }


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
    assert route.selection_mode == "EXACT_SKILL_QUALIFICATION"
    assert route.routing_basis_sha256 is None


def test_resolver_accepts_a_replaceable_qualification_evidence_repository(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """Routing depends on a repository API, allowing a verified service cache to replace files."""
    routing = _routing_module()
    root, skill_sha256, suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")
    capability = _capability()
    requested_skills: list[str] = []

    class ServiceCacheRepository:
        """Return one already verified route as a future local service/cache adapter would."""

        def records_for_skill(self, skill_id: str):
            """Record the bounded lookup and return exact qualification evidence."""
            requested_skills.append(skill_id)
            return [{
                "provider": "codex",
                "model_id": capability.model,
                "capability_fingerprint": routing.capability_fingerprint(capability),
                "reasoning_id": "medium",
                "skill_id": "saw-rtc",
                "skill_sha256": skill_sha256,
                "suite_id": "alpha1-saw-rtc",
                "suite_sha256": suite_sha256,
                "policy_version": "alpha1-1",
                "qualification_status": "QUALIFIED",
                "evidence_sha256": "d" * 64,
                "cost_class": capability.cost_class,
                "semantic_score": 1.0,
                "semantic_score_material": False,
            }]

    route = routing.resolve_skill_route(
        root,
        "saw-rtc",
        [_status("codex", capability)],
        evidence_repository=ServiceCacheRepository(),
    )

    assert requested_skills == ["saw-rtc"]
    assert route.identity.model_id == capability.model
    assert route.identity.reasoning_id == "medium"
    assert route.evidence_sha256 == "d" * 64


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


def test_resolver_uses_medium_provisionally_when_no_evidence_exists(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """Removing the Alpha no-data branch must return the obsolete no-qualified-route error."""
    routing = _routing_module()
    root, _skill_sha256, _suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")

    route = routing.resolve_skill_route(root, "saw-rtc", [_status("codex", _capability())])

    assert route.identity.provider == "codex"
    assert route.identity.model_id == "gpt-5.6-sol"
    assert route.identity.reasoning_id == "medium"
    assert route.qualification == "PROVISIONAL_UNQUALIFIED"
    assert route.selection_mode == "PROVISIONAL_PROVIDER_DEFAULT"
    assert route.evidence_sha256 is None
    assert route.routing_basis_sha256 is not None


def test_resolver_uses_qualification_data_instead_of_no_data_medium(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """Ignoring current data must leave automatic routing on the no-data Medium fallback."""
    routing = _routing_module()
    root, skill_sha256, suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")
    capability = _capability()
    provisional = routing.resolve_skill_route(root, "saw-rtc", [_status("codex", capability)])
    assert provisional.identity.reasoning_id == "medium"
    assert provisional.selection_mode == "PROVISIONAL_PROVIDER_DEFAULT"

    _write_seed(
        root,
        provider="codex",
        capability=capability,
        fingerprint=routing.capability_fingerprint(capability),
        reasoning_id="high",
        skill_id="saw-rtc",
        skill_sha256=skill_sha256,
        suite_sha256=suite_sha256,
    )
    qualified = routing.resolve_skill_route(root, "saw-rtc", [_status("codex", capability)])
    assert qualified.identity.reasoning_id == "high"
    assert qualified.qualification == "RECOMMENDED"
    assert qualified.selection_mode == "EXACT_SKILL_QUALIFICATION"


@pytest.mark.parametrize(
    ("qualification_status", "reason_code"),
    (("FAILED", "MODEL_QUALIFICATION_FAILED"), ("UNRELIABLE", "MODEL_QUALIFICATION_UNRELIABLE")),
)
def test_resolver_blocks_known_adverse_evidence_instead_of_using_provisional(
    package_root: Path,
    tmp_path: Path,
    qualification_status: str,
    reason_code: str,
) -> None:
    """Dropping an adverse-evidence branch must incorrectly make a tested bad route executable."""
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
        status=qualification_status,
    )

    with pytest.raises(ValidationError) as caught:
        routing.resolve_skill_route(root, "saw-rtc", [_status("codex", capability)])

    assert caught.value.code == reason_code


def test_resolver_uses_medium_without_a_release_state_gate(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """A true no-data state must use Medium independently of release phase."""
    routing = _routing_module()
    root, _skill_sha256, _suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")
    standard_path = root / "system/config/sage-standard.json"
    standard = json.loads(standard_path.read_text(encoding="utf-8"))
    standard["release"]["status"] = "RELEASE_CANDIDATE"
    standard_path.write_text(json.dumps(standard, indent=2) + "\n", encoding="utf-8")

    route = routing.resolve_skill_route(root, "saw-rtc", [_status("codex", _capability())])

    assert route.identity.reasoning_id == "medium"
    assert route.qualification == "PROVISIONAL_UNQUALIFIED"


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


def test_legacy_workflow_recommendation_labels_automatic_no_data_medium(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """Calling a no-data route evidence-qualified must make the compatibility result fail."""
    root, _skill_sha256, _suite_sha256 = _route_workspace(
        package_root,
        tmp_path,
        "bic-inspect",
    )

    recommendation = recommend_model(
        root=root,
        status=_status("codex", _capability()),
        workflow="bic",
        operation="inspect",
    )

    assert recommendation.complexity == "PROVISIONAL_NO_DATA"
    assert recommendation.reasoning_effort == "medium"
    assert recommendation.qualification_status == "PROVISIONAL_UNQUALIFIED"
    assert recommendation.qualification_basis.startswith("provisional routing policy ")
    assert recommendation.selection_basis == "automatic_no_data_default"


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


def test_model_service_lists_qualified_and_provisional_skills_separately(
    package_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Folding provisional rows into qualified status must make the truthful counts fail."""
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

    assert result["status"] == "READY_PROVISIONAL"
    assert result["qualified_skills"] == 1
    assert result["provisional_skills"] == len(REGISTERED_SKILLS) - 1
    assert rows["saw-rtc"]["qualification"] == "RECOMMENDED"
    assert rows["saw-stc"]["qualification"] == "PROVISIONAL_UNQUALIFIED"
    assert rows["saw-stc"]["selection_mode"] == "PROVISIONAL_PROVIDER_DEFAULT"
    assert rows["saw-stc"]["reason_code"] is None


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
    assert {
        item["skill_id"] for item in result["models"][0]["provisional_skill_routes"]
    } == set(REGISTERED_SKILLS) - {"saw-rtc"}
    assert all(
        item["qualification"] == "PROVISIONAL_UNQUALIFIED"
        and item["evidence_sha256"] is None
        for item in result["models"][0]["provisional_skill_routes"]
    )


def test_model_service_reports_no_data_route_as_provisional(
    package_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard-coding recommendation status must mislabel an unqualified no-data route."""
    root, _skill_sha256, _suite_sha256 = _route_workspace(package_root, tmp_path, "saw-rtc")
    service = ModelService(root)
    status = _status("codex", _capability())
    monkeypatch.setattr(service, "probe", lambda *_args, **_kwargs: (status, None))

    result = service.recommendation_for_skill("saw-rtc")

    assert result["status"] == "PROVISIONAL_UNQUALIFIED"
    assert result["qualification"] == "PROVISIONAL_UNQUALIFIED"
    assert result["selection_mode"] == "PROVISIONAL_PROVIDER_DEFAULT"
    assert result["reasoning_id"] == "medium"
    assert result["evidence_sha256"] is None


def test_legacy_model_service_does_not_hardcode_recommended_for_no_data(
    package_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard-coding the compatibility status must contradict its provisional recommendation body."""
    root, _skill_sha256, _suite_sha256 = _route_workspace(
        package_root,
        tmp_path,
        "bic-inspect",
    )
    service = ModelService(root)
    status = _status("codex", _capability())
    monkeypatch.setattr(service, "probe", lambda *_args, **_kwargs: (status, None))

    result = service.recommendation("bic", "inspect")

    assert result["status"] == "PROVISIONAL_UNQUALIFIED"
    assert result["qualification_status"] == "PROVISIONAL_UNQUALIFIED"


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
