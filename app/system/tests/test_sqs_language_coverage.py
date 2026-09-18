"""SAGE-side echo of the language onboarding consistency check (Task 6)."""
from __future__ import annotations

from pathlib import Path

from sage.sqs_language_coverage import (
    check_language_onboarding_consistency,
    load_coverage_manifest,
    sage_grammar_profile_ids,
)


def test_current_sage_profiles_are_fully_reconciled_against_the_shared_manifest():
    """The real, current SAGE grammar-profile registry must be fully accounted for in the
    shared manifest -- expected to be the common case; a violation here means a profile was
    added without recording its SQS coverage status (Task 1b's coordination requirement)."""
    assert check_language_onboarding_consistency() == []


def test_sage_grammar_profile_ids_reads_the_real_repository_layout():
    """Confirms the default (no explicit dir) path actually resolves into the real registry."""
    ids = sage_grammar_profile_ids()
    assert "en-US" in ids
    assert "README.md" not in ids


def test_manifest_lists_every_current_sage_profile():
    """Every real SAGE grammar profile has a corresponding manifest entry."""
    manifest = load_coverage_manifest()
    for profile_id in sage_grammar_profile_ids():
        assert profile_id in manifest, f"{profile_id} exists in SAGE but is missing from the manifest"


def test_detects_a_sage_profile_missing_from_the_manifest(tmp_path: Path):
    """Proves the check actually catches drift, not just passes vacuously."""
    fake_dir = tmp_path / "grammar"
    fake_dir.mkdir()
    (fake_dir / "xx-YY").mkdir()
    violations = check_language_onboarding_consistency(grammar_profiles_dir=fake_dir)
    assert any("xx-YY" in v and "no entry in the shared" in v for v in violations)


def test_detects_an_invalid_status_for_a_sage_profile(tmp_path: Path):
    """A manifest entry with a status invalid for a SAGE profile (e.g. an SQS-only status) is flagged."""
    fake_dir = tmp_path / "grammar"
    fake_dir.mkdir()
    (fake_dir / "xx-YY").mkdir()
    fake_manifest = tmp_path / "manifest.yml"
    fake_manifest.write_text(
        "profiles:\n  xx-YY: {status: SQS_ONLY_PENDING_SAGE_PROFILE}\n", encoding="utf-8",
    )
    violations = check_language_onboarding_consistency(manifest_path=fake_manifest, grammar_profiles_dir=fake_dir)
    assert any("xx-YY" in v and "is not valid" in v for v in violations)
