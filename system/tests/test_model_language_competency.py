"""Regression coverage for model-release-specific estimated language competency."""

from pathlib import Path

from sage.executors.base import ModelCapability, ProviderStatus, ReasoningEffortOption
from sage.model_language_competency import (
    exact_language_assessed,
    load_competency_policy,
    load_competency_registry,
    lookup_language,
    model_record,
    model_release_key,
)
from sage.model_service import ModelService

ROOT = Path(__file__).resolve().parents[2]


def test_release_seed_is_model_specific_and_keeps_plain_tier_names() -> None:
    """The bundled heuristic table belongs to one model release and tiers are not suffixed with 'estimated'."""
    policy = load_competency_policy(ROOT)
    assert policy["policy"]["tiers"] == ["EXCELLENT", "GOOD", "FAIR", "UNASSESSED"]
    seed = policy["seed_models"][0]
    assert seed["provider"] == "codex"
    assert seed["model"] == "gpt-5.6-terra"
    assert seed["model_version"] == "gpt-5.6-terra"
    assert seed["languages"]["en-US"]["tier"] == "EXCELLENT"
    assert seed["languages"]["fa-IR"]["tier"] == "GOOD"
    assert seed["languages"]["ti-ER"]["tier"] == "FAIR"


def test_regional_seed_uses_operational_country_or_region_keys(make_workspace) -> None:
    """The operator table uses regional/scripted BCP-47 identities rather than bare language keys."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    record = model_record(root, "codex", "gpt-5.6-terra")
    assert lookup_language(record, "uk-UA")["tier"] == "GOOD"
    assert exact_language_assessed(record, "uk-UA") is True
    assert exact_language_assessed(record, "sw-KE") is False


class _FakeCompetencyExecutor:
    """Provide provider status and fail if competency lookup attempts generation."""

    def __init__(self, model: str) -> None:
        """Bind the fake executor to one concrete model release."""
        self.model = model

    def status(self, *, model=None, reasoning_effort=None):
        """Return a ready provider snapshot with medium reasoning support."""
        selected = model or self.model
        capability = ModelCapability(
            id=selected,
            model=selected,
            display_name=selected,
            supported_reasoning_efforts=(ReasoningEffortOption("medium"),),
            default_reasoning_effort="medium",
            is_default=True,
        )
        return ProviderStatus(
            provider="codex",
            available=True,
            ready=True,
            auth_mode="CHATGPT",
            version="OpenAI Codex v9.9.9",
            selected_model=selected,
            model_capabilities=(capability,),
            models=(selected,),
        )

    def execute_prevalidated(self, request, status):
        """Prove that registry lookup never asks the model to rate itself."""
        raise AssertionError("language competency lookup must not execute the model")

    def execute(self, request):
        """Prove that readiness and registry lookup remain non-generative."""
        raise AssertionError("non-generative model service path attempted execution")


def test_provider_readiness_check_does_not_generate_model_output(make_workspace, monkeypatch) -> None:
    """Readiness resolves runtime/model state through status only."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    fake = _FakeCompetencyExecutor("gpt-5.6-terra")
    monkeypatch.setattr("sage.model_service.make_executor", lambda provider, settings: fake)

    result = ModelService(root).readiness_check()

    assert result["status"] == "READY"
    assert result["model"] == "gpt-5.6-terra"
    assert result["generation_tested"] is False


def test_new_model_release_remains_unassessed_without_registry_evidence(make_workspace, monkeypatch) -> None:
    """A newly observed model release cannot create evidence by rating itself."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    fake = _FakeCompetencyExecutor("gpt-6-new")
    monkeypatch.setattr("sage.model_service.make_executor", lambda provider, settings: fake)
    service = ModelService(root)
    result = service.lookup_language_competency(
        [{"canonical_tag": "uk-UA", "language": "Ukrainian", "region": "UA", "script": "Cyrl"}],
    )
    assert result["model"] == "gpt-6-new"
    assert result["status"] == "REGISTRY_EVIDENCE_MISSING"
    assert result["assessments"][0]["tier"] == "UNASSESSED"
    registry = load_competency_registry(root)
    assert model_release_key("codex", "gpt-5.6-terra") in registry["models"]
    assert model_release_key("codex", "gpt-6-new") not in registry["models"]


def test_new_imported_language_is_unassessed_without_exact_or_base_evidence(make_workspace, monkeypatch) -> None:
    """A new regional language is not appended from an unverified model opinion."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    fake = _FakeCompetencyExecutor("gpt-5.6-terra")
    monkeypatch.setattr("sage.model_service.make_executor", lambda provider, settings: fake)
    service = ModelService(root)
    result = service.lookup_imported_language_competency(
        canonical_tag="sw-KE", language_name="Swahili", region="KE", script="Latn"
    )
    assert result["trigger"] == "NEW_LANGUAGE"
    assert result["status"] == "REGISTRY_EVIDENCE_MISSING"
    assert result["assessments"][0]["tier"] == "UNASSESSED"
    record = model_record(root, "codex", "gpt-5.6-terra")
    assert exact_language_assessed(record, "sw-KE") is False
