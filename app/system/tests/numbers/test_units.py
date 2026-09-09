"""Registered unit examples preserve exact scope, qualifiers and other quantities."""
import json
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from sage.errors import ValidationError
from sage.numbers.models import Extraction, NumericExpression, ReferenceBundle, ReferenceRow
from sage.numbers.reference import parse_values
from sage.numbers.units import compare_registered_units, parse_registered_quantity
from sage.vrs import VerseRef

CASES = json.loads((Path(__file__).parent / 'fixtures/registered-units.json').read_text())


def unit_case(record):
    """Create a minimal immutable reference case from authorized unit metadata."""
    ref = VerseRef(record['BK'], int(record['CH']), int(record['VS']))
    row = ReferenceRow(ref, record['OL_REF'], 'GRK', 'Synthetic source', parse_values(record['OL_VALUES']), 'Authoritative display', parse_values(record['NIV_VALUES']), {'SOURCE_IDS': record['SOURCE_IDS']})
    sources = {source: {'SOURCE_ID': source} for source in record['SOURCE_IDS'].split(';')}
    bundle = ReferenceBundle('registered-unit-fixture', '0' * 64, {ref: row}, {}, {}, {ref: record}, sources, 'QUALIFIED')
    return row, bundle


def expression(value, role='unconverted'):
    """Represent an independently retained source quantity with no converted unit."""
    return NumericExpression((Fraction(value),), 'CARDINAL', str(value), (0, len(str(value))), role=role)


def target_for(record, extras=()):
    """Supply hand-specified unrelated values alongside the registered target unit examples."""
    converted = tuple(replace(item, role=f'measure-{index}') for index, item in enumerate(parse_registered_quantity(record['NIV_QUANTITY'])))
    return Extraction(tuple(expression(value) for value in extras) + converted, 'COMPLETE')


def test_registered_range_and_qualifier_are_retained():
    """A registered approximate range is not flattened or treated as exact."""
    item, = parse_registered_quantity('about 3-4 miles')
    assert item.kind == 'RANGE'
    assert item.values == (Fraction(3), Fraction(4))
    assert item.unit == 'mile'
    assert item.qualifier == 'ABOUT'


@pytest.mark.parametrize(('index', 'extras'), [(0, ()), (1, ()), (2, ()), (3, (2,)), (4, (6,)), (5, ()), (6, ()), (7, (1,)), (8, ()), (9, ()), (10, (4,)), (11, ())])
def test_all_registered_unit_pairs_preserve_unrelated_source_values(index, extras):
    """Each registered example accepts only its exact typed conversion and retained values."""
    record = CASES[index]
    row, bundle = unit_case(record)
    result = compare_registered_units(row, target_for(record, extras), bundle=bundle)
    assert result.outcome == 'PASS_UNIT_CONVERSION'
    assert result.evidence_ids == tuple(record['SOURCE_IDS'].split(';'))


def test_jar_count_cannot_change_alongside_capacity_conversion():
    """JHN 2:6 does not authorize changing six jars to seven."""
    record = next(record for record in CASES if record['REF'] == 'JHN 2:6')
    row, bundle = unit_case(record)
    assert compare_registered_units(row, target_for(record, (7,)), bundle=bundle).outcome == 'REVIEW_VALUE_DIFFERENCE'


@pytest.mark.parametrize('change', [{'unit': 'yard'}, {'qualifier': 'EXACT'}, {'values': (Fraction(8),)}])
def test_wrong_unit_qualifier_and_quantity_do_not_pass(change):
    """A registered approximate distance cannot authorize another unit or magnitude."""
    record = next(record for record in CASES if record['REF'] == 'LUK 24:13')
    row, bundle = unit_case(record)
    target = target_for(record, (2,))
    modified = replace(target, expressions=(target.expressions[0], replace(target.expressions[1], **change)))
    assert compare_registered_units(row, modified, bundle=bundle).outcome == 'REVIEW_VALUE_DIFFERENCE'


def test_unregistered_verse_and_unrecognized_quantity_remain_unsupported():
    """No universal conversion factor is inferred from the registered examples."""
    row, bundle = unit_case(CASES[0])
    assert compare_registered_units(row, target_for(CASES[0]), bundle=replace(bundle, units={})).outcome == 'INSUFFICIENT_EVIDENCE'
    for raw in ['3 unknowns', '3.5 miles', 'about many pounds']:
        with pytest.raises(ValidationError): parse_registered_quantity(raw)


def test_partial_extraction_and_missing_referents_do_not_pass_unit_conversion():
    """Missing target semantic evidence blocks a conversion pass."""
    row, bundle = unit_case(CASES[0])
    partial = replace(target_for(CASES[0]), status='PARTIAL')
    assert compare_registered_units(row, partial, bundle=bundle).outcome == 'INSUFFICIENT_EVIDENCE'
    without_role = Extraction(parse_registered_quantity(CASES[0]['NIV_QUANTITY']), 'COMPLETE')
    assert compare_registered_units(row, without_role, bundle=bundle).outcome == 'INSUFFICIENT_EVIDENCE'


@pytest.mark.parametrize(('reference', 'secondary_residual'), [('LUK 16:7', (2,)), ('JHN 19:39', ())])
def test_unit_example_does_not_authorize_secondary_unrelated_numeric_changes(reference, secondary_residual):
    """A unit conversion cannot import NIV's extra ordinal or omit OL's unrelated ordinal."""
    record = next(record for record in CASES if record['REF'] == reference)
    row, bundle = unit_case(record)
    assert compare_registered_units(row, target_for(record, secondary_residual), bundle=bundle).outcome == 'REVIEW_VALUE_DIFFERENCE'
