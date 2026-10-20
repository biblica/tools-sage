"""Check that each WIP number is attached to the same item as in the source ("30 gold bowls").

Local and deterministic. The WIP side is the extraction's English gloss of what each number
counts (``counts_en``); the source side is the typed index's REFERENT per value (NIV wording
first, original-language gloss as fallback). Only words that tell the items of one verse apart
are compared: in "gold dishes 30, silver dishes 1,000" the shared word "dishes" says nothing,
"gold" and "silver" decide.

Result per verse:
- ``WRONG``: some WIP number sits on an item the source gives a different number
  ("1 000 gold dishes" where the source has 30 gold dishes and 1 000 silver dishes);
- ``CONFIRMED``: every decided WIP number matches its own source item and at most one is
  undecided (it can only belong to the one item left over);
- ``UNVERIFIED``: too little gloss evidence to decide.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
import re
from typing import Sequence

_STOP = {"of", "the", "a", "an", "and", "for", "in", "on", "to", "with", "from", "by", "his", "her", "their",
         "its", "your", "my", "our", "each", "all", "other", "more", "than"}


def _tokens(text: str) -> set[str]:
    """Content words, lowercased, with a plural -s/-es removed."""
    words = set()
    for word in re.findall(r"[a-z]+", text.lower()):
        if word in _STOP:
            continue
        if len(word) > 4 and word.endswith("es"):
            word = word[:-2]
        elif len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        words.add(word)
    return words


@dataclass(frozen=True)
class Pairing:
    """One WIP number and the source item its gloss matches."""

    wip_value: Fraction
    wip_counts: str
    source_value: Fraction | None
    source_referent: str


@dataclass(frozen=True)
class Association:
    """The association verdict for one verse with its evidence rows."""

    verdict: str
    pairings: tuple[Pairing, ...] = field(default_factory=tuple)


def check(wip_values: Sequence[Fraction], wip_counts_en: Sequence[str],
          source_values: Sequence[Fraction], source_referents: Sequence[str]) -> Association:
    """Compare which item each WIP number counts with the source pairing of numbers and items."""
    if not wip_counts_en or len(wip_counts_en) != len(wip_values) or len(source_referents) != len(source_values):
        return Association("UNVERIFIED")
    source = [_tokens(referent) for referent in source_referents]
    if len(source) < 2:
        return Association("UNVERIFIED")
    shared = set.intersection(*source) if source else set()
    distinct = [tokens - shared for tokens in source]
    chosen: list[int | None] = []
    for value, gloss in zip(wip_values, wip_counts_en):
        words = _tokens(gloss) - shared
        scores = [len(words & tokens) for tokens in distinct]
        best = max(scores) if scores else 0
        matches = [index for index, score in enumerate(scores) if score == best]
        index = matches[0] if words and best and len(matches) == 1 else None
        if index is not None and source_values[index] != value:
            # Nested items name one thing: "tenth" (1/10) and "tenth fine flour" (1) are the measure
            # and its count (LEV 14:21), so a gloss landing on either may carry the other's number.
            nested = [other for other, tokens in enumerate(distinct) if other != index and tokens
                      and (tokens <= distinct[index] or distinct[index] <= tokens)
                      and source_values[other] == value]
            index = nested[0] if nested else index
        chosen.append(index)
    # A gloss that lands different WIP values on one source item does not tell the items apart
    # ("12 bulls ... 3 [bulls] facing north"): those numbers stay undecided rather than WRONG.
    values_per_item: dict[int, set[Fraction]] = {}
    for value, index in zip(wip_values, chosen):
        if index is not None:
            values_per_item.setdefault(index, set()).add(value)
    # A source item without distinguishing words can never be matched, so a gloss cannot rule it out:
    # "righteous people 50" may belong to the unglossed 50 rather than to "people 5" (GEN 18:28).
    blind = any(not tokens for tokens in distinct)
    pairings, decided, wrong = [], 0, False
    for value, gloss, index in zip(wip_values, wip_counts_en, chosen):
        if (index is None or len(values_per_item[index]) > 1
                or blind and source_values[index] != value):
            pairings.append(Pairing(value, gloss, None, ""))
            continue
        decided += 1
        pairings.append(Pairing(value, gloss, source_values[index], source_referents[index]))
        if source_values[index] != value:
            wrong = True
    if wrong:
        return Association("WRONG", tuple(pairings))
    # One undecided number can only belong to the one source item left over: no swap is possible.
    if decided and len(wip_values) - decided <= 1:
        return Association("CONFIRMED", tuple(pairings))
    return Association("UNVERIFIED", tuple(pairings))
