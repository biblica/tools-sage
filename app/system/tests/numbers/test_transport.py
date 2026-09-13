"""Exact source slices and immutable projection bindings for optimized extraction."""
from dataclasses import replace

import pytest

from sage.errors import ValidationError
from sage.usj import compile_usfm_text
from sage.numbers.target import target_units, extract_heading_units


def test_stream_records_copy_nested_payload_and_bind_exact_sfm():
    """Caller mutation cannot change the source evidence after construction."""
    from sage.numbers.transport import make_stream_input
    from sage.work_units import EvidenceRecord
    record = EvidenceRecord('MAT', 1, 1, 1, {'nested': ['original']}, '\\v 1 Three men.')
    value = make_stream_input(owner_unit_id='one', stream_id='main', purpose='BODY',
        target_references=record.refs, records=(record,), text='Three men.', source_sha256='0' * 64,
        language='en', conventions={})
    record.payload['nested'][0] = 'changed'
    assert value.records[0].payload['nested'] == ('original',)
    assert value.routed_sfm == '\\id MAT\n\\c 1\n\\v 1 Three men.\n'
    with pytest.raises(TypeError):
        value.records[0].payload['nested'] = ()
    with pytest.raises(ValidationError):
        replace(value, routed_sfm='different')
    with pytest.raises(ValidationError):
        replace(value, source_sha256='bad')


def test_projection_hash_binds_text_stream_coordinates_source_and_conventions():
    """Reuse identity changes with each admitted extraction boundary."""
    from sage.numbers.transport import make_stream_input
    from sage.work_units import EvidenceRecord
    record = EvidenceRecord('MAT', 1, 1, 1, {}, '\\v 1 Three men.')
    kwargs = dict(owner_unit_id='one', stream_id='main', purpose='BODY',
        target_references=record.refs, records=(record,), text='Three men.', source_sha256='0' * 64,
        language='en', conventions={})
    baseline = make_stream_input(**kwargs)
    for key, value in [('text', 'Thirty men.'), ('stream_id', 'note:1'), ('source_sha256', '1' * 64),
                       ('language', 'fr'), ('conventions', {'digits': 'Latin'})]:
        assert make_stream_input(**dict(kwargs, **{key: value})).projection_sha256 != baseline.projection_sha256


def test_body_notes_and_heading_bind_to_source_owned_stream_offsets():
    """Every projection retains source wording, marker identity, and its own offsets."""
    from sage.numbers.transport import streams_for_target
    source = compile_usfm_text('\\id MAT Fixture\n\\c 1\n\\s1 Section 200\n\\p\n'
        '\\v 1 Three men.\\f + \\fr 1:1 \\ft Thirty men.\\f*\\f + \\ft Forty men.\\f*\n')
    body, = target_units(source, source_sha256='0' * 64)
    heading, = extract_heading_units(source, source_sha256='0' * 64)
    values = streams_for_target(body, source, language='en', conventions={})
    style, = streams_for_target(heading, source, language='en', conventions={}, heading=True)
    assert [value.text for value in values] == ['Three men.', 'Thirty men.', 'Forty men.']
    assert [value.purpose for value in values] == ['BODY', 'NOTE_STYLE', 'NOTE_STYLE']
    assert all(value.records[0].sfm == source['sage']['verse_records'][0]['raw_usfm'] for value in values)
    assert style.text == 'Section 200'
    assert '\\s1 Section 200' in style.routed_sfm and '\\v 1' not in style.routed_sfm
    assert style.records[0].payload['source_locator']['content_index'] == heading.source_locator['content_index']
    assert style.records[0].payload['source_nodes'][0]['marker'] == 's1'


def test_multiple_psalm_superscriptions_keep_marker_and_projection_paragraph_offsets():
    """Canonical verse zero is bounded from structural source nodes, never synthetic verse text."""
    from sage.numbers.transport import streams_for_target
    source = compile_usfm_text('\\id PSA Fixture\n\\c 60\n\\d First title.\n\\d Twelve thousand.\n\\v 1 Three.\n')
    title = target_units(source, source_sha256='0' * 64)[0]
    value, = streams_for_target(title, source, language='en', conventions={})
    assert value.text == 'First title.\nTwelve thousand.'
    assert value.routed_sfm.count('\\d ') == 2
    assert '\\v 0' not in value.routed_sfm and '\\v 1' not in value.routed_sfm
    assert value.records[0].payload['source_locator']['paragraph_1_start'] == 13


@pytest.mark.parametrize('damage', ['text', 'note', 'identity'])
def test_changed_projection_cannot_bind_to_unchanged_source(damage):
    """A valid-looking hash cannot legitimize text or notes not present in the bound source."""
    from sage.numbers.transport import streams_for_target
    source = compile_usfm_text('\\id MAT Fixture\n\\c 1\n\\v 1 Three.\\f + \\ft Thirty.\\f*\n')
    unit, = target_units(source, source_sha256='0' * 64)
    if damage == 'text':
        unit = replace(unit, main_text='Fabricated.')
    elif damage == 'note':
        unit = replace(unit, notes=(replace(unit.notes[0], text='Fabricated.', content_spans=()),))
    else:
        value = streams_for_target(unit, source, language='en', conventions={})[0]
        with pytest.raises(ValidationError):
            replace(value, input_id='forged')
        return
    with pytest.raises(ValidationError):
        streams_for_target(unit, source, language='en', conventions={})


def test_combined_source_group_binds_exact_component_offsets_and_raw_records():
    """Cross-chapter protected groups keep their two real source slices and projection offsets."""
    from sage.numbers.transport import streams_for_target
    from sage.numbers.projection import _combined
    source = compile_usfm_text('\\id 1SA Fixture\n\\c 20\n\\v 42 Two.\n\\c 21\n\\v 1 Continuation.\n')
    group = _combined(target_units(source, source_sha256='0' * 64))
    value, = streams_for_target(group, source, language='en', conventions={})
    assert value.text == 'Two.\nContinuation.'
    assert [record.sfm for record in value.records] == ['\\v 42 Two.', '\\v 1 Continuation.']
    assert group.source_locator['component_1_start'] == 5
    damaged = dict(group.source_locator, component_1_start=4)
    with pytest.raises(ValidationError):
        streams_for_target(replace(group, source_locator=damaged), source, language='en', conventions={})


def test_structural_inline_markers_keep_delimiters_and_source_text():
    """An unpaired structural marker must not absorb the following source word."""
    from sage.numbers.transport import streams_for_target
    source = compile_usfm_text('\\id MAT Fixture\n\\c 1\n\\s1 Section \\zcustom Two\n\\v 1 Three.\n')
    heading, = extract_heading_units(source, source_sha256='0' * 64)
    value, = streams_for_target(heading, source, language='en', conventions={}, heading=True)
    assert '\\zcustom Two' in value.routed_sfm
    assert value.text == 'Section Two'
