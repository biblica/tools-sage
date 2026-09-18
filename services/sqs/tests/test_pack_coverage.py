from pathlib import Path

import yaml

from sage_sqs.evaluation.packs import load_pack_catalog

GRAMMAR = {
    "meaning_preservation", "negation_scope", "participant_reference",
    "morphology_syntax_agreement", "clause_relationship_ambiguity", "zero_finding",
}
REWRITE = {
    "proposition_participant_preservation", "authorized_fix_only", "protected_content",
    "register_constraints", "no_introduced_claims_omissions", "no_change",
}


def root():
    return Path(__file__).resolve().parents[1]


def test_all_twenty_profiles_have_both_exact_packs():
    profiles = {p.stem for p in (root() / "seed" / "languages").glob("*.yml")}
    catalog = load_pack_catalog(root() / "config" / "evaluation-packs")
    assert len(profiles) == 20
    assert len(catalog) == 40
    for profile_id in profiles:
        assert (profile_id, "GRAMMAR_ANALYSIS") in catalog
        assert (profile_id, "SEMANTIC_REWRITE") in catalog


def test_each_pack_has_complete_diagnostic_coverage_and_repeatability():
    catalog = load_pack_catalog(root() / "config" / "evaluation-packs")
    for (_, capability), pack in catalog.items():
        expected = GRAMMAR if capability == "GRAMMAR_ANALYSIS" else REWRITE
        assert {case.diagnostic_class for case in pack.cases} == expected
        assert len(pack.cases) == 6
        assert any(case.critical for case in pack.cases)
        assert len(pack.confirmation_cases()) >= 2
        assert pack.repeat_confirmation_cases >= 2
        assert pack.review_state == "READY"


def test_punjabi_scripts_are_separate_exact_pack_identities():
    catalog = load_pack_catalog(root() / "config" / "evaluation-packs")
    assert catalog[("pa-Guru-IN", "GRAMMAR_ANALYSIS")].profile_id == "pa-Guru-IN"
    assert catalog[("pa-Arab-PK", "GRAMMAR_ANALYSIS")].profile_id == "pa-Arab-PK"
    assert catalog[("pa-Guru-IN", "GRAMMAR_ANALYSIS")].pack_id != catalog[("pa-Arab-PK", "GRAMMAR_ANALYSIS")].pack_id


def test_seed_catalog_declares_pack_state_ready():
    for path in (root() / "seed" / "languages").glob("*.yml"):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert payload["profile_build"]["evaluation_pack_state"] == "READY"
