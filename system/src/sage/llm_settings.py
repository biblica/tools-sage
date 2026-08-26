"""Persistent local SAGE LLM-provider selection with no API-key fields."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .storage import storage_layout
from .errors import ConfigurationError, ValidationError
from .build_policy import ENABLED_AUTOMATED_PROVIDER_IDS
from .executors import PROVIDER_IDS
from .executors.base import sage_supports_reasoning_effort
from .executors.http import validate_local_endpoint
from .ollama_policy import (
    SAGE_LOCAL_ADMIN_CONCURRENCY,
    SAGE_LOCAL_ADMIN_CONTEXT_WINDOW,
    SAGE_LOCAL_ADMIN_KEEP_ALIVE,
    SAGE_LOCAL_ADMIN_MODEL,
)


DEFAULT_LLM_SETTINGS: dict[str, Any] = {
    "schema_version": "1.2",
    "selected_provider": "codex",
    "providers": {
        "codex": {"model": None, "reasoning_effort": None, "selection_mode": "AUTO"},
        "ollama": {
            "model": SAGE_LOCAL_ADMIN_MODEL,
            "endpoint": "http://127.0.0.1:11434",
            "context_window": SAGE_LOCAL_ADMIN_CONTEXT_WINDOW,
            "keep_alive": SAGE_LOCAL_ADMIN_KEEP_ALIVE,
            "concurrency": SAGE_LOCAL_ADMIN_CONCURRENCY,
            "admin_assistant_enabled": False,
        },
    },
    "policy": {
        "openai_api_keys": "PROHIBITED",
        "remote_local_provider_endpoints": "PROHIBITED",
        "codex_required_auth": "CHATGPT",
    },
}

LOCAL_AI_AUTHORITY = "ASSISTIVE_ONLY"
LOCAL_AI_REPORTING_MODE = "SINGLE_LANGUAGE"
LOCAL_AI_EXTERNAL_RENDERING_REQUIRED = "LOCAL_AI_EXTERNAL_RENDERING_REQUIRED"


def settings_path(root: Path) -> Path:
    """Return the operator-owned provider-settings path under SAGE state."""
    return storage_layout(root).state_root / "llm-settings.json"


def local_ai_enabled(root: Path) -> bool:
    """Return whether the persisted assistive-only Local AI switch is enabled."""
    return bool(load_llm_settings(root)["providers"]["ollama"].get("admin_assistant_enabled", False))


def local_ai_policy_status(root: Path) -> dict[str, Any]:
    """Return normalized Local AI authority/reporting state without probing Ollama."""
    settings = load_llm_settings(root)
    item = dict(settings["providers"]["ollama"])
    enabled = bool(item.get("admin_assistant_enabled", False))
    return {
        "enabled": enabled,
        "provider": "ollama",
        "model": item.get("model"),
        "authority": LOCAL_AI_AUTHORITY,
        "readiness": "NOT_PROBED",
        "reporting_mode": LOCAL_AI_REPORTING_MODE if enabled else "MULTILINGUAL_AVAILABLE",
        "secondary_language_allowed": True,
        "enablement_blocked": False,
        "reason_code": None,
        "conflicts": [],
    }


def load_llm_settings(root: Path) -> dict[str, Any]:
    """Load provider selection while rejecting credential-bearing extensions."""
    path = settings_path(root)
    if not path.is_file():
        return json.loads(json.dumps(DEFAULT_LLM_SETTINGS))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Invalid LLM settings: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("LLM settings root must be an object")
    merged = json.loads(json.dumps(DEFAULT_LLM_SETTINGS))
    selected = str(raw.get("selected_provider", merged["selected_provider"])).strip().lower()
    if selected not in PROVIDER_IDS:
        raise ConfigurationError(f"Unsupported selected LLM provider: {selected}")
    # The current build policy activates CODEX only. Unsupported automated selections
    # normalize to CODEX while retaining non-secret provisioning settings.
    merged["selected_provider"] = (
        selected if selected in ENABLED_AUTOMATED_PROVIDER_IDS else "codex"
    )
    providers = raw.get("providers", {})
    if isinstance(providers, dict):
        for provider in PROVIDER_IDS:
            item = providers.get(provider)
            if isinstance(item, dict):
                merged["providers"][provider].update(
                    {
                        key: value
                        for key, value in item.items()
                        if key
                        in {
                            "model",
                            "endpoint",
                            "reasoning_effort",
                            "selection_mode",
                            "context_window",
                            "keep_alive",
                            "concurrency",
                            "admin_assistant_enabled",
                        }
                    }
                )
    merged["providers"]["ollama"]["endpoint"] = validate_local_endpoint(
        str(merged["providers"]["ollama"]["endpoint"]),
        provider="ollama",
    )
    ollama = merged["providers"]["ollama"]
    if ollama.get("model") != SAGE_LOCAL_ADMIN_MODEL:
        ollama["model"] = SAGE_LOCAL_ADMIN_MODEL
    ollama["context_window"] = SAGE_LOCAL_ADMIN_CONTEXT_WINDOW
    ollama["keep_alive"] = SAGE_LOCAL_ADMIN_KEEP_ALIVE
    ollama["concurrency"] = SAGE_LOCAL_ADMIN_CONCURRENCY
    ollama["admin_assistant_enabled"] = bool(ollama.get("admin_assistant_enabled", False))
    # Deliberately reject any credential-bearing extension rather than silently ignoring it.
    forbidden = {"api_key", "token", "secret", "authorization", "author" + "ization"}
    text_keys = {str(key).casefold() for key in raw.keys()}
    for item in providers.values() if isinstance(providers, dict) else []:
        if isinstance(item, dict):
            text_keys.update(str(key).casefold() for key in item.keys())
    if forbidden.intersection(text_keys):
        raise ConfigurationError("SAGE LLM settings must not contain API keys, tokens, or secrets")
    return merged


def save_llm_settings(root: Path, value: dict[str, Any]) -> Path:
    """Persist validated non-secret provider/model settings atomically."""
    # Re-load through the same validation path by writing a temporary logical structure in memory.
    selected = str(value.get("selected_provider", "")).strip().lower()
    if selected not in PROVIDER_IDS:
        raise ConfigurationError(f"Unsupported selected LLM provider: {selected}")
    if selected not in ENABLED_AUTOMATED_PROVIDER_IDS:
        raise ConfigurationError(
            f"Selected provider {selected} is disabled by this build policy; CODEX is the only enabled automated provider"
        )
    codex = value.get("providers", {}).get("codex", {})
    if str(codex.get("selection_mode", "AUTO")).upper() not in {"AUTO", "EXPLICIT"}:
        raise ConfigurationError("Codex selection_mode must be AUTO or EXPLICIT")
    effort = codex.get("reasoning_effort")
    if effort is not None and not isinstance(effort, str):
        raise ConfigurationError("Codex reasoning_effort must be a string or null")
    if isinstance(effort, str) and effort.strip() and not sage_supports_reasoning_effort(effort):
        raise ConfigurationError("Codex reasoning_effort exceeds the SAGE ceiling; highest supported level is xhigh")
    ollama = value.get("providers", {}).get("ollama", {})
    validate_local_endpoint(str(ollama.get("endpoint", "")), provider="ollama")
    ollama.update(
        {
            "model": SAGE_LOCAL_ADMIN_MODEL,
            "context_window": SAGE_LOCAL_ADMIN_CONTEXT_WINDOW,
            "keep_alive": SAGE_LOCAL_ADMIN_KEEP_ALIVE,
            "concurrency": SAGE_LOCAL_ADMIN_CONCURRENCY,
            "admin_assistant_enabled": bool(ollama.get("admin_assistant_enabled", False)),
        }
    )
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, value)
    return path


def set_local_admin_enabled(root: Path, enabled: bool) -> dict[str, Any]:
    """Enable or disable only the local admin assistant, never workflow execution."""
    value = load_llm_settings(root)
    value["providers"]["ollama"]["admin_assistant_enabled"] = bool(enabled)
    save_llm_settings(root, value)
    return value


def update_llm_selection(
    root: Path,
    *,
    provider: str,
    model: str | None = None,
    endpoint: str | None = None,
    reasoning_effort: str | None = None,
    auto: bool = False,
) -> dict[str, Any]:
    """Update the selected provider/model without accepting credential material."""
    value = load_llm_settings(root)
    provider_id = provider.strip().lower()
    if provider_id not in PROVIDER_IDS:
        raise ConfigurationError(f"Unsupported LLM provider: {provider}")
    if provider_id not in ENABLED_AUTOMATED_PROVIDER_IDS:
        raise ConfigurationError(f"Provider {provider_id} is provisionable but disabled for automated execution in this build")
    value["selected_provider"] = provider_id
    item = value["providers"][provider_id]
    if provider_id == "codex" and auto:
        item["model"] = None
        item["reasoning_effort"] = None
        item["selection_mode"] = "AUTO"
    elif model is not None:
        item["model"] = model.strip() or None
        if provider_id == "codex":
            item["selection_mode"] = "EXPLICIT"
            if reasoning_effort is None:
                item["reasoning_effort"] = None
    if reasoning_effort is not None:
        if provider_id != "codex":
            raise ConfigurationError("Reasoning-effort selection is currently supported only for Codex")
        if reasoning_effort.strip() and not sage_supports_reasoning_effort(reasoning_effort):
            raise ConfigurationError("Codex reasoning_effort exceeds the SAGE ceiling; highest supported level is xhigh")
        item["reasoning_effort"] = reasoning_effort.strip().lower() or None
        if item.get("model"):
            item["selection_mode"] = "EXPLICIT"
    if endpoint is not None:
        if provider_id == "codex":
            raise ConfigurationError("Codex provider does not accept an endpoint")
        item["endpoint"] = validate_local_endpoint(endpoint, provider=provider_id)
    save_llm_settings(root, value)
    return value
