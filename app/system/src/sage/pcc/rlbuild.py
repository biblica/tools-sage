"""Top-down reference-list build (plan §5b.7 refined builder, P5b-2; D14 revised, D17, D19).

The list starts from original-language **concepts**, never from frequent reference wordings:

1. **Inventory.** The union of Paratext Biblical Terms (when the Operator imported them), the SAGE Key
   Concepts package (when present), phrases the team declared, and concepts inherited from a base list;
   concepts the base list dropped are removed. Concepts merge by ``concept_key`` (D13).
2. **Occurrences.** Every MACULA word of the concept in the reference's verses (through versification). A
   multi-lemma concept occurs where all its lemmas stand within a short window, in any order.
3. **Realize.** Each occurrence takes the reference tokens aligned to the concept's own segments (P5b-0),
   extended over an adjacent unlinked token the alignment model gives to the same word, compacted to one
   contiguous span, and trimmed of function tokens at its edges. An occurrence with no aligned token is
   ``no_realization``; one rendered only by function tokens (a pronoun for a name) is ``function_only``.
   Nothing is guessed.
4. **Partition (D19).** Inside a concept, senses come from the reference's own lexical choice: the stem of the
   wording's first token (learned suffixes) plus its case outside sentence starts (*Spirit* / *spirit*). A
   sentence-start occurrence joins the case its stem mostly has. Multi-word renderings of one head
   (*brothers and sisters*) stay in that head's sense.
5. **Select (D17).** A sense recurs when it is realized in at least ``min_verses`` verses of the whole
   reference; rarer senses are pooled as ``OTHER`` evidence. A concept with no recurring sense is left out,
   and the left-out summary counts every concept by reason.

Function tokens are measured, not listed: a reference token form whose alignment links point mostly at
non-content original-language segments (article, conjunction, preposition, pronoun); one spread over many
lemmas with none dominant that is seldom a word's only rendering token (an auxiliary: *will*, *have*); or one
linked to several lemmas that is almost never a word's only rendering token (vocative *O*). Content words
spread over many lemmas (*leaders*, *life*) are often the only token, so they stay. Multi-lemma concepts
occur only inside one MACULA syntax-tree phrase group when the package provides groups (plan R7).
Deterministic: the same inputs give the same entries.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from ..ol_analysis import OlAnalysis, ol_family_for_book
from ..vrs import VerseRef, VersificationSchema
from .align import Alignment, CONTENT_POS, _label, segment_key
from .discovery import SourceUnit, _gap_joins
from .glossary import BiblicalTerm
from .contracts import RL_REALIZATION_COUNTS
from .ids import concept_key, sense_key
from .segment import Token, at_sentence_start, case_feature
from .traits import MIN_STEM, WipTraits

DEFAULT_MIN_VERSES = 3
MULTI_WINDOW_EXTRA = 3          # a multi-lemma concept spans at most len(lemmas) + this many words
MAX_SPAN_GAP = 2                # tokens between two realized tokens that still make one span
FUNCTION_MIN_KEYS = 20          # a form spread over at least this many lemmas ...
FUNCTION_MAX_TOP_SHARE = 0.2    # ... none of them above this share ...
FUNCTION_MAX_SOLO = 0.15        # ... and seldom a word's only rendering token is a function token (auxiliary)
COMPANION_MIN_KEYS = 5          # a form linked to this many lemmas ...
COMPANION_MAX_SOLO = 0.02       # ... and almost never a word's only rendering token (vocative "O") is one too
HINT_MIN_POSTERIOR = 0.5        # measured on NIV: *leaders* (Jewish leaders) 0.56-0.98; *has*, *protested* <= 0.4
EDGE_MIN_SHARE = 0.05          # an edge token stays when at least this share of its links go to the concept
DECLARED_ANCHOR_SHARE = 0.5     # a declared phrase is anchored on content lemmas in at least half its occurrences
REASONS = ("CATEGORY_OFF", "DROPPED_IN_BASE", "NOT_LOCATABLE", "NOT_IN_REFERENCE", "NO_REALIZATION",
           "FUNCTION_ONLY", "BELOW_RECURRENCE")
ORIGIN_ORDER = ("DECLARED", "INHERITED", "BIBLICAL_TERMS", "KEY_CONCEPTS")
OTHER_SENSE = "\0OTHER"
_METHOD_RANK = {"gold": 0, "transitive": 1, "direct": 2, "located": 3}


@dataclass(frozen=True)
class Concept:
    """One inventory concept before realization."""

    kind: str                          # OL | BT | WORDING
    anchor: tuple[str, ...]            # sorted OL keys, (term id,) or ("<lang>|<wording>",)
    label: str
    category: str
    status: str                        # ACTIVE | PROPOSED
    sources: tuple[str, ...]
    surfaces: tuple[tuple[str, ...], ...] = ()   # BT: folded original-language word alternatives
    references: tuple[str, ...] = ()             # BT: Paratext word-level references
    family: str = ""
    notes: str = ""

    @property
    def key(self) -> str:
        """The concept key (D13)."""
        return concept_key(self.kind, list(self.anchor) if self.kind == "OL" else self.anchor[0])


@dataclass
class BuildResult:
    """Entries ready for ``write_reference_list``, the left-out summary and build counts."""

    entries: list[dict[str, Any]]
    left_out: dict[str, int]
    left_out_examples: dict[str, list[str]]
    stats: dict[str, int] = field(default_factory=dict)
    declared_problems: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """The manifest's ``build.summary``."""
        return {"left_out": dict(self.left_out), "stats": dict(self.stats),
                "declared_problems": list(self.declared_problems)}


# --- inventory -------------------------------------------------------------------------------------


def fold_ol(text: str) -> str:
    """Original-language comparison form: no accents or points, lower case, final sigma folded."""
    kept = "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.category(c).startswith("M"))
    return unicodedata.normalize("NFC", kept).casefold().replace("ς", "σ")


def ol_words(text: str) -> list[str]:
    """Original-language words: runs of letters with their marks (vowel points and accents stay inside)."""
    words, current = [], []
    for char in unicodedata.normalize("NFC", text):
        if char.isalpha() or unicodedata.category(char).startswith("M"):
            current.append(char)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def _surface_alternatives(name: str) -> tuple[tuple[str, ...], ...]:
    """``"εἰς Χριστὸν, ἐν Χριστῷ"`` -> folded word tuples per alternative (parentheses are optional words)."""
    out = []
    for part in name.split(","):
        words = tuple(fold_ol(w) for w in ol_words(part))
        if words:
            out.append(words)
    return tuple(out)


def concepts_from_biblical_terms(terms: Iterable[BiblicalTerm], *, categories: Iterable[str] | None = None
                                 ) -> tuple[list[Concept], Counter[str]]:
    """Biblical Terms as concepts; returns (concepts, terms left out by category).

    A one-word term, or a phrase with a Strong's number per content word, is keyed by its original-language
    lemmas, so it merges with the same concept from any other source (homographs such as ``πνεῦμα-1/-2/-3``
    become one concept whose senses the reference decides, D19). A phrase that names fewer lemmas than it has
    content words (*in Christ*: only χριστός) keeps the Biblical Terms id and is located by its words.
    """
    allowed = None if categories is None else {c.upper() for c in categories}
    found: list[Concept] = []
    skipped: Counter[str] = Counter()
    for term in terms:
        if allowed is not None and term.category.upper() not in allowed:
            skipped["CATEGORY_OFF"] += 1
            continue
        words = ol_words(term.name.split(",")[0])
        lemmas = sorted({f"{term.family}:{n}" for n in term.strongs})
        source = f"BT:{term.term_id}"
        if lemmas and (len(words) <= 1 or len(lemmas) >= 2):
            found.append(Concept("OL", tuple(lemmas), term.name, term.category, "ACTIVE", (source,),
                                 family=term.family, notes=term.gloss))
        else:
            found.append(Concept("BT", (term.term_id,), term.name, term.category, "ACTIVE", (source,),
                                 surfaces=_surface_alternatives(term.name), references=term.references,
                                 family=term.family, notes=term.gloss))
    return found, skipped


def concepts_from_entries(entries: Iterable[Mapping[str, Any]], origin: str) -> tuple[list[Concept], set[str]]:
    """Concepts from reference-list entries (a base list or the Key Concepts package); returns (kept, dropped keys)."""
    kept, dropped = [], set()
    for entry in entries:
        if entry["status"] == "DROPPED":
            dropped.add(entry["concept_key"])
            continue
        kind = entry["anchor"]["kind"]
        anchor = tuple(sorted(entry["anchor"]["value"])) if kind == "OL" else tuple(entry["anchor"]["value"][:1])
        kept.append(Concept(kind, anchor, entry["label"], entry["category"], entry["status"], (origin,),
                            notes=entry.get("notes", "")))
    return kept, dropped


def merge_inventory(*groups: Iterable[Concept]) -> dict[str, Concept]:
    """Union by concept key: sources merge, ``ACTIVE`` wins, the first label/category given is kept."""
    merged: dict[str, Concept] = {}
    for group in groups:
        for concept in group:
            key = concept.key
            old = merged.get(key)
            if old is None:
                merged[key] = concept
                continue
            notes = "; ".join(dict.fromkeys(n for n in (old.notes, concept.notes) if n))
            merged[key] = replace(old, sources=tuple(dict.fromkeys(old.sources + concept.sources)),
                                  status="ACTIVE" if "ACTIVE" in (old.status, concept.status) else old.status,
                                  surfaces=old.surfaces or concept.surfaces,
                                  references=old.references or concept.references,
                                  family=old.family or concept.family, notes=notes)
    return merged


# --- original-language words per unit -----------------------------------------------------------------


@dataclass(frozen=True)
class _Word:
    """One MACULA word of a unit, reduced to what the builder needs."""

    ref: str
    keys: tuple[str, ...]          # one per segment
    content: tuple[bool, ...]
    folded: str
    lemmas: tuple[str, ...]        # folded
    glosses: tuple[str, ...]
    lemma_text: tuple[str, ...]


def ol_words_by_unit(units: Iterable[SourceUnit], analysis: OlAnalysis,
                     schema: VersificationSchema) -> dict[str, list[_Word]]:
    """MACULA words per unit, in original-language order (the aligner's view of the same verses)."""
    found: dict[str, list[_Word]] = {}
    for unit in units:
        family = ol_family_for_book(unit.canonical_ref.split(" ")[0])
        if family is None:
            continue
        table = analysis.verses(family)
        seen: set[VerseRef] = set()
        words: list[_Word] = []
        for label in unit.native_refs:
            for canonical in sorted(schema.local_to_canonical(_label(label)), key=lambda r: (r.chapter, r.verse)):
                if canonical in seen:
                    continue
                seen.add(canonical)
                for word in table.get(canonical, ()):
                    segs = word.segments
                    words.append(_Word(word.word_id, tuple(segment_key(family, s) for s in segs),
                                       tuple((s.get("pos") or "") in CONTENT_POS for s in segs), fold_ol(word.text),
                                       tuple(fold_ol(s.get("lemma") or "") for s in segs),
                                       tuple(s.get("gloss") or "" for s in segs),
                                       tuple(s.get("lemma") or "" for s in segs)))
        if words:
            found[unit.unit_id] = words
    return found


@dataclass(frozen=True)
class Occurrence:
    """One concept occurrence: unit and the original-language words (refs) and segment keys it covers."""

    unit: str
    words: tuple[str, ...]
    keys: frozenset[str]


def _bt_word_index(reference: str) -> tuple[str, int] | None:
    """Paratext ``BBBCCCVVVWWWWW`` -> (``BOOK C:V``, MACULA word number); Greek numbering is word x 2 (measured)."""
    from ..canon import NT_27, OT_39
    books = list(OT_39) + list(NT_27)
    if not re.fullmatch(r"\d{14}", reference):
        return None
    number = int(reference[:3])
    if not 1 <= number <= len(books):
        return None
    return f"{books[number - 1]} {int(reference[3:6])}:{int(reference[6:9])}", int(reference[9:]) // 2


def find_occurrences(concept: Concept, index: Mapping[str, list[tuple[str, int]]],
                     words: Mapping[str, list[_Word]], verse_units: Mapping[str, list[str]],
                     groups: Mapping[str, Sequence[Any]] | None = None) -> list[Occurrence]:
    """Every occurrence of ``concept`` in the reference (index: OL key -> [(unit, word position)]).

    ``groups``: MACULA word ref -> phrase groups (``OlGroup``) it belongs to; when given, a multi-lemma
    window counts only if one group holds all its words.
    """
    if concept.kind == "OL":
        keys = set(concept.anchor)
        if len(keys) == 1:
            key = concept.anchor[0]
            return [Occurrence(u, (words[u][i].ref,), frozenset(keys)) for u, i in index.get(key, ())]
        return _multi_occurrences(keys, index, words, groups)
    if concept.kind == "BT":
        return _bt_occurrences(concept, words, verse_units)
    return []


def _multi_occurrences(keys: set[str], index: Mapping[str, list[tuple[str, int]]],
                       words: Mapping[str, list[_Word]], groups: Mapping[str, Sequence[Any]] | None) -> list[Occurrence]:
    """Windows holding every lemma of a multi-lemma concept (any order), each word used once."""
    rarest = min(sorted(keys), key=lambda k: len(index.get(k, ())))
    found: list[Occurrence] = []
    limit = len(keys) + MULTI_WINDOW_EXTRA
    for unit in dict.fromkeys(u for u, _ in index.get(rarest, ())):
        items = words[unit]
        used: set[int] = set()
        for i, word in enumerate(items):
            if i in used or not keys.intersection(word.keys):
                continue
            chosen: dict[str, int] = {}
            for j in range(i, min(len(items), i + limit)):
                if j in used:
                    continue
                for key in items[j].keys:
                    if key in keys and key not in chosen:
                        chosen[key] = j
            if len(chosen) == len(keys):
                positions = sorted(set(chosen.values()))
                refs = {items[p].ref for p in positions}
                if groups is not None and not any(refs <= set(g.refs) for g in groups.get(items[positions[0]].ref, ())):
                    continue
                used.update(positions)
                found.append(Occurrence(unit, tuple(items[p].ref for p in positions), frozenset(keys)))
    return found


def _bt_occurrences(concept: Concept, words: Mapping[str, list[_Word]],
                    verse_units: Mapping[str, list[str]]) -> list[Occurrence]:
    """A Biblical Terms phrase without lemma keys: its listed verses, located by its original-language words."""
    found: list[Occurrence] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for reference in concept.references:
        parsed = _bt_word_index(reference)
        if parsed is None:
            continue
        verse, number = parsed
        for unit in verse_units.get(verse, ()):
            items = words.get(unit, [])
            best: list[int] = []
            for alternative in concept.surfaces:
                hits = [i for i, w in enumerate(items) if w.ref.startswith(verse + "!")
                        and (w.folded in alternative or any(l in alternative for l in w.lemmas))]
                # Greek references number words (x2); keep the hits nearest the referenced word.
                anchor = next((i for i, w in enumerate(items) if w.ref == f"{verse}!{number}"), None)
                if anchor is not None and hits:
                    hits = [i for i in hits if abs(i - anchor) <= len(alternative) + 1]
                if len(hits) > len(best):
                    best = hits
            if best:
                refs = tuple(items[i].ref for i in best)
                if (unit, refs) not in seen:
                    seen.add((unit, refs))
                    keys = frozenset(k for i in best for k, c in zip(items[i].keys, items[i].content)
                                     if c or len(items[i].keys) == 1)
                    found.append(Occurrence(unit, refs, keys))
    return found


# --- realization ---------------------------------------------------------------------------------------


SOLO = "\0SOLO"  # pseudo-key in ``form_links``: how often the form was a word's only linked token


def form_links(alignment: Alignment) -> dict[str, Counter[str]]:
    """Reference token form -> original-language segment keys it is linked to, with counts (plus ``SOLO``)."""
    linked: dict[str, Counter[str]] = defaultdict(Counter)
    for unit, links in alignment.links.items():
        tokens = alignment.tokens[unit]
        per_word = Counter(link.ol_ref for link in links)
        for link in links:
            if link.key:
                form = tokens[link.token].norm
                linked[form][link.key] += 1
                if per_word[link.ol_ref] == 1:
                    linked[form][SOLO] += 1
    return dict(linked)


def function_forms(linked: Mapping[str, Counter[str]], content_keys: Mapping[str, bool]) -> frozenset[str]:
    """Reference token forms that behave as function words in this alignment (measured, see module doc)."""
    out = set()
    for form, counts in linked.items():
        keys = Counter({k: n for k, n in counts.items() if k != SOLO})
        if not keys:
            continue
        total = sum(keys.values())
        top_key, top = keys.most_common(1)[0]
        if not content_keys.get(top_key, False):
            out.add(form)
        elif (len(keys) >= FUNCTION_MIN_KEYS and top / total <= FUNCTION_MAX_TOP_SHARE
              and counts[SOLO] / total <= FUNCTION_MAX_SOLO):
            out.add(form)
        elif len(keys) >= COMPANION_MIN_KEYS and counts[SOLO] / total <= COMPANION_MAX_SOLO:
            out.add(form)
    return frozenset(out)


@dataclass(frozen=True)
class Realization:
    """How one occurrence is rendered in the reference."""

    unit: str
    first: int          # token index range [first, last]
    last: int
    method: str


def realize(occurrence: Occurrence, alignment: Alignment, function: frozenset[str],
            linked_forms: Mapping[str, Counter[str]], text: str, verse_keys: frozenset[str] = frozenset(),
            content_keys: Mapping[str, bool] | None = None) -> Realization | str:
    """The occurrence's reference span, or the reason there is none (``no_realization`` / ``function_only``).

    ``linked_forms``: form -> the segment keys it is linked to, with counts (``form_links``). An unlinked,
    non-function neighbor extends the span when the model hints at the same word and no other word of the
    verse carries the lemma the form usually renders (*leaders* in *the Jewish leaders*; not *is* beside
    a copula). A linked edge token stays only when it is not a function token and at least
    ``EDGE_MIN_SHARE`` of its links go to the concept: a copula or adverb the BSB folds into a chunk
    (*is God*) is trimmed. ``verse_keys``: the original-language keys of the occurrence's verse.
    """
    def explained_elsewhere(form: str) -> bool:
        """The form usually renders a lemma that another word of this verse carries."""
        keys = linked_forms.get(form)
        if not keys:
            return False
        usual = sorted(((n, k) for k, n in keys.items() if k != SOLO), reverse=True)
        return bool(usual) and usual[0][1] not in occurrence.keys and usual[0][1] in verse_keys

    def share(form: str) -> float:
        """Share of the form's links that go to this concept's keys (1.0 for a form never linked)."""
        keys = linked_forms.get(form)
        total = sum(n for k, n in keys.items() if k != SOLO) if keys else 0
        if not total:
            return 1.0
        return sum(n for k, n in keys.items() if k in occurrence.keys) / total

    unit = occurrence.unit
    content_keys = content_keys or {}
    tokens = alignment.tokens.get(unit, [])
    words = set(occurrence.words)
    core = {l.token: l.method for l in alignment.links.get(unit, ()) if l.ol_ref in words and l.key in occurrence.keys}
    if not core:
        return "no_realization"
    linked = {l.token for l in alignment.links.get(unit, ())}
    # tokens rendering another content word of the verse: a span never bridges them
    foreign = {l.token for l in alignment.links.get(unit, ()) if l.ol_ref not in words and content_keys.get(l.key)}
    hints = alignment.hints.get(unit, {})
    picked = set(core)
    for step in (-1, 1):
        i = (min(picked) if step < 0 else max(picked)) + step
        while 0 <= i < len(tokens) and i not in linked and hints.get(i, ("", "", 0.0))[0] in words \
                and hints[i][1] in occurrence.keys and hints[i][2] >= HINT_MIN_POSTERIOR and tokens[i].norm not in function \
                and not explained_elsewhere(tokens[i].norm):
            picked.add(i)
            i += step
    ordered = sorted(picked)
    runs: list[list[int]] = [[ordered[0]]]
    for i in ordered[1:]:
        prev = runs[-1][-1]
        if i - prev - 1 <= MAX_SPAN_GAP and all(_gap_joins(text, tokens[k], tokens[k + 1]) for k in range(prev, i)) \
                and not foreign.intersection(range(prev + 1, i)):
            runs[-1].append(i)
        else:
            runs.append([i])
    run = max(runs, key=lambda r: (sum(1 for i in r if i in core), -r[0]))
    first, last = run[0], run[-1]
    def weak(i: int) -> bool:
        """An edge token that does not belong to the concept's wording."""
        return tokens[i].norm in function or (i in linked and share(tokens[i].norm) < EDGE_MIN_SHARE)

    while first < last and weak(first):
        first += 1
    while last > first and weak(last):
        last -= 1
    if all(tokens[i].norm in function for i in range(first, last + 1)):
        return "function_only"
    method = min((core[i] for i in run if i in core), key=_METHOD_RANK.__getitem__)
    return Realization(unit, first, last, method)


# --- partition and selection -----------------------------------------------------------------------------


def stem(form: str, suffixes: Sequence[str]) -> str:
    """Strip learned suffixes, longest first, until none applies with ``MIN_STEM`` letters left.

    Stripping to a fixpoint makes forms of one word agree (*brother* and *brothers* both end at *broth*); the
    stem is a grouping key only, never shown.
    """
    ordered = sorted(suffixes, key=lambda x: (-len(x), x))
    while True:
        for suffix in ordered:
            if form.endswith(suffix) and len(form) - len(suffix) >= MIN_STEM:
                form = form[:-len(suffix)]
                break
        else:
            return form


@dataclass(frozen=True)
class _Rendered:
    """One realized occurrence with its wording and sense features."""

    verse: str
    order: int
    wording: str        # comparison form
    display: str        # raw text
    stem: str           # of the first token
    stems: str          # of every non-function token, space-joined
    case: str           # UPPER / LOWER / "" (sentence start or uncased)
    method: str
    ol_senses: tuple[str, ...]
    unit: str = ""
    start: int = 0      # code-point span of the wording in the unit text
    end: int = 0


def _examples(verses: Iterable[tuple[int, str]]) -> list[str]:
    """Three spread references: first, middle and last in reference order."""
    ordered = [v for _, v in sorted(set(verses))]
    if len(ordered) <= 3:
        return ordered
    return [ordered[0], ordered[len(ordered) // 2], ordered[-1]]


def partition(concept_key_: str, rendered: Sequence[_Rendered], *, min_verses: int) -> list[dict[str, Any]]:
    """Senses (D19) with wordings, verse counts and examples; non-recurring senses pooled as ``OTHER``."""
    by_stem_case: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rendered:
        if r.case:
            by_stem_case[r.stem][r.case] += 1
    def case_of(r: _Rendered) -> str:
        """The occurrence's case, or at a sentence start the case its stem mostly has."""
        return r.case or (sorted(by_stem_case[r.stem].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                          if by_stem_case.get(r.stem) else "")

    # A whole wording that recurs is a sense of its own (*Jewish leaders* beside *Jewish*); a rarer multi-word
    # wording joins the sense of its first word; what still does not recur is pooled as OTHER.
    full: dict[str, list[_Rendered]] = defaultdict(list)
    for r in rendered:
        full[f"{r.stems}|{case_of(r)}"].append(r)
    groups: dict[str, list[_Rendered]] = defaultdict(list)
    for signature, items in full.items():
        if len({r.verse for r in items}) >= min_verses:
            groups[signature].extend(items)
        else:
            for r in items:
                groups[f"{r.stem}|{case_of(r)}"].append(r)
    senses, other = [], []
    for signature, items in groups.items():
        if len({r.verse for r in items}) >= min_verses:
            senses.append((signature, items))
        else:
            other.extend(items)
    if other:
        senses.append((OTHER_SENSE, other))
    out = []
    for signature, items in senses:
        wordings: dict[str, set[str]] = defaultdict(set)
        displays: dict[str, Counter[str]] = defaultdict(Counter)
        for r in items:
            wordings[r.wording].add(r.verse)
            displays[r.wording][r.display] += 1
        shown = {w: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for w, c in displays.items()}
        ranked = sorted(wordings, key=lambda w: (-len(wordings[w]), shown[w]))
        is_other = signature == OTHER_SENSE
        out.append({
            "sense_key": sense_key(concept_key_, "OTHER" if is_other else signature),
            "kind": "OTHER" if is_other else "SENSE",
            "label": "(other renderings)" if is_other else shown[ranked[0]],
            "wordings": [{"wording": shown[w], "verses": len(wordings[w])} for w in ranked],
            "verses": len({r.verse for r in items}),
            "examples": _examples((r.order, r.verse) for r in items),
            "ol_senses": sorted({s for r in items for s in r.ol_senses}),
            "state": "PROPOSED",
        })
    out.sort(key=lambda s: (s["kind"] == "OTHER", -s["verses"], s["label"]))
    return out


# --- declared phrases ------------------------------------------------------------------------------------


def locate_wording(tokens_by_unit: Mapping[str, Sequence[Token]], wording: Sequence[str]) -> list[tuple[str, int, int]]:
    """Every (unit, first, last) where the token sequence ``wording`` occurs."""
    n = len(wording)
    found = []
    for unit, tokens in tokens_by_unit.items():
        norms = [t.norm for t in tokens]
        for i in range(len(norms) - n + 1):
            if norms[i:i + n] == list(wording):
                found.append((unit, i, i + n - 1))
    return found


def anchor_declared(spans: Sequence[tuple[str, int, int]], alignment: Alignment,
                    content_keys: Mapping[str, bool]) -> tuple[str, ...]:
    """Content lemmas linked inside a declared phrase in at least half its occurrences (sorted), or ()."""
    counts: Counter[str] = Counter()
    for unit, first, last in spans:
        keys = {l.key for l in alignment.links.get(unit, ()) if first <= l.token <= last and content_keys.get(l.key)}
        counts.update(keys)
    if not spans:
        return ()
    return tuple(sorted(k for k, n in counts.items() if n / len(spans) >= DECLARED_ANCHOR_SHARE))


# --- the build -------------------------------------------------------------------------------------------


@dataclass
class BuildContext:
    """What every concept's realization needs: OL words and index, function tokens, the alignment."""

    units: Sequence[SourceUnit]
    alignment: Alignment
    words: dict[str, list[_Word]]
    index: dict[str, list[tuple[str, int]]]
    verse_units: dict[str, list[str]]
    verse_keys: dict[str, frozenset[str]]
    content_keys: dict[str, bool]
    linked_forms: dict[str, Counter[str]]
    function: frozenset[str]
    suffixes: tuple[str, ...]
    cased: bool
    groups: Mapping[str, Sequence[Any]] | None = None
    clear_senses: Mapping[tuple[str, int], str] | None = None

    def __post_init__(self) -> None:
        """Unit lookups."""
        self.by_unit = {u.unit_id: u for u in self.units}
        self.order = {u.unit_id: i for i, u in enumerate(self.units)}

    def realize_concept(self, concept: Concept, spans: Sequence[tuple[str, int, int]] | None = None,
                        units: Collection[str] | None = None) -> tuple[Counter[str], list[_Rendered]]:
        """Counts and rendered occurrences of one concept, optionally only inside ``units``."""
        counts: Counter[str] = Counter()
        items: list[tuple[Realization, tuple[str, ...]]] = []
        if concept.kind == "WORDING":
            if spans is None:
                spans = locate_wording(self.alignment.tokens, concept.anchor[0].split("|", 1)[1].split(" "))
            items = [(Realization(u, a, b, "located"), ()) for u, a, b in spans if units is None or u in units]
            counts["occurrences"] = len(items)
        else:
            occurrences = find_occurrences(concept, self.index, self.words, self.verse_units, self.groups)
            if units is not None:
                occurrences = [o for o in occurrences if o.unit in units]
            counts["occurrences"] = len(occurrences)
            for occ in occurrences:
                result = realize(occ, self.alignment, self.function, self.linked_forms, self.by_unit[occ.unit].text,
                                 self.verse_keys.get(occ.unit, frozenset()), self.content_keys)
                if isinstance(result, str):
                    counts[result] += 1
                else:
                    items.append((result, _clear(occ, self.words, self.clear_senses)))
        rendered = []
        for real, senses in items:
            counts["realized"] += 1
            counts[real.method] += 1
            rendered.append(self.rendered(real, senses))
        return counts, rendered

    def rendered(self, real: Realization, senses: tuple[str, ...] = ()) -> _Rendered:
        """The wording and sense features of one realization."""
        unit = self.by_unit[real.unit]
        tokens = self.alignment.tokens[real.unit]
        span = tokens[real.first:real.last + 1]
        head = tokens[real.first]
        start = at_sentence_start(unit.text, tokens, real.first)
        case = "" if start or not self.cased else case_feature(head)
        head_stem = stem(head.norm, self.suffixes)
        return _Rendered(unit.canonical_ref, self.order[real.unit], " ".join(t.norm for t in span),
                         unit.text[head.start:span[-1].end], head_stem,
                         " ".join(stem(t.norm, self.suffixes) for t in span if t.norm not in self.function) or head_stem,
                         case, real.method, senses, real.unit, head.start, span[-1].end)


def build_context(units: Sequence[SourceUnit], alignment: Alignment, analysis: OlAnalysis,
                  schema: VersificationSchema, *, suffixes: Sequence[str], cased: bool,
                  groups: Mapping[str, Sequence[Any]] | None = None,
                  clear_senses: Mapping[tuple[str, int], str] | None = None,
                  progress: Callable[[str, str], None] | None = None) -> BuildContext:
    """Index the original-language words of ``units`` and measure function tokens from ``alignment``."""
    note = progress or (lambda stage, detail: None)
    note("index", "original-language words")
    words = ol_words_by_unit(units, analysis, schema)
    index: dict[str, list[tuple[str, int]]] = defaultdict(list)
    content_votes: Counter[str] = Counter()
    key_total: Counter[str] = Counter()
    verse_units: dict[str, list[str]] = defaultdict(list)
    current_book = ""
    for unit in units:
        book = unit.canonical_ref.split(" ")[0]
        if book != current_book:
            current_book = book
            note("index", book)
        for label in unit.native_refs:
            verse_units[label].append(unit.unit_id)
        for i, word in enumerate(words.get(unit.unit_id, ())):
            for key, content in zip(word.keys, word.content):
                if not index[key] or index[key][-1] != (unit.unit_id, i):
                    index[key].append((unit.unit_id, i))
                key_total[key] += 1
                content_votes[key] += content
    # A key is a content lemma when most of its segments are (MACULA reuses some prefix numbers on suffixes).
    content_keys = {key: 2 * content_votes[key] > n for key, n in key_total.items()}
    linked_forms = form_links(alignment)
    return BuildContext(units, alignment, words, dict(index), dict(verse_units),
                        {unit: frozenset(k for w in items for k in w.keys) for unit, items in words.items()},
                        content_keys, linked_forms, function_forms(linked_forms, content_keys), tuple(suffixes), cased,
                        groups, clear_senses)


def declared_concepts(ctx: BuildContext, declared: Iterable[tuple[str, Sequence[str], int]], language_tag: str
                      ) -> tuple[list[Concept], dict[str, list[tuple[str, int, int]]], list[str]]:
    """Declared phrases as concepts: anchored on original-language lemmas when the alignment shows them.

    Returns (concepts, located spans of WORDING concepts, problems).
    """
    concepts, located, problems = [], {}, []
    for surface, wording, line in declared:
        spans = locate_wording(ctx.alignment.tokens, wording)
        if not spans:
            problems.append(f"line {line}: not found in the reference")
        anchor = anchor_declared(spans, ctx.alignment, ctx.content_keys)
        source = f"DECLARED:{line}"
        if anchor:
            concepts.append(Concept("OL", anchor, surface, "DECLARED", "ACTIVE", (source,)))
        else:
            concept = Concept("WORDING", (f"{language_tag}|{' '.join(wording)}",), surface, "DECLARED", "ACTIVE",
                              (source,))
            located[concept.key] = spans
            concepts.append(concept)
    return concepts, located, problems


def build_reference_list(
    units: Sequence[SourceUnit],
    alignment: Alignment,
    analysis: OlAnalysis,
    schema: VersificationSchema,
    *,
    traits: WipTraits,
    language_tag: str,
    inventory: Mapping[str, Concept],
    declared: Iterable[tuple[str, Sequence[str], int]] = (),
    dropped: Iterable[str] = (),
    clear_senses: Mapping[tuple[str, int], str] | None = None,
    groups: Mapping[str, Sequence[Any]] | None = None,
    min_verses: int = DEFAULT_MIN_VERSES,
    skipped: Mapping[str, int] | None = None,
    progress: Callable[[str, str], None] | None = None,
) -> BuildResult:
    """Build the entries of one reference list (see module doc). ``declared``: (surface, tokens, line)."""
    note = progress or (lambda stage, detail: None)
    ctx = build_context(units, alignment, analysis, schema, suffixes=[a.form for a in traits.suffixes],
                        cased=traits.cased, groups=groups, clear_senses=clear_senses, progress=progress)
    left_out: Counter[str] = Counter(skipped or {})
    examples: dict[str, list[str]] = defaultdict(list)
    concepts = dict(inventory)
    for key in set(dropped):
        if concepts.pop(key, None) is not None:
            left_out["DROPPED_IN_BASE"] += 1
    extra, located, problems = declared_concepts(ctx, declared, language_tag)
    concepts = merge_inventory(concepts.values(), extra)

    note("realize", f"{len(concepts)} concepts")
    entries: list[dict[str, Any]] = []
    stats: Counter[str] = Counter(concepts=len(concepts))
    for ckey in sorted(concepts):
        concept = concepts[ckey]
        if concept.kind == "BT" and not concept.references:
            _leave(left_out, examples, "NOT_LOCATABLE", concept)
            continue
        counts, rendered = ctx.realize_concept(concept, located.get(ckey))
        if concept.kind == "WORDING" and not rendered:
            entries.append(_entry(concept, [], counts, [], 0))
            stats["declared_not_found"] += 1
            continue
        if not counts["occurrences"]:
            _leave(left_out, examples, "NOT_IN_REFERENCE", concept)
            continue
        if not rendered:
            reason = "FUNCTION_ONLY" if counts["function_only"] else "NO_REALIZATION"
            _leave(left_out, examples, reason, concept)
            continue
        senses = partition(ckey, rendered, min_verses=min_verses)
        if not any(s["kind"] == "SENSE" for s in senses):
            _leave(left_out, examples, "BELOW_RECURRENCE", concept)
            continue
        entries.append(_entry(concept, senses, counts, _examples((r.order, r.verse) for r in rendered),
                              len({r.verse for r in rendered})))
        for name in ("occurrences", "realized", "function_only", "no_realization"):
            stats[name] += counts[name]
    stats["entries"] = len(entries)
    stats["function_forms"] = len(ctx.function)
    return BuildResult(entries, {r: left_out.get(r, 0) for r in REASONS},
                       {r: sorted(v)[:12] for r, v in sorted(examples.items())}, dict(stats), problems)


def sense_candidates(concept_key_: str, r: _Rendered) -> list[str]:
    """Sense keys an occurrence may belong to, most specific first (whole wording, then first word).

    At a sentence start (no case) every case is a candidate; the caller keeps the ones its list has.
    """
    cases = [r.case] if r.case else ["UPPER", "LOWER", ""]
    return [sense_key(concept_key_, f"{stems}|{case}") for stems in (r.stems, r.stem) for case in cases]


def _clear(occ: Occurrence, words: Mapping[str, list[_Word]], clear: Mapping[tuple[str, int], str] | None) -> tuple[str, ...]:
    """Clear word senses of the occurrence's own segments (evidence only)."""
    if not clear:
        return ()
    found = []
    for word in words.get(occ.unit, ()):
        if word.ref in occ.words:
            for i, key in enumerate(word.keys):
                sense = clear.get((word.ref, i))
                if key in occ.keys and sense:
                    found.append(f"{word.lemma_text[i]} {sense}")
    return tuple(found)


def _leave(left_out: Counter[str], examples: dict[str, list[str]], reason: str, concept: Concept) -> None:
    """Count one left-out concept."""
    left_out[reason] += 1
    if len(examples[reason]) < 40:
        examples[reason].append(concept.label)


def _origin(sources: Sequence[str]) -> str:
    """The leading source kind of an entry."""
    kinds = {"DECLARED" if s.startswith("DECLARED") else "INHERITED" if s.startswith("INHERITED")
             else "BIBLICAL_TERMS" if s.startswith("BT:") else "KEY_CONCEPTS" for s in sources}
    return next(k for k in ORIGIN_ORDER if k in kinds)


def _entry(concept: Concept, senses: list[dict[str, Any]], counts: Counter[str], examples: list[str],
           verses: int) -> dict[str, Any]:
    """One ``reference_list_entry``."""
    return {
        "concept_key": concept.key,
        "anchor": {"kind": concept.kind, "value": list(concept.anchor)},
        "label": concept.label,
        "category": concept.category,
        "status": concept.status,
        "origin": _origin(concept.sources),
        "sources": sorted(concept.sources),
        "senses": senses,
        "realization": {name: counts.get(name, 0) for name in RL_REALIZATION_COUNTS},
        "verses": verses,
        "examples": examples,
        "notes": concept.notes,
    }


__all__ = ["BuildResult", "Concept", "build_reference_list", "concepts_from_biblical_terms", "concepts_from_entries",
           "find_occurrences", "fold_ol", "function_forms", "merge_inventory", "ol_words_by_unit", "partition",
           "realize", "stem"]
