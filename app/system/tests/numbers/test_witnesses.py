"""Public-domain versional witnesses (numbers/index_build/witnesses.py)."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from sage.numbers.index_build.english import count
from sage.numbers.index_build.witnesses import (Reading, attests_variant, load, relation, reports_a_number, see_also,
                                                textual_notes)

F = Fraction


def test_witness_text_is_linked_through_its_own_versification(tmp_path, package_root):
    """A Septuagint-numbered verse lands on its Western coordinate (MAL 3:19 LXX = MAL 4:1 English)."""
    folder = tmp_path / "witnesses" / "eng-Brenton"
    folder.mkdir(parents=True)
    (folder / "40-MALeng-Brenton.usfm").write_text(
        "\\id MAL test\n\\c 3\n\\v 19 For behold, a day comes burning as an oven.\n", encoding="utf-8")
    texts = load(tmp_path, package_root / "system/resources/scripture", "LXX_BRENTON")
    assert list(texts) == ["MAL 4:1"]


def test_relation_distinguishes_absent_verses_from_uncovered_chapters():
    """A missing verse is evidence only when the witness has the rest of its chapter."""
    assert relation((), [F(2)], [F(30), F(42)], present=False, chapter_present=True) == "ABSENT"
    assert relation((), [F(2)], [F(30), F(42)], present=False, chapter_present=False) == "UNAVAILABLE"
    assert relation((F(190),), [F(390)], [F(390)], present=True) == "OTHER"
    assert relation((F(4),), [F(7)], [F(4)], present=True) == "AGREES_NIV"


def test_only_a_new_number_or_a_missing_verse_attests_a_variant():
    """"One year" for "a son of a year" is rendering; "190" for "390" is a variant."""
    rendering = Reading("VULGATE_DRA", "1SA 13:1", "child of one year", (F(1), F(2)), "OTHER")
    assert attests_variant(rendering, [F(2), F(1)]) is False
    assert attests_variant(Reading("LXX_BRENTON", "EZK 4:5", "190 days", (F(190),), "OTHER"), [F(390)])
    assert attests_variant(Reading("LXX_BRENTON", "1SA 13:1", "", (), "ABSENT"), [F(2)])


def test_archaic_numbers_are_read_only_when_asked():
    """KJV-era "five and twenty" is 25; in modern English it stays a range of two numbers."""
    assert [item.value for item in count("two hundred threescore and sixteen souls", archaic=True)] == [276]
    assert [item.value for item in count("the one and twentieth day", archaic=True)] == [21]
    assert [item.value for item in count("between five and twenty")] == [5, 20]


def test_greek_esther_maps_to_esther_and_its_additions_stay_apart(tmp_path, package_root):
    """Brenton codes Greek Esther ESG; lettered sub-verses (the additions) are not Esther verses."""
    folder = tmp_path / "witnesses" / "eng-Brenton"
    folder.mkdir(parents=True)
    (folder / "43-ESGeng-Brenton.usfm").write_text(
        "\\id ESG test\n\\c 1\n\\v 1 In the second year of Artaxerxes.\n\\v 1b a Jew dwelling in Susa.\n"
        "\\v 5 the king made a banquet for six days.\n", encoding="utf-8")
    texts = load(tmp_path, package_root / "system/resources/scripture", "LXX_BRENTON")
    assert texts["EST 1:5"].endswith("six days.") and "a Jew dwelling" not in texts["EST 1:1"]


def test_bsb_footnotes_count_only_when_they_report_a_number_in_another_text():
    """A version or manuscript reading a number is evidence; a literal rendering or a cross-reference is not."""
    assert reports_a_number("LXX and Syriac; Hebrew seventh")
    assert reports_a_number("Hebrew; some LXX manuscripts 8,300; see the total in verse 39.")
    assert not reports_a_number("Hebrew half a yoke")  # literal rendering, no other text
    assert not reports_a_number("Or from Ramathaim, a Zuphite; see LXX and 1 Chronicles 6:26 and 35.")
    assert not reports_a_number("One Hebrew manuscript and LXX; most Hebrew manuscripts on each side")


def test_bsb_notes_are_read_with_the_bsb_text(tmp_path, package_root):
    """BSB footnotes keep their Western verse; notes without another text's number are left out."""
    folder = tmp_path / "witnesses" / "engbsb"
    folder.mkdir(parents=True)
    (folder / "08-JDGengbsb.usfm").write_text(
        "\\id JDG test\n\\c 14\n\\v 15 On the fourth day\\f + \\fr 14:15 \\ft LXX and Syriac; Hebrew seventh\\f* they said.\n"
        "\\v 16 Then Samson’s wife\\f + \\fr 14:16 \\ft Hebrew half a yoke\\f* wept.\n", encoding="utf-8")
    notes = textual_notes(tmp_path, package_root / "system/resources/scripture")
    assert notes == {"JDG 14:15": ["LXX and Syriac; Hebrew seventh"]}
    assert load(tmp_path, package_root / "system/resources/scripture", "BSB")["JDG 14:15"] == "On the fourth day they said."


def test_see_also_names_the_original_language_the_niv_and_the_other_witnesses():
    """The BSB is cited with where to look next; an uncovered witness is left out."""
    others = {"LXX_BRENTON": Reading("LXX_BRENTON", "JDG 14:15", "fourth day", (F(4),), "AGREES_NIV"),
              "VULGATE_DRA": Reading("VULGATE_DRA", "JDG 14:15", "", (), "ABSENT"),
              "KJV": Reading("KJV", "JDG 14:15", "", (), "UNAVAILABLE")}
    assert see_also("JDG 14:15", [F(7)], [F(4)], others) == "MT 7; NIV 4; LXX 4; Vulgate verse absent"
    assert see_also("ACT 10:19", [], [F(3)], {}) == "Greek NT no numbers; NIV 3"

