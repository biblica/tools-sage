"""Governed NCA style preferences cannot change numeric meaning."""
from copy import deepcopy
from fractions import Fraction

import pytest

from sage.errors import ValidationError
from sage.numbers.models import Extraction, NumericExpression
from sage.numbers.style import assess_style, validate_style_profile


AREAS = ('digits', 'bands', 'grouping', 'decimal', 'ordinals', 'fractions', 'ranges', 'qualifiers', 'contexts', 'units')


def configured_profile():
    """Return explicit, reusable synthetic style decisions, with no inferred rules."""
    return {'schema_version': '1.0', 'profile': {'id': 'fixture-en', 'version': '1', 'language': 'en', 'script': 'Latn', 'projects': ['*'], 'source_guide': 'Synthetic project guide', 'recorded_by': 'Fixture operator', 'recorded_date': '2026-09-09', 'status': 'CONFIGURED'}, 'rules': {area: {'id': f'NCA-{area.upper()}', 'status': 'NOT_SPECIFIED'} for area in AREAS}}


def extraction(surface, value=3, **changes):
    """Create one supported exact numeric expression for style assessment."""
    fields = dict(values=(Fraction(value),), kind='CARDINAL', surface=surface, span=(0, len(surface)), role='men')
    fields.update(changes)
    return Extraction((NumericExpression(**fields),), 'COMPLETE')


def rule(profile, area, **fields):
    """Configure a single rule area while leaving every other decision explicit."""
    if area == 'contexts' and 'decisions' in fields:
        fields['decisions'] = {**{name: {'status': 'INHERIT'} for name in ('ages', 'dates', 'time', 'money', 'measurements', 'counts', 'genealogies')}, **fields['decisions']}
    profile['rules'][area].update(status='CONFIGURED', **fields)
    return profile


def reviews(result):
    """Select actual style findings, separately from visible unassessed areas."""
    return [item for item in result if item['status'] == 'REVIEW']


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


def test_words_digits_rule_preserves_normalized_value():
    """A words requirement reports presentation without modifying the quantity."""
    raw = rule(configured_profile(), 'bands', bands=[{'min': '0', 'max': '9', 'form': 'WORDS'}, {'min': '10', 'max': None, 'form': 'DIGITS'}])
    target = extraction('3')
    result = reviews(assess_style(target, profile=raw, location='body', context='counts'))
    assert [item['code'] for item in result] == ['NCA_STYLE_NUMBER_FORM']
    assert result[0]['rule_id'] == 'NCA-BANDS'
    assert target.expressions[0].values == (Fraction(3),)
    assert reviews(assess_style(extraction('three'), profile=raw, location='body', context='counts')) == []


def test_grouping_western_indic_and_exact_space_choices():
    """The exact selected grouping convention governs digit presentation."""
    raw = rule(configured_profile(), 'grouping', style='INDIC', separator=',', minimum='1000')
    assert reviews(assess_style(extraction('1,23,456', 123456), profile=raw, location='body', context='counts')) == []
    assert [item['code'] for item in reviews(assess_style(extraction('123,456', 123456), profile=raw, location='body', context='counts'))] == ['NCA_STYLE_GROUPING']
    rule(raw, 'grouping', style='WESTERN', separator='\u202f', minimum='1000')
    assert reviews(assess_style(extraction('1\u202f234', 1234), profile=raw, location='body', context='counts')) == []
    assert reviews(assess_style(extraction('1 234', 1234), profile=raw, location='body', context='counts'))


def test_digit_system_rule_checks_unicode_decimal_digits():
    """The configured ten-digit alphabet applies independently of numeric value."""
    raw = rule(configured_profile(), 'digits', preferred='٠١٢٣٤٥٦٧٨٩', allowed=['٠١٢٣٤٥٦٧٨٩'])
    assert reviews(assess_style(extraction('٣'), profile=raw, location='body', context='counts')) == []
    assert reviews(assess_style(extraction('3'), profile=raw, location='body', context='counts'))[0]['code'] == 'NCA_STYLE_DIGIT_SYSTEM'


def test_fraction_and_range_notation_are_explicit():
    """Fraction and range display rules preserve exact rational endpoints."""
    raw = rule(configured_profile(), 'fractions', notation='SLASH', forms={})
    assert reviews(assess_style(extraction('½', Fraction(1, 2), kind='FRACTION'), profile=raw, location='body', context='counts'))[0]['code'] == 'NCA_STYLE_FRACTION'
    raw = rule(configured_profile(), 'ranges', separator='–')
    target = extraction('3-4', kind='RANGE', values=(Fraction(3), Fraction(4)))
    assert reviews(assess_style(target, profile=raw, location='body', context='counts'))[0]['code'] == 'NCA_STYLE_RANGE'


def test_known_context_override_and_unknown_context_are_distinct():
    """An age exception applies only with supported age context."""
    raw = rule(configured_profile(), 'bands', bands=[{'min': '0', 'max': None, 'form': 'WORDS'}])
    rule(raw, 'contexts', decisions={'ages': {'status': 'OVERRIDE', 'rules': {'bands': {'bands': [{'min': '0', 'max': None, 'form': 'DIGITS'}]}}}})
    assert reviews(assess_style(extraction('3'), profile=raw, location='body', context='ages')) == []
    unknown = assess_style(extraction('3'), profile=raw, location='body', context=None)
    assert reviews(unknown) == []
    assert any(item['code'] == 'NCA_STYLE_CONTEXT_UNASSESSED' for item in unknown)


def test_not_specified_context_does_not_inherit_general_rule():
    """A missing age decision cannot silently apply the general number band."""
    raw = rule(configured_profile(), 'bands', bands=[{'min': '0', 'max': None, 'form': 'WORDS'}])
    rule(raw, 'contexts', decisions={'ages': {'status': 'NOT_SPECIFIED'}})

    result = assess_style(extraction('3'), profile=raw, location='body', context='ages')

    assert reviews(result) == []
    assert any(item['area'] == 'contexts' and item['status'] == 'NOT_ASSESSED' for item in result)
    assert any(item['area'] == 'bands' and item['status'] == 'NOT_ASSESSED' for item in result)


def test_majority_format_does_not_replace_guide_authority():
    """A scope full of digits still violates a words rule."""
    raw = rule(configured_profile(), 'bands', bands=[{'min': '0', 'max': None, 'form': 'WORDS'}])
    expressions = tuple(NumericExpression((Fraction(v),), 'CARDINAL', str(v), (2*i, 2*i+1), role='men') for i, v in enumerate([3, 4, 5]))
    result = reviews(assess_style(Extraction(expressions, 'COMPLETE'), profile=raw, location='body', context='counts'))
    assert len(result) == 3


def test_unspecified_rules_and_unavailable_locations_remain_unassessed():
    """Neither absent guide rules nor missing table/map content count as passes."""
    raw = configured_profile()
    result = assess_style(extraction('3'), profile=raw, location='body', context=None)
    assert result and all(item['status'] == 'NOT_ASSESSED' for item in result)
    assert reviews(assess_style(extraction('3'), profile=raw, location='map', context=None)) == []


def test_partial_interpretation_cannot_produce_style_findings():
    """Unsupported numeric interpretation is visible instead of inventing style errors."""
    raw = rule(configured_profile(), 'bands', bands=[{'min': '0', 'max': None, 'form': 'WORDS'}])
    result = assess_style(Extraction((), 'UNSUPPORTED', ('Unsupported script',)), profile=raw, location='body', context=None)
    assert reviews(result) == []
    assert any(item['code'] == 'NCA_STYLE_EXTRACTION_UNASSESSED' for item in result)


def test_ordinals_decimals_and_qualifier_forms_follow_explicit_rules():
    """Literal guide forms govern ordinals and qualifiers without changing meanings."""
    raw = rule(configured_profile(), 'ordinals', form='WORDS')
    assert reviews(assess_style(extraction('3rd', kind='ORDINAL'), profile=raw, location='body', context='counts'))[0]['code'] == 'NCA_STYLE_ORDINAL'
    raw = rule(configured_profile(), 'decimal', separator=',')
    assert reviews(assess_style(extraction('1.5', Fraction(3, 2)), profile=raw, location='body', context='measurements'))[0]['code'] == 'NCA_STYLE_DECIMAL'
    assert reviews(assess_style(extraction('1,5', Fraction(3, 2)), profile=raw, location='body', context='measurements')) == []
    raw = rule(configured_profile(), 'qualifiers', forms={'ABOUT': ['approximately']})
    expression = extraction('about 3', qualifier='ABOUT')
    assert reviews(assess_style(expression, profile=raw, location='body', context='counts'))[0]['code'] == 'NCA_STYLE_QUALIFIER'
    assert expression.expressions[0].qualifier == 'ABOUT'


def test_decimal_separator_must_separate_fractional_digits():
    """Grouping punctuation cannot satisfy the configured decimal convention."""
    raw = rule(configured_profile(), 'decimal', separator=',')

    result = reviews(assess_style(
        extraction('1,234.5', Fraction(2469, 2)),
        profile=raw,
        location='body',
        context='measurements',
    ))

    assert [item['code'] for item in result] == ['NCA_STYLE_DECIMAL']


def test_unknown_decimal_presentation_remains_unassessed():
    """A mixed word presentation cannot establish a decimal separator violation."""
    raw = rule(configured_profile(), 'decimal', separator=',')
    result = assess_style(extraction('1 and a half', Fraction(3, 2)), profile=raw, location='body', context='measurements')
    assert not reviews(result)
    assert any(item['code'] == 'NCA_STYLE_DECIMAL_UNASSESSED' for item in result)


def test_unit_abbreviations_apply_only_to_the_configured_location():
    """Heading abbreviations do not become a body or footnote rule."""
    locations = {where: {'status': 'NOT_SPECIFIED'} for where in ('body', 'heading', 'footnote')}
    locations['heading'] = {'status': 'CONFIGURED', 'form': 'ABBREVIATION', 'spacing': 'SPACE', 'forms': {'mile': ['mi']}}
    raw = rule(configured_profile(), 'units', locations=locations)
    assert reviews(assess_style(extraction('3 miles', unit='mile'), profile=raw, location='heading', context='measurements'))[0]['code'] == 'NCA_STYLE_UNIT'
    assert reviews(assess_style(extraction('3 mi', unit='mile'), profile=raw, location='heading', context='measurements')) == []
    assert reviews(assess_style(extraction('3 miles', unit='mile'), profile=raw, location='body', context='measurements')) == []


def test_words_with_parenthesized_digits_can_be_required():
    """Dual presentation is one semantic quantity under the configured band."""
    raw = rule(configured_profile(), 'bands', bands=[{'min': '0', 'max': None, 'form': 'WORDS_AND_DIGITS'}])
    assert reviews(assess_style(extraction('three (3)'), profile=raw, location='body', context='counts')) == []
    assert reviews(assess_style(extraction('3'), profile=raw, location='body', context='counts'))[0]['code'] == 'NCA_STYLE_NUMBER_FORM'


def test_profile_library_import_selection_and_content_conflicts(make_workspace, tmp_path):
    """Imported profiles live in localdata and resolve exactly or require selection."""
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
    selected = resolve_style_profile(config, None, language='en', script='Latn', project='Fixture')
    assert selected.path == imported
    assert selected.selector == 'fixture-en/1'
    assert selected.document['profile']['version'] == '1'
    raw['profile']['id'] = 'second-en'
    source.write_text(yaml.safe_dump(raw), encoding='utf-8')
    import_style_profile(config, source)
    with pytest.raises(ValidationError) as exc:
        resolve_style_profile(config, None, language='en', script='Latn')
    assert exc.value.code == 'NCA_STYLE_PROFILE_SELECTION_REQUIRED'
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
        resolve_style_profile(config, None, language='en', script='Latn')
    assert exc.value.code == 'NCA_STYLE_PROFILE_NOT_CONFIGURED'
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


def test_custom_grouping_separator_is_actually_assessed():
    """A valid nonstandard grouping rule cannot silently skip its own separator."""
    raw = rule(configured_profile(), 'grouping', style='WESTERN', separator="'", minimum='1000')
    assert reviews(assess_style(extraction("12'34", 1234), profile=raw, location='body', context='counts'))[0]['code'] == 'NCA_STYLE_GROUPING'


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
