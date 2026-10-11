"""Local digit-numeral reading: grouping separators and joined numerals."""
from fractions import Fraction




def test_space_joins_only_three_digit_groups():
    """ "in 30 40 years" is two numerals; "12 000" one; "1000 000" one malformed numeral."""
    from sage.numbers.numerals import find_numerals
    assert [n.text for n in find_numerals("in 30 40 years")] == ["30", "40"]
    assert [n.readings for n in find_numerals("12 000 men")] == [(Fraction(12000),)]
    assert [n.malformed for n in find_numerals("1000 000")] == [True]


def test_no_break_spaces_match_a_configured_space_separator():
    """A no-break or narrow no-break space is the configured space separator."""
    from sage.numbers.numerals import readings
    conventions = {"grouping": {"separator": " "}}
    assert readings("12 000", conventions) == (Fraction(12000),)
    assert readings("12 000", conventions) == (Fraction(12000),)


def test_suffixed_digit_numerals_are_marked_as_ordinals():
    """ "his 2nd son" is a rank: SAGE never adds it as a stray cardinal."""
    from sage.numbers.numerals import find_numerals
    assert [n.suffixed for n in find_numerals("his 2nd son, the 3-й day, 12 men")] == [True, True, False]
