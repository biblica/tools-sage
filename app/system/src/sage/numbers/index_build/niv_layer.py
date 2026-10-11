"""Build the NIV (secondary-authority) number layer and compare it with the original language.

The NIV is read from the operator's local Paratext project (never vendored). What ships is
the evidence the number check needs and no NIV Scripture text (NIV fair use: at most 500 verses):

- typed NIV values with their exact surface words and character offsets in the verse;
- a SHA-256 of the NIV verse text and the number of number-bearing footnotes for every verse
  either layer counts in, so a rebuild can prove it read the same NIV (the text itself is quoted
  from the public-domain BSB instead; NIV is cited as "also see");
- a typed OL/NIV comparison per Western verse (``MATCH_STATUS``), computed from the two
  rebuilt layers rather than written as prose;
- a regression diff against the 2026-09-09 package's ``NIV_VALUES`` with a reason class per
  difference, for review.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
import csv
from dataclasses import dataclass
from fractions import Fraction
import hashlib
from pathlib import Path
import re

from .build import explain
from .english import EnglishValue, count, scan
from .niv import Verse

_NUMBER_WORD = re.compile(
    r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|sixty|"
    r"seventy|eighty|ninety|hundred|thousand|half|third|fourth|fifth|tenth)\b", re.I)


@dataclass(frozen=True)
class NivValue:
    """One counted NIV value at a Western coordinate."""

    ref: str
    expression_no: int
    value: Fraction
    kind: str
    role: str
    unit: str
    surface: str
    start: int
    end: int
    referent: str = ""


def ref_key(label: str) -> tuple:
    """Canonical sort key for a 'BOOK C:V' label (book order supplied by the caller's map)."""
    book, _, cv = label.partition(" ")
    chapter, _, verse = cv.partition(":")
    return book, int(chapter), int(verse)


def typed_niv(verses: "OrderedDict[str, Verse]") -> list[NivValue]:
    """Count every NIV verse."""
    records: list[NivValue] = []
    for ref, verse in verses.items():
        for number, item in enumerate(count(verse.text), 1):
            records.append(_record(ref, number, item))
    return records


def _record(ref: str, number: int, item: EnglishValue) -> NivValue:
    """Place one counted value at its verse."""
    return NivValue(ref, number, item.value, item.kind, item.role, item.unit, item.surface, item.start, item.end,
                    item.referent)


def _values(raw: str) -> list[Fraction]:
    """Parse one package value list ("30;410;1000")."""
    return [Fraction(item) for item in raw.split(";") if item.strip()]


def _join(values) -> str:
    """Write values as one package value list."""
    return ";".join(str(value) for value in values)


def match_status(ol: list[Fraction], niv: list[Fraction]) -> str:
    """Typed OL/NIV agreement, in the reference package's MATCH_STATUS vocabulary."""
    if ol == niv:
        return "PASS_EXACT" if ol else "NO_NUMBERS"
    if Counter(ol) == Counter(niv):
        return "PASS_EQUIVALENT_REORDERED"
    if not niv:
        return "OL_EXPLICIT_NIV_NONEXPLICIT"
    if not ol:
        return "NIV_EXPLICIT_OL_NONEXPLICIT"
    return "DIFFERENT_NUMERIC_EXPRESSION"


def comparison(ol_rows: list[dict[str, str]], niv: list[NivValue], order: dict[str, int]) -> list[dict[str, str]]:
    """One row per Western verse that either layer counts in."""
    ol_by_ref: dict[str, list[dict[str, str]]] = {}
    for row in ol_rows:
        ol_by_ref.setdefault(row["WESTERN_REF"], []).append(row)
    niv_by_ref: dict[str, list[NivValue]] = {}
    for record in niv:
        niv_by_ref.setdefault(record.ref, []).append(record)
    rows = []
    for ref in sorted(set(ol_by_ref) | set(niv_by_ref), key=lambda label: _order(label, order)):
        ol_items = ol_by_ref.get(ref, [])
        niv_items = niv_by_ref.get(ref, [])
        ol_values = [Fraction(row["VALUE"]) for row in ol_items]
        niv_values = [record.value for record in niv_items]
        ol_left = Counter(ol_values) - Counter(niv_values)
        niv_left = Counter(niv_values) - Counter(ol_values)
        rows.append({
            "WESTERN_REF": ref,
            "OL_REFS": " ".join(dict.fromkeys(row["OL_REF"] for row in ol_items)),
            "LANG": " ".join(dict.fromkeys(row["LANG"] for row in ol_items)),
            "OL_VALUES": _join(ol_values),
            "OL_KINDS": ";".join(row["KIND"] for row in ol_items),
            "NIV_VALUES": _join(niv_values),
            "NIV_KINDS": ";".join(record.kind for record in niv_items),
            "MATCH_STATUS": match_status(ol_values, niv_values),
            "OL_ONLY": _join(sorted(ol_left.elements())),
            "NIV_ONLY": _join(sorted(niv_left.elements())),
            "OL_SURFACE": " | ".join(row["SURFACE"] for row in ol_items),
            "NIV_SURFACE": " | ".join(record.surface for record in niv_items),
        })
    return rows


def _order(label: str, order: dict[str, int]) -> tuple:
    """Canonical book order sort key."""
    book, chapter, verse = ref_key(label)
    return order.get(book, 999), chapter, verse


def evidence(verses: "OrderedDict[str, Verse]", refs: set[str]) -> list[dict[str, str]]:
    """Fingerprints (no NIV text) of the verses the index needs: text SHA-256 and number-bearing note count."""
    rows = []
    for ref, verse in verses.items():
        if ref not in refs:
            continue
        notes = [note for note in verse.notes if _NUMBER_WORD.search(note)]
        rows.append({
            "WESTERN_REF": ref,
            "NUMBER_NOTES": str(len(notes)),
            "TEXT_SHA256": hashlib.sha256(verse.text.encode("utf-8")).hexdigest(),
        })
    return rows


def reason(text: str, mine: Counter, theirs: Counter) -> tuple[str, str]:
    """Why the rebuilt NIV values differ from the package, and the decision the convention implies.

    Package-only values that the scope excluded from this verse (``english.scan``) are settled by
    the convention; anything else is left for a reviewer.
    """
    extra_mine, extra_theirs = mine - theirs, theirs - mine
    if not text:
        return "NIV_VERSE_ABSENT", ""
    if not extra_mine:
        removed = [(item.value, item.reason) for item in scan(text)[1]]
        removed += [(1 / value, why) for value, why in removed if why == "RANK_ORDINAL" and value]  # "a third kingdom"
        why = explain(extra_theirs, removed)
        if why:
            return f"SCOPE: {why}", "REBUILT"
    if extra_mine and extra_theirs and sorted(extra_mine.elements()) == sorted(
            1 / value for value in extra_theirs.elements() if value):
        return "ORDINAL_FRACTION_READING", ""
    return "OTHER", ""


def regression(niv: list[NivValue], package_rows: list[dict[str, str]],
               verses: "OrderedDict[str, Verse]") -> list[dict[str, str]]:
    """Every package row whose NIV_VALUES differ from the rebuilt NIV layer, then every
    rebuilt verse the package has no row for (status NEW)."""
    built: dict[str, list[NivValue]] = {}
    for record in niv:
        built.setdefault(record.ref, []).append(record)
    rows = []
    known = {f"{row['BK']} {row['CH']}:{row['VS']}" for row in package_rows}
    package_rows = list(package_rows) + [{"BK": ref.split()[0], "CH": ref_key(ref)[1], "VS": ref_key(ref)[2],
                                          "NIV_VALUES": ""} for ref in built if ref not in known]
    for row in package_rows:
        ref = f"{row['BK']} {row['CH']}:{row['VS']}"
        mine = [record.value for record in built.get(ref, ())]
        theirs = _values(row["NIV_VALUES"])
        if Counter(mine) == Counter(theirs):
            continue
        text = verses[ref].text if ref in verses else ""
        why, suggested = reason(text, Counter(mine), Counter(theirs))
        status = "NEW" if not theirs else "DROPPED" if not mine else "CHANGED"
        rows.append({
            "WESTERN_REF": ref, "STATUS": status, "REBUILT_VALUES": _join(mine), "INDEX_VALUES": row["NIV_VALUES"],
            "REBUILT_SURFACE": " | ".join(record.surface for record in built.get(ref, ())),
            "REASON": why, "SUGGESTED_DECISION": suggested,
        })
    return rows
