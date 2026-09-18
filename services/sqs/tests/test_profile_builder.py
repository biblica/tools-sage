from pathlib import Path

import yaml

from sage_sqs.profile_builder import build_profile, load_seed_profiles
from sage_sqs.profile_validation import validate_profile_id

EXPECTED = {
    "en-US", "en-GB", "de-DE", "fr-FR", "fr-011", "es-419", "es-ES",
    "pt-BR", "pt-PT", "ru-RU", "uk-UA", "id-ID", "hi-IN", "sw-KE",
    "sw-CD", "ha-NG", "yo-NG", "ml-IN", "pa-Guru-IN", "pa-Arab-PK",
}


def seed_root() -> Path:
    return Path(__file__).resolve().parents[1] / "seed" / "languages"


def test_seed_catalog_is_exact_and_review_required():
    rows = load_seed_profiles(seed_root())
    assert {p.profile_id for p in rows} == EXPECTED
    assert sum(p.tier == 1 for p in rows) == 9
    assert sum(p.tier == 2 for p in rows) == 6
    assert sum(p.tier == 3 for p in rows) == 5
    assert {p.status for p in rows} == {"REVIEW_REQUIRED"}
    assert len({p.evaluation_identity_sha256 for p in rows}) == 20


def test_numeric_region_and_script_specific_ids_are_valid():
    assert validate_profile_id("es-419") == []
    assert validate_profile_id("pa-Guru-IN") == []
    assert validate_profile_id("pa-Arab-PK") == []
    assert validate_profile_id("english-US")[0].code == "INVALID_PROFILE_ID"


def test_builder_reports_reference_gap_for_absent_sage_profile():
    seed = yaml.safe_load((seed_root() / "ru-RU.yml").read_text(encoding="utf-8"))
    seed["profile_build"]["sage_profile_available_in_reference_snapshot"] = False
    draft = build_profile(seed)
    assert draft.status == "REVIEW_REQUIRED"
    assert "SAGE_0.02ALPHA1_GRAMMAR_PROFILE_ABSENT" in {issue.code for issue in draft.issues}


def test_builder_rejects_identity_mismatch():
    seed = yaml.safe_load((seed_root() / "en-US.yml").read_text(encoding="utf-8"))
    seed["identity"]["region"] = "GB"
    draft = build_profile(seed)
    assert "PROFILE_REGION_MISMATCH" in {issue.code for issue in draft.issues}
