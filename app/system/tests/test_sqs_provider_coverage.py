"""Cross-catalog provider onboarding consistency: SAGE's governed providers vs. SQS's execution channels."""
from __future__ import annotations

from pathlib import Path

from sage.sqs_provider_coverage import (
    check_provider_onboarding_consistency,
    sage_governed_provider_ids,
    sqs_execution_channel_ids,
)


def test_current_catalogs_are_fully_reconciled():
    """The real, current state of both catalogs must be fully accounted for -- expected to be
    the common case; a violation here means a governed provider or execution channel was added
    to one side without recording the other (Task 6's coordination requirement)."""
    assert check_provider_onboarding_consistency() == []


def test_sage_has_exactly_one_governed_provider_today():
    """Confirms the real, current governed-provider set this check is reconciling against."""
    assert sage_governed_provider_ids() == frozenset({"codex"})


def test_sqs_has_the_matching_execution_channel_seeded():
    """Confirms the real, current SQS execution-channel catalog this check reads."""
    assert "codex_workspace" in sqs_execution_channel_ids()


def test_detects_a_governed_provider_missing_its_execution_channel(tmp_path: Path, monkeypatch):
    """A governed provider with no matching SQS execution channel is flagged, not silently accepted."""
    import sage.sqs_provider_coverage as module

    monkeypatch.setattr(module, "ENABLED_AUTOMATED_PROVIDER_IDS", ("codex", "some_new_provider"))
    monkeypatch.setitem(module.SAGE_PROVIDER_TO_EXECUTION_CHANNEL, "some_new_provider", "some_new_channel")
    violations = check_provider_onboarding_consistency()
    assert any("some_new_provider" in v and "no such channel" in v for v in violations)


def test_detects_an_unregistered_sqs_execution_channel(tmp_path: Path):
    """An SQS execution channel with no SAGE provider mapped to it is flagged, not silently ignored."""
    (tmp_path / "codex-workspace.yml").write_text(
        "execution_channel: codex_workspace\nprovider_family: openai\n", encoding="utf-8",
    )
    (tmp_path / "future-channel.yml").write_text(
        "execution_channel: future_unmapped_channel\nprovider_family: openai\n", encoding="utf-8",
    )
    violations = check_provider_onboarding_consistency(tmp_path)
    assert any("future_unmapped_channel" in v and "no SAGE provider maps" in v for v in violations)
