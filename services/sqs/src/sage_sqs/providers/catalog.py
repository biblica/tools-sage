"""Provider-family model catalogs: loading, tier mapping proposals, and ADMIN-reviewed sync.

A catalog file (`<family>-provider.yml`) is one model vendor's planning metadata. Pricing and ranks are
priors, never qualification evidence. `pack_token_scale` is how many tokens the family's tokenizer spends
on pack text relative to the o200k counts the evaluation packs are sized in (measured by SAGE's
`calibrate_token_estimator.py`); it only sharpens planning cost estimates.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

import yaml

from ..domain import ModelRecord, ReasoningTier, canonical_sha256

if TYPE_CHECKING:  # pragma: no cover
    from ..repository import Repository

_DEFAULT_ROUTINE = ("low", "medium", "high")
_DEFAULT_PREMIUM = ("xhigh", "max")


def model_fingerprint(*, model_id: str, reasoning_levels: Iterable[str], capability_rank: int,
                      cost_rank: int, input_usd_per_mtok: float, output_usd_per_mtok: float) -> str:
    """Return execution identity only; pricing/ranking are catalog metadata, not linguistic capability."""
    return canonical_sha256({
        "model_id": model_id,
        "reasoning_levels": list(reasoning_levels),
    })


def load_provider_catalog(path: str | Path) -> list[ModelRecord]:
    """Load one provider family's catalog with its declared routine and premium reasoning levels."""
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    provider_family = str(payload["provider_family"])
    routine = tuple(str(x) for x in payload.get("routine_reasoning_levels") or _DEFAULT_ROUTINE)
    premium = tuple(str(x) for x in payload.get("premium_reasoning_levels_not_routine") or _DEFAULT_PREMIUM)
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
                canonical_band=(level if level in routine else ("high" if level in premium else None)),
                tier_class=("OFF" if level == "none" else "PREMIUM" if level in premium else "ROUTINE"),
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
            pack_token_scale=float(raw.get("pack_token_scale", 1.0)),
        ))
    return rows


def catalog_paths(config_root: str | Path) -> list[Path]:
    """Return every provider-family catalog in a config or seed directory, in stable order."""
    return sorted(Path(config_root).glob("*-provider.yml"))


def routine_reasoning(model: ModelRecord) -> tuple[str, ...]:
    return model.routine_reasoning()


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
