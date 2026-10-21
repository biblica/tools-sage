"""Model catalog refresh contracts: changes are recorded, described, and never qualify a route."""

from __future__ import annotations

from sage.executors.base import ModelCapability, ProviderStatus, ReasoningEffortOption
from sage.model_policy import cache_provider_catalog, describe_catalog_change, load_cached_catalog


def _status(version: str, models: dict[str, tuple[str, ...]]) -> ProviderStatus:
    """Return a ready Codex status exposing the given models and reasoning levels."""
    return ProviderStatus(
        provider="codex",
        available=True,
        ready=True,
        auth_mode="CHATGPT",
        version=version,
        model_capabilities=tuple(
            ModelCapability(
                id=name,
                model=name,
                display_name=name,
                supported_reasoning_efforts=tuple(ReasoningEffortOption(value) for value in efforts),
            )
            for name, efforts in models.items()
        ),
    )


def test_first_snapshot_is_a_baseline_without_a_change(make_workspace) -> None:
    """The first listing has nothing to compare with and records no change."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    cache_provider_catalog(root, _status("0.163.0", {"gpt-a": ("low", "medium")}))

    snapshot = load_cached_catalog(root)

    assert snapshot["last_change"] is None
    assert snapshot["provider_runtime_version"] == "0.163.0"
    assert describe_catalog_change(snapshot["last_change"]) == []


def test_new_model_and_effort_after_cli_update_are_recorded_and_kept(make_workspace) -> None:
    """A CLI update that adds a model and a reasoning level is recorded and survives an unchanged re-listing."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    cache_provider_catalog(root, _status("0.163.0", {"gpt-a": ("low", "medium")}))
    cache_provider_catalog(root, _status("0.164.0", {"gpt-a": ("low", "medium", "max"), "gpt-b": ("medium",)}))

    change = load_cached_catalog(root)["last_change"]

    assert change["trigger"] == "PROVIDER_CLI_VERSION"
    assert change["previous_provider_runtime_version"] == "0.163.0"
    assert change["added_models"] == ["gpt-b"]
    assert change["added_efforts"] == {"gpt-a": ["max"]}
    assert change["removed_models"] == [] and change["removed_efforts"] == {}

    cache_provider_catalog(root, _status("0.164.0", {"gpt-a": ("low", "medium", "max"), "gpt-b": ("medium",)}))
    assert load_cached_catalog(root)["last_change"] == change

    text = "\n".join(describe_catalog_change(change))
    assert "New models: gpt-b" in text
    assert "New reasoning levels on gpt-a: max" in text
    assert "UNQUALIFIED" in text


def test_removed_models_and_server_side_changes_are_recorded(make_workspace) -> None:
    """A model withdrawn without any version change is a catalog change, not a CLI change."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    cache_provider_catalog(root, _status("0.164.0", {"gpt-a": ("medium",), "gpt-b": ("medium", "high")}))
    cache_provider_catalog(root, _status("0.164.0", {"gpt-a": ("medium",), "gpt-b": ("medium",)}))
    assert load_cached_catalog(root)["last_change"]["removed_efforts"] == {"gpt-b": ["high"]}
    assert load_cached_catalog(root)["last_change"]["trigger"] == "PROVIDER_CATALOG"

    cache_provider_catalog(root, _status("0.164.0", {"gpt-a": ("medium",)}))
    change = load_cached_catalog(root)["last_change"]

    assert change["removed_models"] == ["gpt-b"]
    assert "No longer offered: gpt-b" in "\n".join(describe_catalog_change(change))
