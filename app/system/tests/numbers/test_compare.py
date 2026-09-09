"""Numeric equivalence preserves roles, kinds, units, qualifiers and multiplicity."""
from fractions import Fraction

import pytest

from sage.numbers.compare import compare_expressions
from sage.numbers.models import Extraction, NumericExpression


def quantity(value, role='men', **changes):
    """Build one hand-specified typed quantity for correspondence tests."""
    fields = dict(values=(Fraction(value),), kind='CARDINAL', surface=str(value), span=(0, len(str(value))), role=role)
    fields.update(changes)
    return NumericExpression(**fields)


def test_equal_value_bag_does_not_justify_reassigned_quantities():
    """Equal value bag does not justify reassigned quantities."""
    ol = (quantity(3, 'sheep'), quantity(7, 'goats'))
    target = Extraction((quantity(7, 'sheep'), quantity(3, 'goats')), 'COMPLETE')
    assert compare_expressions(ol, target, allow_reordering=True).outcome == 'REVIEW_VALUE_DIFFERENCE'


def test_reordered_corresponding_quantities_can_pass():
    """Reordered corresponding quantities can pass."""
    ol = (quantity(3, 'sheep'), quantity(7, 'goats'))
    target = Extraction((quantity(7, 'goats'), quantity(3, 'sheep')), 'COMPLETE')
    assert compare_expressions(ol, target, allow_reordering=True).outcome == 'PASS_EQUIVALENT_NUMERIC_EXPRESSION'


def test_surface_style_does_not_change_numeric_meaning():
    """Surface style does not change numeric meaning."""
    ol = (quantity(318),)
    target = Extraction((quantity(318, surface='three hundred and eighteen', span=(0, 26)),), 'COMPLETE')
    assert compare_expressions(ol, target).outcome == 'PASS_AUTHORITY1'


@pytest.mark.parametrize(('values', 'expected'), [([3], 'REVIEW_NUMBER_MISSING'), ([3, 4, 5], 'REVIEW_NUMBER_ADDED'), ([3, 9], 'REVIEW_VALUE_DIFFERENCE')])
def test_missing_added_and_replaced_values_are_distinct(values, expected):
    """Missing added and replaced values are distinct."""
    ol = (quantity(3), quantity(4))
    target = Extraction(tuple(quantity(value) for value in values), 'COMPLETE')
    assert compare_expressions(ol, target).outcome == expected


def test_repeated_values_cannot_disappear_in_a_set_comparison():
    """Repeated values cannot disappear in a set comparison."""
    ol = (quantity(10000), quantity(10000), quantity(1000), quantity(1000))
    target = Extraction((quantity(10000), quantity(1000)), 'COMPLETE')
    assert compare_expressions(ol, target, allow_reordering=True).outcome == 'REVIEW_NUMBER_MISSING'


@pytest.mark.parametrize('changes', [{'unit': 'mile'}, {'qualifier': 'ABOUT'}, {'kind': 'ORDINAL'}, {'values': (Fraction(1, 3),), 'kind': 'FRACTION'}, {'role': 'goats'}])
def test_semantic_attributes_cannot_be_changed_by_value_equality(changes):
    """Semantic attributes cannot be changed by value equality."""
    assert compare_expressions((quantity(3),), Extraction((quantity(3, **changes),), 'COMPLETE')).outcome == 'REVIEW_VALUE_DIFFERENCE'


def test_ratio_members_remain_ordered_even_when_reordering_is_allowed():
    """Ratio members remain ordered even when reordering is allowed."""
    ol = (quantity(10, kind='RATIO', values=(Fraction(10), Fraction(100))),)
    target = Extraction((quantity(10, kind='RATIO', values=(Fraction(100), Fraction(10))),), 'COMPLETE')
    assert compare_expressions(ol, target, allow_reordering=True).outcome == 'REVIEW_VALUE_DIFFERENCE'


@pytest.mark.parametrize('status', ['PARTIAL', 'UNSUPPORTED'])
def test_incomplete_extraction_cannot_pass_or_assert_missing_numbers(status):
    """Incomplete extraction cannot pass or assert missing numbers."""
    assert compare_expressions((quantity(3),), Extraction((), status, ('Unsupported language context',))).outcome == 'INSUFFICIENT_EVIDENCE'


def test_flat_source_value_equality_without_role_evidence_is_insufficient():
    """Flat source value equality without role evidence is insufficient."""
    result = compare_expressions((quantity(3, None), quantity(7, None)), Extraction((quantity(3, None), quantity(7, None)), 'COMPLETE'))
    assert result.outcome == 'INSUFFICIENT_EVIDENCE'
    assert 'SOURCE_CORRESPONDENCE_UNSUPPORTED' in result.reason_codes


def test_empty_complete_typed_sequences_agree():
    """Empty complete typed sequences agree."""
    assert compare_expressions((), Extraction((), 'COMPLETE')).outcome == 'PASS_AUTHORITY1'


def test_matching_values_cannot_authorize_unapproved_reordering():
    """Matching values cannot authorize unapproved reordering."""
    ol = (quantity(3, 'sheep'), quantity(7, 'goats'))
    target = Extraction((quantity(7, 'goats'), quantity(3, 'sheep')), 'COMPLETE')
    result = compare_expressions(ol, target)
    assert result.outcome == 'REVIEW_VALUE_DIFFERENCE'
    assert result.reason_codes == ('NUMERIC_MEANING_DIFFERENT',)


@pytest.mark.parametrize('role', [None, '', '  '])
@pytest.mark.parametrize('side', ['source', 'target'])
@pytest.mark.parametrize('different_count', [False, True])
def test_missing_or_blank_role_evidence_cannot_classify_numeric_changes(role, side, different_count):
    """Missing or blank role evidence cannot classify numeric changes."""
    source = (quantity(3, role if side == 'source' else 'men'),)
    actual = (quantity(3, role if side == 'target' else 'men'),)
    if different_count:
        actual += (quantity(4),)
    result = compare_expressions(source, Extraction(actual, 'COMPLETE'))
    assert result.outcome == 'INSUFFICIENT_EVIDENCE'
    assert result.reason_codes == (f'{side.upper()}_CORRESPONDENCE_UNSUPPORTED',)
