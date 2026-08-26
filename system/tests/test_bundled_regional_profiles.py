"""Regression coverage for rc4 regional language-profile starter library."""
from pathlib import Path

from sage.grammar import load_grammar_profile
from sage.language_codes import canonical_language_tag
from sage.iso_languages import preferred_operational_primary, regional_profile_candidates
from sage.registry import load_ecosystem

ROOT = Path(__file__).resolve().parents[2]

EXPECTED = {
    "am-ET": "Ethi", "ar-145": "Arab", "ar-SA": "Arab", "de-DE": "Latn",
    "en-GB": "Latn", "en-US": "Latn", "es-419": "Latn", "es-BR": "Latn",
    "fa-IR": "Arab", "fr-011": "Latn", "fr-FR": "Latn", "ha-NE": "Latn",
    "ha-NG": "Latn", "hi-IN": "Deva", "id-ID": "Latn", "pt-419": "Latn",
    "pt-BR": "Latn", "ti-ER": "Ethi", "ti-ET": "Ethi", "uk-UA": "Cyrl",
}


def test_regional_starter_profiles_are_registered_and_valid() -> None:
    """Every bundled regional WIP starter must load and match its registered namespace."""
    config = load_ecosystem(ROOT / "ecosystem.yml")
    assert set(config.language_profiles) == set(EXPECTED)
    for tag, script in EXPECTED.items():
        namespace = config.language_profiles[tag]
        assert namespace.script == script
        variant = namespace.variants["wip"]
        profile = load_grammar_profile(
            variant.path,
            expected_profile_id="wip",
            expected_language=tag,
            expected_role="WIP",
        )
        assert profile.status == "PROJECT_REVIEW_REQUIRED"
        assert len(profile.checks) >= 8


def test_primary_iso_aliases_normalize_for_import_resolution() -> None:
    """Common ISO 639-2/3 forms normalize to the regional primary tags used by SAGE."""
    samples = {
        "eng-US": "en-US", "ind-ID": "id-ID", "ukr-UA": "uk-UA", "fas-IR": "fa-IR",
        "per-IR": "fa-IR", "hin-IN": "hi-IN", "fra-FR": "fr-FR", "fre-011": "fr-011",
        "amh-ET": "am-ET", "tir-ER": "ti-ER", "hau-NG": "ha-NG", "spa-419": "es-419",
        "por-BR": "pt-BR", "deu-DE": "de-DE", "ger-DE": "de-DE", "ara-145": "ar-145",
    }
    for raw, expected in samples.items():
        assert canonical_language_tag(raw, "test", require_preferred=False) == expected
    assert preferred_operational_primary("pes", "Iranian Persian") == "pes"
    assert preferred_operational_primary("pa", "Persian / Farsi") == "fa"
    assert preferred_operational_primary("pa", "Panjabi") == "pa"


def test_guided_builder_creates_review_required_regional_profile(make_workspace) -> None:
    """The guided builder writes a regional local profile and registers it without touching system starters."""
    from sage.menu import MenuIO, SageControlCenter, ScriptedInput
    import io

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["Latn", "1", ""]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    assert center._build_guided_grammar_profile(language="sw-TZ", role="WIP") is True
    path = root.parent / "SAGEdata" / "resources" / "grammar-profiles" / "sw-TZ" / "wip.yml"
    assert path.is_file()
    profile = load_grammar_profile(path, expected_language="sw-TZ", expected_role="WIP")
    assert profile.status == "PROJECT_REVIEW_REQUIRED"
    config = load_ecosystem(root / "ecosystem.yml")
    assert config.language_profiles["sw-TZ"].variants["wip"].path == path.resolve()


def test_import_candidates_keep_paratext_pa_persian_separate_from_punjabi() -> None:
    """Paratext shorthand `pa` plus Persian/Farsi metadata must recommend Persian, never Punjabi."""
    config = load_ecosystem(ROOT / "ecosystem.yml")
    assert regional_profile_candidates(
        language_code="pa", language_name="Persian / Farsi", configured_profiles=config.language_profiles
    ) == ("fa-IR",)
    assert regional_profile_candidates(
        language_code="pa", language_name="Panjabi", configured_profiles=config.language_profiles
    ) == ()
