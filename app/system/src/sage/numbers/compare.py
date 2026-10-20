"""Deterministic, local comparison of WIP-extracted numbers against the index.

No model call. Two modes, chosen by policy before the Run (numbers/policy.py's
`numeric_comparison_mode`), because unordered set comparison cannot distinguish
a legitimate reordering from a real swapped-referent error:

- UNORDERED: multiset equality. Never false-positives on reordering; never
  catches a swap (by design, not oversight).
- ORDERED: exact sequence equality. A multiset-equal but differently-ordered
  WIP extraction is NEEDS_REVIEW with the OL/NIV source text attached.

A BLOCKING FAIL is reserved for a mismatch against an original-language (OL)
reading the index actually vouches for. Every other mismatch is NEEDS_REVIEW,
because the index itself says the reading is not authoritative there:

- NIV-only rows (OL has no explicit number) and bridged groups that mix OL and
  NIV authority -- the index's own guidance is "do not auto-validate from NIV";
- the WIP follows a registered alternate (textual-variant) reading;
- OL_VALUES was normalized away from the literal OL tokens (normalization
  overrides): undocumented verse overrides always, documented ones when undoing
  them reproduces the WIP values (EZR 1:10 drops OL "second");
- the WIP follows the NIV where the NIV differs from the original language (decision D1);
- the only difference is extra WIP values the extractor tagged as convention
  edge cases (ordinals, multipliers, percentages, approximations);
- the index value at that verse is rebuilt but not yet reviewed (typed packages,
  REVIEW_STATUS PROVISIONAL).

A WIP that matches neither the original language nor the NIV is a FAIL (a mistyped or misread
number). With the same numbers as the source, each number must sit on the same item: a swap
("1 000 gold dishes" for "30 gold dishes") is a FAIL ``WRONG_ASSOCIATION`` where the original
language vouches for the items (review elsewhere); a faithful reordering is a PASS with a note.
Two FAILs concern the WIP's own digits, whatever the source authority: a malformed numeral
(``MALFORMED_NUMERAL``) and a digit numeral where the source has no number
(``NUMBER_NOT_IN_SOURCE``, numbers/grouping.py); both are typing defects, not readings.

Every comparison that is not a PASS carries the OL and NIV text, values and
match status as review evidence, FAIL included.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from typing import Mapping, Sequence, Tuple

from .models import COMPARISON_MODES, COMPARISON_OUTCOMES, ReferenceRow

AUTHORITIES = frozenset({"OL", "NIV", "MIXED", "NONE"})
REVIEW_KINDS = frozenset({
    "ORDER_DIFFERENCE",
    "NIV_ONLY_AUTHORITY",
    "MIXED_AUTHORITY",
    "ATTESTED_VARIANT_READING",
    "OL_NORMALIZED_UNDOCUMENTED",
    "OL_NORMALIZATION_DIFFERENCE",
    "MATCHES_SECONDARY_AUTHORITY",
    "CONVENTION_EDGE_CASE",
    "NO_INDEXED_VALUES",
    "PROVISIONAL_INDEX",
    "APPARATUS_VARIANT",
    "ONE_ONLY_DIFFERENCE",
    "VALUE_OMITTED",
    "VALUE_ADDED",
    "UNIT_CONVERSION",
    "WRONG_ASSOCIATION",  # on NIV-only or mixed groups (BLOCKING only under OL authority)
})
# FAIL kinds: a value differs from the source, a number sits on the wrong item, a numeral is
# malformed, or a digit numeral stands in a verse the source has no number for.
FAIL_KINDS = frozenset({"VALUE_DIFFERENCE", "WRONG_ASSOCIATION", "MALFORMED_NUMERAL", "NUMBER_NOT_IN_SOURCE"})
# Extracted value kinds the counting convention marks as edge cases: an extra WIP value
# of one of these kinds is a convention question for review, not a numeric error.
EDGE_KINDS = frozenset({"ORDINAL", "MULTIPLIER", "PERCENT", "APPROX"})
_UNDOCUMENTED_OVERRIDE_LAYER = "FINAL_OL_VERSE_OVERRIDE"
_MAX_REVERSIBLE_OVERRIDES = 8


def _enum(field_name: str, value: str, allowed: frozenset[str]) -> None:
    """Require one value to belong to its closed comparator vocabulary."""
    if value not in allowed:
        raise ValueError(f"Invalid NCA comparator {field_name}: {value!r}")


@dataclass(frozen=True)
class ComparisonResult:
    """One group's numeric comparison outcome with its review evidence."""

    outcome: str
    mode: str
    wip_values: Tuple[Fraction, ...]
    expected_values: Tuple[Fraction, ...]
    authority: str
    review_context: Mapping[str, object] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        """Validate the closed vocabularies and freeze optional review context."""
        _enum("outcome", self.outcome, COMPARISON_OUTCOMES)
        _enum("mode", self.mode, COMPARISON_MODES)
        _enum("authority", self.authority, AUTHORITIES)
        if self.review_context is None:
            object.__setattr__(self, "review_context", {})
        if self.outcome == "NEEDS_REVIEW":
            if not self.review_context:
                raise ValueError("NEEDS_REVIEW requires review_context evidence")
            _enum("review kind", str(self.review_context.get("kind")), REVIEW_KINDS)


@dataclass(frozen=True)
class AlternateReading:
    """One registered alternate reading the WIP may legitimately follow at one reference."""

    reference: str
    values: Tuple[Fraction, ...]
    guidance: Mapping[str, str]


def _parsed(raw: str) -> Counter:
    """Parse one override value list (semicolon-separated, blank allowed) into a multiset."""
    return Counter(Fraction(item.strip()) for item in raw.split(";") if item.strip())


def _reverse(expected: Counter, override: Mapping[str, str]) -> Counter | None:
    """Undo one documented override on the expected multiset, or None when it cannot apply."""
    final, original = _parsed(override["FINAL_VALUES"]), _parsed(override["ORIGINAL_VALUES"])
    if final - expected:
        return None
    return expected - final + original


def _normalization_explains(
    wip_values: Tuple[Fraction, ...],
    expected_values: Tuple[Fraction, ...],
    overrides: Sequence[Mapping[str, str]],
) -> bool:
    """Whether undoing some subset of documented overrides reproduces the WIP multiset."""
    target, base = Counter(wip_values), Counter(expected_values)
    documented = [item for item in overrides if item["LAYER"] != _UNDOCUMENTED_OVERRIDE_LAYER]
    documented = documented[:_MAX_REVERSIBLE_OVERRIDES]
    for size in range(1, len(documented) + 1):
        for subset in combinations(documented, size):
            reading: Counter | None = base
            for override in subset:
                reading = _reverse(reading, override)
                if reading is None:
                    break
            if reading is not None and reading == target:
                return True
    return False


def _row_part(row: ReferenceRow) -> tuple[Tuple[Fraction, ...], str]:
    """Return one row's expected values and the authority that supplies them."""
    if row.ol_values:
        return row.ol_values, "OL"
    if row.niv_values:
        return row.niv_values, "NIV"
    return (), "NONE"


def _authority(parts: Sequence[str]) -> str:
    """Combine per-row authorities; rows without values do not dilute the authority."""
    used = {part for part in parts if part != "NONE"}
    if not used:
        return "NONE"
    return used.pop() if len(used) == 1 else "MIXED"


def apparatus_entries(rows: Sequence[ReferenceRow]) -> list[dict[str, object]]:
    """Structured apparatus evidence of the rows (typed packages; empty otherwise)."""
    import json
    found = []
    for row in rows:
        raw = str(row.metadata.get("TC_EVIDENCE") or "")
        if raw.startswith("["):
            found.extend({**item, "reference": row.western_reference.label()} for item in json.loads(raw))
    return found


def _evidence(rows: Sequence[ReferenceRow]) -> dict[str, object]:
    """Collect the OL/NIV text, values, index status and apparatus a reviewer needs for one group."""
    return {
        "apparatus": apparatus_entries(rows),
        "references": [row.western_reference.label() for row in rows],
        "ol_text": " ".join(row.ol_text for row in rows if row.ol_text),
        "ol_values": [str(value) for row in rows for value in row.ol_values],
        "bsb_text": " ".join(row.bsb_text for row in rows if row.bsb_text),
        "niv_values": [str(value) for row in rows for value in row.niv_values],
        "match_status": [str(row.metadata.get("MATCH_STATUS", "")) for row in rows],
    }


def _review(kind: str, mode: str, wip: Tuple[Fraction, ...], expected: Tuple[Fraction, ...],
            authority: str, evidence: Mapping[str, object], **extra: object) -> ComparisonResult:
    """Build one NEEDS_REVIEW result carrying its kind and the shared evidence."""
    return ComparisonResult("NEEDS_REVIEW", mode, wip, expected, authority,
                            {"kind": kind, **evidence, **extra})


def _edge_case_only(wip: Tuple[Fraction, ...], expected: Tuple[Fraction, ...],
                    kinds: Sequence[str]) -> bool:
    """Whether the only difference is extra WIP values tagged as convention edge cases."""
    if len(kinds) != len(wip) or Counter(expected) - Counter(wip):
        return False
    extra = Counter(wip) - Counter(expected)
    edge = Counter(value for value, kind in zip(wip, kinds) if kind in EDGE_KINDS)
    return bool(extra) and not (extra - edge)


def _one_only(wip: Tuple[Fraction, ...], expected: Tuple[Fraction, ...]) -> bool:
    """Whether the WIP differs from the source only by added or missing values of 1."""
    difference = (Counter(wip) - Counter(expected)) + (Counter(expected) - Counter(wip))
    return bool(difference) and set(difference) == {Fraction(1)}


def _omission_only(wip: Tuple[Fraction, ...], expected: Tuple[Fraction, ...]) -> bool:
    """Whether every WIP value is in the source and the WIP only leaves some source values out."""
    return not (Counter(wip) - Counter(expected)) and bool(Counter(expected) - Counter(wip))


def _addition_only(wip: Tuple[Fraction, ...], expected: Tuple[Fraction, ...]) -> bool:
    """Whether the WIP keeps every source value and only adds numbers the source does not state."""
    return not (Counter(expected) - Counter(wip)) and bool(Counter(wip) - Counter(expected))


def _words(text: str) -> set[str]:
    """Lowercased content words of an English gloss, plural -s removed ("talents" -> "talent")."""
    from .association import _tokens
    return _tokens(text.replace(".", " "))


def _unit_conversions(wip: Tuple[Fraction, ...], expected: Tuple[Fraction, ...], rows: Sequence[ReferenceRow],
                      wip_kinds: Sequence[str], wip_counts_en: Sequence[str]) -> list[dict[str, str]]:
    """Source values the WIP states in another unit, each with the WIP value; [] unless that explains it all.

    Two deterministic patterns, as the NVI and NIV render them: an hour of the day as clock time
    (the 11th hour is 5 in the afternoon: ``(hour + 6) mod 12``), and a measure restated in a
    different unit with one scale factor for every value (5 and 2 talents as 5,000 and 2,000 coins).
    A WIP "one" left over may be the stated "a day's wage" or "to another, one [talent]".
    """
    items = [item for row in rows for item in row.ol_items]
    missing = Counter(expected) - Counter(wip)
    extra = Counter(wip) - Counter(expected)
    if not missing or not extra:
        return []
    kinds = dict(zip(wip, wip_kinds)) if len(wip_kinds) == len(wip) else {}
    glosses = dict(zip(wip, wip_counts_en)) if len(wip_counts_en) == len(wip) else {}
    def unit(value: Fraction) -> dict[str, str] | None:
        """The OL item that carries this value, with its unit and role."""
        return next((item for item in items if Fraction(item["VALUE"]) == value), None)
    conversions: list[dict[str, str]] = []
    for value in list(missing.elements()):
        item = unit(value)
        if item is None or item.get("KIND") != "ORDINAL" or "hour" not in _words(item.get("UNIT", "")):
            continue
        clock = Fraction((int(value) + 6) % 12 or 12) if value.denominator == 1 and 1 <= value <= 12 else None
        if clock is not None and extra[clock] and kinds.get(clock) != "ORDINAL":
            conversions.append({"ol_value": str(value), "ol_unit": "hour of the day", "wip_value": str(clock),
                                "conversion": "HOUR_TO_CLOCK"})
            missing[value] -= 1
            extra[clock] -= 1
    measures = [value for value in (+missing).elements()
                if (unit(value) or {}).get("ROLE") == "MEASURE" and (unit(value) or {}).get("UNIT")]
    if measures and len(measures) == sum((+missing).values()):
        factor = max(extra.elements()) / max(measures)
        scaled = [value * factor for value in measures]
        source_units = set().union(*(_words(unit(value)["UNIT"]) for value in measures))
        changed = all(glosses.get(value) and not (_words(glosses[value]) & source_units) for value in scaled)
        if factor != 1 and changed and not Counter(scaled) - extra:
            for value, converted in zip(measures, scaled):
                conversions.append({"ol_value": str(value), "ol_unit": unit(value)["UNIT"].replace(".", " "),
                                    "wip_value": str(converted), "wip_unit": glosses[converted],
                                    "conversion": "UNIT_SCALED"})
                missing[value] -= 1
                extra[converted] -= 1
            if extra[factor] and glosses.get(factor) and not (_words(glosses[factor]) & source_units):
                extra[factor] -= 1  # "and to another, one [talent]" restated as 1,000 coins
    if +missing or set((+extra).elements()) - {Fraction(1)}:
        return []
    return conversions


def _source_referents(rows: Sequence[ReferenceRow], expected: Tuple[Fraction, ...]) -> tuple[list, list]:
    """Source values with what each counts: NIV wording when it has the same numbers, else the OL gloss."""
    niv_items = [item for row in rows for item in row.niv_items]
    ol_items = [item for row in rows for item in row.ol_items]
    for items in (niv_items, ol_items):
        values = [Fraction(item["VALUE"]) for item in items]
        if items and Counter(values) == Counter(expected) and any(item.get("REFERENT") for item in items):
            return values, [str(item.get("REFERENT") or "") for item in items]
    return [], []


def compare_group(
    wip_values: Tuple[Fraction, ...],
    rows: Sequence[ReferenceRow],
    *,
    mode: str,
    alternates: Sequence[AlternateReading] = (),
    wip_kinds: Sequence[str] = (),
    wip_counts_en: Sequence[str] = (),
    wip_issues: Sequence[str] = (),
) -> ComparisonResult:
    """Compare one group's WIP numbers with its indexed rows (in reference order).

    An empty ``rows`` means no coordinate in the group is indexed: the index holds a row
    for every verse with a number in OL or NIV, so the group is NOT_INDEXED rather than an
    assessment gap. ``wip_kinds`` and ``wip_counts_en`` (English gloss of what each number
    counts) are parallel to ``wip_values``; ``wip_issues`` are numeral problems SAGE found.
    """
    from .association import check
    _enum("mode", mode, COMPARISON_MODES)
    if not rows:
        return ComparisonResult("NOT_INDEXED", mode, wip_values, (), "NONE")
    parts = [_row_part(row) for row in rows]
    expected = tuple(value for values, _authority_part in parts for value in values)
    authority = _authority([part for _values, part in parts])
    evidence = _evidence(rows)
    malformed = [issue.split(":", 1)[1] for issue in wip_issues if issue.startswith("MALFORMED_NUMERAL:")]
    if malformed:
        return ComparisonResult("FAIL", mode, wip_values, expected, authority,
                                {"kind": "MALFORMED_NUMERAL", "numerals": malformed, **evidence})
    if Counter(wip_values) == Counter(expected):
        source_values, referents = _source_referents(rows, expected)
        association = check(wip_values, list(wip_counts_en), source_values, referents)
        pairing = [{"wip_value": str(item.wip_value), "wip_counts": item.wip_counts,
                    "source_value": "" if item.source_value is None else str(item.source_value),
                    "source_referent": item.source_referent} for item in association.pairings]
        if association.verdict == "WRONG":
            # BLOCKING only where the original language vouches for the items; an NIV-only or
            # mixed group reports the same evidence for review.
            return ComparisonResult("FAIL" if authority == "OL" else "NEEDS_REVIEW", mode, wip_values,
                                    expected, authority,
                                    {"kind": "WRONG_ASSOCIATION", "pairings": pairing,
                                     "source_items": [{"value": str(v), "referent": r}
                                                      for v, r in zip(source_values, referents)], **evidence})
        if mode == "UNORDERED" or wip_values == expected or association.verdict == "CONFIRMED":
            note = ({"note": "ORDER_DIFFERS_ITEMS_MATCH", "pairings": pairing}
                    if wip_values != expected else {})
            return ComparisonResult("PASS", mode, wip_values, expected, authority, note)
        # Same values, different order, and the items could not be matched: a reviewer decides.
        return _review("ORDER_DIFFERENCE", mode, wip_values, expected, authority, evidence,
                       wip_order=[str(value) for value in wip_values],
                       expected_order=[str(value) for value in expected],
                       authority_text=evidence["ol_text"] if authority == "OL" else evidence["bsb_text"],
                       authority_text_source="OL" if authority == "OL" else "BSB")
    for alternate in alternates:
        if Counter(wip_values) == Counter(alternate.values):
            return _review("ATTESTED_VARIANT_READING", mode, wip_values, expected, authority, evidence,
                           variant_reference=alternate.reference,
                           alternate_values=[str(value) for value in alternate.values],
                           variant_guidance=dict(alternate.guidance))
    if authority == "NONE":
        return _review("NO_INDEXED_VALUES", mode, wip_values, expected, authority, evidence)
    if authority == "NIV":
        return _review("NIV_ONLY_AUTHORITY", mode, wip_values, expected, authority, evidence)
    if authority == "MIXED":
        return _review("MIXED_AUTHORITY", mode, wip_values, expected, authority, evidence)
    overrides = [item for row in rows for item in row.ol_normalizations]
    if any(item["LAYER"] == _UNDOCUMENTED_OVERRIDE_LAYER for item in overrides):
        return _review("OL_NORMALIZED_UNDOCUMENTED", mode, wip_values, expected, authority, evidence,
                       normalizations=[dict(item) for item in overrides])
    if overrides and _normalization_explains(wip_values, expected, overrides):
        return _review("OL_NORMALIZATION_DIFFERENCE", mode, wip_values, expected, authority, evidence,
                       normalizations=[dict(item) for item in overrides])
    niv = tuple(value for row in rows for value in row.niv_values)
    if Counter(niv) != Counter(expected) and Counter(wip_values) == Counter(niv):
        # Follows the NIV where it differs from the original language (decision D1): review.
        return _review("MATCHES_SECONDARY_AUTHORITY", mode, wip_values, expected, authority, evidence)
    conversions = _unit_conversions(wip_values, expected, rows, wip_kinds, wip_counts_en)
    if conversions:
        # Release gate 2026-10-20: the NVI states hours as clock time and talents as coins, as the
        # NIV does. A faithful conversion is a consistency and style question, not a wrong number.
        return _review("UNIT_CONVERSION", mode, wip_values, expected, authority, evidence,
                       conversions=conversions)
    if any(row.metadata.get("OL_REVIEW_STATUS") == "PROVISIONAL" for row in rows):
        # The index value here is rebuilt but not yet reviewed: report, never FAIL.
        return _review("PROVISIONAL_INDEX", mode, wip_values, expected, authority, evidence)
    if _edge_case_only(wip_values, expected, wip_kinds):
        return _review("CONVENTION_EDGE_CASE", mode, wip_values, expected, authority, evidence,
                       wip_kinds=list(wip_kinds))
    if _one_only(wip_values, expected):
        # Release gate 2026-10-18: "one" is where languages differ most (an implied singular made
        # explicit, "year-old" read as 1); both judges called every such FAIL a false alarm.
        return _review("ONE_ONLY_DIFFERENCE", mode, wip_values, expected, authority, evidence)
    if _omission_only(wip_values, expected):
        # Release gate 2026-10-18: a WIP that states a repeated number once ("twenty cubits long and
        # wide") or folds it into an idiom is a style choice to confirm; every measured genuine FAIL
        # was a different value, never a pure omission. PO decision 2026-10-18: review, not BLOCKING.
        return _review("VALUE_OMITTED", mode, wip_values, expected, authority, evidence,
                       omitted=[str(value) for value in (Counter(expected) - Counter(wip_values)).elements()])
    if _addition_only(wip_values, expected):
        # REV 11:4 "these two witnesses": a number made explicit from context. PO decision 2026-10-20:
        # an added number is always review, never BLOCKING.
        return _review("VALUE_ADDED", mode, wip_values, expected, authority, evidence,
                       added=[str(value) for value in (Counter(wip_values) - Counter(expected)).elements()])
    if any(row.metadata.get("TC_STATUS") == "VARIANT_ATTESTED" for row in rows):
        # The apparatus records a number variant here: the WIP may follow another witness. Review.
        return _review("APPARATUS_VARIANT", mode, wip_values, expected, authority, evidence)
    # Matches neither the original language nor the NIV: a wrong number (likely mistyped or misread).
    return ComparisonResult("FAIL", mode, wip_values, expected, authority,
                            {"kind": "VALUE_DIFFERENCE", **evidence})


def compare_values(
    wip_values: Tuple[Fraction, ...],
    row: ReferenceRow | None,
    *,
    mode: str,
    alternates: Sequence[AlternateReading] = (),
    wip_kinds: Sequence[str] = (),
    wip_counts_en: Sequence[str] = (),
    wip_issues: Sequence[str] = (),
) -> ComparisonResult:
    """Compare one single-coordinate group; ``row=None`` means the coordinate is not indexed."""
    return compare_group(wip_values, [row] if row is not None else [], mode=mode,
                         alternates=alternates, wip_kinds=wip_kinds, wip_counts_en=wip_counts_en,
                         wip_issues=wip_issues)


def not_assessed(mode: str) -> ComparisonResult:
    """Placeholder outcome for a group whose numbers could not be compared."""
    _enum("mode", mode, COMPARISON_MODES)
    return ComparisonResult("NOT_ASSESSED", mode, (), (), "NONE")
