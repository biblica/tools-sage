"""Numeric candidates for RTC and STC from the NCA number index, so the model skips what code settles.

For each WIP verse that the number index covers or that carries digit numerals, the WIP's digit values
are compared with the index values. A verse whose digits match needs no number finding; a verse whose
digits differ, or that writes its numbers in words, is a candidate for the model and for an NCA Run.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Mapping

from .errors import ValidationError
from .registry import EcosystemConfig
from .vrs import VerseRef

# The index values are keyed to the WLC and SBLGNT editions, not to the bundled OL SFM editions.
INDEX_EDITION_CAVEAT = (
    "Index values follow the WLC (Hebrew) and SBLGNT (Greek) editions; the bundled original-language "
    "texts can differ from them in rare places."
)
_BUNDLE_CACHE: dict[Path, Any] = {}


def _bundle(config: EcosystemConfig) -> Any | None:
    """Return the qualified bundled number index once per process, or None when it is unavailable."""
    from .numbers.resources import reference_package_path, resolve_reference_package

    try:
        path = reference_package_path(config)
        if path not in _BUNDLE_CACHE:
            _BUNDLE_CACHE[path] = resolve_reference_package(config)
        return _BUNDLE_CACHE[path]
    except ValidationError:
        return None


def _label(value: Fraction) -> str:
    """Render one value the way the index writes it."""
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def numeric_candidates(config: EcosystemConfig, verses: Iterable[tuple[VerseRef, str, str]]) -> dict[str, Any]:
    """Classify WIP verses ``(reference, label, plain text)`` against the number index.

    Returns the index identity, the edition caveat, and one row per verse with index values or WIP digits:
    ``MATCH`` (the WIP digits are exactly the index values), ``DIFFERS``, or ``NOT_IN_DIGITS``.
    """
    from .numbers.numerals import find_numerals

    bundle = _bundle(config)
    if bundle is None:
        return {"status": "INDEX_UNAVAILABLE", "caveat": INDEX_EDITION_CAVEAT, "rows": []}
    rows: list[dict[str, Any]] = []
    for reference, label, text in verses:
        row = bundle.rows.get(reference)
        expected = set(row.ol_values) | set(row.niv_values) if row is not None else set()
        numerals = find_numerals(text)
        wip_values = {value for numeral in numerals for value in numeral.readings[:1]}
        if not expected and not wip_values:
            continue
        if not wip_values:
            status = "NOT_IN_DIGITS"
        elif wip_values == expected:
            status = "MATCH"
        else:
            status = "DIFFERS"
        rows.append(
            {
                "reference": label,
                "status": status,
                "index_values": sorted(_label(value) for value in expected),
                "wip_digit_values": sorted(_label(value) for value in wip_values),
            }
        )
    return {
        "status": "AVAILABLE",
        "index_package": bundle.package_id,
        "caveat": INDEX_EDITION_CAVEAT,
        "rows": rows,
    }


def packet_verses(packet: Path) -> list[tuple[VerseRef, str, str]]:
    """Return ``(reference, label, plain text)`` for each verse of a bounded USJ packet."""
    import json

    from .usj import visible_text

    try:
        usj = json.loads(packet.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    book = str(usj.get("sage", {}).get("book_code") or "")
    verses: list[tuple[VerseRef, str, str]] = []
    for item in usj.get("sage", {}).get("verse_records", []):
        if not isinstance(item, Mapping):
            continue
        start, end = int(item["verse_start"]), int(item["verse_end"])
        label = f"{book} {item['chapter']}:{start}" + (f"-{end}" if end != start else "")
        verses.append((VerseRef(book, int(item["chapter"]), start), label, visible_text(item.get("content") or [])))
    return verses
