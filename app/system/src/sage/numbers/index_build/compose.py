"""Compose classified numeral words into counted values, keeping the words behind each value.

Rules (calibrated against the 2026-09-09 index; see the regression report):

1. A *run* is a stretch of adjacent numeral words. Inside a run, a scale multiplies what
   precedes it (שֵׁשׁ מֵאוֹת = 600) and a thousand-scale closes a group (שֵׁשׁ מֵאוֹת אֶלֶף =
   600,000; "a thousand thousands" = 1,000,000).
2. Hebrew: two adjacent units are separate numbers ("one, thirty and a hundred" = 1, 130;
   distributive "two two" = 2, 2) except a unit followed by the teen ten (14). Greek writes
   compounds adjacently, so adjacent Greek units add (ἑκατὸν πεντήκοντα τριῶν = 153).
3. Runs joined by a conjunction form one number when each part has a new decimal
   magnitude ("five and twenty" = 25, "fifty and five hundred" = 550); same-magnitude parts
   stay separate ("one ... and five" = 1, 5). A counted noun repeated around the
   conjunction still joins ("five years and a hundred years" = 105).
4. A singular thousand after a joined compound multiplies the pending part below a
   thousand ("a hundred eighty and five thousand" = 185,000); a plural "thousands" with its
   own unit stays local ("five hundred and four thousands" = 4,500).
5. A bare plural scale with no unit ("the thousands", "commanders of hundreds") is its own
   value and never joins another.
6. Ordinals, fractions and multipliers are whole values. A fraction word directly after a
   number is its measure ("three tenths" = 3); "and a half" adds 1/2 to the preceding
   number or measure noun ("a cubit and a half" = 3/2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable, Sequence

from .lexicon import Numeral
from .macula import Word, normalized

F = Fraction
_HALF_MEASURES = {normalized("אַמָּה")}
# Only "and" joins number parts; "or" (אוֹ, ἤ) keeps them separate ("eight or ten").
_AND = {normalized("וְ"), normalized("καί")}


@dataclass
class Expression:
    """One counted value and the original-language words it came from."""

    value: Fraction
    kind: str
    words: list[Word] = field(default_factory=list)


def _magnitude(value: Fraction) -> int:
    """Decimal magnitude of an integer part (units 0, tens 1, hundreds 2, ...)."""
    number, power = int(value), 0
    while number >= 10:
        number //= 10
        power += 1
    return power


def _term_value(items: Sequence[tuple[Word, Numeral]]) -> Fraction:
    """Multiplicative value of one term of adjacent cardinal words."""
    if len(items) > 1 and items[0][1].role == "SCALE" and items[0][1].plural \
            and all(numeral.role == "UNIT" for _w, numeral in items[1:]):
        # Greek counts a plural scale with a following unit: μυριάδας πέντε = 50,000.
        return items[0][1].value * _term_value(items[1:])
    total, current = F(0), F(0)
    for _word, numeral in items:
        if numeral.role == "SCALE":
            if current:
                current *= numeral.value
            elif total and numeral.value >= 1000:
                total *= numeral.value  # "a thousand thousands"
                continue
            else:
                current = numeral.value
            if numeral.value >= 1000:
                total, current = total + current, F(0)
        else:
            current += numeral.value
    return total + current


def _leads_next(terms, term, words: Sequence[Word]) -> bool:
    """A lone unit directly followed by a larger number belongs to that number's phrase."""
    position = terms.index(term)
    if len(term) != 1 or position + 1 >= len(terms):
        return False
    following = terms[position + 1]
    return following[0][0] == term[-1][0] + 1 and following[0][2].value > term[0][2].value


def _attributive(words: Sequence[Word], word: Word) -> bool:
    """A Hebrew "one" with its own article after a noun ("the one curtain") starts no compound."""
    position = list(words).index(word)
    return position >= 2 and words[position - 1].subtype == "definite article" and words[position - 2].pos == "noun"


def _same_noun_follows(words: Sequence[Word], start: int, last_end: int) -> bool:
    """חֲצִי הַמַּטֶּה after "nine tribes and": the half counts the same noun, so 9 1/2."""
    counted = next((word.lemma for word in words[last_end:start] if word.pos == "noun"), None)
    after = next((word.lemma for word in words[start + 1:start + 3] if word.pos == "noun"), None)
    return counted is not None and counted == after


def tail_is_compound(items) -> bool:
    """A term like "five ... thousand" whose singular thousand multiplies a joined compound."""
    tail = items[-1][1]
    return tail.role == "SCALE" and not tail.plural and len(items) > 1


def _split_terms(run: list[tuple[int, Word, Numeral]], *, split_adjacent_units: bool):
    """Cut one run of adjacent numeral words into terms (rules 1, 2 and 5)."""
    terms: list[list[tuple[int, Word, Numeral]]] = []
    piece: list[tuple[int, Word, Numeral]] = []
    for item in run:
        _index, _word, numeral = item
        previous = piece[-1][2] if piece else None
        cut = False
        if previous is not None:
            if previous.kind == "MULTIPLIER" and numeral.role == "UNIT" and not split_adjacent_units \
                    and numeral.value < previous.value:
                cut = False  # ἑβδομηκοντάκις ἑπτά "seventy-seven times" = 77; πεντάκις τεσσεράκοντα stays 5, 40
            elif numeral.role == "WHOLE" or previous.role == "WHOLE":
                cut = True
            elif previous.role == "SCALE" and previous.value >= 1000 and numeral.role == "UNIT" \
                    and not (not split_adjacent_units and previous.plural and len(piece) == 1):
                cut = True  # (Greek keeps a post-positive unit: χιλιάδες πέντε = 5,000)
            elif split_adjacent_units and numeral.role == "SCALE" and previous.role == "UNIT" and (
                    previous.value == 1 or numeral.value == 100 and not numeral.plural):
                cut = True  # Hebrew writes 500 as חֲמֵשׁ מֵאוֹת: חֲמִשָּׁה מֵאָה is "five [chase] a hundred"
            elif numeral.role == "SCALE" and previous.role == "UNIT" and previous.value >= numeral.value:
                cut = True  # "twice ten thousand, thousands": a scale never multiplies a larger value
            elif len(piece) == 1 and previous.role == "SCALE" and previous.plural and split_adjacent_units:
                cut = True
            elif (split_adjacent_units and numeral.role == "UNIT" and previous.role in ("UNIT", "TEEN")):
                cut = True
            elif not split_adjacent_units and numeral.role == "UNIT" and previous.role == "UNIT" \
                    and _magnitude(numeral.value) >= _magnitude(previous.value):
                cut = True  # Greek compounds descend (ἑκατὸν πεντήκοντα τρεῖς); "three, one" are separate
        if cut:
            terms.append(piece)
            piece = []
        piece.append(item)
    if piece:
        terms.append(piece)
    return terms


def compose(words: Sequence[Word], classify: Callable[[Word], Numeral | None], *,
            split_adjacent_units: bool) -> list[Expression]:
    """Compose one verse's words into counted expressions, in reading order."""
    numerals = [classify(word) for word in words]
    runs: list[list[tuple[int, Word, Numeral]]] = []
    index = 0
    while index < len(words):
        if numerals[index] is None:
            index += 1
            continue
        run = []
        while index < len(words) and numerals[index] is not None:
            run.append((index, words[index], numerals[index]))
            index += 1
            # An article between a unit and its scale or teen is transparent: חֲמֵשׁ הַמֵּאוֹת = 500,
            # שְׁנֵים הֶעָשָׂר "the twelfth" = 12.
            if (index + 1 < len(words) and words[index].subtype == "definite article"
                    and numerals[index + 1] is not None and numerals[index + 1].role in ("SCALE", "TEEN")
                    and run[-1][2].role == "UNIT"):
                index += 1
        runs.append(run)
    terms = [term for run in runs for term in _split_terms(run, split_adjacent_units=split_adjacent_units)]

    out: list[Expression] = []
    state = {"big": F(0), "small": F(0), "classes": set(), "big_classes": set(), "words": [], "open": False}
    last_end = None

    def close() -> None:
        """Emit the open number, if any, and reset the accumulator."""
        if state["open"]:
            out.append(Expression(state["big"] + state["small"], "CARDINAL", list(state["words"])))
        state.update(big=F(0), small=F(0), classes=set(), big_classes=set(), words=[], open=False)

    def bridged(previous_end: int, start: int) -> bool:
        """Whether the words between two terms let them form one number (rule 3)."""
        between = words[previous_end:start]
        if len(between) == 1 and between[0].lemma in _AND:
            return True
        if len(between) == 2 and between[0].lemma in _AND and between[1].subtype == "definite article":
            return True  # הַשְּׁלֹשָׁה וְהַשִּׁבְעִים וְהַמָּאתָיִם "the 273"
        if len(between) == 2 and between[0].pos == "noun" and between[1].lemma in _AND:
            follow = words[start:start + 4]
            return any(word.pos == "noun" and word.lemma == between[0].lemma for word in follow)
        return False

    for term in terms:
        start, end = term[0][0], term[-1][0] + 1
        items = [(word, numeral) for _i, word, numeral in term]
        term_words = [word for word, _n in items]
        first = items[0][1]
        if first.kind == "MULTIPLIER" and len(items) > 1:
            close()
            out.append(Expression(sum((numeral.value for _w, numeral in items), F(0)), "MULTIPLIER", term_words))
            last_end = end
            continue
        if first.role == "WHOLE":
            close()
            if first.kind == "FRACTION" and start > 0:
                previous = words[start - 1]
                if first.value == F(1, 2) and previous.pos in ("conjunction", "conj"):
                    if out and out[-1].kind == "CARDINAL" and last_end is not None and last_end >= start - 3 \
                            and (items[0][0].state != "construct" or _same_noun_follows(words, start, last_end)):
                        out[-1].value += first.value  # "two cubits and a half" = 5/2
                        out[-1].words.extend(term_words)
                        last_end = end
                        continue
                    if start >= 2 and words[start - 2].lemma in _HALF_MEASURES:
                        whole = 2 if words[start - 2].number == "dual" else 1
                        out.append(Expression(whole + first.value, "CARDINAL", [words[start - 2], *term_words]))
                        last_end = end
                        continue
                if last_end == start and out and out[-1].kind == "CARDINAL":
                    last_end = end  # measure word directly after a number ("three tenths")
                    continue
            out.append(Expression(first.value, first.kind, term_words))
            last_end = end
            continue
        value = _term_value(items)
        bare_plural = len(items) == 1 and first.role == "SCALE" and first.plural
        adjacent_descending = (state["open"] and last_end == start and value < 1000 and state["classes"]
                               and _magnitude(value) < min(state["classes"]))
        adjacent_thousands = (state["open"] and last_end == start and value >= 1000 and state["big_classes"]
                              and _magnitude(value) < min(state["big_classes"]))
        joined = state["open"] and not bare_plural and last_end is not None and (
            bridged(last_end, start) or adjacent_descending or adjacent_thousands
            or (last_end == start and state["big"] and value < 1000))
        if joined and value < 1000 and _magnitude(value) in state["classes"]:
            joined = False
        if joined and state["big"] >= 1000 and value > state["big"]:
            joined = False  # אֶלֶף ... וּרְבָבָה "a thousand ... and ten thousand": thousands descend
        if joined and last_end != start and _leads_next(terms, term, words):
            joined = False  # τριάκοντα καὶ ἓν ἑξήκοντα: "thirty, and one sixty", not 31
        if joined and split_adjacent_units and value == 1 and len(items) == 1 and state["big"] and last_end == start:
            joined = False  # אֶלֶף אֶחָד "a thousand [flee] at one": Hebrew writes 1001 with "and"
        if joined and split_adjacent_units and len(state["words"]) == 1 and state["small"] == 1 \
                and _attributive(words, state["words"][0]):
            joined = False  # הַיְרִיעָה הָאֶחָת וַחֲמִשִּׁים "the one curtain, and fifty": not 51
        if joined and value >= 1000 and state["big"] and _magnitude(value) in state["big_classes"] \
                and not (tail_is_compound(items) and state["small"]):
            joined = False  # "22,000 returned and 10,000 remained" stay separate
        if not joined:
            close()
        state["open"] = True
        state["words"].extend(term_words)
        tail = items[-1][1]
        if value >= 1000:
            if joined and tail.role == "SCALE" and not tail.plural and len(items) > 1:
                state["big"] += (state["small"] + _term_value(items[:-1])) * tail.value
                state["small"], state["classes"] = F(0), set()
            else:
                state["big"] += value
            state["big_classes"].add(_magnitude(state["big"]))
        else:
            state["small"] += value
            state["classes"].add(_magnitude(value))
        if bare_plural:
            close()
        last_end = end
    close()
    return out
