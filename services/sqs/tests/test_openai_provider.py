from pathlib import Path

from sage_sqs.providers.base import ProviderResult
from sage_sqs.providers.openai_provider import (
    load_openai_catalog,
    model_fingerprint,
    routine_reasoning,
)


def catalog():
    path = Path(__file__).resolve().parents[1] / "seed" / "openai-provider.yml"
    return {m.model_id: m for m in load_openai_catalog(path)}


def test_routine_reasoning_excludes_premium():
    terra = catalog()["gpt-5.6-terra"]
    assert routine_reasoning(terra) == ("low", "medium", "high")


def test_provider_position_is_planning_prior_not_evidence():
    rows = catalog()
    assert rows["gpt-5.6-luna"].capability_rank == 1
    assert rows["gpt-5.6-terra"].capability_rank == 2
    assert rows["gpt-5.6-sol"].capability_rank == 3


def test_runtime_fingerprint_ignores_price_but_changes_with_reasoning_set():
    terra = catalog()["gpt-5.6-terra"]
    original = model_fingerprint(
        model_id=terra.model_id,
        reasoning_levels=terra.reasoning_levels,
        capability_rank=terra.capability_rank,
        cost_rank=terra.cost_rank,
        input_usd_per_mtok=terra.input_usd_per_mtok,
        output_usd_per_mtok=terra.output_usd_per_mtok,
    )
    repriced = model_fingerprint(
        model_id=terra.model_id,
        reasoning_levels=terra.reasoning_levels,
        capability_rank=terra.capability_rank,
        cost_rank=terra.cost_rank,
        input_usd_per_mtok=terra.input_usd_per_mtok + 0.01,
        output_usd_per_mtok=terra.output_usd_per_mtok,
    )
    assert original == terra.capability_fingerprint
    assert original == repriced
    changed_reasoning = model_fingerprint(
        model_id=terra.model_id, reasoning_levels=terra.reasoning_levels + ("ultra",),
        capability_rank=terra.capability_rank, cost_rank=terra.cost_rank,
        input_usd_per_mtok=terra.input_usd_per_mtok, output_usd_per_mtok=terra.output_usd_per_mtok,
    )
    assert original != changed_reasoning


def test_provider_result_preserves_raw_usage():
    row = ProviderResult(text='{}', input_tokens=10, output_tokens=4, usage_raw={"input_tokens": 10})
    assert row.input_tokens == 10
    assert row.usage_raw["input_tokens"] == 10
