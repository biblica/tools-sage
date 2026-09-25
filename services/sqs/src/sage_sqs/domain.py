"""Immutable SQS domain records and stable evaluation identities."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any



class Capability(StrEnum):
    GRAMMAR_ANALYSIS = "GRAMMAR_ANALYSIS"
    SEMANTIC_REWRITE = "SEMANTIC_REWRITE"


class QualificationStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"
    UNASSESSED = "UNASSESSED"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RouteValue(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EvidenceBasis(StrEnum):
    MEASURED = "MEASURED"
    CONFIRMED = "CONFIRMED"


class PlannerDisposition(StrEnum):
    TEST = "TEST"
    DEFER = "DEFER"
    PRUNE = "PRUNE"
    MEASURED = "MEASURED"
    CONFIRMED = "CONFIRMED"

def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class LanguageProfile:
    profile_id: str
    display_name: str
    status: str
    revision: int
    tier: int
    cluster: str
    iso_639_1: str
    iso_639_3: str
    script: str
    region: str

    @property
    def evaluation_identity_sha256(self) -> str:
        return canonical_sha256({
            "profile_id": self.profile_id,
            "revision": self.revision,
            "tier": self.tier,
            "cluster": self.cluster,
            "iso_639_1": self.iso_639_1,
            "iso_639_3": self.iso_639_3,
            "script": self.script,
            "region": self.region,
        })

    def public_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "tier": self.tier,
            "cluster": self.cluster,
            "script": self.script,
            "region": self.region,
            "revision": self.revision,
            "evaluation_identity_sha256": self.evaluation_identity_sha256,
        }



@dataclass(frozen=True)
class ExecutionChannelDescriptor:
    """How a governed host actually reaches a provider_family's models.

    Distinct from provider_family (the model vendor): a qualification is keyed on
    the model itself so it never needs re-testing just because the access channel
    changes, while execution_channel records which channel actually produced the
    evidence.
    """

    execution_channel: str
    provider_family: str
    display_name: str
    provisioning_model: str
    capability_classes: tuple[str, ...]
    reasoning_tier_taxonomy: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "execution_channel": self.execution_channel,
            "provider_family": self.provider_family,
            "display_name": self.display_name,
            "provisioning_model": self.provisioning_model,
            "capability_classes": list(self.capability_classes),
            "reasoning_tier_taxonomy": self.reasoning_tier_taxonomy,
        }


@dataclass(frozen=True)
class ReasoningTier:
    native_id: str
    ordinal: int
    canonical_band: str | None
    tier_class: str = "ROUTINE"

    def public_dict(self) -> dict[str, Any]:
        return {
            "native_id": self.native_id,
            "ordinal": self.ordinal,
            "canonical_band": self.canonical_band,
            "tier_class": self.tier_class,
        }


@dataclass(frozen=True)
class ModelRecord:
    provider_family: str
    model_id: str
    status: str
    revision: int
    reasoning_levels: tuple[str, ...]
    capability_fingerprint: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    capability_rank: int = 0
    cost_rank: int = 0
    reasoning_tiers: tuple[ReasoningTier, ...] = ()
    tier_mapping_revision: int = 0
    tier_mapping_fingerprint: str = ""
    tier_mapping_approved: bool = True

    def __post_init__(self) -> None:
        tiers = self.reasoning_tiers
        if not tiers:
            tiers = tuple(ReasoningTier(value, index * 10 + 10, value if value in {"low", "medium", "high"} else None, "ROUTINE" if value in {"low", "medium", "high"} else "UNUSED") for index, value in enumerate(self.reasoning_levels))
            object.__setattr__(self, "reasoning_tiers", tiers)
        if not self.tier_mapping_fingerprint:
            object.__setattr__(self, "tier_mapping_fingerprint", canonical_sha256([tier.public_dict() for tier in tiers]))
        if self.tier_mapping_revision == 0 and tiers:
            object.__setattr__(self, "tier_mapping_revision", 1)

    def routine_reasoning(self) -> tuple[str, ...]:
        return tuple(t.native_id for t in sorted(self.reasoning_tiers, key=lambda item: item.ordinal) if t.tier_class == "ROUTINE")

    @property
    def catalog_fingerprint(self) -> str:
        return canonical_sha256({
            "provider_family": self.provider_family,
            "model_id": self.model_id,
            "reasoning_levels": list(self.reasoning_levels),
            "capability_rank": self.capability_rank,
            "cost_rank": self.cost_rank,
            "input_usd_per_mtok": self.input_usd_per_mtok,
            "output_usd_per_mtok": self.output_usd_per_mtok,
        })

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider_family": self.provider_family,
            "model_id": self.model_id,
            "reasoning_levels": list(self.routine_reasoning()),
            "reasoning_tiers": [tier.public_dict() for tier in self.reasoning_tiers],
            "tier_mapping_revision": self.tier_mapping_revision,
            "tier_mapping_fingerprint": self.tier_mapping_fingerprint,
            "capability_rank": self.capability_rank,
            "cost_rank": self.cost_rank,
            "input_usd_per_mtok": self.input_usd_per_mtok,
            "output_usd_per_mtok": self.output_usd_per_mtok,
            "capability_fingerprint": self.capability_fingerprint,
        }


@dataclass(frozen=True)
class Qualification:
    provider_family: str
    execution_channel: str
    model_id: str
    model_capability_fingerprint: str
    profile_id: str
    profile_identity_sha256: str
    capability: str
    status: str
    minimum_reasoning: str | None
    quality_score: float
    reliability_score: float
    confidence: str
    value: str
    evidence_basis: str
    estimated_unit_cost_usd: float
    evaluated_at: str
    evidence_sha256: str
    minimum_native_reasoning: str | None = None
    tier_mapping_fingerprint: str | None = None

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.status == "NOT_QUALIFIED":
            value["minimum_reasoning"] = None
            value["minimum_native_reasoning"] = None
        elif value.get("minimum_native_reasoning") is None:
            value["minimum_native_reasoning"] = value.get("minimum_reasoning")
        return value
