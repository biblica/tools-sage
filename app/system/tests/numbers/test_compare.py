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


def row(ol_values=(), niv_values=(), *, ol_text='OL text', bsb_text='BSB text'):
    """Build one hand-specified reference row for comparator tests."""
    return ReferenceRow(
        VerseRef('MAT', 5, 1), 'MAT 5:1', 'grc', ol_text,
        tuple(Fraction(value) for value in ol_values), bsb_text,
        tuple(Fraction(value) for value in niv_values), {},
    )


def values(*raw):
    """Build one ordered WIP-extracted value tuple."""
    return tuple(Fraction(value) for value in raw)


def test_row_absent_is_not_indexed_under_either_mode():
    """No indexed row means no number in OL or NIV: NOT_INDEXED, never an assessment gap."""
    for mode in ('ORDERED', 'UNORDERED'):
        result = compare_values(values(3), None, mode=mode)
        assert result.outcome == 'NOT_INDEXED'
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


def test_row_with_neither_ol_nor_niv_values_routes_wip_numbers_to_review():
    """A row that indexes no values cannot vouch for a FAIL; WIP numbers there need review."""
    result = compare_values(values(3), row((), ()), mode='ORDERED')
    assert result.outcome == 'NEEDS_REVIEW'
    assert result.review_context['kind'] == 'NO_INDEXED_VALUES'
    assert result.authority == 'NONE'
    assert compare_values(values(), row((), ()), mode='ORDERED').outcome == 'PASS'


def test_needs_review_requires_nonempty_review_context():
    """The comparator's own dataclass invariant: NEEDS_REVIEW must carry evidence."""
    from sage.numbers.compare import ComparisonResult
    with pytest.raises(ValueError):
        ComparisonResult('NEEDS_REVIEW', 'ORDERED', values(3), values(3), 'OL', {})


def override(layer='AUDITED_OL_NORMALIZATION_MANIFEST', action='DROP_EXPR', *, expression='',
             original='', final='', reason='reviewed'):
    """Build one normalization_overrides.tsv row as the reference loader carries it."""
    return {'LAYER': layer, 'ACTION': action, 'SOURCE_EXPRESSION': expression, 'ORIGINAL_VALUES': original,
            'FINAL_VALUES': final, 'RULE_CLASS': 'FIXTURE', 'REASON': reason}


def normalized_row(ol_values, *overrides, niv_values=()):
    """Build a reference row whose OL_VALUES came from audited normalization overrides."""
    base = row(ol_values, niv_values, ol_text='OL text', bsb_text='BSB text')
    return type(base)(base.western_reference, base.ol_reference, base.language, base.ol_text,
                      base.ol_values, base.bsb_text, base.niv_values, base.metadata, tuple(overrides))


def test_undocumented_verse_override_mismatch_is_review_not_blocking_fail():
    """EZR 1:10: the index silently drops OL "second"; a WIP that keeps it is not an OL failure."""
    reference = normalized_row((30, 410, 1000), override('FINAL_OL_VERSE_OVERRIDE', 'REPLACE_VERSE_VALUES',
                               final='30;410;1000'), niv_values=(30, 410, 1000))
    for mode in ('ORDERED', 'UNORDERED'):
        result = compare_values(values(30, 2, 410, 1000), reference, mode=mode)
        assert result.outcome == 'NEEDS_REVIEW'
        assert result.review_context['kind'] == 'OL_NORMALIZED_UNDOCUMENTED'
        assert result.review_context['ol_text'] == 'OL text'
        assert result.review_context['bsb_text'] == 'BSB text'
        assert result.review_context['normalizations'][0]['LAYER'] == 'FINAL_OL_VERSE_OVERRIDE'
    assert compare_values(values(30, 410, 1000), reference, mode='UNORDERED').outcome == 'PASS'


def test_documented_drop_explains_mismatch_only_when_reversal_reproduces_wip():
    """A dropped lexical false positive routes to review only if restoring it yields the WIP values."""
    reference = normalized_row((40,), override(expression='הַשְּׁמִינִית', original='8', reason='musical term'))
    explained = compare_values(values(8, 40), reference, mode='UNORDERED')
    assert explained.outcome == 'NEEDS_REVIEW'
    assert explained.review_context['kind'] == 'OL_NORMALIZATION_DIFFERENCE'
    assert compare_values(values(7, 40), reference, mode='UNORDERED').outcome == 'FAIL'


def test_documented_recomposition_reversal_is_review():
    """A seed compound (1100) recomposed as 1000;100 still explains a WIP that keeps 1100."""
    reference = normalized_row((1000, 100, 5), override(action='REPLACE_VERSE_VALUES', original='1100',
                               final='1000;100'))
    assert compare_values(values(1100, 5), reference, mode='ORDERED').outcome == 'NEEDS_REVIEW'
    assert compare_values(values(1100, 6), reference, mode='ORDERED').outcome == 'FAIL'


def test_niv_authority_is_never_rerouted_by_ol_normalizations():
    """OL overrides never reroute an NIV-authority mismatch; it is NIV-only review, not a FAIL."""
    reference = normalized_row((), override('FINAL_OL_VERSE_OVERRIDE', 'REPLACE_VERSE_VALUES'), niv_values=(3,))
    result = compare_values(values(4), reference, mode='UNORDERED')
    assert (result.outcome, result.authority) == ('NEEDS_REVIEW', 'NIV')
    assert result.review_context['kind'] == 'NIV_ONLY_AUTHORITY'


def test_order_difference_review_context_is_labelled():
    """The reorder review keeps its evidence and now names its kind for report routing."""
    result = compare_values(values(200, 14), row((14, 200)), mode='ORDERED')
    assert result.review_context['kind'] == 'ORDER_DIFFERENCE'


def _niv_row(ol_values, niv_values, match_status):
    """Build one row carrying an index MATCH_STATUS."""
    base = row(ol_values, niv_values)
    return type(base)(base.western_reference, base.ol_reference, base.language, base.ol_text, base.ol_values,
                      base.bsb_text, base.niv_values, {'MATCH_STATUS': match_status})


def test_fail_is_reserved_for_ol_authority_and_carries_ol_and_niv_evidence():
    """A BLOCKING FAIL only ever stands on an OL reading, and always shows OL + NIV text."""
    result = compare_values(values(4), row((3,), (3,), ol_text='שְׁלֹשָׁה', bsb_text='three'), mode='UNORDERED')
    assert (result.outcome, result.authority) == ('FAIL', 'OL')
    assert result.review_context['kind'] == 'VALUE_DIFFERENCE'
    assert result.review_context['ol_text'] == 'שְׁלֹשָׁה'
    assert result.review_context['bsb_text'] == 'three'


def test_niv_only_rows_never_block():
    """The index says 'do not auto-validate from NIV': an NIV-only mismatch is review."""
    result = compare_values(values(), row((), (1,)), mode='UNORDERED')
    assert result.outcome == 'NEEDS_REVIEW'
    assert result.review_context['kind'] == 'NIV_ONLY_AUTHORITY'


def test_follows_niv_where_it_differs_is_review_and_neither_is_fail():
    """OL and NIV differ: following the NIV is review (D1); matching neither is a wrong number."""
    row = _niv_row((100,), (1,), 'DIFFERENT_NUMERIC_EXPRESSION')
    follows = compare_values(values(1), row, mode='UNORDERED')
    assert follows.outcome == 'NEEDS_REVIEW' and follows.review_context['kind'] == 'MATCHES_SECONDARY_AUTHORITY'
    neither = compare_values(values(7), row, mode='UNORDERED')
    assert neither.outcome == 'FAIL' and neither.review_context['kind'] == 'VALUE_DIFFERENCE'


def test_wip_matching_niv_is_review_not_fail():
    """A WIP that matches the NIV but not OL is a reading choice for review."""
    result = compare_values(values(10, 1), _niv_row((10, 1, 10), (10, 1), 'PASS_EXACT'), mode='UNORDERED')
    assert result.review_context['kind'] == 'MATCHES_SECONDARY_AUTHORITY'


def test_registered_alternate_reading_is_review_with_guidance():
    """NEH 7:68-69: a WIP following an attested alternate reading is review, not BLOCKING."""
    from sage.numbers.compare import AlternateReading
    alternate = AlternateReading('NEH 7:68', values(736, 245, 435, 6720), {'footnote_if_target_follows_alt': 'REQUIRE'})
    result = compare_values(values(736, 245, 435, 6720), row((435, 6720), (435, 6720)), mode='UNORDERED',
                            alternates=(alternate,))
    assert result.review_context['kind'] == 'ATTESTED_VARIANT_READING'
    assert result.review_context['variant_guidance']['footnote_if_target_follows_alt'] == 'REQUIRE'


def test_extra_edge_kind_values_are_convention_review():
    """EZR 1:10 shape: an extra WIP value tagged ORDINAL is a convention question, not a FAIL."""
    result = compare_values(values(30, 2, 410, 1000), row((30, 410, 1000), (30, 410, 1000)), mode='UNORDERED',
                            wip_kinds=('CARDINAL', 'ORDINAL', 'CARDINAL', 'CARDINAL'))
    assert result.review_context['kind'] == 'CONVENTION_EDGE_CASE'
    untagged = compare_values(values(30, 2, 410, 1000), row((30, 410, 1000), (30, 410, 1000)), mode='UNORDERED',
                              wip_kinds=('CARDINAL',) * 4)
    assert untagged.outcome == 'FAIL'


def test_bridged_group_mixing_ol_and_niv_is_mixed_review():
    """Expected values that combine OL and NIV-only rows cannot vouch for a FAIL."""
    from sage.numbers.compare import compare_group
    result = compare_group(values(9), [row((3,), (3,)), row((), (4,))], mode='UNORDERED')
    assert (result.outcome, result.authority) == ('NEEDS_REVIEW', 'MIXED')
    assert result.expected_values == values(3, 4)


def test_bridge_placeholder_and_variant_routing_against_shipped_index(package_root):
    """NEH 7:68-69 against the real index: the bridged WIP follows the attested NIV reading."""
    from types import SimpleNamespace
    from sage.numbers.compare import compare_group
    from sage.numbers.grouping import alternate_readings
    from sage.numbers.reference import load_reference
    bundle = load_reference(package_root / 'system/resources/numbers/2026-09-09')
    western = (VerseRef('NEH', 7, 69),)
    refs = [*western, VerseRef('NEH', 7, 68)]
    alternates = alternate_readings(SimpleNamespace(western_references=western), SimpleNamespace(bundle=bundle), refs)
    rows = [bundle.lookup(ref) for ref in western]
    result = compare_group(values(736, 245, 435, 6720), rows, mode='UNORDERED', alternates=alternates)
    assert result.review_context['kind'] == 'ATTESTED_VARIANT_READING'
    assert result.review_context['variant_reference'] == 'NEH 7:68'


def _typed_row(pairs):
    """One typed row whose OL and NIV both give these (value, item) pairs."""
    items = tuple({"VALUE": str(value), "REFERENT": referent} for value, referent in pairs)
    vals = tuple(Fraction(value) for value, _referent in pairs)
    return ReferenceRow(VerseRef('EZR', 1, 9), 'EZR 1:9', 'HEB', '', vals, '', vals,
                        {'MATCH_STATUS': 'PASS_EXACT', 'OL_REVIEW_STATUS': 'AGREES'},
                        ol_items=items, niv_items=items)


EZR_1_9 = ((30, "gold dishes"), (1000, "silver dishes"), (29, "silver pans"))


def test_swapped_items_are_a_wrong_association_fail():
    """Same numbers as the source but 1 000 on the gold dishes: FAIL WRONG_ASSOCIATION."""
    result = compare_values(values(1000, 30, 29), _typed_row(EZR_1_9), mode='UNORDERED',
                            wip_counts_en=("gold dishes", "silver dishes", "silver pans"))
    assert result.outcome == 'FAIL' and result.review_context['kind'] == 'WRONG_ASSOCIATION'
    assert {item['referent'] for item in result.review_context['source_items']} == {
        'gold dishes', 'silver dishes', 'silver pans'}


def test_swapped_items_on_an_niv_only_row_are_for_review_not_blocking():
    """BLOCKING needs original-language authority: an NIV-only swap is reported for review."""
    items = tuple({"VALUE": str(value), "REFERENT": referent} for value, referent in EZR_1_9)
    vals = tuple(Fraction(value) for value, _referent in EZR_1_9)
    row = ReferenceRow(VerseRef('EZR', 1, 9), 'EZR 1:9', 'HEB', '', (), '', vals,
                       {'MATCH_STATUS': 'NIV_ONLY', 'OL_REVIEW_STATUS': 'AGREES'}, niv_items=items)
    result = compare_values(values(1000, 30, 29), row, mode='UNORDERED',
                            wip_counts_en=("gold dishes", "silver dishes", "silver pans"))
    assert result.outcome == 'NEEDS_REVIEW' and result.review_context['kind'] == 'WRONG_ASSOCIATION'
    assert result.authority == 'NIV'


def test_faithful_reordering_passes_with_a_note():
    """A different order with each number on its own item is a PASS carrying an order note."""
    result = compare_values(values(1000, 30, 29), _typed_row(EZR_1_9), mode='ORDERED',
                            wip_counts_en=("silver dishes", "gold dishes", "silver pans"))
    assert result.outcome == 'PASS' and result.review_context['note'] == 'ORDER_DIFFERS_ITEMS_MATCH'


def test_unverifiable_reordering_in_ordered_mode_is_review():
    """Without counted-item evidence a reordering cannot be confirmed: review, not PASS."""
    result = compare_values(values(1000, 30, 29), _typed_row(EZR_1_9), mode='ORDERED')
    assert result.outcome == 'NEEDS_REVIEW' and result.review_context['kind'] == 'ORDER_DIFFERENCE'


def test_malformed_numeral_is_a_fail_even_when_values_match():
    """A mistyped numeral ("10,0000") is reported as a FAIL with the numeral."""
    result = compare_values(values(30, 1000, 29), _typed_row(EZR_1_9), mode='UNORDERED',
                            wip_issues=("MALFORMED_NUMERAL:10,0000",))
    assert result.outcome == 'FAIL' and result.review_context['numerals'] == ['10,0000']


def test_text_critical_note_records_which_reading_the_wip_follows():
    """Where OL and NIV differ the operator gets the decision, the footnote state and guidance."""
    from types import SimpleNamespace
    from sage.numbers.grouping import text_critical_note
    from sage.numbers.models import Extraction
    ol_niv = row((2,), (30, 42))
    bundle = SimpleNamespace(footnote_guidance={})
    target = SimpleNamespace(notes=("note",))
    note = text_critical_note([ol_niv], Extraction((Fraction(30), Fraction(42)), 'COMPLETE'), target, bundle)
    assert note['kind'] == 'TEXT_CRITICAL' and note['follows'] == 'NIV' and note['footnote_in_wip'] is True
    agree = row((3,), (3,))
    assert text_critical_note([agree], Extraction((Fraction(3),), 'COMPLETE'), target, bundle) is None
