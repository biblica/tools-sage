"""Numeric candidates for RTC and STC from the NCA number index."""

from __future__ import annotations

from fractions import Fraction
from types import SimpleNamespace

import sage.numeric_candidates as numeric
from sage.vrs import VerseRef


def test_digits_matching_the_index_need_no_model_finding(monkeypatch) -> None:
    """MATCH, DIFFERS, and NOT_IN_DIGITS rows carry the index caveat; verses with no numbers are skipped."""
    rows = {
        VerseRef("NUM", 1, 46): SimpleNamespace(ol_values=(Fraction(603550),), niv_values=(Fraction(603550),)),
        VerseRef("NUM", 1, 47): SimpleNamespace(ol_values=(Fraction(22),), niv_values=()),
        VerseRef("NUM", 1, 48): SimpleNamespace(ol_values=(Fraction(3),), niv_values=()),
    }
    monkeypatch.setattr(numeric, "_bundle", lambda _config: SimpleNamespace(package_id="IDX", rows=rows))

    result = numeric.numeric_candidates(
        None,
        [
            (VerseRef("NUM", 1, 46), "NUM 1:46", "The total was 603,550 men."),
            (VerseRef("NUM", 1, 47), "NUM 1:47", "There were 23 of them."),
            (VerseRef("NUM", 1, 48), "NUM 1:48", "There were three of them."),
            (VerseRef("NUM", 1, 49), "NUM 1:49", "No numbers here."),
        ],
    )

    assert result["index_package"] == "IDX"
    assert "WLC" in result["caveat"] and "SBLGNT" in result["caveat"]
    assert [(row["reference"], row["status"]) for row in result["rows"]] == [
        ("NUM 1:46", "MATCH"),
        ("NUM 1:47", "DIFFERS"),
        ("NUM 1:48", "NOT_IN_DIGITS"),
    ]
    assert result["rows"][1]["wip_digit_values"] == ["23"]


def test_missing_index_reports_unavailable_instead_of_failing(monkeypatch) -> None:
    """Without the bundled index the candidates say so and list nothing."""
    monkeypatch.setattr(numeric, "_bundle", lambda _config: None)
    assert numeric.numeric_candidates(None, [])["status"] == "INDEX_UNAVAILABLE"
