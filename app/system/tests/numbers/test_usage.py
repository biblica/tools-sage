"""Observed number usage is descriptive, bounded and separated by evidence stream."""
from copy import deepcopy

import pytest

from sage.errors import ValidationError


def expression(surface, value='12', *, stream='main', kind='CARDINAL', unit=None):
    """Build a complete serialized extraction expression at the start of its text."""
    return dict(expression_id='e1', stream_id=stream, surface=surface, span=[0, len(surface)],
                values=[value], kind=kind, unit=unit, qualifier='EXACT', role=None,
                role_spans=[], representations=[])


def usage_document():
    """Keep one bridged body, one heading and one footnote in distinct domains."""
    groups = []
    for identity, surface, precision in [('body', 'twelve', 'BRIDGE'), ('heading', '12', 'STYLE_STREAM')]:
        groups.append(dict(unit_id=identity, projection=dict(target_references=['MAT 1:1', 'MAT 1:2'],
            precision=precision, target_text=surface, target_note_streams=[], target_note_metadata=[]),
            extraction=dict(status='COMPLETE', limitations=[], expressions=[expression(surface)]),
            note_extractions={}))
    body = groups[0]
    body['projection']['target_note_streams'] = [{'note_id': 'n1', 'text': '12'}]
    body['projection']['target_note_metadata'] = [{'note_id': 'n1', 'anchor_references': ['MAT 1:2']}]
    body['note_extractions'] = {'n1': dict(status='COMPLETE', limitations=[],
        expressions=[expression('12', stream='n1')])}
    return dict(groups=groups, check_policy={'checks': {'presentation_consistency': True}})


def test_usage_preserves_bridge_once_and_separates_note_and_heading():
    """Count each admitted expression once rather than once per projected verse."""
    from sage.numbers.usage import number_usage
    result = number_usage(usage_document())
    assert result['expression_count'] == 3
    assert result['forms'] == {'WORDS': 1, 'DIGITS': 2}
    assert [row['location'] for row in result['examples']] == ['body', 'footnote', 'heading']
    assert result['examples'][0]['target_references'] == ['MAT 1:1', 'MAT 1:2']
    assert result['examples'][1]['target_references'] == ['MAT 1:2']
    assert not result['mixed_usage']  # Distinct stream purposes are not contradictions.


def test_usage_reports_mixed_body_forms_without_inventing_a_rule():
    """Same-valued body forms become reviewable observations, never style violations."""
    from sage.numbers.usage import number_usage
    document = usage_document()
    other = deepcopy(document['groups'][1])
    other['unit_id'] = 'other-body'
    other['projection'].update(precision='COORDINATE', target_references=['MAT 2:1'])
    document['groups'].append(other)
    result = number_usage(document)
    assert len(result['mixed_usage']) == 1
    assert result['mixed_usage'][0]['forms'] == ['DIGITS', 'WORDS']
    assert result['mixed_usage'][0]['values'] == ['12']
    assert all('expected' not in row for row in result['examples'])


def test_partial_and_missing_note_extraction_remain_visible():
    """Historical missing note evidence is not interpreted as a zero-number note."""
    from sage.numbers.usage import number_usage
    document = usage_document()
    document['groups'][0]['extraction'].update(status='PARTIAL', limitations=['Ambiguous word'])
    del document['groups'][0]['note_extractions']
    result = number_usage(document)
    assert result['expression_count'] == 2
    assert result['coverage'] == {'COMPLETE': 1, 'PARTIAL': 1, 'NOT_ASSESSED': 1}
    assert any(row['note_id'] == 'n1' for row in result['unassessed'])


@pytest.mark.parametrize('damage', ['span', 'foreign', 'duplicate', 'value', 'stream', 'missing'])
def test_note_usage_rejects_unanchored_or_invented_evidence(damage):
    """Reportable note expressions must pass the existing exact expression contract."""
    from sage.numbers.usage import validate_note_extractions
    document = usage_document()['groups'][0]
    raw = document['note_extractions']
    validate_note_extractions(raw, document['projection'], enabled=True)
    if damage == 'span':
        raw['n1']['expressions'][0]['span'] = [1, 3]
    elif damage == 'foreign':
        raw['foreign'] = raw.pop('n1')
    elif damage == 'duplicate':
        raw['n1']['expressions'] *= 2
    elif damage == 'value':
        raw['n1']['expressions'][0]['values'] = ['1.2']
    elif damage == 'stream':
        raw['n1']['expressions'][0]['stream_id'] = 'main'
    else:
        raw.clear()
    with pytest.raises(ValidationError):
        validate_note_extractions(raw, document['projection'], enabled=True)


def test_report_includes_usage_and_marks_absent_stylesheet():
    """The normal report exposes observations without a stylesheet dependency."""
    from sage.nca_reporting import render_nca_report
    from .test_reporting import report_document
    document = report_document()
    document['provenance']['style_profile'] = {'selector': None, 'sha256': None}
    document['units'] = []
    document['findings'] = []
    report = render_nca_report(document)
    assert 'Number Usage Report' in report
    assert 'No stylesheet selected' in report
    assert 'approved rules' in report


def test_usage_report_quotes_source_text_without_rendering_markup():
    """Numeric source surfaces cannot inject table columns, HTML or Markdown links."""
    from sage.numbers.usage import render_number_usage
    from sage.nca_reporting import _ENGLISH
    document = usage_document()
    document['provenance'] = {'style_profile': {'selector': None}}
    document['groups'][0]['extraction']['expressions'][0]['surface'] = '12 | `<script>`\n'
    report = '\n'.join(render_number_usage(document, _ENGLISH.__getitem__))
    assert '<script>' not in report
    assert '\\u007c' in report and '\\u003cscript' in report and '\\n' in report


def test_stylesheet_absence_requires_both_provenance_fields_explicitly_null():
    """Missing or half-null style provenance cannot masquerade as sealed absence."""
    from sage.numbers.results import _validate_provenance
    base = dict(run_id='r', job_id='j', reference_package={'package_id': 'p', 'sha256': 'a' * 64},
                wip={'identity': 'w', 'sha256': 'b' * 64})
    _validate_provenance(dict(base, style_profile={'selector': None, 'sha256': None}))
    for style in ({}, {'selector': 'profile/1', 'sha256': None}, {'selector': None, 'sha256': 'a' * 64}):
        with pytest.raises(ValidationError):
            _validate_provenance(dict(base, style_profile=style))
