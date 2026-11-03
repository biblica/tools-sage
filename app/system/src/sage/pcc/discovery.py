"""Function A discovery: recurring SOURCE expressions and their occurrences (plan §5 A1-A2).

Pure and deterministic: SOURCE units in, ``expression`` and ``occurrence`` records out. Candidates are
(1) curated index entries, (2) team ``phrases.txt`` lines, (3) normalized 1..N-token n-grams that recur
in at least ``min_occurrences`` distinct verses. Curated and local entries are never pruned, and a local
phrase absent from the SOURCE is reported, never dropped (AT30). Everything found is located in the
actual SOURCE text; an index built on another edition only supplies candidates.

The stoplist is measured from the SOURCE itself (tokens present in a large share of verses), so no
language data is needed. Automatic n-grams do not cross clause punctuation. For an unspaced SOURCE
script automatic n-grams are skipped (a character window is not a word segmenter, doc 02); curated and
local phrases are still matched.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .contracts import SCHEMA_VERSION
from .ids import IdRegistry
from .segment import Token, tokenize
from .traits import WipTraits
from .trie import TokenTrie

STOP_SHARE = 0.15       # a token in this share of verses (and at least STOP_MIN verses) is a stop word
STOP_MIN_VERSES = 20
MIN_UNIGRAM_LETTERS = 3
ORIGIN_RANK = {"LOCAL_INPUT": 0, "AUTHORIZED_REFERENCE": 1, "SOURCE_DISCOVERY": 2}
_JOINERS = frozenset("-‐‑'’ʼ‘")


@dataclass(frozen=True)
class SourceUnit:
    """One SOURCE verse record: identity, references and the visible body text offsets index."""

    unit_id: str
    canonical_ref: str
    native_refs: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class Seed:
    """A phrase to look for: curated (index) or local (phrases.txt)."""

    surface: str
    tokens: tuple[str, ...]
    origin: str
    category: str = "FIXED_PHRASE"
    senses: tuple[dict[str, str], ...] = ()
    line: int | None = None


@dataclass
class Discovery:
    """Result of one discovery pass."""

    expressions: list[dict[str, Any]] = field(default_factory=list)
    occurrences: list[dict[str, Any]] = field(default_factory=list)
    stats: list[dict[str, Any]] = field(default_factory=list)
    unfound: list[Seed] = field(default_factory=list)
    nested_in: dict[str, str] = field(default_factory=dict)
    auto_discovery: str = "RAN"
    stop_tokens: int = 0


def _gap_joins(text: str, left: Token, right: Token) -> bool:
    """True when only whitespace or a hyphen/apostrophe separates two tokens (no clause punctuation)."""
    return all(c.isspace() or c in _JOINERS for c in text[left.end:right.start])


def _chunks(text: str, tokens: Sequence[Token]) -> list[tuple[int, int]]:
    """Index ranges ``[a, b)`` of tokens not separated by clause punctuation."""
    ranges: list[tuple[int, int]] = []
    begin = 0
    for i in range(1, len(tokens)):
        if not _gap_joins(text, tokens[i - 1], tokens[i]):
            ranges.append((begin, i))
            begin = i
    if tokens:
        ranges.append((begin, len(tokens)))
    return ranges


def _letters(norm: str) -> int:
    return sum(1 for c in norm if c.isalpha())


def _category(tokens: tuple[str, ...], origin: str) -> str:
    if len(tokens) == 1:
        return "TERM"
    return "FIXED_PHRASE" if origin != "SOURCE_DISCOVERY" else "COLLOCATION"


def discover(
    units: Iterable[SourceUnit],
    *,
    source_corpus_id: str,
    source_sha256: str,
    traits: WipTraits,
    seeds: Iterable[Seed] = (),
    min_occurrences: int = 2,
    min_tokens: int = 1,
    max_tokens: int = 6,
) -> Discovery:
    """Find and locate expressions in ``units``. ``traits`` are the SOURCE text's measured traits."""
    unit_list = sorted(units, key=lambda u: u.unit_id)
    tokenized: list[tuple[SourceUnit, list[Token]]] = [
        (u, tokenize(u.text, cased=traits.cased, letter_marks=traits.letter_marks, unspaced=traits.unspaced))
        for u in unit_list
    ]
    result = Discovery()

    # Seeds: first by origin rank, then input order; a repeated token sequence keeps the first.
    chosen: dict[tuple[str, ...], Seed] = {}
    for seed in sorted(seeds, key=lambda s: (ORIGIN_RANK[s.origin], s.line or 0, s.surface)):
        chosen.setdefault(seed.tokens, seed)

    # Automatic candidates: level-wise n-gram counts inside clause chunks.
    auto: dict[tuple[str, ...], list[tuple[int, int, int]]] = {}
    if traits.unspaced:
        result.auto_discovery = "SKIPPED_UNSPACED"
    else:
        verse_freq: Counter[str] = Counter()
        for _, toks in tokenized:
            verse_freq.update({t.norm for t in toks})
        threshold = max(STOP_SHARE * len(tokenized), STOP_MIN_VERSES)
        stops = {t for t, c in verse_freq.items() if c >= threshold}
        result.stop_tokens = len(stops)
        chunk_data = [(i, toks, _chunks(u.text, toks)) for i, (u, toks) in enumerate(tokenized)]
        previous: set[tuple[str, ...]] | None = None
        for n in range(1, max_tokens + 1):
            found: dict[tuple[str, ...], list[tuple[int, int, int]]] = defaultdict(list)
            for index, toks, ranges in chunk_data:
                for a, b in ranges:
                    for i in range(a, b - n + 1):
                        gram = tuple(t.norm for t in toks[i:i + n])
                        if previous is not None and (gram[:-1] not in previous or gram[1:] not in previous):
                            continue
                        found[gram].append((index, i, i + n))
            previous = {g for g, hits in found.items() if len(hits) >= min_occurrences}
            if n < min_tokens:
                continue
            for gram, hits in found.items():
                if len({h[0] for h in hits}) < min_occurrences:
                    continue
                if n == 1 and (gram[0] in stops or _letters(gram[0]) < MIN_UNIGRAM_LETTERS):
                    continue
                if n > 1 and (gram[0] in stops or gram[-1] in stops):
                    continue
                auto[gram] = hits
            if not previous:
                break

    trie = TokenTrie()
    for tokens, seed in chosen.items():
        trie.add(tokens, ("SEED", seed))
    occurrences_by_form: dict[tuple[str, ...], list[tuple[int, int, int]]] = {}
    seed_hits: dict[tuple[str, ...], list[tuple[int, int, int]]] = defaultdict(list)
    if len(trie):
        for index, (_, toks) in enumerate(tokenized):
            for match in trie.find_all([t.norm for t in toks]):
                seed_hits[match.key].append((index, match.start, match.end))
    for key, seed in chosen.items():
        hits = seed_hits.get(key, [])
        if hits:
            occurrences_by_form[key] = hits
        else:
            result.unfound.append(seed)
    origin: dict[tuple[str, ...], Seed | None] = {k: chosen[k] for k in occurrences_by_form}
    for gram, hits in auto.items():
        if gram not in occurrences_by_form:
            occurrences_by_form[gram] = hits
            origin[gram] = None

    ids = IdRegistry()
    counts = {k: len(v) for k, v in occurrences_by_form.items()}
    expression_ids: dict[tuple[str, ...], str] = {}
    for key in sorted(occurrences_by_form, key=lambda k: " ".join(k)):
        hits = occurrences_by_form[key]
        seed = origin[key]
        form = " ".join(key)
        eid = ids.mint("expression", {"source": source_sha256, "form": form})
        expression_ids[key] = eid
        spans = Counter(
            tokenized[i][0].text[tokenized[i][1][a].start:tokenized[i][1][b - 1].end] for i, a, b in hits
        )
        surface = seed.surface if seed else sorted(spans, key=lambda s: (-spans[s], s))[0]
        sense_id = ids.mint("sense", {"expression": eid, "sense": "UNASSESSED"})
        senses = [dict(s) for s in seed.senses] if seed and seed.senses else [
            {"sense_id": sense_id, "label": "unassessed wording", "discriminator": "no sense evidence assessed yet",
             "review_state": "CURATED" if seed and seed.origin == "AUTHORIZED_REFERENCE" else "PROVISIONAL"}
        ]
        result.expressions.append({
            "schema_version": SCHEMA_VERSION,
            "expression_id": eid,
            "source_corpus_id": source_corpus_id,
            "source_surface": surface,
            "normalized_source_form": form,
            "origin": seed.origin if seed else "SOURCE_DISCOVERY",
            "category": seed.category if seed else _category(key, "SOURCE_DISCOVERY"),
            "senses": senses,
        })
        verses: dict[str, str] = {}
        books: Counter[str] = Counter()
        for i, a, b in sorted(hits):
            unit, toks = tokenized[i]
            start, end = toks[a].start, toks[b - 1].end
            result.occurrences.append({
                "schema_version": SCHEMA_VERSION,
                "occurrence_id": ids.mint("occurrence", {
                    "source": source_sha256, "ref": unit.canonical_ref, "span": [start, end], "expression": eid}),
                "expression_id": eid,
                "source_corpus_id": source_corpus_id,
                "source_corpus_sha256": source_sha256,
                "source_unit_id": unit.unit_id,
                "canonical_ref": unit.canonical_ref,
                "native_refs": list(unit.native_refs),
                "body_start": start,
                "body_end": end,
                "offset_units": "UNICODE_CODE_POINT",
                "source_text_span": unit.text[start:end],
                "sense_id": None,
                "sense_state": "UNRESOLVED",
                "sense_evidence": [],
            })
            verses.setdefault(unit.unit_id, unit.canonical_ref)
            books[unit.canonical_ref.split(" ")[0]] += 1
        examples = [verses[u] for u in sorted(verses)][:3]
        result.stats.append({
            "expression_id": eid,
            "origin": seed.origin if seed else "SOURCE_DISCOVERY",
            "token_count": len(key),
            "occurrences": len(hits),
            "distinct_verses": len(verses),
            "books": dict(sorted(books.items())),
            "examples": examples,
            "local_line": seed.line if seed else None,
        })
    # Display dedupe: a phrase fully contained in a longer one with the same count is shown under it.
    by_len = sorted(occurrences_by_form, key=len, reverse=True)
    for longer in by_len:
        if len(longer) < 2:
            continue
        for n in range(1, len(longer)):
            for i in range(len(longer) - n + 1):
                sub = longer[i:i + n]
                if sub in counts and counts[sub] == counts[longer] and expression_ids[sub] not in result.nested_in:
                    result.nested_in[expression_ids[sub]] = expression_ids[longer]
    result.stats.sort(key=lambda s: (-s["distinct_verses"], -s["token_count"], s["expression_id"]))
    return result
