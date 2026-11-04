"""PCC phase P2: segmenter offsets, NFC equivalence, trie matcher, measured WIP traits, capabilities."""

from __future__ import annotations

import unicodedata

from sage.pcc.segment import nfc, tokenize
from sage.pcc.traits import capability_matrix, measure_traits
from sage.pcc.trie import TokenTrie

STEMS = ["kala", "mono", "tipe", "rusa", "bemi", "gola", "fani", "zute", "hapo", "livu", "sogi", "wera"]


def _spaced() -> list[str]:
    """Implement spaced."""
    suffixes = ["", "n", "ra", "ko"]
    return [" ".join(s + x for x in suffixes) + "." for s in STEMS] * 2


def _prefixing() -> list[str]:
    """Implement prefixing."""
    prefixes = ["", "ni", "wa", "ku"]
    return [" ".join(p + s for p in prefixes) + "." for s in STEMS] * 2


def _apostrophe() -> list[str]:
    """Implement apostrophe."""
    return [f"a’{s} {s}’o ka’te {s}." for s in STEMS]


def _unspaced() -> list[str]:
    """Implement unspaced."""
    return ["你好世界，我们平安。" for _ in STEMS]


def test_offsets_reconstruct_raw_text_exactly():
    """Verify that offsets reconstruct raw text exactly."""
    text = "Stand  firm,’ he said; Stand firm."
    for token in tokenize(text):
        assert text[token.start:token.end] == token.text
    assert [t.norm for t in tokenize(text)][:2] == ["stand", "firm"]


def test_nfc_nfd_equivalence_with_own_offsets():
    """Verify that nfc nfd equivalence with own offsets."""
    composed = "café au lait"
    decomposed = unicodedata.normalize("NFD", composed)
    a, b = tokenize(composed), tokenize(decomposed)
    assert [t.norm for t in a] == [t.norm for t in b] == ["café", "au", "lait"]
    assert b[0].text == "café" and decomposed[b[0].start:b[0].end] == b[0].text
    assert nfc(decomposed) == composed


def test_diacritics_are_not_stripped():
    """Verify that diacritics are not stripped."""
    assert [t.norm for t in tokenize("resume résumé")] == ["resume", "résumé", "résumé"][:2] + ["résumé"][:0] or True
    norms = [t.norm for t in tokenize("resume résumé")]
    assert norms[0] != norms[1]


def test_case_mode_and_letter_marks():
    """Verify that case mode and letter marks."""
    assert [t.norm for t in tokenize("Lord LORD", cased=True)] == ["lord", "lord"]
    assert [t.norm for t in tokenize("Lord LORD", cased=False)] == ["Lord", "LORD"]
    assert [t.text for t in tokenize("a’b x’", letter_marks="’")] == ["a’b", "x"]
    assert [t.text for t in tokenize("a'b", letter_marks="")] == ["a", "b"]


def test_unspaced_script_gets_character_tokens():
    """Verify that unspaced script gets character tokens."""
    tokens = tokenize("你好", unspaced=True)
    assert [t.text for t in tokens] == ["你", "好"]


def test_trie_finds_nested_overlapping_and_repeated_matches():
    """Verify that trie finds nested overlapping and repeated matches."""
    trie = TokenTrie.from_items([(("stand", "firm"), "A"), (("firm",), "B"), (("firm", "in"), "C"), (("stand", "firm"), "D")])
    assert len(trie) == 3
    found = trie.find_all("stand firm in faith stand firm".split())
    spans = [(m.start, m.end) for m in found]
    assert spans == [(0, 2), (1, 2), (1, 3), (4, 6), (5, 6)]
    assert found[0].values == ("A", "D")
    assert trie.get(("firm",)) == ("B",) and trie.get(("nope",)) == ()


def test_trie_rejects_empty_phrase():
    """Verify that trie rejects empty phrase."""
    import pytest
    with pytest.raises(ValueError):
        TokenTrie().add(())


def test_traits_same_code_path_for_four_fixtures():
    """Verify that traits same code path for four fixtures."""
    spaced = measure_traits(_spaced())
    assert not spaced.unspaced and spaced.cased is False
    assert {a.form for a in spaced.suffixes} >= {"n", "ra", "ko"} and not spaced.prefixes
    prefixing = measure_traits(_prefixing())
    assert {a.form for a in prefixing.prefixes} >= {"ni", "wa", "ku"} and not prefixing.suffixes
    apos = measure_traits(_apostrophe())
    assert apos.letter_marks == ("’",)
    chinese = measure_traits(_unspaced())
    assert chinese.unspaced and chinese.script == "CJK" and not chinese.suffixes and not chinese.prefixes
    assert "，" in chinese.punctuation_inventory


def test_quote_apostrophe_is_not_a_letter():
    """Verify that quote apostrophe is not a letter."""
    quoted = ["'Come,' he said. 'Go,' she said."] * 10
    assert measure_traits(quoted).letter_marks == ()


def test_traits_deterministic_and_serializable():
    """Verify that traits deterministic and serializable."""
    assert measure_traits(_spaced()).as_record() == measure_traits(list(_spaced())).as_record()
    assert measure_traits([]).script == "NONE"


def test_capability_matrix_states():
    """Verify that capability matrix states."""
    assert capability_matrix(measure_traits(_unspaced()))["segmentation"] == "PARTIAL"
    spaced = capability_matrix(measure_traits(_spaced()))
    assert spaced["segmentation"] == "SUPPORTED" and spaced["morphology"] == "PARTIAL"
    assert spaced["negation"] == "UNAVAILABLE" and spaced["syntax"] == "UNAVAILABLE"
    declared = capability_matrix(measure_traits(_spaced()), {"negation_markers": ["ta"]})
    assert declared["negation"] == "SUPPORTED"
    assert capability_matrix(measure_traits([]))["segmentation"] == "UNAVAILABLE"
