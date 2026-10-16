"""How the WIP renders each original-language name, and the verses where that rendering is missing.

MACULA marks every proper name in the Hebrew and Greek text. SAGE aligns those names with the WIP's words
across every book the WIP has, using a small EM word aligner restricted to names (IBM Model 1 with a NULL
word). Alignment learns each name's spelling stems, including inflected forms and names that always occur
together, as in genealogies. A verse whose original-language text has a name but whose WIP text carries none
of that name's stems is a candidate:

- ``VARIANT``: the verse has a rare word spelled close to one of the name's stems;
- ``SUBSTITUTION``: the verse has another name's rendering that its original-language text does not have;
- ``ABSENT``: neither, which is often a pronoun or a restructured sentence.

STC receives only ``VARIANT`` and ``SUBSTITUTION`` (``STC_CANDIDATE_KINDS``). In an LLM-judged audit of 84
sampled candidates from six WIPs (2026-10-16), 3 of 59 ``ABSENT`` candidates were worth a reviewer's time,
against 7 of 25 of the other kinds. ``ABSENT`` also made up most of the volume, and STC's own review already
looks for omissions.

Code only finds candidates. The model judges them, so nothing here is a finding by itself. Every step is
deterministic: the same WIP text and package give the same stems and candidates.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .atomic import atomic_write_json
from .ol_analysis import OlAnalysis, ol_family_for_book
from .vrs import VerseRef

NAME_ALIGNER_VERSION = "SAGE_NAME_ALIGNMENT_V2"
CANDIDATE_KINDS = ("VARIANT", "SUBSTITUTION", "ABSENT")
STC_CANDIDATE_KINDS = ("VARIANT", "SUBSTITUTION")

EM_ITERATIONS = 6
MIN_NAME_VERSES = 3  # a name needs this many WIP verses before its rendering is learned
RELATIVE_STEM_PROBABILITY = 0.2  # share of the name's best EM probability a stem needs to join its rendering
# A stem identifies a name when at least MIN_STEM_PRECISION of the WIP verses carrying it have the name in
# their original-language verse. Translations add frequent names (Jesus where the Greek has a pronoun) and render
# Adonai and YHWH alike, so the bar is well below 1. A stem rare outside the name's verses (at most
# MAX_BACKGROUND_RATE of the other verses) needs only MIN_RARE_STEM_PRECISION, which still keeps out common
# words that keep company with a rare name, such as "begot" in a genealogy.
MIN_STEM_PRECISION = 0.4
MAX_BACKGROUND_RATE = 0.02
MIN_RARE_STEM_PRECISION = 0.15
MIN_COVERAGE = 0.5  # share of a name's verses its stems must cover before missing verses are flagged
STRONG_COVERAGE = 0.6  # a name must be this established before its rendering counts as a substitution
STRONG_VERSES = 5
EXTEND_TOLERANCE = 0.05  # a stem is lengthened while it still covers 95% of the verses of the shorter stem
ABSENT_MIN_COVERAGE = 0.9  # a missing name is a candidate only when the WIP renders that name this consistently
RARE_WORD_COUNT = 10  # a VARIANT word occurs at most this many times in the whole WIP
SUFFIX_MAX = 4  # longest learned inflection ending, in letters (vowel signs and viramas do not count)
SUFFIX_MIN_NAMES = 5  # an ending is inflection when it alternates in the forms of at least this many names
_STEM_MIN, _STEM_MAX, _MAX_OFFSET = 4, 8, 2
_NGRAM_MIN, _NGRAM_MAX = 2, 6
_UNSPACED_SCRIPTS = ("CJK", "HIRAGANA", "KATAKANA", "THAI", "LAO", "KHMER", "MYANMAR", "TIBETAN")
# Scripts whose combining marks are optional diacritics (accents, Hebrew points, Arabic harakat). Elsewhere
# (Malayalam, Devanagari, Thai, ...) a mark is a vowel sign or virama and part of the spelling, so it is kept.
_DIACRITIC_SCRIPTS = ("LATIN", "GREEK", "CYRILLIC", "HEBREW", "ARABIC", "SYRIAC", "ARMENIAN", "GEORGIAN")


def fold(text: str) -> str:
    """Comparison form of WIP text: NFD, casefolded, without the marks of diacritic scripts."""
    kept: list[str] = []
    strip = False
    for char in unicodedata.normalize("NFD", str(text)):
        if unicodedata.category(char).startswith("M"):
            if not strip:
                kept.append(char)
            continue
        strip = unicodedata.name(char, "").startswith(_DIACRITIC_SCRIPTS)
        kept.append(char)
    return "".join(kept).casefold()


def words(text: str) -> list[str]:
    """The folded words of one text: runs of letters with their combining marks."""
    found: list[str] = []
    current: list[str] = []
    for char in fold(text):
        if char.isalpha() or (current and unicodedata.category(char).startswith("M")):
            current.append(char)
        elif current:
            found.append("".join(current))
            current = []
    if current:
        found.append("".join(current))
    return found


def is_unspaced(texts: Iterable[str]) -> bool:
    """True when most letters belong to scripts written without spaces between words (Chinese, Thai, ...)."""
    unspaced = total = 0
    for text in texts:
        for char in text:
            if not char.isalpha():
                continue
            total += 1
            if unicodedata.name(char, "").startswith(_UNSPACED_SCRIPTS):
                unspaced += 1
        if total >= 20000:
            break
    return total > 0 and unspaced / total > 0.5


def stems(word: str, *, unspaced: bool) -> set[str]:
    """Candidate name units in one folded word.

    Spaced scripts: prefixes of 4 to 8 letters starting at the first, second, or third letter, so that
    case endings (Яків, Якова) and short proclitics (وإبراهيم) still share a stem; a word of 2 or 3 letters
    is its own unit. Unspaced scripts: every substring of 2 to 6 characters.
    """
    if unspaced:
        return {word[i:i + n] for n in range(_NGRAM_MIN, _NGRAM_MAX + 1) for i in range(len(word) - n + 1)}
    if len(word) < _STEM_MIN:
        return {word} if len(word) >= 2 else set()
    return {
        word[offset:offset + n]
        for offset in range(_MAX_OFFSET + 1)
        if len(word) - offset >= _STEM_MIN
        for n in range(_STEM_MIN, min(len(word) - offset, _STEM_MAX) + 1)
    }


def carries(word: str, stem: str, *, unspaced: bool, offsets: Iterable[int] = range(_MAX_OFFSET + 1)) -> bool:
    """True when ``stem`` is one of the units ``stems`` takes from ``word``, at one of ``offsets``."""
    if unspaced:
        return stem in word
    if len(stem) < _STEM_MIN:
        return word == stem
    return any(word.startswith(stem, offset) for offset in offsets)


def _letters(text: str) -> int:
    """Letters in ``text``, not counting combining marks: Malayalam -ിന്റെ ("of") has two."""
    return sum(1 for char in text if not unicodedata.category(char).startswith("M"))


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def close_spelling(word: str, stem: str) -> bool:
    """True when some part of ``word`` near its start is one or two edits from ``stem``.

    Stems of up to 6 letters allow one edit; longer stems allow two.
    """
    if len(stem) < _STEM_MIN or len(word) < 3:
        return False
    limit = 1 if len(stem) <= 6 else 2
    for offset in range(_MAX_OFFSET + 1):
        for length in (len(stem) - 1, len(stem), len(stem) + 1):
            part = word[offset:offset + length]
            if len(part) == length and _edit_distance(part, stem) <= limit:
                return True
    return False


@dataclass(frozen=True)
class OlName:
    """One MACULA proper name: its family-qualified lemma and English gloss."""

    key: str
    lemma: str
    gloss: str


def ol_names_by_verse(analysis: OlAnalysis, family: str, books: Iterable[str]) -> tuple[dict[VerseRef, set[str]], dict[str, OlName]]:
    """MACULA proper names per original-language verse, in MACULA's own numbering."""
    by_verse: dict[VerseRef, set[str]] = defaultdict(set)
    glosses: dict[str, Counter] = defaultdict(Counter)
    wanted = set(books)
    for reference, ol_words in analysis.verses(family).items():
        if reference.book not in wanted:
            continue
        for word in ol_words:
            for segment in word.segments:
                if segment.get("type") != "proper" or not segment.get("lemma"):
                    continue
                lemma = unicodedata.normalize("NFC", segment["lemma"])
                key = f"{family}:{lemma}"
                glosses[key][str(segment.get("gloss") or "").strip()] += 1
                by_verse[reference].add(key)
    names = {
        key: OlName(key, key.partition(":")[2], min(counts, key=lambda gloss: (-counts[gloss], gloss)))
        for key, counts in glosses.items()
    }
    return dict(by_verse), names


@dataclass(frozen=True)
class NameRendering:
    """What the WIP does with one name: its stems, the words carrying them, and how often they appear."""

    name: OlName
    verse_count: int
    stems: tuple[str, ...]
    offsets: tuple[tuple[int, ...], ...]  # where each stem starts in the name's words
    forms: tuple[tuple[str, int], ...]
    coverage: float

    @property
    def established(self) -> bool:
        """True when the stems cover enough of the name's verses for a missing one to mean something."""
        return bool(self.stems) and self.verse_count >= MIN_NAME_VERSES and self.coverage >= MIN_COVERAGE

    @property
    def strong(self) -> bool:
        """True when the rendering is consistent enough to identify the name wherever it appears."""
        return self.established and self.verse_count >= STRONG_VERSES and self.coverage >= STRONG_COVERAGE


@dataclass(frozen=True)
class NameCandidate:
    """One verse whose original-language text has a name the WIP verse does not visibly render."""

    reference: str
    name: OlName
    kind: str
    rendering: tuple[str, ...]
    words: tuple[str, ...]
    other_names: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Serializable form."""
        return {
            "wip_reference": self.reference,
            "name_key": self.name.key,
            "lemma": self.name.lemma,
            "gloss": self.name.gloss,
            "kind": self.kind,
            "usual_rendering": list(self.rendering),
            "verse_words": list(self.words),
            "other_names": list(self.other_names),
        }

    def question(self) -> str:
        """The candidate as a question for the model."""
        name = f"{self.name.gloss} ({self.name.lemma})" if self.name.gloss else self.name.lemma
        usual = ", ".join(self.rendering) or "none learned"
        if self.kind == "VARIANT":
            found = f"it has {', '.join(self.words)}, spelled differently from the usual rendering ({usual})"
        elif self.kind == "SUBSTITUTION":
            found = f"it has {', '.join(self.words)}, which the WIP uses for {', '.join(self.other_names)}"
        else:
            found = f"none of the usual renderings ({usual}) appear"
        return (
            f"The original-language verse names {name}; {found}. Is the name rendered inconsistently, "
            "replaced, or left out? A pronoun or restructured sentence that keeps the meaning is not a finding."
        )


class NameModel:
    """Name renderings learned from one WIP, with the candidate check for any of its verses."""

    def __init__(
        self,
        verses: Mapping[str, str],
        occurrences: Mapping[str, Iterable[str]],
        names: Mapping[str, OlName],
        *,
        iterations: int = EM_ITERATIONS,
    ) -> None:
        """Align the names of every verse in ``occurrences`` with that verse's WIP words.

        ``verses`` maps every WIP verse reference to its text; ``occurrences`` maps a WIP verse to the names in
        its original-language verses.
        """
        self.names = dict(names)
        all_words = {ref: words(text) for ref, text in verses.items()}
        self.unspaced = is_unspaced(verses.values())
        self.word_counts = Counter(word for ws in all_words.values() for word in ws)
        self.occurrences = {ref: sorted(set(keys)) for ref, keys in occurrences.items() if ref in verses and keys}
        self.verse_words = {ref: sorted(set(all_words[ref])) for ref in self.occurrences}
        units = {ref: set().union(*(stems(w, unspaced=self.unspaced) for w in ws)) if ws else set() for ref, ws in all_words.items()}
        document_frequency = Counter(unit for unit_set in units.values() for unit in unit_set)
        # Hebrew and Greek lemmas of one person share a WIP spelling (Moses), so a stem's precision is
        # measured among the verses of the name's own testament.
        testament_frequency: dict[str, Counter] = defaultdict(Counter)
        testament_total: Counter = Counter()
        for ref, unit_set in units.items():
            family = ol_family_for_book(ref.partition(" ")[0]) or ""
            testament_frequency[family].update(unit_set)
            testament_total[family] += 1
        name_verses: dict[str, list[str]] = defaultdict(list)
        for ref, keys in self.occurrences.items():
            for key in keys:
                name_verses[key].append(ref)
        probability = self._align(units, document_frequency, iterations)
        self.renderings: dict[str, NameRendering] = {}
        self._all_forms: dict[str, Counter] = {}
        for key, refs in name_verses.items():
            family = key.partition(":")[0]
            self.renderings[key] = self._rendering(
                key, refs, units, probability.get(key, {}), testament_frequency[family], testament_total[family]
            )
        self.suffixes = self._learn_suffixes()
        self._bases = {key: self._inflection_bases(forms) for key, forms in self._all_forms.items()}
        # The words each strong name is written with: a word counts when most WIP verses using it have the
        # name, so a common word that merely shares a stem ("сина", son, against Sinai) does not.
        verse_count = Counter(word for ws in self.verse_words.values() for word in ws)
        self._strong_words: dict[str, set[str]] = defaultdict(set)
        for key, forms in self._all_forms.items():
            if self.renderings[key].strong:
                for word, count in forms.items():
                    if count >= 2 and count / verse_count[word] >= MIN_STEM_PRECISION:
                        self._strong_words[word].add(key)

    def _align(self, units: Mapping[str, set[str]], document_frequency: Counter, iterations: int) -> dict[str, dict[str, float]]:
        """IBM Model 1 restricted to names: p(stem | name), with a NULL word absorbing the other words."""
        corpus = [
            (keys, [unit for unit in units[ref] if document_frequency[unit] >= 2])
            for ref, keys in self.occurrences.items()
        ]
        table: dict[tuple[str, str], float] = defaultdict(lambda: 1e-3)
        null_weight = 1e-3
        for _ in range(iterations):
            counts: dict[tuple[str, str], float] = defaultdict(float)
            totals: dict[str, float] = defaultdict(float)
            for keys, verse_units in corpus:
                for unit in verse_units:
                    z = sum(table[(key, unit)] for key in keys) + null_weight
                    for key in keys:
                        share = table[(key, unit)] / z
                        counts[(key, unit)] += share
                        totals[key] += share
            table = defaultdict(lambda: 1e-9, {pair: value / totals[pair[0]] for pair, value in counts.items()})
        best: dict[str, float] = defaultdict(float)
        for (key, _), value in table.items():
            best[key] = max(best[key], value)
        # The overlapping prefixes of one word share its probability, so the bar is relative to the best stem.
        result: dict[str, dict[str, float]] = defaultdict(dict)
        for (key, unit), value in table.items():
            if value >= RELATIVE_STEM_PROBABILITY * best[key]:
                result[key][unit] = value
        return result

    def _rendering(
        self,
        key: str,
        refs: Sequence[str],
        units: Mapping[str, set[str]],
        probability: Mapping[str, float],
        document_frequency: Counter,
        total: int,
    ) -> NameRendering:
        """Choose the stems that identify one name, greedily by alignment probability."""
        inside = Counter(unit for ref in refs for unit in units[ref])
        outside_total = max(1, total - len(refs))
        chosen: list[str] = []
        covered: set[str] = set()
        min_gain = max(2, math.ceil(0.05 * len(refs)))
        for unit, _ in sorted(probability.items(), key=lambda item: (-item[1], -len(item[0]), item[0])):
            background = (document_frequency[unit] - inside[unit]) / outside_total
            precision = inside[unit] / document_frequency[unit]
            if inside[unit] < 2 or precision < (MIN_RARE_STEM_PRECISION if background <= MAX_BACKGROUND_RATE else MIN_STEM_PRECISION):
                continue
            if any(unit.startswith(other) for other in chosen):
                continue  # a longer form of a chosen stem adds nothing
            # A shorter stem replaces the chosen stems it is a prefix of when it covers more verses (Ісус
            # covers Ісуса and Ісусові); otherwise the longer stem stays, so misspellings remain visible.
            kept = [other for other in chosen if not other.startswith(unit)]
            gain = {ref for ref in refs if unit in units[ref]} - covered
            if len(gain) < min_gain:
                continue
            before = {ref for ref in refs if any(other in units[ref] for other in kept)}
            unit = self._extend(unit, refs, units, inside)
            chosen = [*kept, unit]
            covered = before | {ref for ref in refs if unit in units[ref]}
        forms: Counter = Counter()
        starts: dict[str, Counter] = {unit: Counter() for unit in chosen}
        for ref in refs:
            for word in self.verse_words[ref]:
                hits = [unit for unit in chosen if carries(word, unit, unspaced=self.unspaced)]
                if hits:
                    forms[word] += 1
                for unit in hits:
                    starts[unit][word.find(unit)] += 1
        # A stem matches only where it starts in the name's own words: Abraham's stem "раам" (from "авраам")
        # must not match Raamah ("раама").
        offsets = tuple(
            tuple(sorted(offset for offset, count in starts[unit].items() if count >= max(2, 0.1 * sum(starts[unit].values()))))
            or (starts[unit].most_common(1)[0][0] if starts[unit] else 0,)
            for unit in chosen
        )
        self._all_forms[key] = forms
        return NameRendering(
            name=self.names[key],
            verse_count=len(refs),
            stems=tuple(chosen),
            offsets=offsets,
            forms=tuple(sorted(forms.items(), key=lambda item: (-item[1], item[0]))[:8]),
            coverage=round(len(covered) / len(refs), 3) if refs else 0.0,
        )

    def _learn_suffixes(self) -> frozenset[str]:
        """Word endings that alternate in the forms of many names: the WIP's inflection (Яків, Якова, Якову)."""
        if self.unspaced:
            return frozenset()
        names_with: dict[str, set[str]] = defaultdict(set)
        for key, forms in self._all_forms.items():
            if not self.renderings[key].established:
                continue
            words_ = sorted(forms)
            for i, first in enumerate(words_):
                for second in words_[i + 1:]:
                    k = 0
                    while k < min(len(first), len(second)) and first[k] == second[k]:
                        k += 1
                    if k >= 3 and _letters(first[k:]) <= SUFFIX_MAX and _letters(second[k:]) <= SUFFIX_MAX:
                        names_with[first[k:]].add(key)
                        names_with[second[k:]].add(key)
        return frozenset(suffix for suffix, keys in names_with.items() if len(keys) >= SUFFIX_MIN_NAMES)

    def _inflection_bases(self, forms: Mapping[str, int]) -> frozenset[str]:
        """Each form of a name with a learned ending removed."""
        return frozenset(
            form[:k]
            for form in forms
            for k in range(3, len(form) + 1)
            if form[k:] in self.suffixes
        )

    def _inflects(self, key: str, word: str) -> bool:
        """True when ``word`` is a form of the name with another learned ending."""
        bases = self._bases.get(key, frozenset())
        return any(word[:k] in bases and word[k:] in self.suffixes for k in range(3, len(word) + 1))

    @staticmethod
    def _extend(unit: str, refs: Sequence[str], units: Mapping[str, set[str]], inside: Counter) -> str:
        """The longest stem starting with ``unit`` that covers all but a few of the verses ``unit`` covers.

        Alignment favours the stem that covers every verse, including a verse that misspells the name;
        a longer stem that leaves out a few verses keeps those verses visible as candidates.
        """
        covered = sum(1 for ref in refs if unit in units[ref])
        tolerance = max(1, math.floor(EXTEND_TOLERANCE * covered))
        best = unit
        for other, count in inside.items():
            if len(other) > len(best) and other.startswith(unit) and count >= covered - tolerance:
                best = other
        return best

    def _rendered(self, key: str, verse_words: Sequence[str]) -> set[str]:
        """The verse words that carry one of a name's stems."""
        rendering = self.renderings.get(key)
        if rendering is None:
            return set()
        return {
            word
            for word in verse_words
            if any(carries(word, unit, unspaced=self.unspaced, offsets=at) for unit, at in zip(rendering.stems, rendering.offsets))
            or self._inflects(key, word)
        }

    def _strong_names_in(self, verse_words: Sequence[str]) -> dict[str, set[str]]:
        """Strong names whose usual words appear among ``verse_words``, with those words."""
        found: dict[str, set[str]] = defaultdict(set)
        for word in verse_words:
            for key in self._strong_words.get(word, ()):
                found[key].add(word)
        return found

    def status(self, reference: str) -> dict[str, str]:
        """``OK``, ``NOT_CHECKED``, or a candidate kind for each name in one WIP verse."""
        return {key: kind for key, kind, _ in self._classify(reference)}

    def _classify(self, reference: str) -> list[tuple[str, str, NameCandidate | None]]:
        """Classify every name of one verse."""
        keys = self.occurrences.get(reference, [])
        verse_words = self.verse_words.get(reference, [])
        explained = set().union(*(self._rendered(key, verse_words) for key in keys)) if keys else set()
        rows: list[tuple[str, str, NameCandidate | None]] = []
        for key in keys:
            rendering = self.renderings[key]
            if not rendering.established:
                rows.append((key, "NOT_CHECKED", None))
                continue
            if self._rendered(key, verse_words):
                rows.append((key, "OK", None))
                continue
            loose = [word for word in verse_words if word not in explained]
            family = key.partition(":")[0]
            substitutes = {
                other: found
                for other, found in self._strong_names_in(loose).items()
                if other not in keys and other.partition(":")[0] == family
            }
            others = sorted(substitutes)
            variants = [
                word
                for word in loose
                if self.word_counts[word] <= RARE_WORD_COUNT
                and not self.unspaced
                and any(close_spelling(word, unit) for unit in rendering.stems)
            ]
            kind = "VARIANT" if variants else "SUBSTITUTION" if others else "ABSENT"
            evidence = variants or sorted(set().union(*substitutes.values()))
            rows.append((
                key,
                kind,
                NameCandidate(
                    reference=reference,
                    name=rendering.name,
                    kind=kind,
                    # In unspaced scripts a "word" is a whole phrase, so the stems are what the name looks like.
                    rendering=rendering.stems[:4] if self.unspaced else tuple(form for form, _ in rendering.forms[:4]),
                    words=tuple(evidence[:4]),
                    other_names=tuple(self.renderings[other].name.gloss or self.renderings[other].name.lemma for other in others[:3]),
                ),
            ))
        return rows

    def candidates(self, references: Iterable[str], *, kinds: Sequence[str] = CANDIDATE_KINDS) -> list[NameCandidate]:
        """Candidates of the requested kinds in the given WIP verses, in verse order.

        ``ABSENT`` counts only for names the WIP renders in at least ABSENT_MIN_COVERAGE of their verses.
        """
        rows = []
        for reference in references:
            for key, kind, candidate in self._classify(reference):
                if candidate is None or kind not in kinds:
                    continue
                if kind == "ABSENT" and self.renderings[key].coverage < ABSENT_MIN_COVERAGE:
                    continue
                rows.append(candidate)
        return rows


def wip_name_occurrences(
    analysis: OlAnalysis,
    family: str,
    books: Iterable[str],
    locate: Callable[[VerseRef], Iterable[str]],
) -> tuple[dict[str, set[str]], dict[str, OlName]]:
    """MACULA names per WIP verse; ``locate`` maps a MACULA (canonical) verse to the WIP verses holding it."""
    by_verse, names = ol_names_by_verse(analysis, family, books)
    occurrences: dict[str, set[str]] = defaultdict(set)
    for reference, keys in by_verse.items():
        for local in locate(reference):
            occurrences[local] |= keys
    return dict(occurrences), names


def wip_name_candidate_table(
    analysis: OlAnalysis,
    records: Sequence[Any],
    records_for_canonical: Callable[[Iterable[VerseRef]], Sequence[Any]],
    cache_dir: Path | None = None,
) -> dict[str, list[dict[str, object]]]:
    """Name candidates for every verse of one WIP, keyed by WIP reference.

    ``records`` are the WIP's verse records across all its books (``reference`` and ``payload["body_text"]``);
    ``records_for_canonical`` is the WIP verse index lookup. Alignment takes about half a minute for a whole
    Bible, so the table is cached in ``cache_dir`` under a digest of the aligner version, the package, and
    the WIP text and numbering it was built from.
    """
    verses = {record.reference: str(record.payload.get("body_text") or "") for record in records}
    books = {record.book for record in records}
    occurrences: dict[str, set[str]] = defaultdict(set)
    names: dict[str, OlName] = {}
    for family in ("HEB", "GRK"):
        found, family_names = wip_name_occurrences(
            analysis,
            family,
            books,
            lambda ref: [record.reference for record in records_for_canonical((ref,))],
        )
        for reference, keys in found.items():
            occurrences[reference] |= keys
        names.update(family_names)
    digest = hashlib.sha256(
        json.dumps(
            {
                "aligner": NAME_ALIGNER_VERSION,
                "package": analysis.package_id,
                "verses": sorted(verses.items()),
                "occurrences": sorted((ref, sorted(keys)) for ref, keys in occurrences.items()),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    cache_path = cache_dir / f"{digest}.json" if cache_dir is not None else None
    if cache_path is not None and cache_path.is_file():
        try:
            return dict(json.loads(cache_path.read_text(encoding="utf-8"))["candidates"])
        except (OSError, ValueError, KeyError):
            pass  # rebuild a damaged cache entry
    model = NameModel(verses, occurrences, names)
    table: dict[str, list[dict[str, object]]] = {}
    for candidate in model.candidates(sorted(model.occurrences), kinds=STC_CANDIDATE_KINDS):
        row = candidate.to_dict()
        row["question"] = candidate.question()
        table.setdefault(candidate.reference, []).append(row)
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(cache_path, {"aligner": NAME_ALIGNER_VERSION, "package": analysis.package_id, "candidates": table})
    return table
