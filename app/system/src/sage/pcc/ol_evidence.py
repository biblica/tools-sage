"""Adapter: original-language (MACULA) lemma items for SOURCE verse units, through versification.

Each SOURCE verse (project numbering) is mapped to the canonical ``org`` numbering the MACULA package
uses, and its words are reduced to ``OlItem`` evidence fields. A verse with no mapping or no words simply
has no entry, so its occurrences report ``NO_OL_ALIGNMENT`` instead of being guessed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ..ol_analysis import OlAnalysis, ol_family_for_book
from ..vrs import VerseRef, VersificationSchema
from .discovery import SourceUnit
from .sense import OlItem


def _parse(label: str) -> VerseRef:
    book, _, cv = label.partition(" ")
    chapter, _, verse = cv.partition(":")
    return VerseRef(book, int(chapter), int(verse))


def ol_items_for_units(
    units: Iterable[SourceUnit], analysis: OlAnalysis, schema: VersificationSchema,
) -> dict[str, list[OlItem]]:
    """OL evidence per ``unit_id`` for every unit whose canonical verses have MACULA words."""
    found: dict[str, list[OlItem]] = {}
    for unit in units:
        family = ol_family_for_book(unit.canonical_ref.split(" ")[0])
        if family is None:
            continue
        table = analysis.verses(family)
        items: list[OlItem] = []
        seen: set[VerseRef] = set()
        for label in unit.native_refs:
            for canonical in sorted(schema.local_to_canonical(_parse(label)), key=lambda r: (r.chapter, r.verse)):
                if canonical in seen:
                    continue
                seen.add(canonical)
                for word in table.get(canonical, ()):
                    summary = word.summary()
                    key = summary.get("strong") or summary.get("lemma")
                    if key:
                        items.append(OlItem(family + ":" + key, summary.get("lemma", ""), summary.get("strong", ""),
                                            summary.get("gloss", "")))
        if items:
            found[unit.unit_id] = items
    return found
