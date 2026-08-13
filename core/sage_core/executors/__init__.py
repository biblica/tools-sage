"""SAGE provider-neutral executor registry."""

from __future__ import annotations

from typing import Any

from ..build_policy import IMPLEMENTED_PROVIDER_IDS, require_provider_enabled
from ..errors import ConfigurationError
from .base import Executor, ModelCapability, ProviderRequest, ProviderResponse, ProviderStatus, ReasoningEffortOption
from .codex_cli import CodexCLIExecutor
from .lmstudio import LMStudioExecutor
from .ollama import OllamaExecutor

PROVIDER_IDS = IMPLEMENTED_PROVIDER_IDS


def make_executor(provider: str, settings: dict[str, Any]) -> Executor:
    """Construct the selected executor from non-secret SAGE provider settings."""
    provider_id = require_provider_enabled(provider)
    providers = settings.get("providers", {}) if isinstance(settings, dict) else {}
    item = providers.get(provider_id, {}) if isinstance(providers, dict) else {}
    if provider_id == "codex":
        return CodexCLIExecutor()
    if provider_id == "ollama":
        return OllamaExecutor(str(item.get("endpoint", "http://127.0.0.1:11434")))
    if provider_id == "lmstudio":
        return LMStudioExecutor(str(item.get("endpoint", "http://127.0.0.1:1234")))
    raise ConfigurationError(f"Unknown LLM provider: {provider}")


__all__ = [
    "Executor",
    "ModelCapability",
    "ReasoningEffortOption",
    "ProviderRequest",
    "ProviderResponse",
    "ProviderStatus",
    "PROVIDER_IDS",
    "make_executor",
]
