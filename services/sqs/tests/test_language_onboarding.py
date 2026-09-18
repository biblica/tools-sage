from __future__ import annotations

from pathlib import Path

from sage_sqs.language_coverage import (
    check_language_onboarding_consistency,
    load_coverage_manifest,
    sage_grammar_profile_ids,
    sqs_seeded_language_ids,
)

_MANIFEST = Path("config/language-coverage-status.yml")
_SEED_LANGUAGES = Path("seed/languages")


def test_manifest_lists_every_sqs_seeded_language():
    manifest = load_coverage_manifest(_MANIFEST)
    for profile_id in sqs_seeded_language_ids(_SEED_LANGUAGES):
        assert profile_id in manifest, f"{profile_id} is seeded in SQS but missing from the coverage manifest"


def test_current_catalogs_are_fully_reconciled_against_the_manifest():
    """The real, current state of both catalogs must be fully accounted for in
    the checked-in manifest -- this is expected to be the common case; a
    violation here means someone added a language to one side without
    recording its onboarding status (Task 1b's coordination requirement)."""
    violations = check_language_onboarding_consistency(
        manifest_path=_MANIFEST,
        seed_languages_dir=_SEED_LANGUAGES,
    )
    assert violations == [], "\n".join(violations)


def test_detects_a_sage_profile_missing_from_the_manifest(tmp_path: Path):
    """Proves the check actually catches drift, not just passes vacuously."""
    fake_sage_dir = tmp_path / "grammar"
    fake_sage_dir.mkdir()
    (fake_sage_dir / "xx-YY").mkdir()
    violations = check_language_onboarding_consistency(
        manifest_path=_MANIFEST,
        seed_languages_dir=_SEED_LANGUAGES,
        sage_grammar_profiles_dir=fake_sage_dir,
    )
    assert any("xx-YY" in v and "no entry in the coverage manifest" in v for v in violations)


def test_detects_onboarded_status_without_a_real_sage_profile(tmp_path: Path):
    """A manifest claiming ONBOARDED must be backed by an actual SAGE profile,
    not just an SQS seed file -- catches a profile removed from SAGE without
    updating the manifest."""
    fake_manifest = tmp_path / "manifest.yml"
    fake_manifest.write_text(
        "profiles:\n  en-US: {status: ONBOARDED}\n",
        encoding="utf-8",
    )
    fake_sage_dir = tmp_path / "grammar"
    fake_sage_dir.mkdir()  # en-US deliberately absent
    fake_seed_dir = tmp_path / "seed-languages"
    fake_seed_dir.mkdir()
    (fake_seed_dir / "en-US.yml").write_text("profile_id: en-US\n", encoding="utf-8")
    violations = check_language_onboarding_consistency(
        manifest_path=fake_manifest,
        seed_languages_dir=fake_seed_dir,
        sage_grammar_profiles_dir=fake_sage_dir,
    )
    assert any("en-US" in v and "no matching SAGE grammar profile" in v for v in violations)


def test_sage_grammar_profile_ids_reads_the_real_repository_layout():
    """Confirms the default (no explicit dir) path actually resolves into the
    real app/system/config/profiles/grammar directory in this monorepo."""
    ids = sage_grammar_profile_ids()
    assert "en-US" in ids
    assert "README.md" not in ids
