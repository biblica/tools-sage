"""Noteworthy text-critical info: a local, deterministic, non-blocking advisory lookup."""
from sage.numbers.footnotes import noteworthy_note
from sage.numbers.models import ReferenceBundle
from sage.vrs import VerseRef


def bundle(guidance):
    """Build one minimal qualified bundle exposing only footnote guidance."""
    return ReferenceBundle(
        package_id='fixture', sha256='0' * 64, rows={}, variants={},
        footnote_guidance=guidance, units={}, provenance={}, qualification_status='QUALIFIED',
    )


def test_indexed_coordinate_returns_the_registered_guidance_fields():
    """Every registered field is surfaced verbatim, keyed by its own western label."""
    ref = VerseRef('MRK', 16, 9)
    record = bundle({ref: {
        'CLASS': 'TEXTUAL_VARIANT', 'SCHOLARSHIP_STATUS': 'DIVIDED',
        'MANUSCRIPT_EVIDENCE': 'Absent from the earliest manuscripts.',
        'SCHOLARSHIP_POSITION': 'Widely considered a later addition.',
        'OL_VALUES': '', 'ALT_NIV_VALUES': '',
    }})

    note = noteworthy_note(ref, bundle=record)

    assert note == {
        'western_reference': 'MRK 16:9',
        'classification': 'TEXTUAL_VARIANT',
        'scholarship_status': 'DIVIDED',
        'manuscript_evidence': 'Absent from the earliest manuscripts.',
        'scholarship_position': 'Widely considered a later addition.',
        'ol_values': '',
        'alternate_values': '',
    }


def test_unindexed_coordinate_returns_none():
    """A coordinate with no registered guidance produces no note, not an empty one."""
    record = bundle({})
    assert noteworthy_note(VerseRef('MAT', 1, 1), bundle=record) is None


def test_missing_fields_render_as_empty_strings_not_none():
    """Partial guidance records still produce every field, defaulting to an empty string."""
    ref = VerseRef('JHN', 5, 4)
    record = bundle({ref: {'CLASS': 'TEXTUAL_VARIANT'}})

    note = noteworthy_note(ref, bundle=record)

    assert note['classification'] == 'TEXTUAL_VARIANT'
    assert note['scholarship_status'] == ''
    assert note['manuscript_evidence'] == ''
    assert note['scholarship_position'] == ''
    assert note['ol_values'] == ''
    assert note['alternate_values'] == ''


def test_note_lookup_never_blocks_on_the_numeric_result():
    """The advisory is a pure function of the bundle and coordinate -- no model call, no state."""
    ref = VerseRef('LUK', 3, 1)
    record = bundle({ref: {'CLASS': 'NONE', 'SCHOLARSHIP_STATUS': 'ACCEPTED'}})

    first = noteworthy_note(ref, bundle=record)
    second = noteworthy_note(ref, bundle=record)

    assert first == second
