"""A second provider family (anthropic) alongside openai: catalogs, discovery, planning, and ADMIN."""
from dataclasses import replace
from pathlib import Path

import pytest

from sage_sqs.admin import AdminApp
from sage_sqs.db import Database
from sage_sqs.discovery import validate_discovery
from sage_sqs.domain import LanguageProfile, ModelRecord, canonical_sha256
from sage_sqs.evaluation.lifecycle import _estimated_pack_cost, replan_repository
from sage_sqs.evaluation.packs import load_pack_catalog
from sage_sqs.providers.catalog import catalog_paths, load_provider_catalog
from sage_sqs.publisher import Publisher
from sage_sqs.repository import Repository

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "config" / "evaluation-packs"


def _repo(tmp_path, *models):
    """Return a repository with one active profile and the given models."""
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    repo.save_profile(LanguageProfile("en-US", "English", "ACTIVE", 1, 1, "english", "en", "eng", "Latn", "US"))
    for model in models:
        repo.save_model(model)
    return repo


def _claude(model_id="claude-opus-5-5", **overrides):
    """Return one approved Anthropic model record."""
    model = ModelRecord("anthropic", model_id, "APPROVED", 1, ("low", "medium", "high"), "f" * 64, 4.0, 20.0, 3, 3,
                        pack_token_scale=1.61)
    return replace(model, **overrides)


def test_every_seed_catalog_loads_with_its_family_and_routine_tiers():
    """Both catalogs load; Claude's xhigh/max are premium, never routine."""
    families = {}
    for path in catalog_paths(ROOT / "seed"):
        for model in load_provider_catalog(path):
            families.setdefault(model.provider_family, []).append(model)
    assert set(families) == {"openai", "anthropic"}
    opus = next(model for model in families["anthropic"] if model.model_id == "claude-opus-5-5")
    assert opus.routine_reasoning() == ("low", "medium", "high")
    assert opus.pack_token_scale == 1.61
    assert all(model.pack_token_scale == 1.0 for model in families["openai"])


def test_openai_catalog_fingerprints_are_unchanged_by_the_generalization():
    """Existing OpenAI rows must not be re-flagged for ADMIN review by a code refactor."""
    for model in load_provider_catalog(ROOT / "seed" / "openai-provider.yml"):
        legacy = canonical_sha256({
            "provider_family": model.provider_family, "model_id": model.model_id,
            "reasoning_levels": list(model.reasoning_levels), "capability_rank": model.capability_rank,
            "cost_rank": model.cost_rank, "input_usd_per_mtok": model.input_usd_per_mtok,
            "output_usd_per_mtok": model.output_usd_per_mtok,
        })
        assert model.catalog_fingerprint == legacy


def test_discovery_accepts_registered_families_only():
    """An anthropic model discovery is valid; an unknown vendor is not."""
    observed = {"provider_family": "anthropic", "model_id": "claude-opus-5-5", "reasoning_levels": ["medium"],
                "capability_fingerprint": "a" * 64}
    payload = {"kind": "MODEL", "sage_version": "0.02a3", "observed": observed}
    assert validate_discovery(payload) == payload
    with pytest.raises(ValueError, match="INVALID_DISCOVERY"):
        validate_discovery({**payload, "observed": {**observed, "provider_family": "acme"}})


def test_replan_queues_the_candidate_under_its_own_family(tmp_path):
    """Planned tests were queued as openai regardless of the model's family."""
    repo = _repo(tmp_path, _claude())
    rows = replan_repository(repo, PACKS)
    queued = [row for row in rows if row.disposition.value == "TEST"]
    assert queued and all(row.provider_family == "anthropic" for row in queued)
    pending = repo.list_pending_evaluations()
    assert [item["provider_family"] for item in pending] == ["anthropic"]


def test_pack_cost_estimate_follows_the_tokenizer_density():
    """Packs are o200k-sized; a 1.61x denser tokenizer costs 1.61x the input tokens."""
    pack = next(iter(load_pack_catalog(PACKS).values()))
    dense = _claude(output_usd_per_mtok=0.0)
    plain = replace(dense, pack_token_scale=1.0)
    assert _estimated_pack_cost(pack, dense) == pytest.approx(1.61 * _estimated_pack_cost(pack, plain))


def test_admin_queues_an_evaluation_for_any_family(tmp_path):
    """ADMIN evaluation queueing is no longer pinned to openai."""
    repo = _repo(tmp_path, _claude())
    admin = AdminApp(repo, publisher=Publisher(repo, authority_id="test", publication_epoch=1, output_paths=()))
    item = admin.queue_evaluation(model_id="claude-opus-5-5", profile_id="en-US", capability="GRAMMAR_ANALYSIS",
                                  provider_family="anthropic")
    assert item["provider_family"] == "anthropic"
    assert admin.status_snapshot()["models_approved_by_family"] == {"anthropic": 1}
    with pytest.raises(ValueError, match="MODEL_NOT_APPROVED"):
        admin.queue_evaluation(model_id="claude-opus-5-5", profile_id="en-US", capability="GRAMMAR_ANALYSIS")
