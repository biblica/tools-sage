"""Release-specific feature activation layered over provider capabilities."""

from __future__ import annotations

from .errors import ConfigurationError

BUILD_POLICY_VERSION = "0.01beta"
IMPLEMENTED_PROVIDER_IDS = ("codex", "ollama")
ENABLED_AUTOMATED_PROVIDER_IDS = ("codex",)
FUTURE_PROVIDER_IDS = ("grok", "gemini")


def provider_is_enabled(provider: str) -> bool:
    """Return whether this release permits automated execution through one provider."""
    return provider.strip().lower() in ENABLED_AUTOMATED_PROVIDER_IDS


def require_provider_enabled(provider: str) -> str:
    """Return a normalized enabled provider ID or fail closed under build policy."""
    provider_id = provider.strip().lower()
    if provider_id not in IMPLEMENTED_PROVIDER_IDS:
        raise ConfigurationError(f"Unsupported LLM provider: {provider}")
    if provider_id not in ENABLED_AUTOMATED_PROVIDER_IDS:
        raise ConfigurationError(
            f"Provider {provider_id} is provisionable but disabled by the {BUILD_POLICY_VERSION} build policy; "
            "CODEX is the only enabled automated provider in this build"
        )
    return provider_id
