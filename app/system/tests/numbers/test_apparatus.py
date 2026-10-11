"""Apparatus evidence for the number index (numbers/index_build/apparatus.py)."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from sage.numbers.compare import compare_group
from sage.numbers.index_build.apparatus import collect, net_names_a_number, net_tc_notes, sblgnt_units
from sage.numbers.models import ReferenceRow
from sage.vrs import VerseRef

F = Fraction


def _cache(tmp_path: Path) -> Path:
    """A tiny cache: one NET chapter, one SBLGNT book, one OSHB book."""
    cache = tmp_path / "apparatus"
    (cache / "net").mkdir(parents=True)
    (cache / "sblgntapp").mkdir()
    (cache / "morphhb").mkdir()
    content = ('<span class="netVerse"><a class="netNoteSuper" pos="1" data-book="1 Samuel" data-chapter="13" '
               'data-verse="1" id="noteSuper_1_1_Samuel_13">1</a><a class="netNoteSuper" pos="1" data-book="1 Samuel" '
               'data-chapter="13" data-verse="2" id="noteSuper_2_1_Samuel_13">2</a></span>')
    notes = ('<div class="note"><sup><span class="noteNoteSuper" id="note_1">1</span>&nbsp;</sup>'
             '<span class="notetype">tc</span> The MT does not have “thirty.” A number appears to have dropped out.'
             '<div class="note"><sup><span class="noteNoteSuper" id="note_2">2</span>&nbsp;</sup>'
             '<span class="notetype">tn</span> Heb “two years.”')
    (cache / "net" / "1SA-013.json").write_text(json.dumps({"content": content, "notes": notes}), encoding="utf-8")
    (cache / "sblgntapp" / "Luke.txt").write_text(
        "Luke 10:1\n10:1 καὶ Treg RP ] – WH NA28\n• ⸀δύο WH NA28 ] – Treg RP\n\nLuke 10:2\n2 δὲ WH ] – RP\n",
        encoding="utf-8")
    (cache / "morphhb" / "Ezra.xml").write_text(
        '<verse osisID="Ezra.2.6"><note type="variant"><catchWord>ארבע</catchWord><rdg type="x-qere">'
        '<w lemma="2568">חָמֵשׁ</w></rdg></note></verse>'
        '<verse osisID="Ezra.2.7"><note type="variant"><catchWord>אלפים</catchWord><rdg type="x-qere">'
        '<w lemma="505">אַלְפַּיִם</w></rdg></note></verse>', encoding="utf-8")
    return cache


def test_net_tc_notes_map_to_their_verse_and_skip_translator_notes(tmp_path):
    """Only tc notes are evidence, each on the verse its marker sits in."""
    notes = net_tc_notes(_cache(tmp_path), "1SA", 13)
    assert list(notes) == [1] and notes[1][0].startswith("The MT does not have “thirty.”")


def test_net_note_is_about_a_number_only_when_a_reading_names_one():
    """'One Hebrew ms reads “Riphath”' is not a number variant; “three” for “seven” is."""
    assert net_names_a_number("The LXX reads “three” instead of “seven”.")
    assert not net_names_a_number("One Hebrew ms reads “Riphath”.")


def test_sblgnt_numeral_units_and_oshb_numeral_qere_are_collected(tmp_path):
    """Greek numeral variants and Hebrew numeral qere readings that change the number become evidence;
    a qere that only respells or inflects the same numeral (EZR 2:7 here) does not."""
    cache = _cache(tmp_path)
    assert sblgnt_units(cache)["LUK 10:1"][1].startswith("⸀δύο")
    found = collect(cache, ["LUK 10:1", "LUK 10:2", "1SA 13:1", "1SA 13:2", "EZR 2:6", "EZR 2:7"], {"505", "2568"})
    assert {ref: [item.source for item in items] for ref, items in found.items()} == {
        "LUK 10:1": ["SBLGNT_APPARATUS"], "1SA 13:1": ["NET_TC"], "EZR 2:6": ["OSHB_KETIV_QERE"]}


def test_mismatch_at_an_attested_variant_is_review_not_fail():
    """Where the apparatus records a number variant, a WIP following another witness is reviewed."""
    row = ReferenceRow(VerseRef("LUK", 10, 1), "LUK 10:1", "GRK", "", (F(72),), "", (F(72),),
                       {"MATCH_STATUS": "PASS_EXACT", "OL_REVIEW_STATUS": "AGREES", "TC_STATUS": "VARIANT_ATTESTED",
                        "TC_EVIDENCE": "SBLGNT_APPARATUS: δύο WH NA28 ] – Treg RP"})
    result = compare_group((F(70),), [row], mode="UNORDERED")
    assert result.outcome == "NEEDS_REVIEW" and result.review_context["kind"] == "APPARATUS_VARIANT"
    plain = ReferenceRow(VerseRef("LUK", 10, 1), "LUK 10:1", "GRK", "", (F(72),), "", (F(72),),
                         {"MATCH_STATUS": "PASS_EXACT", "OL_REVIEW_STATUS": "AGREES", "TC_STATUS": "NONE",
                          "TC_EVIDENCE": ""})
    assert compare_group((F(70),), [plain], mode="UNORDERED").outcome == "FAIL"


def test_net_parallel_references_are_read_from_tagged_tc_notes(tmp_path):
    """A number-relevant tc note's tagged reference is its cited parallel; tn notes are ignored."""
    from sage.numbers.index_build.apparatus import net_tc_parallels
    cache = tmp_path / "apparatus"
    (cache / "net").mkdir(parents=True)
    content = '<a class="netNoteSuper" pos="1" data-book="1 Chronicles" data-chapter="19" data-verse="18" id="noteSuper_1_1">1</a>'
    notes = ('<div class="note"><sup><span class="noteNoteSuper" id="note_1">1</span>&nbsp;</sup>'
             '<span class="notetype">tc</span> The parallel text of <data ref="Bible:2Sa 10:18">2 Sam 10:18</data> '
             'has “seven hundred.”')
    (cache / "net" / "1CH-019.json").write_text(json.dumps({"content": content, "notes": notes}), encoding="utf-8")
    assert net_tc_parallels(cache, "1CH", 19) == {18: ["2SA 10:18"]}


def test_only_synoptic_parallels_count():
    """Samuel-Kings/Chronicles and Ezra/Nehemiah parallels count; a neighbouring verse does not."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("bni", Path(__file__).parents[2] / "tools/build_numbers_index.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    assert tool._synoptic("1CH 19:18", "2SA 10:18") and tool._synoptic("NEH 7:69", "EZR 2:66")
    assert not tool._synoptic("JDG 14:15", "JDG 14:14") and not tool._synoptic("LUK 10:1", "DEU 10:22")


def test_net_basis_names_the_witnesses_or_conjecture():
    """A NET-only reading records which kind of witness it rests on, or that it is conjectural."""
    from sage.numbers.index_build.apparatus import net_basis_label
    assert net_basis_label("The Syriac Peshitta has “thirty.”", "1CH") == "Syriac Peshitta"
    assert net_basis_label("Only a few medieval Hebrew mss lack “50,000,” reading simply “70.” It is",
                           "1SA") == "Hebrew manuscripts"
    assert net_basis_label("The Qere and many medieval Hebrew mss read “three.”",
                           "2SA") == "Qere/Kethib; Hebrew manuscripts"
    assert net_basis_label("The BHS editors suggest emending to “and the debt.”", "NEH") == "Conjecture or emendation"
    assert net_basis_label("An ancient Greek witness and the Syriac version read “20 cubits.” A cubit",
                           "2CH").startswith("Septuagint (specific manuscripts or recension); Syriac Peshitta")
    assert net_basis_label("One early ms (B) and an early version (sa) read “about seventy-six.”", "ACT") \
        == "Greek NT manuscripts; Early versions (Coptic, Old Latin) (B sa)"
    note = ("Most mss , especially the later ones (A [ * ] W Θ ƒ 1,13 M sy), have “on the third day.” "
            "The most reliable witnesses ( א B C D L 579 it co), have resisted this temptation.")
    assert net_basis_label(note, "MRK") == "Syriac Peshitta; Greek NT manuscripts (A W Θ ƒ1,13 𝔐 sy)"
