"""Versification-aware linking of every index source to NCA's Western coordinates.

NCA keys its index by Western (``eng.vrs``) coordinates, the same baseline the WIP projection
uses (numbers/scope.py, VersificationService ``eng.vrs``). Each source is linked through .vrs:

- original-language sources numbered like the Hebrew/Greek editions (MACULA WLC/SBLGNT, OSHB
  ketiv/qere, SBLGNT apparatus) map ``org`` -> ``eng`` through the explicit ``eng.vrs``
  mappings (JOL 3:1 -> JOL 2:28, MAL 3:19 -> MAL 4:1, PSA 60:1-2 -> PSA 60:0, 1KI 5:1 -> 1KI 4:21);
- English-numbered sources (the NIV, NET notes) keep their own label wherever ``eng.vrs`` has
  that verse, because both use English numbering; a verse ``eng.vrs`` does not have (for example
  a chapter longer in the NIV) is linked through the NIV project's ``Custom.vrs`` to its
  ``org`` content and from there to ``eng``.

Linking back (Western -> original-language numbering) lets the apparatus join find an
``org``-numbered entry for a Western verse.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sage.vrs import VerseRef, VersificationSchema, compose_vrs, parse_vrs_file


def _parse(label: str) -> VerseRef:
    """Parse one 'BOOK C:V' label."""
    book, _, cv = label.partition(" ")
    chapter, _, verse = cv.partition(":")
    return VerseRef(book, int(chapter), int(verse))


def _order(ref: VerseRef) -> tuple[int, int]:
    """Chapter/verse order within a book."""
    return ref.chapter, ref.verse


class Linker:
    """Link original-language, NIV and apparatus coordinates to Western (eng.vrs) coordinates."""

    def __init__(self, scripture_root: Path, niv_custom: Path | None = None) -> None:
        """Load eng.vrs and, when given, the NIV project's Custom.vrs over it."""
        self.eng: VersificationSchema = parse_vrs_file(scripture_root / "eng.vrs", schema_id="eng", canonical_id="org")
        custom = parse_vrs_file(niv_custom, schema_id="niv-custom", canonical_id="org") \
            if niv_custom is not None and niv_custom.is_file() else None
        self.niv: VersificationSchema = compose_vrs(self.eng, custom, schema_id="niv")

    @lru_cache(maxsize=None)
    def ol_to_western(self, label: str) -> str:
        """Western coordinate of an org-numbered (Hebrew/Greek edition) verse."""
        local = sorted(self.eng.canonical_to_local(_parse(label)), key=_order)
        return local[0].label() if local else label

    @lru_cache(maxsize=None)
    def western_to_ol(self, label: str) -> tuple[str, ...]:
        """org-numbered coordinates of a Western verse (several at a split or merge)."""
        return tuple(sorted({ref.label() for ref in self.eng.local_to_canonical(_parse(label))}))

    def in_western(self, label: str) -> bool:
        """Whether eng.vrs has this verse."""
        ref = _parse(label)
        limit = self.eng.chapter_limit(ref.book, ref.chapter)
        return limit is not None and 0 <= ref.verse <= limit

    @lru_cache(maxsize=None)
    def english_to_western(self, label: str) -> str:
        """Western coordinate of an English-numbered verse (NIV, NET)."""
        if self.in_western(label):
            return label
        canonical = sorted(self.niv.local_to_canonical(_parse(label)), key=_order)
        local = sorted({ref for item in canonical for ref in self.eng.canonical_to_local(item)}, key=_order)
        return local[0].label() if local else label
