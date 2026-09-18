"""Timer-driven DB-backed SQS evaluation worker."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from .db import Database
from .domain import EvidenceBasis
from .evaluation.packs import load_pack_catalog
from .evaluation.lifecycle import replan_repository
from .evaluation.runner import run_planned_test
from .providers.openai_provider import OpenAIProvider
from .qualification import synthesize_qualification
from .repository import Repository


def claim_next_planned_test(repo: Repository) -> dict[str, Any] | None:
    return repo.claim_next_evaluation()


class Worker:
    def __init__(self, repo: Repository, *, provider, pack_dir: Path, execution_channel: str):
        self.repo = repo
        self.provider = provider
        self.pack_dir = Path(pack_dir)
        self.execution_channel = execution_channel

    def run_once(self) -> bool:
        item = claim_next_planned_test(self.repo)
        if item is None:
            return False
        run_id = str(item["id"])
        try:
            provider_family = str(item.get("provider_family", "openai"))
            profile = self.repo.latest_profile(str(item["profile_id"]))
            model = self.repo.latest_model(provider_family, str(item["model_id"]))
            if profile is None or profile.status != "ACTIVE":
                raise RuntimeError("PROFILE_NOT_ACTIVE")
            if model is None or model.status != "APPROVED":
                raise RuntimeError("MODEL_NOT_APPROVED")
            pack = load_pack_catalog(self.pack_dir).get((profile.profile_id, str(item["capability"])))
            if pack is None:
                raise RuntimeError("EXACT_EVALUATION_PACK_MISSING")
            if pack.review_state != "READY":
                raise RuntimeError("EVALUATION_PACK_NOT_READY")
            result = run_planned_test(
                pack=pack,
                provider=self.provider,
                model=model,
                starting_reasoning=str(item.get("reasoning", "medium")),
                scope=str(item.get("scope", "FULL")),
            )
            qualification = synthesize_qualification(
                model=model,
                profile=profile,
                capability=str(item["capability"]),
                run=result,
                evidence_basis=EvidenceBasis.CONFIRMED if str(item.get("scope", "FULL")) == "CONFIRMATION" else EvidenceBasis.MEASURED,
                route_value="HIGH",
                execution_channel=self.execution_channel,
            )
            self.repo.save_evaluation_attempt(run_id, {
                "minimum_reasoning": result.minimum_reasoning,
                "quality_score": result.quality_score,
                "reliability_score": result.reliability_score,
                "total_input_tokens": result.total_input_tokens,
                "total_output_tokens": result.total_output_tokens,
                "estimated_unit_cost_usd": result.estimated_unit_cost_usd,
                "reasoning_runs": [run.reasoning for run in result.reasoning_runs],
            })
            self.repo.save_qualification(qualification)
            self.repo.complete_evaluation(run_id)
            replan_repository(self.repo, self.pack_dir)
            return True
        except Exception as exc:
            self.repo.fail_evaluation(run_id, str(exc))
            self.repo.upsert_attention(
                attention_key=f"EVALUATION_FAILURE:{run_id}",
                category="EVALUATION_FAILURE",
                severity="HIGH",
                summary="Evaluation run failed",
                payload={"run_id": run_id, "error": str(exc)},
            )
            return True

    def drain(self, *, max_items: int | None = None) -> int:
        processed = 0
        while max_items is None or processed < max_items:
            if not self.run_once():
                break
            processed += 1
        return processed


def drain(repo: Repository, *, provider=None, pack_dir: Path | None = None, execution_channel: str | None = None) -> int:
    if provider is None:
        # NOTE: this default path is the api_key execution channel (raw OpenAI API
        # key), which SAGE's governed policy currently prohibits -- SAGE hosts must
        # pass an explicit provider/execution_channel for the codex_workspace
        # channel instead. This default is only exercised directly against SQS
        # (e.g. ADMIN-driven qualification runs), never reachable from SAGE.
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required on the worker host")
        provider = OpenAIProvider(api_key)
    if pack_dir is None:
        pack_dir = Path(os.environ.get("SQS_PACK_DIR", "/etc/sage-sqs/evaluation-packs"))
    if execution_channel is None:
        execution_channel = os.environ.get("SQS_EXECUTION_CHANNEL")
        if not execution_channel:
            raise RuntimeError("SQS_EXECUTION_CHANNEL is required on the worker host")
    Worker(repo, provider=provider, pack_dir=pack_dir, execution_channel=execution_channel).drain()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drain", action="store_true", required=True)
    parser.parse_args()
    repo = Repository(Database.open(Path(os.environ.get("SQS_DB_PATH", "/var/lib/sage-sqs/sqs.db"))))
    return drain(repo)
