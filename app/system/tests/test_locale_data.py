"""Coverage for bundled CLDR locale facts and their project/namespace override resolution."""
from sage.locale_data import locale_facts, resolve_locale_facts


def test_exact_tag_hit_returns_bundled_facts() -> None:
    """A tag present verbatim in the bundle resolves directly, no fallback."""
    facts = locale_facts("pt-BR")
    assert facts is not None
    assert facts["numbers"]["decimal_separator"] == ","
    assert facts["numbers"]["group_separator"] == "."


def test_base_language_fallback() -> None:
    """A registered tag absent from the bundle falls back to its base language."""
    assert locale_facts("es-XX") == locale_facts("es")


def test_universal_fallback_for_unknown_language() -> None:
    """A tag with no bundled data at any tier falls back to the universal default (en)."""
    assert locale_facts("zz-ZZ") == locale_facts("en")


def test_universal_fallback_is_always_present() -> None:
    """The bundle must always be able to resolve the universal fallback tag itself."""
    assert locale_facts("en") is not None


def test_resolve_prefers_project_ldml_over_namespace_and_bundled() -> None:
    """Project-parsed LDML conventions outrank both a namespace override and the CLDR default."""
    facts = resolve_locale_facts(
        tag="fr-FR",
        namespace_override={"punctuation": {"quote_start": "<<ns>>"}},
        ldml_conventions={"punctuation": {"quote_start": "«", "quote_end": "»"}},
    )
    assert facts["punctuation"]["quote_start"] == "«"
    assert facts["punctuation"]["source"] == "project_ldml"


def test_resolve_prefers_namespace_override_over_bundled() -> None:
    """A namespace's own locale_overrides outrank the bundled CLDR default."""
    facts = resolve_locale_facts(
        tag="fr-FR",
        namespace_override={"punctuation": {"quote_start": "<<ns>>", "quote_end": "<<ns>>"}},
    )
    assert facts["punctuation"]["quote_start"] == "<<ns>>"
    assert facts["punctuation"]["source"] == "namespace_override"


def test_resolve_falls_back_to_bundled_cldr_default() -> None:
    """With no project or namespace override, the resolved facts come from the CLDR bundle."""
    facts = resolve_locale_facts(tag="pt-BR")
    assert facts["numbers"]["decimal_separator"] == ","
    assert facts["numbers"]["source"] == "cldr:pt-BR"


def test_resolve_field_groups_are_independent() -> None:
    """A namespace override of one field-group must not blank out the others."""
    facts = resolve_locale_facts(
        tag="pt-BR",
        namespace_override={"punctuation": {"quote_start": "<<ns>>", "quote_end": "<<ns>>"}},
    )
    assert facts["punctuation"]["source"] == "namespace_override"
    assert facts["numbers"]["source"] == "cldr:pt-BR"
    assert facts["numbers"]["decimal_separator"] == ","


def test_resolve_returns_empty_group_when_nothing_available() -> None:
    """A field-group absent everywhere resolves to an empty mapping, never a crash."""
    facts = resolve_locale_facts(tag="en")
    assert facts["datetime"] or facts["datetime"] == {}
    for group in ("numbers", "punctuation", "datetime"):
        assert isinstance(facts[group], dict)
