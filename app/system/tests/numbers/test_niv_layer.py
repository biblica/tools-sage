"""The NIV (secondary-authority) number layer (numbers/index_build: niv, english, niv_layer).

English rules are pinned with short phrases; the reader with a synthetic Paratext book; a
real-data check runs when SAGE_NIV_PROJECT points at a local usNIVv2 project.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
import os
from pathlib import Path

import pytest

from sage.numbers.index_build.english import count, scan
from sage.numbers.index_build.niv import read_book, read_project
from sage.numbers.index_build.niv_layer import match_status, reason, typed_niv

F = Fraction


def values(text):
    """Counted values of one English phrase."""
    return [item.value for item in count(text)]


@pytest.mark.parametrize("text, expected", [
    ("On the first day of the seventh month", [1, 7]),
    ("30 gold bowls, 410 matching silver bowls, and 1,000 other articles", [30, 410, 1000]),
    ("a hundred and thirty shekels", [130]),
    ("in the six hundred and first year", [601]),
    ("forty-two thousand three hundred sixty", [42360]),
    ("a thousand thousands", [1000000]),
    ("Such are the ten thousands of Ephraim", [10000]),
    ("twice ten thousand times ten thousand", [200000000]),
    ("two or three", [2, 3]),
    ("Send two or three thousand men", [2000, 3000]),
    ("the nine-and-a-half tribes", [F(19, 2)]),
    ("a three-day journey", [3]),
    ("When he was ninety-nine years old", [99]),
])
def test_cardinals_compose(text, expected):
    """Words and numerals compose into one value per quantity; separate quantities stay separate."""
    assert values(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("a cubit and a half long", [F(3, 2)]),
    ("two and a half cubits", [F(5, 2)]),
    ("two cubits and a half", [F(5, 2)]),
    ("a third of a hin of wine", [F(1, 3)]),
    ("half an hour", [F(1, 2)]),
    ("a quarter of a cab", [F(1, 4)]),
    ("one-tenth of an ephah", [F(1, 10)]),
    ("three-tenths of an ephah", [3]),
])
def test_fractions_and_measures(text, expected):
    """Fractions of a measure or time unit count; "N tenths" of a measure is N, as in the OL index."""
    assert values(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("He took one man", [1]),
    ("one log of oil", [1]),
    ("in one day", [1]),
    ("one of my brothers came", []),
    ("one of you will betray me", []),
    ("should one walk on hot coals", []),
    ("one will be taken and the other left", []),
    ("Blessed is the one who does not walk", []),
    ("no one to rescue me", []),
    ("love one another", []),
    ("the Holy One of Israel", []),
    ("One day the angels came", []),
    ("so one does not go on threshing", []),
    ("The first one married", []),
])
def test_one_counts_only_as_a_quantity(text, expected):
    """Convention 2.0 rule 2: "one" counts only with the thing it numbers."""
    assert values(text) == expected


@pytest.mark.parametrize("text, expected, kind", [
    ("about three thousand men", [3000], "APPROX"),
    ("on the fourteenth day of the first month", [14, 1], "ORDINAL"),
    ("in the six hundredth year", [600], "ORDINAL"),
])
def test_approximations_and_dates(text, expected, kind):
    """Approximate numbers and date ordinals carry their convention kind."""
    found = count(text)
    assert [item.value for item in found] == expected and found[0].kind == kind


@pytest.mark.parametrize("text, reason", [
    ("they came to Three Taverns", "NAME"),
    ("both of them went", "BOTH"),
    ("both buyer and seller", "BOTH"),
    ("a pair of sandals", "PAIR"),
    ("Saul has slain his thousands", "INDEFINITE_PLURAL"),
    ("tens of thousands assail me", "INDEFINITE_PLURAL"),
    ("bore Jacob a fifth son", "RANK_ORDINAL"),
    ("a third time the Lord called", "RANK_ORDINAL"),
    ("first of all", "RANK_ORDINAL"),
    ("should one walk", "PRONOUN_ONE"),
    ("He did it twice", "IMPLICIT_NUMBER"),
    ("pay sevenfold", "IMPLICIT_NUMBER"),
    ("a double portion", "IMPLICIT_NUMBER"),
    ("bring your tithes", "IMPLICIT_NUMBER"),
    ("seven times", "FREQUENCY"),
    ("three times a year", "FREQUENCY"),
    ("a third of the city", "FRACTION_NO_MEASURE"),
    ("the half-tribe of Manasseh", "FRACTION_NO_MEASURE"),
    ("two-thirds will be struck down", "FRACTION_NO_MEASURE"),
])
def test_out_of_scope_words_are_excluded_with_a_reason(text, reason):
    """Convention 2.0: words that only look like numbers are kept apart, each with its reason."""
    counted, excluded = scan(text)
    assert counted == [] and [item.reason for item in excluded] == [reason]


def test_surface_offsets_point_into_the_verse():
    """Every value cites the exact words and character span it came from."""
    text = "There were 736 horses, two hundred and forty-five mules"
    found = count(text)
    assert [(item.surface, text[item.start:item.end]) for item in found] == [
        ("736", "736"), ("two hundred and forty-five", "two hundred and forty-five")]


SAMPLE = """\\id PSA - English-US: test
\\h Psalms
\\c 60
\\cl Psalm 60
\\d For the director of music. A \\tl miktam\\tl*\\f + \\fr 60:0 \\fl Title: \\ft Probably a musical term\\f* when Joab struck down twelve thousand Edomites.
\\q1
\\v 1 You have rejected us, God.
\\c 61
\\s1 A heading with seven words
\\p
\\v 1 Saul reigned forty-\\f + \\fr 61:1 \\ft Masoretic Text does not have \\fq forty-\\ft .\\f* two years.
\\v 2 \\vp [2]\\vp*\\f + \\fr 61:2 \\ft Some manuscripts include here 70 words.\\f*
"""


def test_reader_keeps_scripture_and_drops_apparatus(tmp_path):
    """Titles are verse 0; headings, published labels and notes leave the text; notes are kept apart."""
    path = tmp_path / "19PSAtest.SFM"
    path.write_text(SAMPLE, encoding="utf-8")
    verses = read_book(path, "PSA")
    assert verses["PSA 60:0"].text == ("For the director of music. A miktam when Joab struck down twelve "
                                       "thousand Edomites.")
    assert verses["PSA 60:0"].notes == ["Title: Probably a musical term"]
    assert verses["PSA 61:1"].text == "Saul reigned forty-two years."
    assert verses["PSA 61:2"].text == "" and verses["PSA 61:2"].notes == ["Some manuscripts include here 70 words."]
    assert [record.value for record in typed_niv(verses)] == [12000, 42]


def test_match_status_vocabulary():
    """OL/NIV agreement is computed from typed values, in the package vocabulary."""
    assert match_status([F(30), F(410)], [F(30), F(410)]) == "PASS_EXACT"
    assert match_status([F(30), F(410)], [F(410), F(30)]) == "PASS_EQUIVALENT_REORDERED"
    assert match_status([F(2)], []) == "OL_EXPLICIT_NIV_NONEXPLICIT"
    assert match_status([], [F(1)]) == "NIV_EXPLICIT_OL_NONEXPLICIT"
    assert match_status([F(30), F(2)], [F(30)]) == "DIFFERENT_NUMERIC_EXPRESSION"


def test_regression_reasons():
    """Package differences the scope settles on its own carry a suggested decision."""
    assert reason("no one to help them", Counter(), Counter({F(1): 1})) == ("SCOPE: PRONOUN_ONE", "REBUILT")
    assert reason("bring the tithes", Counter(), Counter({F(1, 10): 1})) == ("SCOPE: IMPLICIT_NUMBER", "REBUILT")
    assert reason("both God and the king", Counter(), Counter({F(2): 1})) == ("SCOPE: BOTH", "REBUILT")
    assert reason("bore Jacob a fifth son", Counter(), Counter({F(1, 5): 1})) == ("SCOPE: RANK_ORDINAL", "REBUILT")
    assert reason("a pair of sandals", Counter(), Counter({F(2): 1})) == ("SCOPE: PAIR", "REBUILT")


NIV_PROJECT = os.environ.get("SAGE_NIV_PROJECT")


@pytest.mark.skipif(not NIV_PROJECT or not Path(NIV_PROJECT).is_dir(), reason="SAGE_NIV_PROJECT not set")
def test_real_niv_key_verses():
    """On the local usNIVv2 project: EZR 1:10 list totals, the NEH 7:68 added verse, a Psalm title."""
    verses = read_project(Path(NIV_PROJECT))
    assert values(verses["EZR 1:10"].text) == [30, 410, 1000]
    assert values(verses["NEH 7:68"].text) == [736, 245]
    assert 12000 in values(verses["PSA 60:0"].text)


@pytest.mark.skipif(not NIV_PROJECT or not Path(NIV_PROJECT).is_dir(), reason="SAGE_NIV_PROJECT not set")
def test_every_niv_numeral_is_counted():
    """Every digit numeral in NIV Scripture text ("30", "1,000", "42,360") is a number to verify."""
    import re
    missed = []
    for ref, verse in read_project(Path(NIV_PROJECT)).items():
        spans = [(item.start, item.end) for item in count(verse.text)]
        for match in re.finditer(r"\d{1,3}(?:,\d{3})+|\d+", verse.text):
            if not any(start <= match.start() and match.end() <= end for start, end in spans):
                missed.append((ref, match[0]))
    assert missed == []


def test_a_numeral_is_never_excluded():
    """No scope rule removes a numeral: "70 times" still counts 70."""
    assert values("forgive 70 times") == [70] and values("about 3,000 men") == [3000]
