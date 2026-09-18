"""Repository-backed planner snapshot and deterministic replan lifecycle."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .packs import load_pack_catalog
from .planner import PlannedTest, plan_next_tests
from ..repository import Repository


def _estimated_pack_cost(pack, model) -> float:
    input_tokens = sum(case.estimated_input_tokens for case in pack.cases)
    output_tokens = sum(case.estimated_output_tokens for case in pack.cases)
    # Medium-first boundary normally executes at most two reasoning levels.
    return 2.0 * ((input_tokens / 1_000_000) * model.input_usd_per_mtok + (output_tokens / 1_000_000) * model.output_usd_per_mtok)


def build_planner_snapshot(repo: Repository, pack_dir: Path) -> dict[str, Any]:
    packs = load_pack_catalog(pack_dir)
    profiles = {profile.profile_id: profile for profile in repo.active_profiles()}
    models = repo.approved_models()
    qualifications = {
        (q.provider_family, q.model_id, q.profile_id, q.capability): q
        for q in repo.all_qualifications()
    }
    candidates: list[dict[str, Any]] = []
    for (profile_id, capability), pack in sorted(packs.items()):
        profile = profiles.get(profile_id)
        if profile is None or pack.review_state != "READY":
            continue
        for model in models:
            key = (model.provider_family, model.model_id, profile_id, capability)
            q = qualifications.get(key)
            if q is not None and q.model_capability_fingerprint == model.capability_fingerprint and q.profile_identity_sha256 == profile.evaluation_identity_sha256:
                continue
            predecessor_reasoning = repo.predecessor_boundary(model.model_id, profile_id, capability, provider_family=model.provider_family)
            candidates.append({
                "candidate_id": f"{model.provider_family}:{model.model_id}:{profile_id}:{capability}",
                "provider_family": model.provider_family,
                "model_id": model.model_id,
                "profile_id": profile_id,
                "capability": capability,
                "cluster": profile.cluster,
                "script": profile.script,
                "estimated_cost_usd": _estimated_pack_cost(pack, model),
                "unsupported_coverage": q is None,
                "predecessor_reasoning": predecessor_reasoning,
                "new_or_changed_model": predecessor_reasoning is not None,
                "generation_sentinel": predecessor_reasoning is not None and profile.tier == 1,
                "exact_confirmation_available": bool(pack.confirmation_cases()),
            })
    return {"candidates": candidates}


def replan_repository(repo: Repository, pack_dir: Path) -> list[PlannedTest]:
    rows = plan_next_tests(build_planner_snapshot(repo, pack_dir))
    queued_next = False
    for row in rows:
        repo.record_planner_event(
            disposition=row.disposition.value,
            reason_code=row.reason_code,
            payload={
                "candidate_id": row.candidate_id,
                "profile_id": row.profile_id,
                "model_id": row.model_id,
                "capability": row.capability,
                "reasoning": row.reasoning,
                "scope": row.scope,
                "benefit_points": row.benefit_points,
                "estimated_cost_usd": row.estimated_cost_usd,
            },
        )
        if row.disposition.value == "TEST" and not queued_next:
            repo.queue_test({
                "provider_family": "openai",
                "profile_id": row.profile_id,
                "model_id": row.model_id,
                "capability": row.capability,
                "reasoning": row.reasoning,
                "scope": row.scope,
            })
            queued_next = True
    return rows
