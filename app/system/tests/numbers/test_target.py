"""NCA preserves exact body evidence, note streams and superscriptions."""
from copy import deepcopy

import pytest

from sage.errors import ValidationError
from sage.numbers.target import target_units, extract_heading_units
from sage.usj import compile_usfm_text
from sage.vrs import VerseRef


def test_note_digits_do_not_enter_main_text():
    """Note digits do not enter main text."""
    usj = compile_usfm_text(
        '\\id MAT Fixture\n\\c 1\n'
        '\\v 1 Three men.\\f + \\fr 1:1 \\ft Other witnesses read thirty.\\f*\n'
    )
    before = deepcopy(usj)
    unit, = target_units(usj, source_sha256='0' * 64)
    assert unit.main_text == 'Three men.'
    assert unit.notes[0].text == 'Other witnesses read thirty.'
    assert unit.notes[0].anchor_references == (VerseRef('MAT', 1, 1),)
    assert unit.source_locator['line_start'] == 3
    assert usj == before


def test_editorial_headings_are_separate_exact_style_streams():
    """Heading numbers remain available for style without entering body accuracy."""
    usj = compile_usfm_text('\\id MAT Fixture\n\\c 1\n\\s1 Section 200\n\\p\n\\v 1 Three men.\n')
    before = deepcopy(usj)
    heading, = extract_heading_units(usj, source_sha256='0' * 64)
    assert heading.main_text == 'Section 200'
    assert heading.target_references == (VerseRef('MAT', 1, 1),)
    assert heading.source_locator['heading'] == 1
    assert target_units(usj, source_sha256='0' * 64)[0].main_text == 'Three men.'
    assert usj == before


def test_canonical_psalm_title_is_not_duplicated_as_editorial_heading():
    """The accuracy-bearing superscription is assessed once in its canonical stream."""
    usj = compile_usfm_text('\\id PSA Fixture\n\\c 60\n\\d Twelve thousand men.\n\\p\n\\v 1 Three men.\n')
    assert extract_heading_units(usj, source_sha256='0' * 64) == ()
    units = target_units(usj, source_sha256='0' * 64)
    assert units[0].target_references == (VerseRef('PSA', 60, 0),)


def test_heading_paragraph_stops_at_first_verse_milestone():
    """A compiler paragraph containing the next verse cannot duplicate its body."""
    usj = compile_usfm_text('\\id MAT Fixture\n\\c 1\n\\s1 Section 200\n\\v 1 Three men.\n')
    heading, = extract_heading_units(usj, source_sha256='0' * 64)
    assert heading.main_text == 'Section 200'


@pytest.mark.parametrize('marker', ['f', 'fe', 'ef', 'efe'])
def test_extended_notes_and_nested_styles_have_exact_content_spans(marker):
    """Extended notes and nested styles have exact content spans."""
    usj = compile_usfm_text(
        f'\\id MAT Fixture\n\\c 1\n\\v 1 Three men.\\{marker} + '
        f'\\fr 1:1 \\ft Other \\+it witnesses\\+it* read thirty.\\fv 9\\{marker}*\n'
    )
    unit, = target_units(usj, source_sha256='0' * 64)
    note, = unit.notes
    assert note.text == 'Other witnesses read thirty.'
    assert note.marker == marker
    locators = [span for span in note.content_spans if span['kind'] == 'LOCATOR']
    assert [span['text'] for span in locators] == ['1:1 ', '9']
    for span in note.content_spans:
        if span['kind'] == 'CONTENT':
            assert note.text[span['start']:span['end']] == span['text']


def test_cross_references_attributes_and_headings_are_not_body_numbers():
    """Cross references attributes and headings are not body numbers."""
    usj = compile_usfm_text(
        '\\id MAT Fixture\n\\c 1\n\\s1 Section 200\n\\p\n'
        '\\v 1 \\w Three|lemma="3" strong="G300"\\w* men.'
        '\\x + \\xo 1:1 \\xt See 3:20.\\x*'
        '\\ex + \\xo 1:1 \\xt See 4:40.\\ex*\n'
    )
    unit, = target_units(usj, source_sha256='0' * 64)
    assert unit.main_text == 'Three men.'
    assert unit.notes == ()


def test_note_only_verse_and_bridge_are_retained_once():
    """Note only verse and bridge are retained once."""
    usj = compile_usfm_text(
        '\\id MAT Fixture\n\\c 1\n\\v 1-2 Three men.\n'
        '\\v 3 \\f + \\ft Other witnesses include four.\\f*\n'
    )
    bridge, note_only = target_units(usj, source_sha256='0' * 64)
    assert bridge.target_references == (VerseRef('MAT', 1, 1), VerseRef('MAT', 1, 2))
    assert bridge.main_text == 'Three men.'
    assert note_only.main_text == ''
    assert note_only.notes[0].text == 'Other witnesses include four.'


def test_superscription_is_accuracy_bearing_but_editorial_heading_is_not():
    """Superscription is accuracy bearing but editorial heading is not."""
    usj = compile_usfm_text(
        '\\id PSA Fixture\n\\c 60\n\\s1 Editorial 88\n'
        '\\d Twelve thousand defeated.\n\\q1\n\\v 1 Three men.\n'
    )
    title, verse = target_units(usj, source_sha256='0' * 64)
    assert title.target_references == (VerseRef('PSA', 60, 0),)
    assert title.main_text == 'Twelve thousand defeated.'
    assert title.source_locator['content_index'] == 3
    assert verse.target_references == (VerseRef('PSA', 60, 1),)


def test_explicit_verse_zero_does_not_duplicate_structural_title():
    """Explicit verse zero does not duplicate structural title."""
    usj = compile_usfm_text('\\id PSA Fixture\n\\c 60\n\\d\\v 0 Twelve thousand.\n\\q1\n\\v 1 Three.\n')
    units = target_units(usj, source_sha256='0' * 64)
    assert sum(VerseRef('PSA', 60, 0) in unit.target_references for unit in units) == 1


def test_explicit_note_anchor_can_identify_a_missing_adjacent_verse():
    """Explicit note anchor can identify a missing adjacent verse."""
    usj = compile_usfm_text(
        '\\id NEH Fixture\n\\c 7\n\\v 69 Other text.'
        '\\f + \\fr 7:68 \\ft Some witnesses include animals.\\f*\n'
    )
    unit, = target_units(usj, source_sha256='0' * 64)
    assert unit.notes[0].anchor_references == (VerseRef('NEH', 7, 68),)


def test_unclosed_note_fails_instead_of_returning_incomplete_body():
    """Unclosed note fails instead of returning incomplete body."""
    usj = compile_usfm_text('\\id MAT Fixture\n\\c 1\n\\v 1 Three.\\f + \\ft Thirty.\n')
    with pytest.raises(ValidationError) as exc:
        target_units(usj, source_sha256='0' * 64)
    assert exc.value.code == 'NCA_TARGET_PARSE_ERROR'


def test_duplicate_target_coordinates_are_rejected():
    """Duplicate target coordinates are rejected."""
    usj = compile_usfm_text('\\id MAT Fixture\n\\c 1\n\\v 1 Three.\n\\v 1 Four.\n')
    with pytest.raises(ValidationError) as exc:
        target_units(usj, source_sha256='0' * 64)
    assert exc.value.code == 'NCA_TARGET_DUPLICATE_REFERENCE'


def test_superscription_stops_at_following_verse_without_paragraph_marker():
    """Superscription stops at following verse without paragraph marker."""
    usj = compile_usfm_text('\\id PSA Fixture\n\\c 60\n\\d Twelve thousand.\n\\v 1 Three.\n')
    title, verse = target_units(usj, source_sha256='0' * 64)
    assert title.main_text == 'Twelve thousand.'
    assert verse.main_text == 'Three.'


def test_multiple_superscription_paragraphs_retain_all_title_content():
    """Multiple superscription paragraphs retain all title content."""
    usj = compile_usfm_text('\\id PSA Fixture\n\\c 60\n\\d For the director.\n\\d Twelve thousand.\n\\q1\n\\v 1 Three.\n')
    title, verse = target_units(usj, source_sha256='0' * 64)
    assert title.main_text == 'For the director.\nTwelve thousand.'


def test_ambiguous_explicit_note_anchor_is_not_replaced_by_current_verse():
    """Ambiguous explicit note anchor is not replaced by current verse."""
    usj = compile_usfm_text('\\id NEH Fixture\n\\c 7\n\\v 69 Text.\\f + \\fr 7:68, 70 \\ft Other reading.\\f*\n')
    unit, = target_units(usj, source_sha256='0' * 64)
    assert unit.notes[0].anchor_references == ()


def test_superscription_collection_stops_after_first_verse_across_paragraphs():
    """Superscription collection stops after first verse across paragraphs."""
    usj = compile_usfm_text('\\id PSA Fixture\n\\c 60\n\\d First title.\n\\q1\n\\v 1 Three.\n\\d Later editorial 44.\n')
    title, verse = target_units(usj, source_sha256='0' * 64)
    assert title.main_text == 'First title.'
