"""Deterministic cross-reference, footnote, and add/nd marker checks."""

from __future__ import annotations

import json

from sage.marker_checks import marker_review, packet_marker_candidates, verse_markers
from sage.usj import compile_usfm_text
from sage.verse_alignment import ProjectVerseIndex
from sage.vrs import parse_vrs_file
from sage.work_units import EvidenceRecord


def _content(usfm_verse: str) -> list:
    """Compile one MAT 1:1 verse and return its USJ inline content."""
    usj = compile_usfm_text(f"\\id MAT\n\\c 1\n\\v 1 {usfm_verse}\n", "41MAT.SFM")
    return usj["sage"]["verse_records"][0]["content"]


def _record() -> EvidenceRecord:
    """Return the MAT 1:1 evidence record."""
    return EvidenceRecord(
        book="MAT", chapter=1, verse_start=1, verse_end=1, payload={"body_text": "x"},
        section_id="S", paragraph_id="P", discourse_unit_id="D", discourse_unit_kind="PARAGRAPH",
        discourse_unit_marker="p",
    )


def _review(tmp_path, wip_verse: str, reference_verse: str) -> dict:
    """Review one WIP verse against one REFERENCE verse at the same coordinate."""
    vrs = tmp_path / "mat.vrs"
    vrs.write_text("MAT 1:1\n", encoding="utf-8")
    schema = parse_vrs_file(vrs, schema_id="mat", canonical_id="org.vrs")
    record = _record()
    key = ("MAT", 1, 1, 1)
    return marker_review(
        [record],
        {key: _content(wip_verse)},
        ProjectVerseIndex.build("WIP", [record], schema),
        ProjectVerseIndex.build("REF", [record], schema),
        {key: _content(reference_verse)},
        wip_project_id="WIP",
        reference_project_id="REF",
    )


def test_verse_markers_summarize_targets_footnotes_and_spans() -> None:
    """Targets keep only chapter:verse numbers because book names are localized."""
    summary = verse_markers(
        _content("The \\nd Lord\\nd* \\add was\\add* here.\\f + \\fr 1:1 \\ft Note.\\f*\\x - \\xt Gen 1:1; Jn 1:1-3\\x*")
    )
    assert summary["targets"] == {(1, 1, 1), (1, 1, 3)}
    assert summary["footnotes"] == [{"origin": "1:1", "has_text": True}]
    assert (summary["add"], summary["nd"]) == (1, 1)


def test_cross_reference_target_difference_is_a_finding(tmp_path) -> None:
    """A target the REFERENCE has and the WIP lacks is reported in code."""
    result = _review(tmp_path, "Text.\\x - \\xt Gén 1:1\\x*", "Text.\\x - \\xt Gen 1:1; Ps 2:7\\x*")
    [finding] = result["findings"]
    assert finding["category"] == "STRUCTURE"
    assert "REF only: 2:7" in finding["issue"]
    assert _review(tmp_path, "Text.\\x - \\xt Gén 1:1\\x*", "Text.\\x - \\xt Gen 1:1\\x*")["findings"] == []


def test_footnote_with_wrong_origin_or_no_text_is_a_finding(tmp_path) -> None:
    """A footnote must name its own verse and carry text."""
    result = _review(tmp_path, "Text.\\f + \\fr 2:4 \\ft \\f*", "Text.")
    issues = [row["issue"] for row in result["findings"]]
    assert any("names origin 2:4" in issue for issue in issues)
    assert any("no footnote text" in issue for issue in issues)


def test_add_and_nd_count_differences_are_candidates_not_findings(tmp_path) -> None:
    """Whether a missing \\nd matters is the model's call; code only lists the difference."""
    result = _review(tmp_path, "The Lord spoke.", "The \\nd Lord\\nd* spoke.")
    assert result["findings"] == []
    assert result["candidates"] == [
        {"target_reference": "MAT 1:1", "marker": "nd", "wip_count": 0, "reference_count": 1}
    ]


def test_packet_marker_candidates_compare_the_routed_usj_packets(tmp_path) -> None:
    """The preflight lists add/nd differences for the task's own verses."""
    wip = tmp_path / "wip.usj"
    reference = tmp_path / "ref.usj"
    wip.write_text(json.dumps(compile_usfm_text("\\id MAT\n\\c 1\n\\v 1 The Lord.\n", "w")), encoding="utf-8")
    reference.write_text(
        json.dumps(compile_usfm_text("\\id MAT\n\\c 1\n\\v 1 The \\nd Lord\\nd*.\n", "r")), encoding="utf-8"
    )
    assert packet_marker_candidates(wip, reference) == [
        {"target_reference": "MAT 1:1", "marker": "nd", "wip_count": 0, "reference_count": 1}
    ]
