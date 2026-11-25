"""Word alignment of a reference text to the original language (plan §5b.7 step 1, P5b-0).

Every reference token gets at most one link to a MACULA word (``ref``, e.g. ``JHN 1:1!5``), by the best
method available:

1. **Through the BSB** (``SAGE_PCC_OL`` gold alignment). The reference verse's tokens are matched in order
   against the BSB English of the same verse, each BSB token carrying the MACULA word it renders. A verse
   in which every BSB token is found in order is the BSB itself: its links are ``gold``. Otherwise matched tokens
   inherit the BSB token's word as ``transitive`` links (an English reference such as the NIV, from which
   the BSB derives).
2. **Direct** (any language). IBM Model 1 with a relative-position prior, trained in both directions over
   the whole reference; a link is kept only when both directions choose it and its posterior reaches
   ``threshold``. Hebrew prefix and suffix segments are separate original-language tokens.

Unlinked tokens stay unlinked: nothing is guessed. No language resource or model is used: alignment is
learned from the texts (plan D11).
"""

from __future__ import annotations

import difflib
import hashlib
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from ..ol_analysis import OlAnalysis, ol_family_for_book
from ..vrs import VerseRef, VersificationSchema
from .discovery import SourceUnit
from .segment import Token, tokenize

ALIGNER_VERSION = "1"
METHODS = ("gold", "transitive", "direct")
DEFAULT_LAMBDA = 8.0
DEFAULT_THRESHOLD = 0.6  # measured 2026-11-25: Greek 94.2% / Hebrew 91.6% precision at 73% word coverage
DEFAULT_ITERATIONS = 6
_NULL = "\0NULL"


@dataclass(frozen=True)
class OlToken:
    """One original-language segment: the word it belongs to and its vocabulary key."""

    ref: str      # MACULA word ref
    key: str      # "GRK:3056" (Strong's digits) or "HEB:lemma" when no number


@dataclass(frozen=True)
class Link:
    """One reference token linked to one original-language word."""

    token: int
    ol_ref: str
    method: str
    score: float


@dataclass
class Alignment:
    """Links per unit, the tokens they index, and counts per method."""

    tokens: dict[str, list[Token]]
    links: dict[str, list[Link]]
    stats: dict[str, int] = field(default_factory=dict)


def _label(label: str) -> VerseRef:
    """Parse ``BOOK C:V``."""
    book, _, cv = label.partition(" ")
    chapter, _, verse = cv.partition(":")
    return VerseRef(book, int(chapter), int(verse))


def ol_tokens_for_units(units: Iterable[SourceUnit], analysis: OlAnalysis,
                        schema: VersificationSchema) -> dict[str, list[OlToken]]:
    """Original-language segments per unit, through versification, in MACULA order."""
    found: dict[str, list[OlToken]] = {}
    for unit in units:
        family = ol_family_for_book(unit.canonical_ref.split(" ")[0])
        if family is None:
            continue
        table = analysis.verses(family)
        seen: set[VerseRef] = set()
        items: list[OlToken] = []
        for label in unit.native_refs:
            for canonical in sorted(schema.local_to_canonical(_label(label)), key=lambda r: (r.chapter, r.verse)):
                if canonical in seen:
                    continue
                seen.add(canonical)
                for word in table.get(canonical, ()):
                    for segment in word.segments:
                        number = re.search(r"\d+", segment.get("strong") or "")
                        key = f"{family}:{int(number.group())}" if number else f"{family}:{segment.get('lemma', '')}"
                        items.append(OlToken(word.word_id, key))
        if items:
            found[unit.unit_id] = items
    return found


def bsb_index(bsb_alignment: Mapping[str, object]) -> dict[str, list[tuple[int, str, str]]]:
    """BSB verse -> [(position, MACULA word ref, English)] for rendered chunks, in BSB order."""
    index: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for ol_ref, link in bsb_alignment.items():
        if link.order > 0:
            index[link.bsb_ref].append((link.order, ol_ref, link.english))
    for chunks in index.values():
        chunks.sort()
    return dict(index)


def _stream(unit: SourceUnit, index: Mapping[str, list[tuple[int, str, str]]], *, cased: bool,
            letter_marks: Iterable[str]) -> list[tuple[str, str]]:
    """The BSB tokens of the unit's verses, each with the MACULA word it renders."""
    out: list[tuple[str, str]] = []
    for label in unit.native_refs:
        for _, ol_ref, english in index.get(label, ()):
            out += [(t.norm, ol_ref) for t in tokenize(english, cased=cased, letter_marks=letter_marks)]
    return out


def align_via_bsb(units: Sequence[SourceUnit], tokens: Mapping[str, Sequence[Token]],
                  index: Mapping[str, list[tuple[int, str, str]]], *, cased: bool = True,
                  letter_marks: Iterable[str] = ()) -> dict[str, list[Link]]:
    """Path 1: ordered token matching against the BSB of the same verse."""
    links: dict[str, list[Link]] = {}
    for unit in units:
        stream = _stream(unit, index, cased=cased, letter_marks=letter_marks)
        mine = [t.norm for t in tokens.get(unit.unit_id, ())]
        if not stream or not mine:
            continue
        theirs = [norm for norm, _ in stream]
        matcher = difflib.SequenceMatcher(None, mine, theirs, autojunk=False)
        blocks = matcher.get_matching_blocks()
        # Every BSB token found in order: this verse is the BSB (extra tokens are words the BSB supplies
        # without an original-language counterpart, which the tables do not list).
        method = "gold" if sum(block.size for block in blocks) == len(theirs) else "transitive"
        found = [Link(block.a + k, stream[block.b + k][1], method, 1.0) for block in blocks for k in range(block.size)]
        if found:
            links[unit.unit_id] = found
    return links


def _em(pairs: Sequence[tuple[Sequence[str], Sequence[str]]], iterations: int) -> dict[tuple[str, str], float]:
    """IBM Model 1: t(e | f) over sentence pairs (e tokens, f tokens), with a NULL source."""
    t: dict[tuple[str, str], float] = defaultdict(lambda: 1.0)
    for _ in range(iterations):
        count: dict[tuple[str, str], float] = defaultdict(float)
        total: dict[str, float] = defaultdict(float)
        for es, fs in pairs:
            sources = list(fs) + [_NULL]
            for e in es:
                z = sum(t[(e, f)] for f in sources)
                for f in sources:
                    share = t[(e, f)] / z
                    count[(e, f)] += share
                    total[f] += share
        t = defaultdict(float, {key: value / total[key[1]] for key, value in count.items()})
    return dict(t)


@dataclass
class DirectModel:
    """Both translation tables of the direct path."""

    e_given_f: dict[tuple[str, str], float]
    f_given_e: dict[tuple[str, str], float]


def train_direct(tokens: Mapping[str, Sequence[Token]], ol: Mapping[str, Sequence[OlToken]],
                 iterations: int = DEFAULT_ITERATIONS) -> DirectModel:
    """Train Model 1 both ways over every unit that has reference and original-language tokens."""
    pairs = [([t.norm for t in tokens[u]], [o.key for o in ol[u]]) for u in sorted(tokens) if tokens[u] and ol.get(u)]
    return DirectModel(_em(pairs, iterations), _em([(f, e) for e, f in pairs], iterations))


def _prior(i: int, size_i: int, j: int, size_j: int, lam: float) -> float:
    """Relative-position prior."""
    return math.exp(-lam * abs((i + 0.5) / size_i - (j + 0.5) / size_j))


def align_direct(tokens: Mapping[str, Sequence[Token]], ol: Mapping[str, Sequence[OlToken]], model: DirectModel, *,
                 lam: float = DEFAULT_LAMBDA, threshold: float = DEFAULT_THRESHOLD) -> dict[str, list[Link]]:
    """Path 2: links both directions agree on, with posterior at least ``threshold``."""
    links: dict[str, list[Link]] = {}
    for unit in sorted(tokens):
        es, fs = [t.norm for t in tokens[unit]], ol.get(unit, ())
        if not es or not fs:
            continue
        size_e, size_f = len(es), len(fs)
        backward: set[tuple[int, int]] = set()
        for j, f in enumerate(fs):
            best, best_score = None, model.f_given_e.get((f.key, _NULL), 0.0) * 0.5
            for i, e in enumerate(es):
                score = model.f_given_e.get((f.key, e), 0.0) * _prior(i, size_e, j, size_f, lam)
                if score > best_score:
                    best, best_score = i, score
            if best is not None:
                backward.add((best, j))
        found = []
        for i, e in enumerate(es):
            scores = [model.e_given_f.get((e, f.key), 0.0) * _prior(i, size_e, j, size_f, lam) for j, f in enumerate(fs)]
            z = sum(scores) + model.e_given_f.get((e, _NULL), 0.0) * 0.5
            j = max(range(size_f), key=scores.__getitem__)
            posterior = scores[j] / z if z else 0.0
            if posterior >= threshold and (i, j) in backward:
                found.append(Link(i, fs[j].ref, "direct", round(posterior, 6)))
        if found:
            links[unit] = found
    return links


def align_reference(units: Sequence[SourceUnit], analysis: OlAnalysis, schema: VersificationSchema, *,
                    bsb_alignment: Mapping[str, object] | None, cased: bool = True, letter_marks: Iterable[str] = (),
                    lam: float = DEFAULT_LAMBDA, threshold: float = DEFAULT_THRESHOLD) -> Alignment:
    """Align a whole reference: the BSB path first, the direct path for tokens it leaves open."""
    marks = tuple(letter_marks)
    tokens = {u.unit_id: tokenize(u.text, cased=cased, letter_marks=marks) for u in units}
    ol = ol_tokens_for_units(units, analysis, schema)
    via = align_via_bsb(units, tokens, bsb_index(bsb_alignment), cased=cased, letter_marks=marks) if bsb_alignment else {}
    direct = align_direct(tokens, ol, train_direct(tokens, ol), lam=lam, threshold=threshold)
    links: dict[str, list[Link]] = {}
    for unit in units:
        chosen = {link.token: link for link in direct.get(unit.unit_id, ())}
        chosen.update({link.token: link for link in via.get(unit.unit_id, ())})
        if chosen:
            links[unit.unit_id] = [chosen[i] for i in sorted(chosen)]
    stats = {"tokens": sum(len(v) for v in tokens.values()),
             **{method: sum(1 for v in links.values() for l in v if l.method == method) for method in METHODS}}
    return Alignment(tokens, links, stats)


def cache_key(reference_sha256: str, *package_ids: str) -> str:
    """Key for a cached alignment: reference content, original-language packages and aligner version."""
    return hashlib.sha256("|".join((ALIGNER_VERSION, reference_sha256, *package_ids)).encode("utf-8")).hexdigest()
