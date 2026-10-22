"""OpenAI Responses API adapter (the api_key execution channel on an SQS worker host).

The provider catalog machinery lives in `catalog.py`; these names are kept for existing callers.
"""
from __future__ import annotations

from .base import ProviderResult
from .catalog import (  # noqa: F401 - re-exported for existing callers
    CatalogSyncResult,
    load_provider_catalog,
    model_fingerprint,
    routine_reasoning,
    sync_provider_catalog,
)

load_openai_catalog = load_provider_catalog


class OpenAIProvider:
    """Lazy OpenAI Responses API adapter so public/API hosts need no OpenAI SDK."""

    def __init__(self, api_key: str):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - deployment-only dependency path
            raise RuntimeError("OpenAI SDK is required only on the SQS worker host") from exc
        self.client = OpenAI(api_key=api_key)

    def execute(self, *, model_id: str, reasoning: str, prompt: str) -> ProviderResult:
        response = self.client.responses.create(model=model_id, reasoning={"effort": reasoning}, input=prompt)
        usage = response.usage.model_dump() if getattr(response, "usage", None) else {}
        return ProviderResult(
            text=response.output_text,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            usage_raw=usage,
        )
