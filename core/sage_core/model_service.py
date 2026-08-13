"""Shared provider discovery, model policy, selection, and connectivity operations."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .build_policy import ENABLED_AUTOMATED_PROVIDER_IDS, provider_is_enabled
from .errors import ConfigurationError, ValidationError
from .executors import PROVIDER_IDS, ProviderRequest, ProviderStatus, make_executor
from .executors.codex_cli import CodexCLIExecutor
from .llm_settings import load_llm_settings, save_llm_settings, update_llm_selection
from .model_policy import (
    cache_provider_catalog,
    ensure_reasoning_effort_supported,
    load_model_policy,
    qualification_for,
    recommend_model,
)


class ModelService:
    """Provide one policy-aware model/provider API for both CLI and menu surfaces."""

    # Read-only queries never persist provider capability state; explicit refresh/selection owns cache writes.

    def __init__(self, root: Path) -> None:
        """Bind provider operations to one SAGE workspace root."""
        self.root = root.expanduser().resolve()

    def settings(self) -> dict[str, Any]:
        """Return the current non-secret local provider settings."""
        return load_llm_settings(self.root)

    def probe(
        self,
        provider: str,
        *,
        use_selection: bool = True,
        settings: dict[str, Any] | None = None,
        cache_catalog: bool = True,
    ) -> tuple[ProviderStatus, Path | None]:
        """Probe one provider and cache live Codex capability metadata when available."""
        provider_id = provider.strip().lower()
        if provider_id not in PROVIDER_IDS:
            raise ConfigurationError(f"Unsupported LLM provider: {provider}")
        current = settings or self.settings()
        item = current["providers"].get(provider_id, {})
        if not provider_is_enabled(provider_id):
            return (
                ProviderStatus(
                    provider=provider_id,
                    available=False,
                    ready=False,
                    auth_mode="LOCAL_NONE",
                    endpoint=item.get("endpoint"),
                    selected_model=item.get("model"),
                    diagnostic=f"{provider_id} is provisionable but disabled by this build policy; CODEX is the only enabled automated provider.",
                    capabilities=("provisionable", "build_disabled"),
                ),
                None,
            )
        executor = make_executor(provider_id, current)
        status = executor.status(
            model=item.get("model") if use_selection else None,
            reasoning_effort=item.get("reasoning_effort") if use_selection else None,
        )
        cache_path = None
        if provider_id == "codex" and status.model_capabilities and cache_catalog:
            cache_path = cache_provider_catalog(self.root, status)
        return status, cache_path

    def status(self, provider: str | None = None) -> dict[str, Any]:
        """Return readiness for one provider or the complete configured provider set."""
        settings = self.settings()
        providers = [provider.strip().lower()] if provider else list(PROVIDER_IDS)
        rows: list[dict[str, Any]] = []
        if len(providers) == 1:
            probe_results = [self.probe(providers[0], settings=settings, cache_catalog=False)]
        else:
            # Provider probes are independent and read-only; parallelism bounds aggregate diagnostic latency.
            with ThreadPoolExecutor(max_workers=len(providers), thread_name_prefix="sage-provider-status") as pool:
                futures = {
                    provider_id: pool.submit(
                        self.probe,
                        provider_id,
                        settings=settings,
                        cache_catalog=False,
                    )
                    for provider_id in providers
                }
                probe_results = [futures[provider_id].result() for provider_id in providers]
        for status, cache_path in probe_results:
            row = status.to_dict()
            if cache_path:
                row["catalog_cache"] = str(cache_path)
            rows.append(row)
        return {
            "status": "READY" if any(row["ready"] for row in rows) else "ACTION_REQUIRED",
            "selected_provider": settings["selected_provider"],
            "providers": rows,
            "policy": settings["policy"],
            "settings_path": str(self.root / "state" / "llm-settings.json"),
        }

    def quick_codex_status(self) -> dict[str, Any]:
        """Return a cheap Codex installation/authentication preflight for normal SAGE startup."""
        status = CodexCLIExecutor().quick_status()
        return status.to_dict()

    def install_codex(self) -> dict[str, Any]:
        """Install Codex CLI after the caller has obtained explicit operator consent."""
        status = CodexCLIExecutor().install()
        return status.to_dict()

    def connect_chatgpt(self, *, device_auth: bool = False) -> dict[str, Any]:
        """Connect Codex to OpenAI through ChatGPT-managed CLI sign-in; never accept API credentials."""
        executor = CodexCLIExecutor()
        status = executor.connect_chatgpt(device_auth=device_auth)
        value = update_llm_selection(self.root, provider="codex", auto=True)
        cache_path = cache_provider_catalog(self.root, status) if status.model_capabilities else None
        return {
            "status": "READY",
            "provider": "codex",
            "auth_mode": status.auth_mode,
            "account_plan_type": status.account_plan_type,
            "selected_provider": value["selected_provider"],
            "selection_mode": value["providers"]["codex"].get("selection_mode"),
            "model_count": len(status.model_capabilities),
            "catalog_cache": str(cache_path) if cache_path else None,
            "diagnostic": status.diagnostic,
        }

    def refresh(self, provider: str) -> dict[str, Any]:
        """Refresh one live provider catalogue without changing persisted model selection."""
        provider_id = provider.strip().lower()
        status, cache_path = self.probe(provider_id, use_selection=False)
        if not status.ready:
            raise ValidationError(status.diagnostic, code="LLM_PROVIDER_NOT_READY")
        return {
            "status": "REFRESHED",
            "provider": provider_id,
            "auth_mode": status.auth_mode,
            "account_plan_type": status.account_plan_type,
            "model_count": len(status.model_capabilities) if status.model_capabilities else len(status.models),
            "catalog_cache": str(cache_path) if cache_path else None,
        }

    def list_models(self, provider: str) -> dict[str, Any]:
        """Return live model rows with Codex reasoning levels and SAGE qualification."""
        provider_id = provider.strip().lower()
        settings = self.settings()
        status, cache_path = self.probe(provider_id, use_selection=False, settings=settings, cache_catalog=False)
        selected_item = settings["providers"].get(provider_id, {})
        selected_model = selected_item.get("model")
        rows: list[dict[str, Any]] = []
        if provider_id == "codex" and status.model_capabilities:
            policy = load_model_policy(self.root)
            for capability in status.model_capabilities:
                qualifications = [
                    profile
                    for profile in policy.get("task_profiles", {})
                    if qualification_for(policy, capability.model, profile)["qualified"]
                ]
                rows.append(
                    {
                        **capability.to_dict(),
                        "reasoning_efforts": list(capability.reasoning_efforts),
                        "qualified_profiles": qualifications,
                        "selected": capability.model == selected_model or capability.id == selected_model,
                    }
                )
        else:
            rows = [{"model": value, "selected": value == selected_model} for value in status.models]
        return {
            "status": "READY" if status.available else "UNAVAILABLE",
            "provider": provider_id,
            "ready": status.ready,
            "auth_mode": status.auth_mode,
            "account_plan_type": status.account_plan_type,
            "selected_model": selected_model,
            "selected_reasoning_effort": selected_item.get("reasoning_effort"),
            "selection_mode": selected_item.get("selection_mode"),
            "models": rows,
            "catalog_cache": str(cache_path) if cache_path else None,
            "diagnostic": status.diagnostic,
        }

    def recommendation(self, workflow: str, operation: str) -> dict[str, Any]:
        """Return the current live Codex recommendation for one governed task profile."""
        status, cache_path = self.probe("codex", use_selection=False, cache_catalog=False)
        if not status.ready:
            raise ValidationError(status.diagnostic, code="LLM_PROVIDER_NOT_READY")
        recommendation = recommend_model(
            root=self.root,
            status=status,
            workflow=workflow,
            operation=operation,
        )
        return {
            "status": "RECOMMENDED",
            **recommendation.to_dict(),
            "catalog_cache": str(cache_path) if cache_path else None,
        }

    def policy(self) -> dict[str, Any]:
        """Return the release-governed Codex qualification and reasoning policy."""
        return load_model_policy(self.root)

    def select(
        self,
        *,
        provider: str,
        model: str | None = None,
        endpoint: str | None = None,
        reasoning_effort: str | None = None,
        auto: bool = False,
    ) -> dict[str, Any]:
        """Persist one validated provider selection and return its current readiness."""
        provider_id = provider.strip().lower()
        if provider_id not in PROVIDER_IDS:
            raise ConfigurationError(f"Unsupported LLM provider: {provider}")
        if provider_id not in ENABLED_AUTOMATED_PROVIDER_IDS:
            raise ConfigurationError(
                f"Provider {provider_id} is provisionable but disabled for automated execution in this build"
            )
        if auto and provider_id != "codex":
            raise ConfigurationError("--auto is currently supported only for the codex provider")
        if auto and (model or reasoning_effort):
            raise ConfigurationError("--auto cannot be combined with --model or --reasoning")
        if provider_id == "codex" and reasoning_effort:
            ensure_reasoning_effort_supported(self.policy(), reasoning_effort)
        if provider_id == "codex" and not auto and (model or reasoning_effort):
            current = self.settings()
            live = make_executor("codex", current).status(
                model=model,
                reasoning_effort=reasoning_effort.strip().lower() if reasoning_effort else None,
            )
            if not live.ready:
                raise ValidationError(live.diagnostic, code="MODEL_SELECTION_NOT_AVAILABLE")
        value = update_llm_selection(
            self.root,
            provider=provider_id,
            model=model,
            endpoint=endpoint,
            reasoning_effort=reasoning_effort,
            auto=auto,
        )
        selected = value["selected_provider"]
        item = value["providers"][selected]
        status, cache_path = self.probe(selected, settings=value)
        return {
            "status": "READY" if status.ready else "SAVED_NOT_READY",
            "selected_provider": selected,
            "selected_model": item.get("model"),
            "selected_reasoning_effort": item.get("reasoning_effort"),
            "selection_mode": item.get("selection_mode"),
            "provider_status": status.to_dict(),
            "catalog_cache": str(cache_path) if cache_path else None,
            "policy": value["policy"],
        }

    def provision(
        self,
        *,
        provider: str,
        model: str | None = None,
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        """Persist non-secret configuration for an implemented provider without activating it."""
        provider_id = provider.strip().lower()
        if provider_id not in PROVIDER_IDS:
            raise ConfigurationError(f"Unsupported LLM provider: {provider}")
        if provider_id == "codex":
            raise ConfigurationError("CODEX uses `sage model use`; provisioning is for disabled local providers")
        value = self.settings()
        item = value["providers"][provider_id]
        if model is not None:
            item["model"] = model.strip() or None
        if endpoint is not None:
            from .executors.http import validate_local_endpoint
            item["endpoint"] = validate_local_endpoint(endpoint, provider=provider_id)
        save_llm_settings(self.root, value)
        return {
            "status": "PROVISIONED_DISABLED",
            "provider": provider_id,
            "enabled_for_execution": False,
            "model": item.get("model"),
            "endpoint": item.get("endpoint"),
        }

    def connectivity_test(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        """Run a minimal structured-output test through one selected provider."""
        settings = self.settings()
        provider_id = (provider or settings["selected_provider"]).strip().lower()
        if provider_id not in PROVIDER_IDS:
            raise ConfigurationError(f"Unsupported LLM provider: {provider_id}")
        item = settings["providers"].get(provider_id, {})
        resolved_model = model if model is not None else item.get("model")
        resolved_reasoning = (
            reasoning_effort if reasoning_effort is not None else item.get("reasoning_effort")
        )
        executor = make_executor(provider_id, settings)
        status = executor.status(model=resolved_model, reasoning_effort=resolved_reasoning)
        if not status.ready:
            raise ValidationError(status.diagnostic, code="LLM_PROVIDER_NOT_READY")
        if provider_id == "codex" and resolved_reasoning:
            ensure_reasoning_effort_supported(self.policy(), resolved_reasoning)
        selected_model = status.selected_model or resolved_model
        selected_reasoning = status.selected_reasoning_effort or resolved_reasoning
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["status"],
            "properties": {"status": {"type": "string", "const": "OK"}},
        }
        response = executor.execute(
            ProviderRequest(
                prompt="Return exactly one JSON object with status set to OK. Do not use tools or external context.",
                schema=schema,
                model=selected_model,
                reasoning_effort=selected_reasoning,
                timeout_seconds=timeout_seconds,
            )
        )
        try:
            parsed = json.loads(response.content.strip())
        except json.JSONDecodeError as exc:
            raise ValidationError(
                "Provider connectivity test returned invalid JSON",
                code="LLM_PROVIDER_RESPONSE_INVALID",
            ) from exc
        if parsed != {"status": "OK"}:
            raise ValidationError(
                "Provider connectivity test did not return the required result",
                code="LLM_PROVIDER_RESPONSE_INVALID",
            )
        return {
            "status": "READY",
            "provider": provider_id,
            "model": response.model or selected_model,
            "reasoning_effort": response.reasoning_effort or selected_reasoning,
            "provider_metadata": response.metadata,
        }
