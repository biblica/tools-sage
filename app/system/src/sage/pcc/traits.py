"""Traits of a WIP measured from its own text, and the capability matrix they imply (plan §7 L1).

No language code is consulted and no resource outside the Job's texts is used. Team-declared facts
(plan §7 L2, imported in P5) arrive as ``declared`` and switch capabilities on; without them a
capability is reported ``UNAVAILABLE`` and its check ``NOT_CHECKED``, never assumed.
"""

from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .segment import APOSTROPHE_LIKE, is_unspaced_char, tokenize

SUFFIX_MAX = 4
PREFIX_MAX = 4
MIN_STEM = 3
MIN_AFFIX_SUPPORT = 5   # distinct stems that alternate with this ending
MAX_AFFIXES = 12
UPPER_SHARE = 0.005     # cased text has some capitals ...
LOWER_SHARE = 0.1       # ... and mostly lowercase letters (a bare capital initial is about 3% of letters)
UNSPACED_SHARE = 0.5
APOSTROPHE_INSIDE_SHARE = 0.8  # share of uses with a letter on both sides before it counts as a letter
APOSTROPHE_MIN_INSIDE = 5
SAMPLE_LETTER_CAP = 2_000_000  # deterministic upper bound on text measured (in code points)


@dataclass(frozen=True)
class Affix:
    """A learned inflection: the string and the number of distinct stems it alternates on."""

    form: str
    support: int


@dataclass(frozen=True)
class WipTraits:
    """What the WIP's own text shows. Serializable, and identical for identical text."""

    letters: int
    words: int
    script: str
    unspaced: bool
    cased: bool
    letter_marks: tuple[str, ...]
    letter_inventory: tuple[str, ...]
    punctuation_inventory: tuple[str, ...]
    suffixes: tuple[Affix, ...] = field(default=())
    prefixes: tuple[Affix, ...] = field(default=())

    def as_record(self) -> dict[str, Any]:
        """Implement as record."""
        return {
            "letters": self.letters, "words": self.words, "script": self.script,
            "unspaced": self.unspaced, "cased": self.cased,
            "letter_marks": list(self.letter_marks),
            "letter_inventory": list(self.letter_inventory),
            "punctuation_inventory": list(self.punctuation_inventory),
            "suffixes": [{"form": a.form, "support": a.support} for a in self.suffixes],
            "prefixes": [{"form": a.form, "support": a.support} for a in self.prefixes],
        }


def _script(char: str) -> str:
    """Implement script."""
    return unicodedata.name(char, "UNKNOWN").split(" ")[0]


def _apostrophe_letters(texts: list[str]) -> tuple[str, ...]:
    """Apostrophe-like code points used inside words often enough to be letters of this orthography."""
    inside: Counter[str] = Counter()
    total: Counter[str] = Counter()
    for text in texts:
        for i, char in enumerate(text):
            if char not in APOSTROPHE_LIKE:
                continue
            total[char] += 1
            if 0 < i < len(text) - 1 and text[i - 1].isalpha() and text[i + 1].isalpha():
                inside[char] += 1
    return tuple(sorted(
        c for c in total
        if inside[c] >= APOSTROPHE_MIN_INSIDE and inside[c] / total[c] >= APOSTROPHE_INSIDE_SHARE
    ))


def _affixes(vocab: Iterable[str], *, prefix: bool) -> tuple[Affix, ...]:
    """Endings (or beginnings) that alternate across many shared stems, learned from the vocabulary."""
    longest = PREFIX_MAX if prefix else SUFFIX_MAX
    forms: dict[str, set[str]] = defaultdict(set)
    for word in vocab:
        for k in range(longest + 1):
            if len(word) - k < MIN_STEM:
                break
            stem, affix = (word[k:], word[:k]) if prefix else (word[:len(word) - k], word[len(word) - k:])
            forms[stem].add(affix)
    support: Counter[str] = Counter()
    for affixes in forms.values():
        if len(affixes) >= 2:
            for affix in affixes:
                if affix:
                    support[affix] += 1
    ranked = sorted(((a, s) for a, s in support.items() if s >= MIN_AFFIX_SUPPORT), key=lambda x: (-x[1], x[0]))
    return tuple(Affix(a, s) for a, s in ranked[:MAX_AFFIXES])


def measure_traits(texts: Iterable[str]) -> WipTraits:
    """Measure script, spacing, case, letter inventory, apostrophe letters and learned affixes."""
    sample: list[str] = []
    size = 0
    for text in texts:
        sample.append(str(text))
        size += len(text)
        if size >= SAMPLE_LETTER_CAP:
            break
    letters: Counter[str] = Counter()
    scripts: Counter[str] = Counter()
    punctuation: Counter[str] = Counter()
    upper = lower = unspaced = 0
    for text in sample:
        for char in text:
            if char.isalpha():
                letters[char] += 1
                scripts[_script(char)] += 1
                if is_unspaced_char(char):
                    unspaced += 1
                if char.isupper():
                    upper += 1
                elif char.islower():
                    lower += 1
            elif not char.isspace() and not char.isdigit() and not unicodedata.category(char).startswith("M"):
                punctuation[char] += 1
    total = sum(letters.values())
    is_unspaced = total > 0 and unspaced / total > UNSPACED_SHARE
    cased = total > 0 and upper / total >= UPPER_SHARE and lower / total >= LOWER_SHARE
    marks = _apostrophe_letters(sample)
    vocab: Counter[str] = Counter()
    word_count = 0
    for text in sample:
        for token in tokenize(text, cased=cased, letter_marks=marks, unspaced=is_unspaced):
            vocab[token.norm] += 1
            word_count += 1
    # Affix learning needs words; unspaced character tokens carry no affix evidence.
    learn = not is_unspaced
    return WipTraits(
        letters=total,
        words=word_count,
        script=scripts.most_common(1)[0][0] if scripts else "NONE",
        unspaced=is_unspaced,
        cased=cased,
        letter_marks=marks,
        letter_inventory=tuple(sorted(letters)),
        punctuation_inventory=tuple(sorted(punctuation)),
        suffixes=_affixes(vocab, prefix=False) if learn else (),
        prefixes=_affixes(vocab, prefix=True) if learn else (),
    )


def capability_matrix(traits: WipTraits, declared: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Capability states for this WIP: ``SUPPORTED``, ``PARTIAL`` or ``UNAVAILABLE`` (handover doc 03).

    Segmentation is ``PARTIAL`` for unspaced scripts and ``SUPPORTED`` otherwise. Morphology is
    ``PARTIAL`` when affixes were learned from the text, else ``UNAVAILABLE``. Negation and the
    orthographic-equivalence check exist only when the team declared them (``negation_markers``,
    ``spelling_equivalences``). Unavailable capabilities fall back to exact matching plus review.
    """
    facts = declared or {}
    learned = bool(traits.suffixes or traits.prefixes)
    return {
        "normalization": "SUPPORTED",
        "segmentation": "PARTIAL" if traits.unspaced else ("SUPPORTED" if traits.words else "UNAVAILABLE"),
        "morphology": "PARTIAL" if learned and not traits.unspaced else "UNAVAILABLE",
        "negation": "SUPPORTED" if facts.get("negation_markers") else "UNAVAILABLE",
        "orthographic_equivalence": "SUPPORTED" if facts.get("spelling_equivalences") else "UNAVAILABLE",
        "syntax": "UNAVAILABLE",
    }
