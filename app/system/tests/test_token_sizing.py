"""Provider-aware token tables, the S/M/L work-unit size, and the learned token correction."""
from __future__ import annotations

from pathlib import Path

import pytest

from sage import build_policy, evidence
from sage.errors import ConfigurationError
from sage.evidence import CLAUDE_TABLE, O200K_TABLE, EvidencePolicy, RTCSizingPolicy, estimate_tokens, token_table_for
from sage.executors import ProviderRequest, ProviderResponse
from sage.llm_settings import load_llm_settings, set_work_unit_size, update_llm_selection
from sage.token_calibration import (
    MIN_OBSERVATIONS,
    correction_status,
    observe_response,
    record_observation,
    sizing_adjustment,
    token_correction,
)

ENGLISH = "\\v 1 In the beginning was the Word, and the Word was with God, and the Word was God.\n" * 40
PUNJABI = "\\v 1 ਆਦ ਵਿੱਚ ਸ਼ਬਦ ਸੀ ਅਤੇ ਸ਼ਬਦ ਪਰਮੇਸ਼ੁਰ ਦੇ ਨਾਲ ਸੀ ਅਤੇ ਸ਼ਬਦ ਪਰਮੇਸ਼ੁਰ ਸੀ।\n" * 40
RTC = {"estimator": "SAGE_MULTILINGUAL_HEURISTIC_2", "wip_target_min_tokens": 7500, "wip_target_max_tokens": 9000,
       "wip_hard_exclusive_tokens": 10000, "route_hard_max_tokens": 40000, "route_hard_serialized_bytes": 224000}


@pytest.fixture(autouse=True)
def _restore_token_table():
    """Keep the process-wide table selection from leaking between tests."""
    yield
    evidence.set_token_table(O200K_TABLE)


def _root(tmp_path: Path) -> Path:
    """Return an empty SAGE Core root for settings-only tests."""
    root = tmp_path / "SAGE" / "app"
    root.mkdir(parents=True)
    return root


def test_each_provider_counts_in_its_own_tokenizer():
    """The same Scripture costs more Claude tokens, far more for Gurmukhi, as measured."""
    assert token_table_for("codex") == O200K_TABLE
    assert token_table_for("claude", "claude-sonnet-5-5") == CLAUDE_TABLE
    english = estimate_tokens(ENGLISH, CLAUDE_TABLE) / estimate_tokens(ENGLISH, O200K_TABLE)
    punjabi = estimate_tokens(PUNJABI, CLAUDE_TABLE) / estimate_tokens(PUNJABI, O200K_TABLE)
    assert 1.2 < english < 2.0
    assert punjabi > english


def test_selecting_claude_switches_the_active_table(tmp_path, monkeypatch):
    """Planning measures in the selected provider's tokens."""
    monkeypatch.setattr(build_policy, "ENABLED_AUTOMATED_PROVIDER_IDS", ("codex", "claude"))
    root = _root(tmp_path)
    assert sizing_adjustment(root).token_table == O200K_TABLE
    assert estimate_tokens(ENGLISH) == estimate_tokens(ENGLISH, O200K_TABLE)
    update_llm_selection(root, provider="claude", auto=True)
    assert sizing_adjustment(root).token_table == CLAUDE_TABLE
    assert estimate_tokens(ENGLISH) == estimate_tokens(ENGLISH, CLAUDE_TABLE)


def test_work_unit_size_is_validated_and_persisted(tmp_path):
    """S/M/L is the only accepted size; M is the default."""
    root = _root(tmp_path)
    assert load_llm_settings(root)["work_unit_size"] == "M"
    set_work_unit_size(root, "s")
    assert load_llm_settings(root)["work_unit_size"] == "S"
    assert sizing_adjustment(root).size_multiplier == 0.5
    with pytest.raises(ConfigurationError, match="Work-unit size"):
        set_work_unit_size(root, "XL")


def test_size_scales_all_limits_and_correction_shrinks_only_targets():
    """Hard limits follow S/M/L only, so a learned correction never rejects a planned unit."""
    base = EvidencePolicy(target_estimated_tokens=22500, hard_estimated_tokens=35000, hard_serialized_bytes=196000,
                          minimum_target_tokens=7500, maximum_primary_verse_units=220)
    large = base.scaled(2.0, 2.0)
    assert (large.target_estimated_tokens, large.hard_estimated_tokens, large.hard_serialized_bytes) == (45000, 70000, 392000)
    assert large.maximum_primary_verse_units == 440
    corrected = base.scaled(1.0, 1.0 / 1.25)
    assert corrected.target_estimated_tokens == 18000
    assert corrected.hard_estimated_tokens == 35000
    assert base.scaled(1.0, 1.0) is base


def test_rtc_contract_freezes_correction_but_not_size_or_table():
    """An approved plan survives a new correction, but not a new size or provider tokenizer."""
    approved = RTCSizingPolicy.from_mapping(RTC).adjusted("M", 1.2, O200K_TABLE)
    assert approved.effective_wip_target_max_tokens == 7500
    assert approved.effective_wip_hard_exclusive_tokens == 10000
    recorded = approved.to_dict()
    assert approved.adjusted("M", 1.4, O200K_TABLE).same_contract(recorded)
    assert not approved.adjusted("L", 1.2, O200K_TABLE).same_contract(recorded)
    assert not approved.adjusted("M", 1.2, CLAUDE_TABLE).same_contract(recorded)


def test_plans_approved_before_sizes_and_tables_stay_valid_for_codex():
    """A legacy contract (provider binding, no size or table) still matches Codex at size M."""
    legacy = {**RTC, "provider": "codex"}
    current = RTCSizingPolicy.from_mapping(legacy).adjusted("M", 1.1, O200K_TABLE)
    assert current.same_contract(legacy)
    assert not current.adjusted("M", 1.1, CLAUDE_TABLE).same_contract(legacy)


def test_correction_needs_enough_observations_and_is_bounded(tmp_path):
    """No correction until a model has enough calls; then the median, clamped to 1.0-1.5."""
    root = _root(tmp_path)
    for _ in range(MIN_OBSERVATIONS - 1):
        record_observation(root, provider="claude", model="claude-opus-5-5", estimated=10000, actual=12000)
    assert token_correction(root, "claude") == 1.0
    record_observation(root, provider="claude", model="claude-opus-5-5", estimated=10000, actual=12000)
    assert token_correction(root, "claude") == 1.2
    for _ in range(MIN_OBSERVATIONS):
        record_observation(root, provider="claude", model="claude-haiku-5-5", estimated=10000, actual=30000)
    assert token_correction(root, "claude") == 1.5
    for _ in range(MIN_OBSERVATIONS):
        record_observation(root, provider="codex", model="gpt-6.1-sol", estimated=10000, actual=6000)
    assert token_correction(root, "codex") == 1.0
    assert correction_status(root, "claude")["models"]["claude-haiku-5-5"]["observations"] == MIN_OBSERVATIONS


def test_small_prompts_and_unreported_usage_are_not_observed(tmp_path):
    """Instruction-dominated prompts and providers without usage teach nothing."""
    root = _root(tmp_path)
    request = ProviderRequest(prompt="Reply OK.", schema={}, model="claude-opus-5-5")
    usage = {"input_tokens": 2, "cache_creation_input_tokens": 1184, "cache_read_input_tokens": 0, "output_tokens": 5}
    observe_response(root, request, ProviderResponse(provider="claude", model="claude-opus-5-5", content="{}",
                                                     metadata={"usage": usage}))
    big = ProviderRequest(prompt=ENGLISH * 3, schema={}, model="gpt-6.1-sol")
    observe_response(root, big, ProviderResponse(provider="codex", model="gpt-6.1-sol", content="{}", metadata={}))
    assert correction_status(root, "claude")["models"] == {}
    assert correction_status(root, "codex")["models"] == {}


def test_observation_estimates_in_the_answering_provider_tokens(tmp_path):
    """A Claude call is compared with the Claude-table estimate, whatever table is active."""
    root = _root(tmp_path)
    request = ProviderRequest(prompt=ENGLISH * 3, schema={}, model="claude-opus-5-5")
    claude_estimate = estimate_tokens(request.prompt, CLAUDE_TABLE)
    usage = {"input_tokens": claude_estimate, "output_tokens": 5}
    for _ in range(MIN_OBSERVATIONS):
        observe_response(root, request, ProviderResponse(provider="claude", model="claude-opus-5-5", content="{}",
                                                         metadata={"usage": usage}))
    assert correction_status(root, "claude")["models"]["claude-opus-5-5"]["median_ratio"] == 1.0
