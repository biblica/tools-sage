"""Rebuilding the original-language number index from MACULA words (numbers/index_build).

Synthetic MACULA words pin each composition rule; a real-data test runs when the pinned
sources are in the SAGE cache (tools/build_numbers_index.py fetch).
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from sage.errors import ValidationError
from sage.numbers.index_build.compose import compose
from sage.numbers.index_build.lexicon import classify_greek, classify_hebrew, exclusion_reason, greek_part
from sage.numbers.index_build.macula import Word, normalized, verify_source


def heb(lemma, gloss, *, subtype="cardinal number", number="singular", pos="adjective", state="absolute",
        strong="", english=""):
    """One synthetic MACULA Hebrew word."""
    return Word(f"o{id(lemma)}{gloss}", "GEN 1:1", 0, normalized(lemma), normalized(lemma), pos, subtype, number,
                state, gloss, "H", strong, english)


def grk(lemma, english, *, pos="adj", number="singular", subtype="", gender="", case=""):
    """One synthetic MACULA Greek word."""
    return Word(f"n{id(lemma)}{english}", "MAT 1:1", 0, normalized(lemma), normalized(lemma), pos, subtype, number,
                "", english, "G", "", english, gender, case)


AND = heb("וְ", "and", subtype="", pos="conjunction")
NOUN = heb("שָׁנָה", "year", subtype="common", pos="noun")
ARTICLE = heb("הַ", "the", subtype="definite article", pos="particle")


def hebrew_values(*words):
    """Composed Hebrew values for one synthetic verse."""
    return [expression.value for expression in compose(words, classify_hebrew, split_adjacent_units=True)]


def greek_values(*words):
    """Composed Greek values for one synthetic verse."""
    return [expression.value for expression in compose(words, classify_greek, split_adjacent_units=False)]


FOUR = heb("אַרְבַּע", "four")
HUNDREDS = heb("מֵאָה", "hundred(s)", number="plural")
HUNDRED = heb("מֵאָה", "one.hundred")
THOUSAND = heb("אֶלֶף", "thousand")
THOUSANDS = heb("אֶלֶף", "thousands", number="plural")
TEN = heb("עֲשָׂרָה", "ten")
FIVE = heb("חָמֵשׁ", "five")
SIX = heb("שֵׁשׁ", "six")
ONE = heb("אֶחָד", "one")
THIRTY = heb("שָׁלֹשׁ", "thirty", number="plural")
EIGHTY = heb("שְׁמֹנֶה", "eighty", number="plural")


def test_hebrew_ezra_1_10_composes_410():
    """אַרְבַּע מֵאוֹת וַעֲשָׂרָה: a scale multiplies its unit; 'and ten' adds a new magnitude."""
    assert hebrew_values(FOUR, HUNDREDS, AND, TEN) == [410]


def test_hebrew_large_numbers_follow_thousand_boundaries():
    """603,550; 185,000 (singular thousand after a compound); 4,500 (plural thousands stay local)."""
    three = heb("שָׁלֹשׁ", "three")
    fifty = heb("חָמֵשׁ", "fifty", number="plural")
    assert hebrew_values(SIX, HUNDREDS, THOUSAND, AND, three, THOUSANDS, AND, FIVE, HUNDREDS, AND, fifty) == [603550]
    assert hebrew_values(HUNDRED, EIGHTY, AND, FIVE, THOUSAND) == [185000]
    assert hebrew_values(FIVE, HUNDREDS, AND, FOUR, THOUSANDS) == [4500]


def test_hebrew_adjacent_units_and_teens():
    """'one, thirty and a hundred' is 1, 130; 'two two' is distributive; unit + teen ten is 14."""
    two = heb("שְׁנַיִם", "two", number="dual")
    teen = heb("עָשָׂר", "teen")
    assert hebrew_values(ONE, THIRTY, AND, HUNDRED) == [1, 130]
    assert hebrew_values(two, two) == [2, 2]
    assert hebrew_values(FOUR, teen) == [14]


def test_hebrew_same_magnitude_parts_and_bare_plurals_stay_separate():
    """'one ... and five' and 'the thousands and the hundreds' are separate quantities."""
    assert hebrew_values(ONE, AND, FIVE) == [1, 5]
    assert hebrew_values(ARTICLE, THOUSANDS, AND, ARTICLE, HUNDREDS) == [1000, 100]


def test_hebrew_counted_noun_bridge_joins_one_number():
    """'five years and a hundred years' is 105."""
    assert hebrew_values(FIVE, NOUN, AND, HUNDRED, NOUN) == [105]


def test_hebrew_halves_attach_to_their_measure():
    """'a cubit and a half' is 3/2; 'two cubits and a half' (dual noun) is 5/2."""
    cubit = heb("אַמָּה", "cubit", subtype="common", pos="noun")
    cubits = heb("אַמָּה", "two.cubits", subtype="common", pos="noun", number="dual")
    half = heb("חֲצִי", "half", subtype="common", pos="noun")
    assert hebrew_values(cubit, AND, half) == [Fraction(3, 2)]
    assert hebrew_values(cubits, AND, half) == [Fraction(5, 2)]


def test_hebrew_homographs_are_excluded_with_a_reason():
    """'years of', fine linen and מִשְׁנֶה are tagged numerals but never counted."""
    years_of = heb("שְׁנַיִם", "the.years", number="dual", english="years")
    linen = heb("שֵׁשׁ", "[is].fine.linen", strong="8336", english="fine linen")
    mishneh = heb("מִשְׁנֶה", "matching", subtype="common", pos="noun")
    assert hebrew_values(years_of) == [] and hebrew_values(linen) == [] and hebrew_values(mishneh) == []
    assert exclusion_reason(linen).startswith("HOMOGRAPH_STRONG")
    assert exclusion_reason(mishneh).startswith("QUALIFIER")


def test_greek_compounds_scales_and_or():
    """ἑκατὸν πεντήκοντα τρεῖς = 153; μυριάδας πέντε = 50,000; 'eight or ten' stays 8, 10."""
    hundred, fifty, three = grk("ἑκατόν", "hundred", pos="num"), grk("πεντήκοντα", "fifty", pos="num"), grk("τρεῖς", "three")
    myriads, five = grk("μυριάς", "ten thousands", pos="noun", number="plural"), grk("πέντε", "five", pos="num")
    eight, ten, either = grk("ὀκτώ", "eight", pos="num"), grk("δέκα", "ten", pos="num"), grk("ἤ", "or", pos="conj")
    assert greek_values(hundred, fifty, three) == [153]
    assert greek_values(myriads, five) == [50000]
    assert greek_values(eight, either, ten) == [8, 10]


def test_greek_multipliers_parts_and_names():
    """ἑβδομηκοντάκις ἑπτά = 77; 'a third of the earth' = 1/3; Three Taverns and ἅπαξ are not counted."""
    seventy_times, seven = grk("ἑβδομηκοντάκις", "seventy times", pos="adv"), grk("ἑπτά", "seven", pos="num")
    assert greek_values(seventy_times, seven) == [77]
    third = grk("τρίτος", "third", gender="neuter", case="nominative")
    earth = grk("γῆ", "earth", pos="noun", case="genitive")
    assert greek_part(third, earth) == Fraction(1, 3)
    assert greek_part(grk("τρίτος", "third", gender="neuter", case="genitive"), earth) is None
    assert greek_values(grk("Τρεῖς", "Three")) == [] and greek_values(grk("ἅπαξ", "once", pos="adv")) == []


def test_unpinned_source_bytes_are_refused(tmp_path: Path):
    """The builder never runs on anything but the pinned MACULA release."""
    fake = tmp_path / "macula-hebrew.tsv"
    fake.write_text("xml:id\tref\n", encoding="utf-8")
    with pytest.raises(ValidationError) as caught:
        verify_source(fake, "HEB")
    assert caught.value.code == "NCA_INDEX_SOURCE_INVALID"


def test_real_rebuild_agrees_and_traces_ezra_1_10(package_root: Path):
    """With the pinned sources cached: >=95% of verses agree with the package or differ only by words
    the quantity-and-date scope excludes, and EZR 1:10 is traced to MACULA words."""
    from collections import Counter
    from fractions import Fraction
    from sage.numbers.index_build.build import excluded_words, explain, regression, scoped_out, typed_values
    from sage.storage import storage_layout
    candidates = (storage_layout(package_root).cache_root / "macula",
                  package_root.parent / "localdata/.system/cache/macula")
    hebrew = next((cache / "macula-hebrew.tsv" for cache in candidates if (cache / "macula-hebrew.tsv").is_file()),
                  candidates[0] / "macula-hebrew.tsv")
    if not hebrew.is_file():
        pytest.skip("pinned MACULA sources are not cached (tools/build_numbers_index.py fetch)")
    records = typed_values(hebrew, "HEB")
    ezra = [record for record in records if record.ol_ref == "EZR 1:10"]
    assert [record.value for record in ezra] == [30, 410, 1000]
    assert all(record.word_ids for record in ezra)
    rows = regression(records, package_root / "system/resources/numbers/2026-09-09/reference")
    removed = scoped_out(hebrew, "HEB")

    def settled(row):
        """Agreement, or a difference the scope accounts for (package-only out-of-scope values)."""
        mine = Counter(Fraction(value) for value in row["REBUILT_VALUES"].split(";") if value)
        theirs = Counter(Fraction(value) for value in row["INDEX_VALUES"].split(";") if value)
        return mine == theirs or not mine - theirs and bool(explain(theirs - mine, removed.get(row["OL_REF"], [])))
    assert sum(settled(row) for row in rows) / len(rows) >= 0.95
    assert any(item.ol_ref == "EZR 1:10" and item.reason.startswith("QUALIFIER")
               for item in excluded_words(hebrew, "HEB"))
