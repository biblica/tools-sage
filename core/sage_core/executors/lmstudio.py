"""Direct localhost LM Studio executor using OpenAI-compatible endpoints without API credentials."""

from __future__ import annotations

from typing import Any

from ..errors import ValidationError
from .base import ProviderRequest, ProviderResponse, ProviderStatus
from .http import get_json, post_json, validate_local_endpoint


class LMStudioExecutor:
    """Execute sealed SAGE requests through the local LM Studio service."""

    provider_id = "lmstudio"

    def __init__(self, endpoint: str = "http://127.0.0.1:1234") -> None:
        """Bind the executor to one validated loopback LM Studio endpoint."""
        self.endpoint = validate_local_endpoint(endpoint, provider="LM Studio")

    def status(
        self,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> ProviderStatus:
        """Probe local availability and discover/select the requested model."""
        try:
            data = get_json(f"{self.endpoint}/v1/models")
            rows = data.get("data", []) if isinstance(data, dict) else []
            models = tuple(
                str(item.get("id"))
                for item in rows
                if isinstance(item, dict) and item.get("id")
            )
            ready = bool(models) and (model in models if model else True)
            diagnostic = (
                "LM Studio is ready."
                if ready
                else "LM Studio is reachable but the selected model is unavailable."
                if model
                else "LM Studio is reachable but no model is loaded/available."
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
                capabilities=("json_object", "localhost_only", "openai_compatible_transport"),
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
                capabilities=("json_object", "localhost_only", "openai_compatible_transport"),
            )

    def execute(self, request: ProviderRequest) -> ProviderResponse:
        """Send one sealed structured request after readiness checks."""
        if not request.model:
            raise ValidationError("LM Studio execution requires an explicit model", code="LLM_MODEL_REQUIRED")
        if request.reasoning_effort:
            raise ValidationError(
                f"{self.provider_id} does not expose a governed reasoning-effort catalog",
                code="LLM_REASONING_EFFORT_UNSUPPORTED",
            )
        status = self.status(model=request.model)
        if not status.ready:
            raise ValidationError(status.diagnostic, code="LLM_MODEL_NOT_READY")
        schema_text = __import__("json").dumps(request.schema, ensure_ascii=False, separators=(",", ":"))
        prompt = request.prompt + "\n\nReturn exactly one JSON object satisfying this JSON Schema:\n" + schema_text
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        data = post_json(f"{self.endpoint}/v1/chat/completions", payload, timeout=request.timeout_seconds)
        choices = data.get("choices", []) if isinstance(data, dict) else []
        content = None
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message", {})
            if isinstance(message, dict):
                content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("LM Studio returned no assistant content", code="LLM_PROVIDER_RESPONSE_INVALID")
        return ProviderResponse(
            provider=self.provider_id,
            model=request.model,
            content=content,
            metadata={"usage": data.get("usage", {}) if isinstance(data, dict) else {}},
        )
