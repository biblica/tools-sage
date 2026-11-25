"""PCC P5b-0: word alignment through the BSB (gold / transitive) and direct (Model 1 both ways). Fabricated data."""

from __future__ import annotations

import random
from dataclasses import dataclass

from sage.pcc.align import (Link, OlToken, align_direct, align_reference, align_via_bsb, bsb_index, cache_key,
                            ol_tokens_for_units, train_direct)
from sage.pcc.discovery import SourceUnit
from sage.pcc.segment import tokenize
from sage.vrs import VerseRef


@dataclass(frozen=True)
class _Link:
    """Stand-in for a ``BsbLink``."""

    bsb_ref: str
    order: int
    english: str


def _unit(n: int, text: str, book: str = "MAT") -> SourceUnit:
    """A fabricated verse unit."""
    return SourceUnit(f"u{n}", f"{book} 1:{n}", (f"{book} 1:{n}",), text)


ALIGNMENT = {"MAT 1:1!1": _Link("MAT 1:1", 2, "beta"), "MAT 1:1!2": _Link("MAT 1:1", 1, "Alpha"),
             "MAT 1:1!3": _Link("MAT 1:1", 3, "gamma delta"), "MAT 1:1!4": _Link("MAT 1:1", 0, "-")}


def test_bsb_index_orders_chunks_and_skips_unrendered_words():
    """Chunks come in BSB order; a word with position 0 (not rendered) is not in the stream."""
    assert bsb_index(ALIGNMENT) == {"MAT 1:1": [(1, "MAT 1:1!2", "Alpha"), (2, "MAT 1:1!1", "beta"),
                                                (3, "MAT 1:1!3", "gamma delta")]}


def test_via_bsb_is_gold_for_the_bsb_and_transitive_for_another_text():
    """The BSB verse (plus a supplied word) is gold; a different wording keeps only its matching tokens."""
    index = bsb_index(ALIGNMENT)
    units = [_unit(1, "Alpha beta, gamma the delta.")]
    tokens = {u.unit_id: tokenize(u.text) for u in units}
    gold = align_via_bsb(units, tokens, index)["u1"]
    assert [(l.token, l.ol_ref, l.method) for l in gold] == [
        (0, "MAT 1:1!2", "gold"), (1, "MAT 1:1!1", "gold"), (2, "MAT 1:1!3", "gold"), (4, "MAT 1:1!3", "gold")]
    other = [_unit(1, "Alpha zeta gamma")]
    links = align_via_bsb(other, {"u1": tokenize("Alpha zeta gamma")}, index)["u1"]
    assert [(l.token, l.ol_ref, l.method) for l in links] == [(0, "MAT 1:1!2", "transitive"),
                                                               (2, "MAT 1:1!3", "transitive")]


def _corpus(seed: int = 7, verses: int = 400):
    """A fabricated parallel corpus: each OL key has one target word; order is shuffled a little."""
    rng = random.Random(seed)
    letters = "bcdfghjklmnpqrstvwxz"
    lexicon = {f"GRK:{k}": letters[k % 20] + "a" + letters[k // 20] for k in range(1, 41)}
    tokens, ol, truth = {}, {}, {}
    for v in range(verses):
        keys = rng.sample(sorted(lexicon), 6)
        words = [lexicon[k] for k in keys]
        i, j = rng.randrange(6), rng.randrange(6)
        words[i], words[j] = words[j], words[i]
        unit = f"u{v}"
        tokens[unit] = tokenize(" ".join(words))
        ol[unit] = [OlToken(f"MAT {v}:1!{n}", key) for n, key in enumerate(keys, start=1)]
        truth[unit] = {t: next(o.ref for o in ol[unit] if lexicon[o.key] == tokens[unit][t].norm) for t in range(6)}
    return tokens, ol, truth


def test_direct_path_recovers_a_consistent_lexicon():
    """Model 1 both ways links nearly every token to its own word, and never two links per token."""
    tokens, ol, truth = _corpus()
    links = align_direct(tokens, ol, train_direct(tokens, ol))
    linked = [(unit, l) for unit, found in links.items() for l in found]
    correct = sum(1 for unit, l in linked if truth[unit][l.token] == l.ol_ref)
    assert len(linked) >= 0.9 * sum(len(t) for t in tokens.values())
    assert correct / len(linked) >= 0.98
    assert all(len({l.token for l in found}) == len(found) for found in links.values())
    assert all(l.method == "direct" and 0.5 <= l.score <= 1 for _, l in linked)


def test_direct_path_is_deterministic():
    """The same inputs give the same links."""
    tokens, ol, _ = _corpus(seed=3, verses=120)
    first = align_direct(tokens, ol, train_direct(tokens, ol))
    assert first == align_direct(tokens, ol, train_direct(tokens, ol))


class _Word:
    """Stand-in for an ``OlWord``."""

    def __init__(self, word_id, *segments):
        """Keep the id and segments."""
        self.word_id, self.segments = word_id, segments


class _Analysis:
    """Stand-in for ``OlAnalysis`` with one Hebrew verse."""

    def verses(self, family):
        """Return the fabricated verses of a family."""
        if family != "HEB":
            return {}
        return {VerseRef("GEN", 1, 1): [_Word("GEN 1:1!1", {"strong": "0871a", "lemma": "p"}, {"strong": "7225", "lemma": "n"}),
                                        _Word("GEN 1:1!2", {"strong": "", "lemma": "x"})]}


class _Schema:
    """Identity versification."""

    def local_to_canonical(self, ref):
        """Same reference."""
        return frozenset({ref})


def test_hebrew_segments_are_separate_tokens_of_their_word():
    """Prefix and suffix segments are their own tokens and all point to the word's ref."""
    found = ol_tokens_for_units([_unit(1, "x", book="GEN")], _Analysis(), _Schema())
    assert found == {"u1": [OlToken("GEN 1:1!1", "HEB:871"), OlToken("GEN 1:1!1", "HEB:7225"),
                            OlToken("GEN 1:1!2", "HEB:x")]}


def test_bsb_links_win_over_direct_links_and_stats_count_methods():
    """Where the BSB path links a token, its link is kept; the direct path fills the rest."""
    result = align_reference([_unit(1, "Alpha beta gamma delta")], _NoAnalysis(), _Schema(), bsb_alignment=ALIGNMENT)
    assert [(l.token, l.method) for l in result.links["u1"]] == [(0, "gold"), (1, "gold"), (2, "gold"), (3, "gold")]
    assert result.stats == {"tokens": 4, "gold": 4, "transitive": 0, "direct": 0}


class _NoAnalysis:
    """An analysis without verses."""

    def verses(self, family):
        """No verses."""
        return {}


def test_cache_key_depends_on_every_input():
    """Changing the reference or a package changes the key."""
    key = cache_key("a" * 64, "SAGE_OL_ANALYSIS_X", "SAGE_PCC_OL_Y")
    assert key != cache_key("b" * 64, "SAGE_OL_ANALYSIS_X", "SAGE_PCC_OL_Y")
    assert key != cache_key("a" * 64, "SAGE_OL_ANALYSIS_X", "SAGE_PCC_OL_Z")
    assert isinstance(Link(0, "r", "gold", 1.0), Link)
