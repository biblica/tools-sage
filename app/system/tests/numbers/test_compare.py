"""Deterministic local comparison of WIP-extracted numbers against the index.

The central design point of the 2026-09-28 simplified-check rewrite: unordered
set comparison cannot distinguish a faithful reordering ("14 elders, 200 men")
from a swapped referent ("200 elders, 14 men") -- both produce the same
multiset {14, 200}. ORDERED mode exists precisely to catch that case, and it
must never silently PASS or FAIL a real reordering -- it must surface it for
human review with both orderings and the OL text attached (see
test_ordered_mode_catches_swapped_referents_as_needs_review below).
"""
from fractions import Fraction

import pytest

from sage.numbers.compare import compare_values
from sage.numbers.models import ReferenceRow
from sage.vrs import VerseRef


def row(ol_values=(), niv_values=(), *, ol_text='OL text', niv_text='NIV text'):
    """Build one hand-specified reference row for comparator tests."""
    return ReferenceRow(
        VerseRef('MAT', 5, 1), 'MAT 5:1', 'grc', ol_text,
        tuple(Fraction(value) for value in ol_values), niv_text,
        tuple(Fraction(value) for value in niv_values), {},
    )


def values(*raw):
    """Build one ordered WIP-extracted value tuple."""
    return tuple(Fraction(value) for value in raw)


def test_row_absent_is_not_assessed_under_either_mode():
    """A coordinate with no indexed reference row is never silently compared."""
    for mode in ('ORDERED', 'UNORDERED'):
        result = compare_values(values(3), None, mode=mode)
        assert result.outcome == 'NOT_ASSESSED'
        assert result.authority == 'NONE'
        assert result.expected_values == ()


def test_exact_order_match_passes_under_both_modes():
    """An exact sequence match is unambiguous regardless of comparison mode."""
    for mode in ('ORDERED', 'UNORDERED'):
        result = compare_values(values(14, 200), row((14, 200)), mode=mode)
        assert result.outcome == 'PASS'
        assert result.authority == 'OL'


def test_ordered_mode_catches_swapped_referents_as_needs_review():
    """Design point: ORDERED mode must never silently PASS or FAIL a real reordering.

    "200 men, 14 elders" vs OL "14 elders, 200 men" -- multiset {14, 200} matches
    either way, so this could be a faithful reordering OR a swapped referent.
    ORDERED mode reports NEEDS_REVIEW with both orderings and the OL text so a
    human can judge; it must not guess.
    """
    reference = row((14, 200), ol_text='δεκατέσσαρες πρεσβύτεροι, διακόσιοι ἄνδρες')
    result = compare_values(values(200, 14), reference, mode='ORDERED')
    assert result.outcome == 'NEEDS_REVIEW'
    assert result.review_context['wip_order'] == ['200', '14']
    assert result.review_context['expected_order'] == ['14', '200']
    assert result.review_context['authority_text'] == 'δεκατέσσαρες πρεσβύτεροι, διακόσιοι ἄνδρες'


def test_unordered_mode_cannot_catch_the_same_swap_by_design():
    """UNORDERED mode is explicitly a multiset comparison: it cannot and does not catch this."""
    reference = row((14, 200))
    result = compare_values(values(200, 14), reference, mode='UNORDERED')
    assert result.outcome == 'PASS'


def test_ordered_mode_fails_when_multiset_also_disagrees():
    """A real value difference is FAIL, not NEEDS_REVIEW, under either mode."""
    reference = row((14, 200))
    for mode in ('ORDERED', 'UNORDERED'):
        result = compare_values(values(14, 9), reference, mode=mode)
        assert result.outcome == 'FAIL'


def test_missing_and_added_values_fail_under_both_modes():
    """A missing or an extra value is a real FAIL, not a reordering question."""
    reference = row((3, 4))
    assert compare_values(values(3), reference, mode='ORDERED').outcome == 'FAIL'
    assert compare_values(values(3, 4, 5), reference, mode='UNORDERED').outcome == 'FAIL'


def test_repeated_values_are_not_collapsed_into_a_set():
    """Multiplicity matters: two missing duplicates is a real FAIL under UNORDERED too."""
    reference = row((10000, 10000, 1000, 1000))
    result = compare_values(values(10000, 1000), reference, mode='UNORDERED')
    assert result.outcome == 'FAIL'


def test_ol_is_authority_one_niv_is_fallback():
    """OL values are Authority 1; NIV is used only when a row has no OL values."""
    ol_row = row((3,), (7,))
    assert compare_values(values(3), ol_row, mode='ORDERED').authority == 'OL'
    niv_only = row((), (7,))
    result = compare_values(values(7), niv_only, mode='ORDERED')
    assert result.authority == 'NIV'
    assert result.expected_values == (Fraction(7),)


def test_row_with_neither_ol_nor_niv_values_is_not_assessed():
    """A row that indexes no values at all cannot be compared against."""
    result = compare_values(values(3), row((), ()), mode='ORDERED')
    assert result.outcome == 'NOT_ASSESSED'
    assert result.authority == 'NONE'


def test_needs_review_requires_nonempty_review_context():
    """The comparator's own dataclass invariant: NEEDS_REVIEW must carry evidence."""
    from sage.numbers.compare import ComparisonResult
    with pytest.raises(ValueError):
        ComparisonResult('NEEDS_REVIEW', 'ORDERED', values(3), values(3), 'OL', {})
