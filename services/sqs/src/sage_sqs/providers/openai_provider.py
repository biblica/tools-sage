"""OpenAI provider registry and isolated Responses API adapter."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml

from ..domain import ModelRecord, ReasoningTier, canonical_sha256
from .base import ProviderResult

_PREMIUM = {"xhigh", "max"}


def model_fingerprint(*, model_id: str, reasoning_levels: Iterable[str], capability_rank: int,
                      cost_rank: int, input_usd_per_mtok: float, output_usd_per_mtok: float) -> str:
    """Return execution identity only; pricing/ranking are catalog metadata, not linguistic capability."""
    return canonical_sha256({
        "model_id": model_id,
        "reasoning_levels": list(reasoning_levels),
    })


def load_openai_catalog(path: str | Path) -> list[ModelRecord]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    provider_family = str(payload.get("provider_family", "openai"))
    rows: list[ModelRecord] = []
    for raw in payload.get("models") or []:
        levels = tuple(str(x) for x in raw.get("reasoning_levels") or [])
        fingerprint = model_fingerprint(
            model_id=str(raw["model_id"]),
            reasoning_levels=levels,
            capability_rank=int(raw.get("capability_rank", 0)),
            cost_rank=int(raw.get("cost_rank", 0)),
            input_usd_per_mtok=float(raw.get("input_usd_per_mtok", 0.0)),
            output_usd_per_mtok=float(raw.get("output_usd_per_mtok", 0.0)),
        )
        tiers = tuple(
            ReasoningTier(
                native_id=level,
                ordinal=index * 10,
                canonical_band=(level if level in {"low", "medium", "high"} else ("high" if level in {"xhigh", "max"} else None)),
                tier_class=("OFF" if level == "none" else "PREMIUM" if level in {"xhigh", "max"} else "ROUTINE"),
            )
            for index, level in enumerate(levels)
        )
        rows.append(ModelRecord(
            provider_family=provider_family,
            model_id=str(raw["model_id"]),
            status=str(raw.get("status", "CANDIDATE")),
            revision=1,
            reasoning_levels=levels,
            capability_fingerprint=fingerprint,
            input_usd_per_mtok=float(raw.get("input_usd_per_mtok", 0.0)),
            output_usd_per_mtok=float(raw.get("output_usd_per_mtok", 0.0)),
            capability_rank=int(raw.get("capability_rank", 0)),
            cost_rank=int(raw.get("cost_rank", 0)),
            reasoning_tiers=tiers,
            tier_mapping_revision=1,
            tier_mapping_approved=False,
        ))
    return rows


def routine_reasoning(model: ModelRecord) -> tuple[str, ...]:
    return model.routine_reasoning()


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

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
if TYPE_CHECKING:  # pragma: no cover
    from ..repository import Repository


@dataclass(frozen=True)
class CatalogSyncResult:
    model_id: str
    changed: bool
    revision: int
    status: str


def sync_provider_catalog(repo: "Repository", models: Iterable[ModelRecord]) -> list[CatalogSyncResult]:
    """Apply provider metadata as priors, invalidating evidence on fingerprint change."""
    results: list[CatalogSyncResult] = []
    for candidate in models:
        latest = repo.latest_model(candidate.provider_family, candidate.model_id)
        if latest is None:
            created = replace(candidate, revision=1, status="REVIEW_REQUIRED")
            repo.save_model(created)
            repo.upsert_attention(
                attention_key=f"MODEL_REVISION:{candidate.provider_family}:{candidate.model_id}:{created.revision}",
                category="MODEL_REVISION",
                severity="INFO",
                summary="New provider model requires ADMIN review",
                payload={"provider_family": candidate.provider_family, "model_id": candidate.model_id, "revision": created.revision},
            )
            repo.upsert_attention(
                attention_key=f"TIER_MAPPING_REVIEW:{candidate.provider_family}:{candidate.model_id}:{created.revision}",
                category="TIER_MAPPING_REVIEW", severity="HIGH",
                summary="Native reasoning tier mapping requires ADMIN approval",
                payload={"provider_family": candidate.provider_family, "model_id": candidate.model_id, "revision": created.revision,
                         "proposed_mapping": [tier.public_dict() for tier in created.reasoning_tiers]},
            )
            results.append(CatalogSyncResult(candidate.model_id, True, created.revision, created.status))
            continue
        if latest.capability_fingerprint == candidate.capability_fingerprint:
            if latest.catalog_fingerprint == candidate.catalog_fingerprint:
                results.append(CatalogSyncResult(candidate.model_id, False, latest.revision, latest.status))
                continue
            metadata = replace(
                candidate, revision=latest.revision + 1, status=latest.status,
                reasoning_tiers=latest.reasoning_tiers, tier_mapping_revision=latest.tier_mapping_revision,
                tier_mapping_fingerprint="", tier_mapping_approved=latest.tier_mapping_approved,
            )
            repo.save_model(metadata)
            repo.upsert_attention(
                attention_key=f"MODEL_METADATA:{candidate.provider_family}:{candidate.model_id}:{metadata.revision}",
                category="MODEL_METADATA_REVIEW", severity="INFO",
                summary="Provider model planning metadata changed; linguistic evidence remains valid",
                payload={"provider_family": candidate.provider_family, "model_id": candidate.model_id,
                         "previous_revision": latest.revision, "revision": metadata.revision,
                         "previous_catalog_fingerprint": latest.catalog_fingerprint,
                         "catalog_fingerprint": metadata.catalog_fingerprint},
            )
            repo.audit("SYSTEM", "MODEL_METADATA_CHANGED", {
                "provider_family": candidate.provider_family, "model_id": candidate.model_id,
                "previous_revision": latest.revision, "revision": metadata.revision,
            })
            results.append(CatalogSyncResult(candidate.model_id, True, metadata.revision, metadata.status))
            continue
        changed = replace(candidate, revision=latest.revision + 1, status="REVIEW_REQUIRED", tier_mapping_approved=False)
        repo.save_model(changed)
        repo.upsert_attention(
            attention_key=f"MODEL_REVISION:{candidate.provider_family}:{candidate.model_id}:{changed.revision}",
            category="MODEL_REVISION",
            severity="HIGH",
            summary="Provider model metadata changed; re-approval and re-evaluation required",
            payload={
                "provider_family": candidate.provider_family,
                "model_id": candidate.model_id,
                "previous_revision": latest.revision,
                "revision": changed.revision,
                "previous_fingerprint": latest.capability_fingerprint,
                "capability_fingerprint": changed.capability_fingerprint,
            },
        )
        repo.upsert_attention(
            attention_key=f"TIER_MAPPING_REVIEW:{candidate.provider_family}:{candidate.model_id}:{changed.revision}",
            category="TIER_MAPPING_REVIEW", severity="HIGH",
            summary="Native reasoning tier mapping requires ADMIN approval",
            payload={"provider_family": candidate.provider_family, "model_id": candidate.model_id, "revision": changed.revision,
                     "proposed_mapping": [tier.public_dict() for tier in changed.reasoning_tiers]},
        )
        repo.audit("SYSTEM", "MODEL_REVISION_CHANGED", {
            "provider_family": candidate.provider_family,
            "model_id": candidate.model_id,
            "previous_revision": latest.revision,
            "revision": changed.revision,
        })
        results.append(CatalogSyncResult(candidate.model_id, True, changed.revision, changed.status))
    return results
