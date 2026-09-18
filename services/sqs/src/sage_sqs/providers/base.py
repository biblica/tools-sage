"""Provider adapter contract used by the SQS evaluator."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderResult:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    usage_raw: dict[str, Any]


class ProviderAdapter(Protocol):
    def execute(self, *, model_id: str, reasoning: str, prompt: str) -> ProviderResult: ...
