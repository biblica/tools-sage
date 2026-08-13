"""Direct localhost Ollama executor with JSON-schema structured output."""

from __future__ import annotations

from typing import Any

from ..errors import ValidationError
from .base import ProviderRequest, ProviderResponse, ProviderStatus
from .http import get_json, post_json, validate_local_endpoint


class OllamaExecutor:
    """Execute sealed SAGE requests through the local Ollama service."""

    provider_id = "ollama"

    def __init__(self, endpoint: str = "http://127.0.0.1:11434") -> None:
        """Bind the executor to one validated loopback Ollama endpoint."""
        self.endpoint = validate_local_endpoint(endpoint, provider="Ollama")

    def status(
        self,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> ProviderStatus:
        """Probe local availability and discover/select the requested model."""
        try:
            data = get_json(f"{self.endpoint}/api/tags")
            rows = data.get("models", []) if isinstance(data, dict) else []
            models = tuple(
                str(item.get("name") or item.get("model"))
                for item in rows
                if isinstance(item, dict) and (item.get("name") or item.get("model"))
            )
            ready = bool(models) and (model in models if model else True)
            diagnostic = (
                "Ollama is ready."
                if ready
                else "Ollama is reachable but the selected model is unavailable."
                if model
                else "Ollama is reachable but no local models are installed."
            )
            return ProviderStatus(
                provider=self.provider_id,
                available=True,
                ready=ready,
                auth_mode="LOCAL_NONE",
                endpoint=self.endpoint,
                selected_model=model,
                selected_reasoning_effort=reasoning_effort,
                models=models,
                diagnostic=diagnostic,
                capabilities=("structured_output", "localhost_only"),
            )
        except ValidationError as exc:
            return ProviderStatus(
                provider=self.provider_id,
                available=False,
                ready=False,
                auth_mode="LOCAL_NONE",
                endpoint=self.endpoint,
                selected_model=model,
                selected_reasoning_effort=reasoning_effort,
                diagnostic=str(exc),
                capabilities=("structured_output", "localhost_only"),
            )

    def execute(self, request: ProviderRequest) -> ProviderResponse:
        """Send one sealed structured request after readiness checks."""
        if not request.model:
            raise ValidationError("Ollama execution requires an explicit model", code="LLM_MODEL_REQUIRED")
        if request.reasoning_effort:
            raise ValidationError(
                f"{self.provider_id} does not expose a governed reasoning-effort catalog",
                code="LLM_REASONING_EFFORT_UNSUPPORTED",
            )
        status = self.status(model=request.model)
        if not status.ready:
            raise ValidationError(status.diagnostic, code="LLM_MODEL_NOT_READY")
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "format": request.schema,
            "stream": False,
            "options": {"temperature": 0},
        }
        data = post_json(f"{self.endpoint}/api/chat", payload, timeout=request.timeout_seconds)
        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("Ollama returned no assistant content", code="LLM_PROVIDER_RESPONSE_INVALID")
        return ProviderResponse(
            provider=self.provider_id,
            model=request.model,
            content=content,
            metadata={
                key: data.get(key)
                for key in ("done_reason", "total_duration", "prompt_eval_count", "eval_count")
                if isinstance(data, dict) and key in data
            },
        )
