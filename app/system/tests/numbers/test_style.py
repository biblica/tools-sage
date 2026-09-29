"""Governed NCA style profile validation and library import/selection.

Per the 2026-09-28 simplified-check rewrite, presentation-style ASSESSMENT
(assess_style/_assess_prepared_style) has no successor -- this pipeline is
number-accuracy (plus its noteworthy-info advisory) only, and `Extraction`
no longer carries the exact-span/kind/role evidence that assessment needed.
`presentation_consistency` remains an accepted no-op check-policy toggle
(see numbers/results.py). Only style-profile parsing/import/selection
remains in scope here; it still backs parsing conventions used by
extraction (see numbers/extraction.py::_parsing_conventions).
"""
import pytest

from sage.errors import ValidationError
from sage.numbers.style import validate_style_profile


AREAS = ('digits', 'bands', 'grouping', 'decimal', 'ordinals', 'fractions', 'ranges', 'qualifiers', 'contexts', 'units')


def configured_profile():
    """Return explicit, reusable synthetic style decisions, with no inferred rules."""
    return {'schema_version': '1.0', 'profile': {'id': 'fixture-en', 'version': '1', 'language': 'en', 'script': 'Latn', 'projects': ['*'], 'source_guide': 'Synthetic project guide', 'recorded_by': 'Fixture operator', 'recorded_date': '2026-09-09', 'status': 'CONFIGURED'}, 'rules': {area: {'id': f'NCA-{area.upper()}', 'status': 'NOT_SPECIFIED'} for area in AREAS}}


def rule(profile, area, **fields):
    """Configure a single rule area while leaving every other decision explicit."""
    if area == 'contexts' and 'decisions' in fields:
        fields['decisions'] = {**{name: {'status': 'INHERIT'} for name in ('ages', 'dates', 'time', 'money', 'measurements', 'counts', 'genealogies')}, **fields['decisions']}
    profile['rules'][area].update(status='CONFIGURED', **fields)
    return profile


@pytest.mark.parametrize('raw', [{}, {'schema_version': '1.0'}])
def test_empty_template_cannot_be_used_as_active_profile(raw):
    """Incomplete profiles fail with a stable setup-remediation code."""
    with pytest.raises(ValidationError) as exc:
        validate_style_profile(raw)
    assert exc.value.code == 'NCA_STYLE_PROFILE_INVALID'


def test_draft_and_missing_decisions_are_not_selectable():
    """A draft or an absent rule area cannot silently become a configured guide."""
    profile = configured_profile()
    profile['profile']['status'] = 'DRAFT'
    with pytest.raises(ValidationError): validate_style_profile(profile)
    profile['profile']['status'] = 'CONFIGURED'
    del profile['rules']['grouping']
    with pytest.raises(ValidationError): validate_style_profile(profile)


def test_profile_compatibility_and_recursive_immutability():
    """Profile identity must match Project language/script and remain immutable."""
    raw = configured_profile()
    validated = validate_style_profile(raw, language='en', script='Latn', project='Fixture')
    raw['profile']['version'] = '2'
    assert validated['profile']['version'] == '1'
    with pytest.raises(TypeError): validated['rules']['digits']['status'] = 'CONFIGURED'
    with pytest.raises(ValidationError): validate_style_profile(raw, language='fr', script='Latn')
    with pytest.raises(ValidationError): validate_style_profile(raw, language='en', script='Arab')


def test_overlapping_bands_duplicate_rule_ids_and_ambiguous_separators_fail():
    """Contradictory guide rules cannot select whichever entry happens to come first."""
    raw = configured_profile()
    rule(raw, 'bands', bands=[{'min': '0', 'max': '9', 'form': 'WORDS'}, {'min': '9', 'max': None, 'form': 'DIGITS'}])
    with pytest.raises(ValidationError): validate_style_profile(raw)
    raw = configured_profile()
    raw['rules']['bands']['id'] = raw['rules']['digits']['id']
    with pytest.raises(ValidationError): validate_style_profile(raw)
    raw = rule(rule(configured_profile(), 'grouping', style='WESTERN', separator=',', minimum='1000'), 'decimal', separator=',')
    with pytest.raises(ValidationError): validate_style_profile(raw)


def test_profile_library_import_selection_and_content_conflicts(make_workspace, tmp_path):
    """Imported profiles live in localdata and resolve only through explicit selection."""
    import yaml
    from sage.numbers.style import import_style_profile, resolve_style_profile
    from sage.registry import load_ecosystem
    from sage.storage import storage_layout

    config = load_ecosystem(make_workspace() / 'ecosystem.yml')
    source = tmp_path / 'profile.yml'
    raw = configured_profile()
    source.write_text(yaml.safe_dump(raw), encoding='utf-8')
    original = source.read_bytes()
    imported = import_style_profile(config, source)
    assert imported.is_relative_to(storage_layout(config.root).styleguides_root)
    assert imported.read_bytes() == original
    selected = resolve_style_profile(config, 'fixture-en/1', language='en', script='Latn', project='Fixture')
    assert selected.path == imported
    assert selected.selector == 'fixture-en/1'
    assert selected.document['profile']['version'] == '1'
    raw['profile']['id'] = 'second-en'
    source.write_text(yaml.safe_dump(raw), encoding='utf-8')
    import_style_profile(config, source)
    assert resolve_style_profile(config, None, language='en', script='Latn') is None
    assert resolve_style_profile(config, 'fixture-en/1', language='en', script='Latn').sha256 == selected.sha256
    raw['profile']['id'] = 'fixture-en'
    raw['profile']['source_guide'] = 'Changed same version'
    source.write_text(yaml.safe_dump(raw), encoding='utf-8')
    with pytest.raises(ValidationError) as exc:
        import_style_profile(config, source)
    assert exc.value.code == 'NCA_STYLE_PROFILE_CONFLICT'
    assert imported.read_bytes() == original


def test_profile_library_rejects_missing_and_escaping_selectors(make_workspace):
    """Missing profiles give setup remediation and selectors cannot escape the library."""
    from sage.numbers.style import resolve_style_profile
    from sage.registry import load_ecosystem

    config = load_ecosystem(make_workspace() / 'ecosystem.yml')
    with pytest.raises(ValidationError) as exc:
        resolve_style_profile(config, 'missing/1', language='en', script='Latn')
    assert exc.value.code == 'NCA_STYLE_PROFILE_INVALID'
    with pytest.raises(ValidationError):
        resolve_style_profile(config, '../../profile', language='en', script='Latn')


@pytest.mark.parametrize(('field', 'value'), [('language', 'en_XX'), ('script', 'Unknown')])
def test_profile_identity_is_validated_even_without_a_project(field, value):
    """Unusable language/script identities cannot enter the reusable library."""
    raw = configured_profile()
    raw['profile'][field] = value
    with pytest.raises(ValidationError) as exc:
        validate_style_profile(raw)
    assert exc.value.code == 'NCA_STYLE_PROFILE_INVALID'


def test_profile_script_compatibility_uses_canonical_code():
    """Equivalent ISO script casing remains compatible without changing source data."""
    raw = configured_profile()
    raw['profile']['script'] = 'latn'

    validated = validate_style_profile(raw, language='en', script='Latn')

    assert validated['profile']['script'] == 'latn'


def test_context_override_cannot_make_decimal_and_grouping_ambiguous():
    """Effective context rules must remain internally consistent."""
    raw = rule(configured_profile(), 'decimal', separator=',')
    rule(raw, 'contexts', decisions={'ages': {'status': 'OVERRIDE', 'rules': {'grouping': {'style': 'WESTERN', 'separator': ',', 'minimum': '1000'}}}})
    with pytest.raises(ValidationError):
        validate_style_profile(raw)


def test_duplicate_profile_yaml_keys_are_rejected(tmp_path):
    """A repeated serialized profile field cannot override an operator decision."""
    import yaml
    from sage.numbers.style import load_style_profile

    path = tmp_path / 'guide.yml'
    path.write_text(yaml.safe_dump(configured_profile()) + 'schema_version: "1.0"\n', encoding='utf-8')
    with pytest.raises(ValidationError) as exc:
        load_style_profile(path)
    assert exc.value.code == 'NCA_STYLE_PROFILE_INVALID'


def test_shipped_number_style_template_requires_configuration(package_root):
    """The standard template is available but cannot silently supply an active guide."""
    from sage.numbers.style import load_style_profile

    path = package_root / 'system/config/profiles/numbers/number-style-template.yml'
    with pytest.raises(ValidationError) as exc:
        load_style_profile(path)
    assert exc.value.code == 'NCA_STYLE_PROFILE_INVALID'
