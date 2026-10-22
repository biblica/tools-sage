"""MACULA anchors and scoped challenge routing for BIC; controller-side only.

An anchor names the original-language content words (lemma, Strong's number, gloss, part of speech) a
challenge most likely concerns. Words in the cited verses are ranked by how many of the challenge's own
words (its summary, and in reports its candidate renderings) match MACULA's English gloss, then by rarity
across the testament, verbs before nouns. Anchors key deduplication, choose the one verse an OL check
uses for a range challenge, and appear in the Operator's challenge report. They are never routed to a
model: INSPECT receives no original-language Scripture, and REWRITE receives it only through the
conditional OL step.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from .errors import SageError, ValidationError
from .ol_analysis import OlAnalysis, OlWord, load_ol_analysis, ol_family_for_book
from .references import ScriptureScope, expand_reference_atoms, parse_scope, reference_overlaps_scope

CONTENT_POS = frozenset({"verb", "noun", "adjective", "adj"})
# Each routed challenge row costs roughly 1 KB; these caps keep REWRITE and SELF-CHECK prompts bounded.
MAX_ROUTED_PER_VERSE = 3
MAX_ROUTED_TOTAL = 24
ROUTED_FIELDS = ("challenge_id", "scripture_reference", "challenge_type", "summary", "recommended_action")
_WORD_RE = re.compile(r"[^\W\d_]{3,}")
_VERSE_MENTION_RE = re.compile(r"\bverses?\s+(\d+)", re.IGNORECASE)
_STOPWORDS = frozenset(
    "the and that this these those with from into onto upon for not but are was were been being have has had "
    "having will would shall should could can may might must his her its their them they him she you your our "
    "who whom whose which what when where while than then there here also only very more most some any all "
    "each other such same verse verses source target text wording rendering clause sense meaning".split()
)
_FREQUENCY: dict[tuple[str, str], dict[str, int]] = {}


def _main_segment(word: OlWord) -> Mapping[str, str]:
    """Return the segment carrying a word's content: its verb, noun, or adjective, else the last segment."""
    return next((segment for segment in word.segments if segment.get("pos") in CONTENT_POS), word.segments[-1])


def _stem(token: str) -> str:
    """Reduce an English word to a crude stem so rebuke, rebuked, and rebukes meet."""
    for suffix in ("ingly", "edly", "ing", "ed", "es", "ly", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            token = token[: -len(suffix)]
            break
    return token[:-1] if token.endswith("e") and len(token) > 4 else token


def _stems(text: str) -> set[str]:
    """Return the content-word stems of an English text."""
    return {_stem(token) for token in _WORD_RE.findall(text.casefold()) if token not in _STOPWORDS}


def lemma_frequency(analysis: OlAnalysis, family: str) -> dict[str, int]:
    """Return, per lemma, how often MACULA lists it as a content word across the family's corpus."""
    key = (analysis.package_id, family)
    if key not in _FREQUENCY:
        counts: dict[str, int] = {}
        for words in analysis.verses(family).values():
            for word in words:
                lemma = str(_main_segment(word).get("lemma") or "")
                if lemma:
                    counts[lemma] = counts.get(lemma, 0) + 1
        _FREQUENCY[key] = counts
    return _FREQUENCY[key]


def ol_anchor(root: Path, reference: str, *, hint: str = "", limit: int = 3) -> dict[str, Any] | None:
    """Return the content words of the cited verses a challenge most likely concerns, or None.

    ``hint`` is the challenge's own English text; each word's ``match`` counts its gloss stems found there.
    The SOURCE reference is used as the original-language reference, as the BIC OL claim checker does; a
    verse MACULA lacks yields no anchor rather than an error.
    """
    try:
        book = parse_scope(reference).book
        family = ol_family_for_book(book)
        analysis = load_ol_analysis(root) if family else None
        refs = expand_reference_atoms([reference])
    except (SageError, OSError, ValueError, KeyError):
        return None
    if analysis is None or family is None or not refs:
        return None
    frequency = lemma_frequency(analysis, family)
    hint_stems = _stems(hint)
    ranked: list[tuple[int, int, int, int, dict[str, Any]]] = []
    for order, word in enumerate(analysis.words(family, refs)):
        segment = _main_segment(word)
        pos = str(segment.get("pos") or "")
        lemma = str(segment.get("lemma") or "")
        if pos not in CONTENT_POS or not lemma:
            continue
        gloss = str(segment.get("gloss") or "")
        match = len(_stems(gloss) & hint_stems)
        occurrences = frequency.get(lemma, 0)
        ranked.append((-match, 0 if pos == "verb" else 1, occurrences, order, {
            "reference": word.reference.label(),
            "text": word.text,
            "lemma": lemma,
            "strong": str(segment.get("strong") or ""),
            "gloss": gloss,
            "pos": pos,
            "match": match,
            "occurrences": occurrences,
        }))
    if not ranked:
        return None
    ranked.sort(key=lambda row: row[:4])
    words: list[dict[str, Any]] = []
    for row in ranked:
        if any(item["lemma"] == row[4]["lemma"] and item["reference"] == row[4]["reference"] for item in words):
            continue
        words.append(row[4])
        if len(words) >= limit:
            break
    family_manifest = dict(dict(analysis.manifest.get("families") or {}).get(family) or {})
    attribution = (
        f"{family_manifest.get('attribution', 'MACULA')} (\u00a9 2022\u20132024 Biblica, Inc., CC BY 4.0, "
        f"https://creativecommons.org/licenses/by/4.0/). Glosses: {family_manifest.get('gloss_source', 'MACULA')}."
    )
    return {"package_id": analysis.package_id, "words": words, "attribution": attribution}


def anchor_verse(root: Path, reference: str, *, hint: str = "") -> str | None:
    """Return the one verse of a range a challenge concerns, or None when its own text does not decide it.

    A verse the challenge names ("verse 43") wins; otherwise the verse of the content word whose gloss best
    matches the challenge text, unless an equally good match sits in another verse. Rarity alone never
    decides, so an undecided range keeps its OL check skipped rather than spent on a guessed verse.
    """
    try:
        refs = expand_reference_atoms([reference])
    except (SageError, ValueError):
        return None
    if not refs:
        return None
    by_number = {ref.verse: ref for ref in refs}
    for match in _VERSE_MENTION_RE.finditer(hint):
        named = by_number.get(int(match.group(1)))
        if named is not None:
            return named.label()
    anchor = ol_anchor(root, reference, hint=hint, limit=8)
    if not anchor:
        return None
    best = [word for word in anchor["words"] if word["match"] > 0]
    if not best:
        return None
    top = best[0]
    if any(word["match"] == top["match"] and word["reference"] != top["reference"] for word in best[1:]):
        return None
    return str(top["reference"])


def routed_challenges(
    rows: Iterable[Mapping[str, Any]],
    scope: ScriptureScope,
    job_id: str,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Select the INSPECT challenges one REWRITE or SELF-CHECK task receives.

    Only this Job's challenges that are not superseded and overlap the task scope qualify. The newest
    challenge wins among those sharing a verse, type, and MACULA anchor lemma (or summary, without an
    anchor); at most ``MAX_ROUTED_PER_VERSE`` per verse and ``MAX_ROUTED_TOTAL`` in all are kept, in
    Scripture order, projected to the fields the model uses.
    """
    eligible = [
        dict(row)
        for row in rows
        if str(row.get("bic_job_id", "")) == job_id
        and str(row.get("status", "OPEN")).upper() != "SUPERSEDED"
        and reference_overlaps_scope(scope, str(row.get("scripture_reference") or row.get("scope") or ""))
    ]
    seen: set[tuple[str, str, str]] = set()
    per_verse: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    for row in reversed(eligible):  # newest commit first
        reference = str(row.get("scripture_reference") or row.get("scope") or "")
        try:
            atoms = expand_reference_atoms([reference])
        except ValidationError:
            atoms = ()
        verse = atoms[0].label() if atoms else reference
        anchor = ol_anchor(root, reference, hint=str(row.get("summary", "")), limit=1) if root is not None else None
        topic = anchor["words"][0]["lemma"] if anchor else " ".join(str(row.get("summary", "")).casefold().split())[:80]
        key = (verse, str(row.get("challenge_type", "")).upper(), topic)
        if key in seen or per_verse.get(verse, 0) >= MAX_ROUTED_PER_VERSE or len(kept) >= MAX_ROUTED_TOTAL:
            continue
        seen.add(key)
        per_verse[verse] = per_verse.get(verse, 0) + 1
        kept.append({field: row.get(field, "") for field in ROUTED_FIELDS})

    def order(row: Mapping[str, Any]) -> tuple[int, int]:
        """Sort routed challenges by their first chapter and verse."""
        try:
            first = expand_reference_atoms([str(row["scripture_reference"])])[0]
            return first.chapter, first.verse
        except (ValidationError, IndexError):
            return 10**6, 0

    return sorted(kept, key=order)


def report_anchor_line(anchor: Mapping[str, Any] | None) -> str:
    """Render one anchor as a compact report fragment: lemma (Strong's, gloss) for each word."""
    if not anchor:
        return ""
    return "; ".join(
        f"{word['reference']} {word['lemma']} ({word['strong'] or '-'}, “{word['gloss']}”)"
        for word in anchor.get("words", [])
    )
