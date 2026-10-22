"""Release-specific feature activation layered over provider capabilities."""

from __future__ import annotations

from .errors import ConfigurationError

BUILD_POLICY_VERSION = "0.02b1"
IMPLEMENTED_PROVIDER_IDS = ("codex", "claude", "ollama")
# Hosted providers reached through their own vendor CLI and the Operator's own subscription
# sign-in. Exactly one of them is the selected provider for all governed LLM work.
GOVERNED_CLI_PROVIDER_IDS = ("codex", "claude")
ENABLED_AUTOMATED_PROVIDER_IDS = ("codex",)
FUTURE_PROVIDER_IDS = ("grok", "gemini")


def enabled_provider_ids() -> tuple[str, ...]:
    """Return the providers this release permits for automated execution, read at call time."""
    return ENABLED_AUTOMATED_PROVIDER_IDS


def provider_is_enabled(provider: str) -> bool:
    """Return whether this release permits automated execution through one provider."""
    return provider.strip().lower() in enabled_provider_ids()


def disabled_provider_message(provider_id: str) -> str:
    """Explain that an implemented provider is not yet enabled by this build."""
    enabled = ", ".join(item.upper() for item in enabled_provider_ids())
    return (
        f"Provider {provider_id} is provisionable but disabled by the {BUILD_POLICY_VERSION} build policy "
        f"(disabled for automated execution); enabled automated providers in this build: {enabled}"
    )


def require_provider_enabled(provider: str) -> str:
    """Return a normalized enabled provider ID or fail closed under build policy."""
    provider_id = provider.strip().lower()
    if provider_id not in IMPLEMENTED_PROVIDER_IDS:
        raise ConfigurationError(f"Unsupported LLM provider: {provider}")
    if not provider_is_enabled(provider_id):
        raise ConfigurationError(disabled_provider_message(provider_id))
    return provider_id
