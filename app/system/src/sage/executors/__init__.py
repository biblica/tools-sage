"""SAGE provider-neutral executor registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..build_policy import GOVERNED_CLI_PROVIDER_IDS, IMPLEMENTED_PROVIDER_IDS, require_provider_enabled
from ..errors import ConfigurationError
from .base import Executor, ModelCapability, ProviderRequest, ProviderResponse, ProviderStatus, ReasoningEffortOption
from .claude_cli import ClaudeCLIExecutor
from .codex_cli import CodexCLIExecutor
from .ollama import OllamaExecutor

PROVIDER_IDS = IMPLEMENTED_PROVIDER_IDS


@dataclass(frozen=True)
class ProviderLabels:
    """Operator-facing names for one governed CLI provider."""

    service: str
    menu_name: str
    cli: str
    account: str
    auth_mode: str


PROVIDER_LABELS = {
    "codex": ProviderLabels(
        service="OpenAI / ChatGPT", menu_name="OpenAI and ChatGPT", cli="Codex CLI", account="ChatGPT",
        auth_mode="CHATGPT",
    ),
    "claude": ProviderLabels(
        service="Anthropic / Claude", menu_name="Anthropic and Claude", cli="Claude Code CLI",
        account="Claude subscription", auth_mode="CLAUDE_SUBSCRIPTION",
    ),
}


# Codex reports its model catalog live (app-server `model/list`); the Claude Code CLI has none,
# so SAGE routes Claude only over its reviewed static catalog.
PROVIDER_CATALOG_SOURCE = {"codex": "LIVE", "claude": "REVIEWED_STATIC"}


def receipt_transport_policy(provider: str) -> dict[str, Any]:
    """Return the sealed-transport policy block recorded on every governed execution receipt."""
    return {
        "provider_api_keys": "PROHIBITED",
        "sealed_transport": True,
        "sage_workspace_exposed_as_provider_cwd": False,
        "filesystem_writes_by_provider": False,
        "provider_catalog": PROVIDER_CATALOG_SOURCE.get(provider.strip().lower(), "UNKNOWN"),
    }


def provider_labels(provider: str) -> ProviderLabels:
    """Return operator-facing names for one governed CLI provider."""
    provider_id = provider.strip().lower()
    if provider_id not in PROVIDER_LABELS:
        raise ConfigurationError(f"Not a governed CLI provider: {provider}")
    return PROVIDER_LABELS[provider_id]


def cli_executor(provider: str) -> CodexCLIExecutor | ClaudeCLIExecutor:
    """Construct one governed CLI executor for setup actions, independent of build enablement."""
    provider_id = provider.strip().lower()
    if provider_id == "codex":
        return CodexCLIExecutor()
    if provider_id == "claude":
        return ClaudeCLIExecutor()
    raise ConfigurationError(f"Not a governed CLI provider: {provider}")


def make_evaluation_executor(provider: str, settings: dict[str, Any]) -> Executor:
    """Construct an executor for sealed synthetic qualification only.

    Evaluation sends no Scripture or Job evidence and is how a provider earns enablement, so an
    implemented governed CLI provider may be evaluated before the build policy enables it.
    """
    provider_id = provider.strip().lower()
    if provider_id in GOVERNED_CLI_PROVIDER_IDS:
        return cli_executor(provider_id)
    return make_executor(provider_id, settings)


def make_executor(provider: str, settings: dict[str, Any]) -> Executor:
    """Construct the selected executor from non-secret SAGE provider settings."""
    provider_id = require_provider_enabled(provider)
    providers = settings.get("providers", {}) if isinstance(settings, dict) else {}
    item = providers.get(provider_id, {}) if isinstance(providers, dict) else {}
    if provider_id in GOVERNED_CLI_PROVIDER_IDS:
        return cli_executor(provider_id)
    if provider_id == "ollama":
        return OllamaExecutor(
            str(item.get("endpoint", "http://127.0.0.1:11434")),
            context_window=int(item.get("context_window", 16_384)),
            keep_alive=int(item.get("keep_alive", 0)),
        )
    raise ConfigurationError(f"Unknown LLM provider: {provider}")


__all__ = [
    "Executor",
    "ModelCapability",
    "ReasoningEffortOption",
    "ProviderLabels",
    "ProviderRequest",
    "ProviderResponse",
    "ProviderStatus",
    "PROVIDER_IDS",
    "PROVIDER_LABELS",
    "cli_executor",
    "make_evaluation_executor",
    "make_executor",
    "provider_labels",
    "receipt_transport_policy",
]
