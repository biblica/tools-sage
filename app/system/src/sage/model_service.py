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
from .llm_settings import (
    SAGE_LOCAL_ADMIN_MODEL,
    load_llm_settings,
    save_llm_settings,
    update_llm_selection,
)
from .model_language_competency import (
    exact_language_assessed,
    known_language_rows,
    load_competency_policy,
    lookup_language as lookup_language_competency,
    model_record as language_competency_model_record,
    operator_rows as language_competency_operator_rows,
)
from .storage import storage_layout
from .model_policy import (
    cache_provider_catalog,
    ensure_reasoning_effort_supported,
    load_model_policy,
    recommend_model,
)
from .skill_routing import resolve_skill_route


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
            "settings_path": str(storage_layout(self.root).state_root / "llm-settings.json"),
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
        """Refresh one live provider catalog without changing persisted model selection."""
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
        if status.model_capabilities:
            policy = load_model_policy(self.root)
            for capability in status.model_capabilities:
                qualifications: list[dict[str, Any]] = []
                for skill_id in policy["skill_routes"]:
                    try:
                        route = resolve_skill_route(self.root, skill_id, [status])
                    except ValidationError:
                        continue
                    if route.identity.model_id != capability.model:
                        continue
                    qualifications.append(
                        {
                            "skill_id": skill_id,
                            "reasoning_id": route.identity.reasoning_id,
                            "qualification": route.qualification,
                            "evidence_sha256": route.evidence_sha256,
                        }
                    )
                rows.append(
                    {
                        **capability.to_dict(),
                        "reasoning_efforts": list(capability.reasoning_efforts),
                        "qualified_skill_routes": qualifications,
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

    def _routing_statuses(self) -> list[ProviderStatus]:
        """Probe every build-enabled automated provider once for route resolution."""
        return [
            self.probe(provider_id, use_selection=False, cache_catalog=False)[0]
            for provider_id in ENABLED_AUTOMATED_PROVIDER_IDS
        ]

    def recommendation_for_skill(self, skill_id: str) -> dict[str, Any]:
        """Return the current exact evidence-qualified route for one registered Skill."""
        route = resolve_skill_route(self.root, skill_id, self._routing_statuses())
        return {"status": "RECOMMENDED", **route.to_dict()}

    def skill_routes(self) -> dict[str, Any]:
        """Return independent readiness for every registered Skill under one catalog snapshot."""
        statuses = self._routing_statuses()
        policy = load_model_policy(self.root)
        rows: list[dict[str, Any]] = []
        ready_count = 0
        for skill_id in policy["skill_routes"]:
            try:
                route = resolve_skill_route(self.root, skill_id, statuses)
            except ValidationError as exc:
                qualification = {
                    "SKILL_ROUTE_EVIDENCE_STALE": "STALE",
                    "PROVIDER_ROUTE_UNAVAILABLE": "QUALIFIED",
                }.get(exc.code, "UNASSESSED")
                rows.append(
                    {
                        "skill_id": skill_id,
                        "availability": (
                            "UNAVAILABLE"
                            if exc.code == "PROVIDER_ROUTE_UNAVAILABLE"
                            else "AVAILABLE"
                        ),
                        "qualification": qualification,
                        "routing_mode": "AUTOMATIC",
                        "reason_code": exc.code,
                        "diagnostic": exc.message,
                    }
                )
            else:
                ready_count += 1
                rows.append({**route.to_dict(), "reason_code": None, "diagnostic": ""})
        overall = "READY" if ready_count == len(rows) else ("PARTIALLY_ROUTABLE" if ready_count else "BLOCKED")
        return {
            "status": overall,
            "routing_mode": "AUTOMATIC",
            "ready_skills": ready_count,
            "total_skills": len(rows),
            "skills": rows,
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

    def language_competency_status(self, provider: str = "codex") -> dict[str, Any]:
        """Return versioned registry evidence for the current concrete model release."""
        provider_id = provider.strip().lower()
        settings = self.settings()
        item = settings["providers"].get(provider_id, {})
        executor = make_executor(provider_id, settings)
        status = executor.status(
            model=item.get("model") if str(item.get("selection_mode") or "AUTO").upper() != "AUTO" else None,
            reasoning_effort=item.get("reasoning_effort"),
        )
        if not status.ready or not status.selected_model:
            return {
                "status": "ACTION_REQUIRED",
                "provider": provider_id,
                "model": status.selected_model,
                "provider_runtime_version": status.version,
                "record": None,
                "rows": [],
                "diagnostic": status.diagnostic,
            }
        record = language_competency_model_record(self.root, provider_id, status.selected_model)
        return {
            "status": "READY" if record is not None else "EVIDENCE_REQUIRED",
            "provider": provider_id,
            "model": status.selected_model,
            "model_version": status.selected_model,
            "provider_runtime_version": status.version,
            "record": record,
            "rows": language_competency_operator_rows(record),
            "policy": load_competency_policy(self.root).get("policy", {}),
            "diagnostic": status.diagnostic,
        }

    def lookup_language_competency(
        self,
        languages: list[dict[str, str]],
        *,
        provider: str = "codex",
    ) -> dict[str, Any]:
        """Resolve requested languages from versioned evidence without model self-assessment."""
        status = self.language_competency_status(provider)
        if status.get("status") == "ACTION_REQUIRED":
            return status
        record = status.get("record")
        assessments: list[dict[str, Any]] = []
        missing: list[str] = []
        for requested in languages:
            tag = str(requested.get("canonical_tag") or "").strip()
            if not tag:
                raise ValidationError(
                    "Language competency lookup requires canonical_tag",
                    code="MODEL_LANGUAGE_COMPETENCY_INVALID",
                )
            evidence = lookup_language_competency(record, tag)
            if evidence is None:
                missing.append(tag)
                assessments.append(
                    {
                        "canonical_tag": tag,
                        "language": str(requested.get("language") or tag),
                        "region": str(requested.get("region") or ""),
                        "script": str(requested.get("script") or ""),
                        "tier": "UNASSESSED",
                        "confidence": "NOT_ASSESSED",
                        "basis": [],
                        "limitations": [
                            "No versioned registry or measured evaluation evidence is available for this model/language."
                        ],
                        "operator_message": "No competency claim is made without registered evidence.",
                        "assessment_source": "NO_REGISTERED_EVIDENCE",
                    }
                )
                continue
            row = dict(evidence)
            row.update(
                {
                    "canonical_tag": tag,
                    "language": str(requested.get("language") or row.get("language") or tag),
                    "region": str(requested.get("region") or row.get("region") or ""),
                    "script": str(requested.get("script") or row.get("script") or ""),
                }
            )
            assessments.append(row)
        return {
            "status": "REGISTRY_EVIDENCE_MISSING" if missing else "REGISTRY_EVIDENCE_READY",
            "provider": status.get("provider"),
            "model": status.get("model"),
            "model_version": status.get("model_version"),
            "provider_runtime_version": status.get("provider_runtime_version"),
            "assessments": assessments,
            "missing_languages": missing,
            "assessment_source": "VERSIONED_REGISTRY_OR_MEASURED_EVALUATION",
        }

    def lookup_current_model_languages(self, provider: str = "codex") -> dict[str, Any]:
        """Resolve all SAGE-known languages from the versioned competency registry."""
        return self.lookup_language_competency(known_language_rows(self.root), provider=provider)

    def lookup_imported_language_competency(
        self,
        *,
        canonical_tag: str,
        language_name: str,
        script: str = "",
        region: str = "",
        provider: str = "codex",
    ) -> dict[str, Any]:
        """Resolve one imported language without asking a model to assess itself."""
        status = self.language_competency_status(provider)
        if status.get("status") == "ACTION_REQUIRED":
            return status
        if status.get("status") == "EVIDENCE_REQUIRED":
            known = known_language_rows(
                self.root,
                extra=[{
                    "canonical_tag": canonical_tag,
                    "language": language_name,
                    "script": script,
                    "region": region,
                }],
            )
            result = self.lookup_language_competency(known, provider=provider)
            result["trigger"] = "NEW_MODEL_RELEASE"
            return result
        record = status.get("record")
        if exact_language_assessed(record, canonical_tag):
            inherited = lookup_language_competency(record, canonical_tag)
            return {
                "status": "EVIDENCE_ALREADY_REGISTERED",
                "provider": status.get("provider"),
                "model": status.get("model"),
                "model_version": status.get("model_version"),
                "provider_runtime_version": status.get("provider_runtime_version"),
                "assessment": inherited,
            }
        result = self.lookup_language_competency(
            [{
                "canonical_tag": canonical_tag,
                "language": language_name,
                "script": script,
                "region": region,
            }],
            provider=provider,
        )
        result["trigger"] = "NEW_LANGUAGE"
        return result

    def readiness_check(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        """Check configured provider/model readiness without generating model output."""
        settings = self.settings()
        provider_id = (provider or settings["selected_provider"]).strip().lower()
        if provider_id not in PROVIDER_IDS:
            raise ConfigurationError(f"Unsupported LLM provider: {provider_id}")
        item = settings["providers"].get(provider_id, {})
        resolved_model = model if model is not None else item.get("model")
        resolved_reasoning = (
            reasoning_effort if reasoning_effort is not None else item.get("reasoning_effort")
        )
        status, _ = self.probe(provider_id, settings=settings, cache_catalog=False)
        if not status.ready:
            raise ValidationError(status.diagnostic, code="LLM_PROVIDER_NOT_READY")
        if provider_id == "codex" and resolved_reasoning:
            ensure_reasoning_effort_supported(self.policy(), resolved_reasoning)
        return {
            "status": "READY",
            "provider": provider_id,
            "model": status.selected_model or resolved_model,
            "reasoning_effort": status.selected_reasoning_effort or resolved_reasoning,
            "auth_mode": status.auth_mode,
            "version": status.version,
            "diagnostic": status.diagnostic,
            "generation_tested": False,
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
        if provider_id == "ollama":
            if model is not None and model.strip() != SAGE_LOCAL_ADMIN_MODEL:
                raise ConfigurationError(
                    f"SAGE supports only {SAGE_LOCAL_ADMIN_MODEL} for the local admin assistant"
                )
            model = SAGE_LOCAL_ADMIN_MODEL
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
