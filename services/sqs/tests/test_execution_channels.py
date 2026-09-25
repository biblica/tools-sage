from __future__ import annotations

from pathlib import Path

import pytest

from sage_sqs.db import Database
from sage_sqs.domain import LanguageProfile, ModelRecord, Qualification
from sage_sqs.execution_channels import (
    known_execution_channels,
    load_execution_channel_catalog,
    load_execution_channel_descriptor,
)
from sage_sqs.publisher import Publisher
from sage_sqs.repository import Repository

_SEED_DIR = Path("seed/execution-channels")


def test_codex_workspace_descriptor_validates_against_schema():
    descriptor = load_execution_channel_descriptor(_SEED_DIR / "codex-workspace.yml")
    assert descriptor.execution_channel == "codex_workspace"
    assert descriptor.provider_family == "openai"
    assert descriptor.provisioning_model == "workspace"
    assert "GRAMMAR_ANALYSIS" in descriptor.capability_classes


def test_catalog_loads_every_seeded_descriptor():
    catalog = load_execution_channel_catalog(_SEED_DIR)
    assert set(catalog) == known_execution_channels(_SEED_DIR)
    assert "codex_workspace" in catalog


def test_duplicate_execution_channel_across_files_fails_closed(tmp_path: Path):
    (tmp_path / "a.yml").write_text(
        "execution_channel: dup\nprovider_family: openai\ndisplay_name: A\n"
        "provisioning_model: workspace\ncapability_classes: [GRAMMAR_ANALYSIS]\n"
        "reasoning_tier_taxonomy: openai-2026\n",
        encoding="utf-8",
    )
    (tmp_path / "b.yml").write_text(
        "execution_channel: dup\nprovider_family: openai\ndisplay_name: B\n"
        "provisioning_model: api_key\ncapability_classes: [GRAMMAR_ANALYSIS]\n"
        "reasoning_tier_taxonomy: openai-2026\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate execution_channel"):
        load_execution_channel_catalog(tmp_path)


def _qualification(execution_channel: str, profile: LanguageProfile, model: ModelRecord) -> Qualification:
    return Qualification(
        provider_family=model.provider_family,
        execution_channel=execution_channel,
        model_id=model.model_id,
        model_capability_fingerprint=model.capability_fingerprint,
        profile_id=profile.profile_id,
        profile_identity_sha256=profile.evaluation_identity_sha256,
        capability="GRAMMAR_ANALYSIS",
        status="QUALIFIED",
        minimum_reasoning="medium",
        quality_score=0.96,
        reliability_score=0.98,
        confidence="HIGH",
        value="HIGH",
        evidence_basis="MEASURED",
        estimated_unit_cost_usd=0.004,
        evaluated_at="2026-09-18T00:00:00Z",
        evidence_sha256="c" * 64,
    )


def test_published_bundle_execution_channels_are_all_registered(tmp_path: Path):
    """Fail closed: every execution_channel published in a bundle must be a known,
    registered channel -- an unregistered channel is a hard error, never silently
    accepted or silently dropped from the consistency check."""
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    profile = LanguageProfile("sw-KE", "Swahili (Kenya)", "ACTIVE", 1, 1, "bantu", "sw", "swa", "Latn", "KE")
    model = ModelRecord(
        provider_family="openai", model_id="gpt-x", status="APPROVED", revision=1,
        reasoning_levels=("low", "medium", "high"), capability_fingerprint="a" * 64,
        input_usd_per_mtok=2.0, output_usd_per_mtok=12.0,
    )
    repo.save_profile(profile)
    repo.save_model(model)
    repo.save_qualification(_qualification("codex_workspace", profile, model))
    bundle = Publisher(repo, authority_id="a", publication_epoch=1, output_paths=()).publish(actor="ADMIN")

    known = known_execution_channels(_SEED_DIR)
    published_channels = {q["execution_channel"] for q in bundle["qualifications"]}
    unregistered = published_channels - known
    assert not unregistered, f"published qualifications reference unregistered execution channels: {unregistered}"


def test_published_bundle_with_unregistered_execution_channel_is_detected(tmp_path: Path):
    """Same check, but proves it actually catches a real drift case rather than
    vacuously passing."""
    repo = Repository(Database.open(tmp_path / "sqs.db"))
    profile = LanguageProfile("sw-KE", "Swahili (Kenya)", "ACTIVE", 1, 1, "bantu", "sw", "swa", "Latn", "KE")
    model = ModelRecord(
        provider_family="openai", model_id="gpt-x", status="APPROVED", revision=1,
        reasoning_levels=("low", "medium", "high"), capability_fingerprint="a" * 64,
        input_usd_per_mtok=2.0, output_usd_per_mtok=12.0,
    )
    repo.save_profile(profile)
    repo.save_model(model)
    repo.save_qualification(_qualification("some_unregistered_channel", profile, model))
    bundle = Publisher(repo, authority_id="a", publication_epoch=1, output_paths=()).publish(actor="ADMIN")

    known = known_execution_channels(_SEED_DIR)
    published_channels = {q["execution_channel"] for q in bundle["qualifications"]}
    unregistered = published_channels - known
    assert unregistered == {"some_unregistered_channel"}
