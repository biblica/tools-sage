"""Provider-neutral execution contracts for SAGE governed LLM tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ReasoningEffortOption:
    """One provider-advertised reasoning level in provider-defined progression order."""

    reasoning_effort: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Render the reasoning option for CLI/menu output."""
        return asdict(self)


@dataclass(frozen=True)
class ModelCapability:
    """One live provider model entry with reasoning metadata and no credential material."""

    id: str
    model: str
    display_name: str
    description: str = ""
    supported_reasoning_efforts: tuple[ReasoningEffortOption, ...] = ()
    default_reasoning_effort: str | None = None
    is_default: bool = False
    hidden: bool = False
    input_modalities: tuple[str, ...] = ()
    supports_personality: bool | None = None
    model_specialty: str | None = None
    service_tiers: tuple[str, ...] = ()
    default_service_tier: str | None = None
    identity_strength: str = "ALIASED"
    cost_class: str = "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        """Render one model capability entry for policy/diagnostic output."""
        return asdict(self)

    @property
    def reasoning_efforts(self) -> tuple[str, ...]:
        """Return reasoning effort IDs without changing provider-advertised order."""
        return tuple(item.reasoning_effort for item in self.supported_reasoning_efforts)


@dataclass(frozen=True)
class ProviderStatus:
    """One provider readiness snapshot with no secret material."""

    provider: str
    available: bool
    ready: bool
    auth_mode: str = "NONE"
    version: str | None = None
    endpoint: str | None = None
    selected_model: str | None = None
    selected_reasoning_effort: str | None = None
    models: tuple[str, ...] = ()
    model_capabilities: tuple[ModelCapability, ...] = ()
    account_plan_type: str | None = None
    diagnostic: str = ""
    capabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Render a provider status snapshot for CLI/menu reporting."""
        return asdict(self)


@dataclass(frozen=True)
class ProviderRequest:
    """Sealed model request assembled by SAGE, independent of provider transport."""

    prompt: str
    schema: dict[str, Any]
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: int = 600


@dataclass(frozen=True)
class ProviderResponse:
    """Raw provider result after transport-level success."""

    provider: str
    model: str | None
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    reasoning_effort: str | None = None


class Executor(Protocol):
    """Minimal interface every SAGE LLM provider implements."""

    provider_id: str

    def status(
        self,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> ProviderStatus:
        """Return non-mutating readiness information for one provider/model."""
        ...

    def execute(self, request: ProviderRequest) -> ProviderResponse:
        """Execute one sealed request and return raw structured provider content."""
        ...
