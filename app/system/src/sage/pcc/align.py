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

Every link also names the original-language **segment** it renders (``Link.key``): a BSB chunk such as
*and the earth* links three tokens to one Hebrew word, and the direct model's table assigns each token to the
word's segment that explains it best (conjunction, article, noun). An unlinked token keeps a **hint**: the
word and segment the direct model prefers for it, used only to extend a realization over an adjacent token of
the same word (P5b-2); a hint is never a link. Alignments are cached on disk by ``cache_key``.
"""

from __future__ import annotations

import difflib
import gzip
import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..ol_analysis import OlAnalysis, ol_family_for_book
from ..vrs import VerseRef, VersificationSchema
from .discovery import SourceUnit
from .segment import Token, measure_elisions, split_elisions, tokenize

ALIGNER_VERSION = "3"
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
    content: bool = False  # noun, verb, adjective or adverb segment


@dataclass(frozen=True)
class Link:
    """One reference token linked to one original-language word."""

    token: int
    ol_ref: str
    method: str
    score: float
    key: str = ""  # the segment of ``ol_ref`` this token renders ("" when the model cannot tell)


@dataclass
class Alignment:
    """Links per unit, the tokens they index, and counts per method."""

    tokens: dict[str, list[Token]]
    links: dict[str, list[Link]]
    stats: dict[str, int] = field(default_factory=dict)
    hints: dict[str, dict[int, tuple[str, str, float]]] = field(default_factory=dict)  # unit -> token -> (word, key, posterior)


def _label(label: str) -> VerseRef:
    """Parse ``BOOK C:V``."""
    book, _, cv = label.partition(" ")
    chapter, _, verse = cv.partition(":")
    return VerseRef(book, int(chapter), int(verse))


CONTENT_POS = frozenset({"noun", "verb", "adjective", "adj", "adverb", "adv"})


def segment_key(family: str, segment: Mapping[str, str]) -> str:
    """Vocabulary key of one MACULA segment: ``GRK:4151`` (Strong's digits), else ``HEB:<lemma>``.

    MACULA's Hebrew numbers are augmented: the article is ``1886a`` while the name Dothan is ``1886``, the
    prefix *b-* is ``0871a`` while the name Atharim is ``0871``. A non-content segment (prefix, suffix,
    particle, pronoun) keeps its letter, so it never shares a key with a name or noun; a content segment keeps
    the digits only, so homographs (``0218a`` / ``0218``) stay one key, as Biblical Terms numbers them.
    """
    number = re.search(r"(\d+)([a-z]?)", segment.get("strong") or "")
    if not number:
        return f"{family}:{segment.get('lemma', '')}"
    letter = number.group(2) if (segment.get("pos") or "") not in CONTENT_POS else ""
    return f"{family}:{int(number.group(1))}{letter}"


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
                        items.append(OlToken(word.word_id, segment_key(family, segment),
                                             (segment.get("pos") or "") in CONTENT_POS))
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
                found.append(Link(i, fs[j].ref, "direct", round(posterior, 6), fs[j].key))
        if found:
            links[unit] = found
    return links


def reference_tokens(units: Sequence[SourceUnit], *, cased: bool = True,
                     letter_marks: Iterable[str] = ()) -> dict[str, list[Token]]:
    """Tokens per unit as the aligner sees them: elided prefixes split where the text shows them (§5b.3 #4)."""
    marks = tuple(letter_marks)
    tokens = {u.unit_id: tokenize(u.text, cased=cased, letter_marks=marks) for u in units}
    prefixes = measure_elisions(tokens.values(), marks)
    return {unit: split_elisions(items, prefixes, marks) for unit, items in tokens.items()} if prefixes else tokens


def _segment_for(token: str, segments: Sequence[OlToken], model: DirectModel) -> str:
    """The segment of one word that best explains ``token`` ("" on a tie at zero, e.g. an unseen token)."""
    if len(segments) == 1:
        return segments[0].key
    scores = [(model.e_given_f.get((token, s.key), 0.0), -i) for i, s in enumerate(segments)]
    best = max(scores)
    return segments[-best[1]].key if best[0] > 0 else ""


def _hints(es: Sequence[str], fs: Sequence[OlToken], linked: set[int], model: DirectModel,
           lam: float) -> dict[int, tuple[str, str, float]]:
    """For unlinked tokens: the word and segment the direct model prefers over NULL, with its posterior."""
    found: dict[int, tuple[str, str, float]] = {}
    size_e, size_f = len(es), len(fs)
    for i, e in enumerate(es):
        if i in linked:
            continue
        scores = [model.e_given_f.get((e, f.key), 0.0) * _prior(i, size_e, j, size_f, lam) for j, f in enumerate(fs)]
        j = max(range(size_f), key=scores.__getitem__)
        null = model.e_given_f.get((e, _NULL), 0.0) * 0.5
        if scores[j] > null:
            found[i] = (fs[j].ref, fs[j].key, round(scores[j] / (sum(scores) + null), 6))
    return found


def align_reference(units: Sequence[SourceUnit], analysis: OlAnalysis, schema: VersificationSchema, *,
                    bsb_alignment: Mapping[str, object] | None, cased: bool = True, letter_marks: Iterable[str] = (),
                    lam: float = DEFAULT_LAMBDA, threshold: float = DEFAULT_THRESHOLD) -> Alignment:
    """Align a whole reference: the BSB path first, the direct path for tokens it leaves open."""
    marks = tuple(letter_marks)
    tokens = reference_tokens(units, cased=cased, letter_marks=marks)
    ol = ol_tokens_for_units(units, analysis, schema)
    via = align_via_bsb(units, tokens, bsb_index(bsb_alignment), cased=cased, letter_marks=marks) if bsb_alignment else {}
    model = train_direct(tokens, ol)
    direct = align_direct(tokens, ol, model, lam=lam, threshold=threshold)
    links: dict[str, list[Link]] = {}
    hints: dict[str, dict[int, tuple[str, str, float]]] = {}
    for unit in units:
        uid = unit.unit_id
        fs = ol.get(uid, ())
        by_word: dict[str, list[OlToken]] = defaultdict(list)
        for f in fs:
            by_word[f.ref].append(f)
        norms = [t.norm for t in tokens[uid]]
        chosen: dict[int, Link] = {}
        for link in direct.get(uid, ()):
            chosen[link.token] = link
        for link in via.get(uid, ()):
            key = _segment_for(norms[link.token], by_word.get(link.ol_ref, ()), model) if by_word.get(link.ol_ref) else ""
            chosen[link.token] = Link(link.token, link.ol_ref, link.method, link.score, key)
        if chosen:
            links[uid] = [chosen[i] for i in sorted(chosen)]
        if fs and norms:
            found = _hints(norms, fs, set(chosen), model, lam)
            if found:
                hints[uid] = found
    stats = {"tokens": sum(len(v) for v in tokens.values()),
             **{method: sum(1 for v in links.values() for l in v if l.method == method) for method in METHODS}}
    return Alignment(tokens, links, stats, hints)


def cache_key(reference_sha256: str, *package_ids: str) -> str:
    """Key for a cached alignment: reference content, original-language packages and aligner version."""
    return hashlib.sha256("|".join((ALIGNER_VERSION, reference_sha256, *package_ids)).encode("utf-8")).hexdigest()


def reference_sha256(units: Iterable[SourceUnit]) -> str:
    """Content hash of a reference as aligned: unit ids, references and text, in order."""
    digest = hashlib.sha256()
    for unit in units:
        digest.update("\x1f".join((unit.unit_id, *unit.native_refs, unit.text)).encode("utf-8") + b"\x1e")
    return digest.hexdigest()


class AlignmentCache:
    """Alignments on disk (``<folder>/<cache_key>.json.gz``); tokens are rebuilt from the units, never stored."""

    def __init__(self, folder: Path):
        """Use ``folder`` (created on first write)."""
        self.folder = Path(folder)

    def _path(self, key: str) -> Path:
        """File of one cache entry."""
        return self.folder / f"{key}.json.gz"

    def get(self, key: str, units: Sequence[SourceUnit], *, cased: bool,
            letter_marks: Iterable[str]) -> Alignment | None:
        """The cached alignment for ``key``, or None (absent or unreadable: realign, never fatal)."""
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            record = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
            links = {u: [Link(t, r, m, s, k) for t, r, m, s, k in rows] for u, rows in record["links"].items()}
            hints = {u: {int(t): (r, k, float(p)) for t, r, k, p in rows} for u, rows in record["hints"].items()}
            stats = dict(record["stats"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return Alignment(reference_tokens(units, cased=cased, letter_marks=letter_marks), links, stats, hints)

    def put(self, key: str, alignment: Alignment) -> Path:
        """Store ``alignment`` under ``key`` (deterministic bytes)."""
        record = {
            "aligner_version": ALIGNER_VERSION,
            "stats": alignment.stats,
            "links": {u: [[l.token, l.ol_ref, l.method, l.score, l.key] for l in v] for u, v in sorted(alignment.links.items())},
            "hints": {u: [[t, r, k, p] for t, (r, k, p) in sorted(v.items())] for u, v in sorted(alignment.hints.items())},
        }
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(gzip.compress(json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8"), mtime=0))
        tmp.replace(path)
        return path


def cached_alignment(units: Sequence[SourceUnit], analysis: OlAnalysis, schema: VersificationSchema, *,
                     bsb_alignment: Mapping[str, object] | None, package_ids: Sequence[str],
                     cache: AlignmentCache | None, cased: bool = True, letter_marks: Iterable[str] = (),
                     lam: float = DEFAULT_LAMBDA, threshold: float = DEFAULT_THRESHOLD) -> tuple[Alignment, bool]:
    """Return (alignment, came from cache). The key covers text, packages, settings and the aligner version."""
    marks = tuple(letter_marks)
    key = cache_key(reference_sha256(units), *package_ids, schema_label(schema), f"cased={cased}",
                    f"marks={''.join(marks)}", f"lam={lam}", f"threshold={threshold}")
    if cache is not None:
        found = cache.get(key, units, cased=cased, letter_marks=marks)
        if found is not None:
            return found, True
    alignment = align_reference(units, analysis, schema, bsb_alignment=bsb_alignment, cased=cased,
                                letter_marks=marks, lam=lam, threshold=threshold)
    if cache is not None:
        cache.put(key, alignment)
    return alignment, False


def schema_label(schema: VersificationSchema) -> str:
    """Identity of a versification schema for cache keys."""
    return f"{schema.schema_id}>{schema.canonical_id}:{len(schema.mappings)}"
