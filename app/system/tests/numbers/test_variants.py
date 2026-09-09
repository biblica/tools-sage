"""Whole registered readings keep OL authority and footnote policy distinct."""
import json
from pathlib import Path
from fractions import Fraction

import pytest

from sage.numbers.models import ReferenceBundle, ReferenceRow, SemanticDecision
from sage.numbers.reference import parse_values
from sage.numbers.variants import select_reading
from sage.vrs import VerseRef


READINGS = json.loads((Path(__file__).parent / 'fixtures/registered-readings.json').read_text())


def reference_case(record):
    """Create immutable minimal authority/policy data from authorized acceptance values."""
    ref = VerseRef(record['BK'], int(record['CH']), int(record['VS']))
    row = ReferenceRow(ref, record['OL_REF'] or None, 'HEB' if record['OL_REF'] else '', 'Synthetic source' if record['OL_REF'] else '', parse_values(record['OL_VALUES']), 'Synthetic alternate', parse_values(record['ALT_NIV_VALUES']), {'SOURCE_IDS': record['SOURCE_IDS']})
    variant = {'OL_VALUE_RESEARCHED': record['OL_VALUES'], 'NIV_VALUE_RESEARCHED': record['ALT_NIV_VALUES'], 'SOURCE_IDS': record['SOURCE_IDS'], 'CLASS': record['CLASS'], 'SCHOLARSHIP_STATUS': record['SCHOLARSHIP_STATUS']}
    sources = {source: {'SOURCE_ID': source} for source in record['SOURCE_IDS'].split(';')}
    bundle = ReferenceBundle('registered-reading-fixture', '0' * 64, {ref: row}, {ref: variant}, {ref: record}, {}, sources, 'QUALIFIED')
    return row, bundle


@pytest.mark.parametrize('record', READINGS, ids=lambda record: f"{record['BK']}-{record['CH']}-{record['VS']}")
def test_entire_registered_reading_matrix_preserves_policy(record):
    """Each of the 21 actual policy pairs retains its source IDs and disclosure actions."""
    row, bundle = reference_case(record)
    ol = select_reading(row, row.ol_values, bundle=bundle, semantic=SemanticDecision('PASS_AUTHORITY1'))
    alt = select_reading(row, row.niv_values, bundle=bundle, semantic=SemanticDecision('PASS_AUTHORITY1'))
    assert ol.selected == 'OL'
    assert ol.footnote_action == record['FOOTNOTE_IF_TARGET_FOLLOWS_OL']
    assert ol.source_validation_outcome == record['VALIDATION_IF_TARGET_FOLLOWS_OL']
    assert alt.selected == 'ALT'
    assert alt.footnote_action == 'REQUIRE'
    assert alt.semantic.outcome == 'REGISTERED_ALTERNATE'
    assert alt.source_validation_outcome == record['VALIDATION_IF_TARGET_FOLLOWS_ALT']
    assert alt.source_ids == tuple(record['SOURCE_IDS'].split(';'))
    assert bundle.lookup(row.western_reference).ol_values == row.ol_values


def test_whole_alternate_sequence_must_match_unchanged_quantities():
    """The alternate age cannot authorize changing the reign length too."""
    row, bundle = reference_case(next(record for record in READINGS if record['BK'] == '2CH' and record['CH'] == '22'))
    invalid = select_reading(row, (Fraction(22), Fraction(2)), bundle=bundle, semantic=SemanticDecision('PASS_AUTHORITY1'))
    assert invalid.selected == 'UNSUPPORTED'
    assert invalid.semantic.outcome == 'REVIEW_VALUE_DIFFERENCE'


def test_niv_equality_without_registry_authorization_cannot_select_alternate():
    """Secondary-index equality alone never authorizes a source reading."""
    from dataclasses import replace
    row, bundle = reference_case(READINGS[0])
    bundle = replace(bundle, variants={}, footnote_guidance={})
    decision = select_reading(row, row.niv_values, bundle=bundle, semantic=SemanticDecision('PASS_AUTHORITY1'))
    assert decision.selected == 'UNSUPPORTED'


def test_registered_values_do_not_erase_failed_semantic_correspondence():
    """A registered value cannot conceal swapped roles or unknown interpretation."""
    row, bundle = reference_case(READINGS[0])
    for outcome in ('INSUFFICIENT_EVIDENCE', 'REVIEW_VALUE_DIFFERENCE', 'NOT_ASSESSED'):
        decision = select_reading(row, row.niv_values, bundle=bundle, semantic=SemanticDecision(outcome))
        assert decision.semantic.outcome == outcome


def test_registered_absence_is_never_an_ordinary_ol_numeric_pass():
    """NEH 7:68 retains a nullable source and the explicit registered-absence state."""
    row, bundle = reference_case(next(record for record in READINGS if record['BK'] == 'NEH'))
    decision = select_reading(row, (), bundle=bundle, semantic=SemanticDecision('PASS_AUTHORITY1'))
    assert row.ol_reference is None
    assert decision.semantic.outcome == 'NO_CONFIGURED_OL_READING'
    assert decision.footnote_action == 'REQUIRE'
