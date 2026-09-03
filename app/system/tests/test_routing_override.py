"""Provider-only settings migration and audited global routing override tests."""

from __future__ import annotations

import importlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import yaml

from sage.errors import ConfigurationError, ValidationError
from sage.executors.base import ModelCapability, ProviderStatus, ReasoningEffortOption
from sage.llm_settings import load_llm_settings, settings_path, update_llm_selection
from sage.model_service import ModelService
from sage.skill_routing import capability_fingerprint, resolve_skill_route


def _override_module():
    """Load the override API after proving the production module exists."""
    assert importlib.util.find_spec("sage.routing_override") is not None
    return importlib.import_module("sage.routing_override")


def _capability() -> ModelCapability:
    """Return one complete live provider capability."""
    return ModelCapability(
        id="gpt-5.6-sol",
        model="gpt-5.6-sol",
        display_name="GPT-5.6 Sol",
        supported_reasoning_efforts=tuple(
            ReasoningEffortOption(value) for value in ("low", "medium", "high")
        ),
        default_reasoning_effort="medium",
        is_default=True,
        identity_strength="ALIASED",
        cost_class="STANDARD",
    )


def _status(capability: ModelCapability, *, ready: bool = True) -> ProviderStatus:
    """Return one complete provider status snapshot."""
    return ProviderStatus(
        provider="codex",
        available=True,
        ready=ready,
        auth_mode="CHATGPT",
        version="1.2.3",
        model_capabilities=(capability,),
        diagnostic="ready" if ready else "offline",
    )


def _qualified_workspace(package_root: Path, tmp_path: Path) -> tuple[Path, ProviderStatus]:
    """Create one disposable workspace with RTC-only exact qualification evidence."""
    root = tmp_path / "routing" / "app"
    shutil.copytree(package_root, root)
    capability = _capability()
    policy_path = root / "system/config/model-policy.yml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    suite_sha256 = "a" * 64
    policy["skill_routes"]["saw-rtc"]["suite_sha256"] = suite_sha256
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    skills = json.loads((root / "system/config/skills.json").read_text(encoding="utf-8"))
    seeds = {
        "schema_version": "1.0",
        "routes": [
            {
                "provider": "codex",
                "model_id": capability.model,
                "capability_fingerprint": capability_fingerprint(capability),
                "reasoning_id": "medium",
                "skill_id": "saw-rtc",
                "skill_sha256": skills["skills"]["saw-rtc"]["adapted_sha256"],
                "suite_id": "alpha1-saw-rtc",
                "suite_sha256": suite_sha256,
                "policy_version": "alpha1-1",
                "qualification_status": "QUALIFIED",
                "evidence_sha256": "b" * 64,
                "cost_class": "STANDARD",
                "semantic_score": 1.0,
                "semantic_score_material": False,
            }
        ],
    }
    (root / "system/config/model-qualification-seeds.json").write_text(
        json.dumps(seeds, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root, _status(capability)


def test_legacy_model_fields_migrate_to_provider_only_settings(
    package_root: Path, tmp_path: Path
) -> None:
    """Legacy global model/reasoning values must not survive as operational state."""
    root = tmp_path / "settings" / "app"
    shutil.copytree(package_root, root)
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.2",
                "selected_provider": "codex",
                "providers": {
                    "codex": {
                        "model": "gpt-5.6-sol",
                        "reasoning_effort": "high",
                        "selection_mode": "EXPLICIT",
                    },
                    "ollama": {
                        "endpoint": "http://127.0.0.1:11434",
                        "admin_assistant_enabled": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    settings = load_llm_settings(root)

    assert settings["schema_version"] == "2.0"
    assert settings["selected_provider"] == "codex"
    assert settings["providers"]["codex"] == {"enabled": True}
    assert settings["providers"]["ollama"]["admin_assistant_enabled"] is True


def test_ordinary_selection_api_rejects_model_and_reasoning_persistence(
    package_root: Path, tmp_path: Path
) -> None:
    """Normal provider setup must direct model pins to the advanced override boundary."""
    root = tmp_path / "selection" / "app"
    shutil.copytree(package_root, root)

    with pytest.raises(ConfigurationError) as caught:
        update_llm_selection(
            root,
            provider="codex",
            model="gpt-5.6-sol",
            reasoning_effort="medium",
        )

    assert "advanced routing override" in caught.value.message


def test_setting_override_records_exact_route_and_skill_coverage(
    package_root: Path, tmp_path: Path
) -> None:
    """Enabling an override must persist exact identity and one auditable action receipt."""
    override = _override_module()
    root, status = _qualified_workspace(package_root, tmp_path)
    route = resolve_skill_route(root, "saw-rtc", [status])
    selection = {
        "provider": route.identity.provider,
        "model_id": route.identity.model_id,
        "capability_fingerprint": route.identity.capability_fingerprint,
        "reasoning_id": route.identity.reasoning_id,
    }

    result = override.set_global_override(root, selection=selection, statuses=[status])
    persisted = override.load_global_override(root)

    assert result["routing_mode"] == "GLOBAL_OVERRIDE"
    assert result["qualified_skill_count"] == 1
    assert result["registered_skill_count"] == 9
    assert result["qualified_skills"] == ["saw-rtc"]
    assert persisted["selection"] == selection
    receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["action"] == "ENABLE"
    assert receipt["previous_mode"] == "AUTOMATIC"
    assert receipt["qualified_skills"] == ["saw-rtc"]


def test_override_fails_closed_for_an_unqualified_skill(package_root: Path, tmp_path: Path) -> None:
    """A route qualified only for RTC must never execute STC under the global pin."""
    override = _override_module()
    root, status = _qualified_workspace(package_root, tmp_path)
    route = resolve_skill_route(root, "saw-rtc", [status])
    override.set_global_override(
        root,
        selection={
            "provider": route.identity.provider,
            "model_id": route.identity.model_id,
            "capability_fingerprint": route.identity.capability_fingerprint,
            "reasoning_id": route.identity.reasoning_id,
        },
        statuses=[status],
    )

    with pytest.raises(ValidationError) as caught:
        override.resolve_routing_mode(root, "saw-stc", [status])

    assert caught.value.code == "GLOBAL_OVERRIDE_NOT_QUALIFIED_FOR_SKILL"


def test_clearing_override_restores_automatic_and_preserves_a_receipt(
    package_root: Path, tmp_path: Path
) -> None:
    """Clearing a pin must remove active state without deleting its audit evidence."""
    override = _override_module()
    root, status = _qualified_workspace(package_root, tmp_path)
    route = resolve_skill_route(root, "saw-rtc", [status])
    override.set_global_override(
        root,
        selection={
            "provider": route.identity.provider,
            "model_id": route.identity.model_id,
            "capability_fingerprint": route.identity.capability_fingerprint,
            "reasoning_id": route.identity.reasoning_id,
        },
        statuses=[status],
    )

    result = override.clear_global_override(root)

    assert result["routing_mode"] == "AUTOMATIC"
    assert override.load_global_override(root) is None
    receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["action"] == "CLEAR"
    assert receipt["previous_mode"] == "GLOBAL_OVERRIDE"


def test_model_service_applies_override_mode_to_each_skill_status(
    package_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shared service status must show the pin and fail-closed Skill coverage truthfully."""
    root, status = _qualified_workspace(package_root, tmp_path)
    route = resolve_skill_route(root, "saw-rtc", [status])
    selection = {
        "provider": route.identity.provider,
        "model_id": route.identity.model_id,
        "capability_fingerprint": route.identity.capability_fingerprint,
        "reasoning_id": route.identity.reasoning_id,
    }
    service = ModelService(root)
    monkeypatch.setattr(service, "probe", lambda *_args, **_kwargs: (status, None))

    enabled = service.set_global_override(selection)
    rows = {row["skill_id"]: row for row in service.skill_routes()["skills"]}
    cleared = service.clear_global_override()

    assert enabled["qualified_skill_count"] == 1
    assert rows["saw-rtc"]["routing_mode"] == "GLOBAL_OVERRIDE"
    assert rows["saw-rtc"]["selection_mode"] == "USER_OVERRIDE"
    assert rows["saw-stc"]["reason_code"] == "GLOBAL_OVERRIDE_NOT_QUALIFIED_FOR_SKILL"
    assert cleared["routing_mode"] == "AUTOMATIC"
