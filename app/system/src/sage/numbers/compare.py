"""Deterministic, local comparison of WIP-extracted numbers against the index.

Per the 2026-09-28 simplified-check rewrite: no model call, no per-reference-row
adjudication. Two modes, chosen by policy before the Run (numbers/policy.py's
`numeric_comparison_mode`), because unordered set comparison cannot distinguish
a legitimate reordering from a real swapped-referent error -- see the plan's
"one real tradeoff this plan must not paper over."

- UNORDERED: multiset equality. Never false-positives on reordering; never
  catches a swap (by design, not oversight).
- ORDERED: exact sequence equality. Catches a swap; a multiset-equal but
  differently-ordered WIP extraction is not silently passed or failed -- it
  is reported NEEDS_REVIEW with the OL/NIV source text attached, so a human
  reviewer can judge a genuine reordering from a real swap quickly. This is
  transparent surfacing, not an automated black-box resolution.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping, Tuple

from .models import COMPARISON_MODES, COMPARISON_OUTCOMES, ReferenceRow


def _enum(field_name: str, value: str, allowed: frozenset[str]) -> None:
    """Require one value to belong to its closed comparator vocabulary."""
    if value not in allowed:
        raise ValueError(f"Invalid NCA comparator {field_name}: {value!r}")


@dataclass(frozen=True)
class ComparisonResult:
    """One group's numeric comparison outcome, with both orderings for review."""

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
        if self.authority not in {"OL", "NIV", "NONE"}:
            raise ValueError(f"Invalid NCA comparator authority: {self.authority!r}")
        if self.review_context is None:
            object.__setattr__(self, "review_context", {})
        if self.outcome == "NEEDS_REVIEW" and not self.review_context:
            raise ValueError("NEEDS_REVIEW requires review_context evidence")


def compare_values(
    wip_values: Tuple[Fraction, ...],
    row: ReferenceRow | None,
    *,
    mode: str,
) -> ComparisonResult:
    """Compare WIP-extracted values to the indexed OL (Authority 1) or NIV (secondary) values.

    Returns NOT_ASSESSED when the coordinate has no indexed reference row (never treats
    an absent row as an authoritative zero-number expectation).
    """
    _enum("mode", mode, COMPARISON_MODES)
    if row is None:
        return ComparisonResult("NOT_ASSESSED", mode, wip_values, (), "NONE")
    if row.ol_values:
        expected, authority = row.ol_values, "OL"
    elif row.niv_values:
        expected, authority = row.niv_values, "NIV"
    else:
        return ComparisonResult("NOT_ASSESSED", mode, wip_values, (), "NONE")
    if mode == "UNORDERED":
        outcome = "PASS" if Counter(wip_values) == Counter(expected) else "FAIL"
        return ComparisonResult(outcome, mode, wip_values, expected, authority)
    if wip_values == expected:
        return ComparisonResult("PASS", mode, wip_values, expected, authority)
    if Counter(wip_values) == Counter(expected):
        # Same values, different order: could be a legitimate translation reordering,
        # or the exact swapped-referent error ORDERED mode exists to catch. Never guess --
        # surface both orderings and the OL/NIV source text for a human to judge.
        context = {
            "wip_order": [str(value) for value in wip_values],
            "expected_order": [str(value) for value in expected],
            "authority_text": row.ol_text if authority == "OL" else row.niv_text,
        }
        return ComparisonResult("NEEDS_REVIEW", mode, wip_values, expected, authority, context)
    return ComparisonResult("FAIL", mode, wip_values, expected, authority)
