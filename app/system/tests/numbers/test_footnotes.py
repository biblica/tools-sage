"""Reading-specific disclosure assessment preserves target-note evidence."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sage.numbers.models import FootnoteDecision, ReadingDecision, SemanticDecision, TargetNote, TargetUnit
from sage.numbers.footnotes import assess_footnote, footnote_recommendation
from sage.vrs import VerseRef
from .test_variants import READINGS, reference_case


def selected(record, choice='OL'):
    """Build a registered selection and its immutable supporting package."""
    row, bundle = reference_case(record)
    reading = ReadingDecision(choice, SemanticDecision('PASS_AUTHORITY1' if choice == 'OL' else 'REGISTERED_ALTERNATE'), record[f'FOOTNOTE_IF_TARGET_FOLLOWS_{choice}'], row.western_reference.label(), tuple(record['SOURCE_IDS'].split(';')), record[f'VALIDATION_IF_TARGET_FOLLOWS_{choice}'])
    return row, bundle, reading


def note_unit(ref, text='Some witnesses read four.', marker='f', anchor=None):
    """Create exact target content with distinct anchor provenance."""
    note = TargetNote('note-1', marker, text, (anchor or ref,), ({'kind': 'CONTENT', 'start': 0, 'end': len(text), 'text': text},))
    unit = TargetUnit('unit-1', (ref,), 'Seven days.', (note,), '0' * 64, {})
    return note, unit


class NoteTasks:
    """Return controlled already validated model decisions without provider calls."""
    def __init__(self, status='ADEQUATE'):
        """Capture the requested model behavior and inspected payloads."""
        self.status = status
        self.calls = []

    def assess_footnote(self, unit, note, guidance, *, required_action):
        """Model only the note supplied by the deterministic target filter."""
        self.calls.append((unit, note, guidance))
        outcome = 'NONE' if self.status == 'ADEQUATE' else 'INSUFFICIENT_EVIDENCE'
        spans = ((0, len(note.text)),) if self.status == 'ADEQUATE' else ()
        return SimpleNamespace(value=FootnoteDecision(required_action, self.status, outcome, spans))


@pytest.mark.parametrize('record', [record for record in READINGS if record['SCHOLARSHIP_STATUS'] == 'DIVIDED'])
@pytest.mark.parametrize('choice', ['OL', 'ALT'])
def test_all_divided_reading_choices_require_target_disclosure(record, choice):
    """All four divided registrations require disclosure for either selected text."""
    row, bundle, reading = selected(record, choice)
    result = assess_footnote(reading, (), bundle=bundle, language='en')
    assert (result.status, result.outcome) == ('MISSING', 'REVIEW_MISSING_FOOTNOTE')


def test_recommended_note_absence_preserves_semantic_pass():
    """An OL recommendation yields an advisory without changing numeric semantics."""
    row, bundle, reading = selected(READINGS[0])
    result = assess_footnote(reading, (), bundle=bundle, language='en')
    assert result.outcome == 'ADVISORY'
    assert reading.semantic.outcome == 'PASS_AUTHORITY1'


@pytest.mark.parametrize('text', ['Some witnesses read four.', 'Other manuscripts: 4.', 'The witnesses differ on this number.', 'This number is reconstructed from the parallel account.'])
def test_supported_disclosure_uses_exact_note_content(text):
    """Model-supported numeric, witness and reconstruction disclosures retain spans."""
    row, bundle, reading = selected(READINGS[0], 'ALT')
    note, unit = note_unit(row.western_reference, text)
    tasks = NoteTasks()
    result = assess_footnote(reading, (note,), bundle=bundle, language='en', unit=unit, model_tasks=tasks)
    assert result.status == 'ADEQUATE'
    assert result.evidence_spans == ((0, len(text)),)
    assert tasks.calls[0][2]['reading'] == 'ALT'


@pytest.mark.parametrize('marker,anchor,text', [('x', None, 'See 4:7.'), ('f', VerseRef('GEN', 1, 1), 'Some witnesses read four.'), ('f', None, '')])
def test_cross_references_wrong_verse_and_locator_only_notes_are_not_disclosure(marker, anchor, text):
    """Target eligibility excludes cross-references and notes without anchored content."""
    row, bundle, reading = selected(READINGS[0], 'ALT')
    note, unit = note_unit(row.western_reference, text, marker, anchor)
    tasks = NoteTasks()
    result = assess_footnote(reading, (note,), bundle=bundle, language='en', unit=unit, model_tasks=tasks)
    assert result.status == 'MISSING'
    assert not tasks.calls


def test_unsupported_note_understanding_is_not_known_inadequacy():
    """An unsupported language cannot become either an adequate or missing disclosure."""
    row, bundle, reading = selected(READINGS[0], 'ALT')
    note, unit = note_unit(row.western_reference)
    for tasks in (None, NoteTasks('NOT_ASSESSED')):
        result = assess_footnote(reading, (note,), bundle=bundle, language='und', unit=unit, model_tasks=tasks)
        assert (result.status, result.outcome) == ('NOT_ASSESSED', 'INSUFFICIENT_EVIDENCE')


def test_known_unrelated_note_is_inadequate_and_requires_revision():
    """A note containing the same number must still disclose the selected variation."""
    row, bundle, reading = selected(READINGS[0], 'ALT')
    note, unit = note_unit(row.western_reference, 'There are four seasons.')
    result = assess_footnote(reading, (note,), bundle=bundle, language='en', unit=unit, model_tasks=NoteTasks('INADEQUATE'))
    assert (result.status, result.outcome) == ('INADEQUATE', 'REVIEW_MISSING_FOOTNOTE')


def test_secondary_notes_cannot_be_substituted_for_target_notes():
    """A note absent from the immutable target unit cannot satisfy disclosure."""
    row, bundle, reading = selected(READINGS[0], 'ALT')
    note, unit = note_unit(row.western_reference)
    result = assess_footnote(reading, (note,), bundle=bundle, language='en', unit=replace(unit, notes=()), model_tasks=NoteTasks())
    assert result.status == 'MISSING'


def test_divided_ol_reading_still_requires_disclosure(empty_bundle):
    """Missing-note policy can be applied without a reference content lookup."""
    reading = ReadingDecision('OL', SemanticDecision('PASS_AUTHORITY1'), 'REQUIRE', '1SA 13:5', ())
    result = assess_footnote(reading, (), bundle=empty_bundle, language='en')
    assert (result.status, result.outcome) == ('MISSING', 'REVIEW_MISSING_FOOTNOTE')


def test_recommendation_retains_registered_wording_without_duplicate_advice():
    """Only absent or inadequate disclosure produces registered add/revise advice."""
    record = {**READINGS[0], 'SUGGESTED_NOTE_IF_ALT_SELECTED': 'Other witnesses read seven.'}
    row, bundle, reading = selected(record, 'ALT')
    result = assess_footnote(reading, (), bundle=bundle, language='en')
    recommendation = footnote_recommendation(reading, result, bundle=bundle)
    assert recommendation['suggested_note'] == record['SUGGESTED_NOTE_IF_ALT_SELECTED']
    assert recommendation['source_ids'] == reading.source_ids
    assert recommendation['action'] == 'ADD'
    assert footnote_recommendation(reading, FootnoteDecision('REQUIRE', 'ADEQUATE', 'NONE'), bundle=bundle) is None


def test_registered_absence_accepts_only_explicit_transferred_anchor():
    """NEH 7:68 can carry an exact adjacent note even with no local verse body."""
    row, bundle, reading = selected(next(item for item in READINGS if item['BK'] == 'NEH'))
    note, unit = note_unit(row.western_reference, 'Some witnesses add the horses and mules here.')
    unit = replace(unit, main_text='', target_references=())
    result = assess_footnote(reading, (note,), bundle=bundle, language='en', unit=unit, model_tasks=NoteTasks())
    assert result.status == 'ADEQUATE'


def test_unknown_reading_cannot_claim_that_no_note_is_required(empty_bundle):
    """An unresolved reading has unresolved disclosure policy even without an action."""
    reading = ReadingDecision('UNSUPPORTED', SemanticDecision('INSUFFICIENT_EVIDENCE'), 'NONE', None, ())
    result = assess_footnote(reading, (), bundle=empty_bundle, language='und')
    assert (result.status, result.outcome) == ('NOT_ASSESSED', 'INSUFFICIENT_EVIDENCE')
