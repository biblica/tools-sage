"""Deterministic WIP omission detection against REFERENCE or original-language text."""

from __future__ import annotations

from sage.references import parse_scope
from sage.text_coverage import gap_findings, omission_rows, psalm_title_chapters
from sage.verse_alignment import ProjectVerseIndex
from sage.vrs import parse_vrs_file
from sage.work_units import EvidenceRecord


def _record(book: str, chapter: int, verse: int, text: str) -> EvidenceRecord:
    """Build one synthetic verse record."""
    return EvidenceRecord(
        book=book,
        chapter=chapter,
        verse_start=verse,
        verse_end=verse,
        payload={"body_text": text},
        section_id="S1",
        paragraph_id="P1",
        discourse_unit_id="D1",
        discourse_unit_kind="PARAGRAPH",
        discourse_unit_marker="p",
    )


def _index(tmp_path, name: str, records, vrs: str) -> ProjectVerseIndex:
    """Index records through one compact VRS fixture."""
    path = tmp_path / name
    path.write_text(vrs, encoding="utf-8")
    return ProjectVerseIndex.build(name, records, parse_vrs_file(path, schema_id=name, canonical_id="org.vrs"))


def _rows(tmp_path, wip, reference, scope: str, *, vrs: str, titles=()):
    """Run omission detection for one fixture."""
    return omission_rows(
        wip,
        _index(tmp_path, "wip.vrs", wip, vrs),
        reference,
        _index(tmp_path, "ref.vrs", reference, vrs),
        parse_scope(scope),
        workflow="RTC",
        authority_stream="REFERENCE",
        authority_project_id="REF",
        wip_project_id="WIP",
        title_chapters=titles,
    )


def test_missing_and_empty_wip_verses_are_omissions(tmp_path) -> None:
    """A verse the WIP lacks or leaves empty is reported where the REFERENCE has text."""
    wip = (_record("MAT", 1, 1, "one"), _record("MAT", 1, 3, ""), _record("MAT", 1, 4, "four"))
    reference = tuple(_record("MAT", 1, verse, f"ref {verse}") for verse in range(1, 5))
    rows = _rows(tmp_path, wip, reference, "MAT 1", vrs="MAT 1:4\n")

    assert [(row["reference"], row["text_relation"]) for row in rows] == [
        ("MAT 1:2", "OMISSION"),
        ("MAT 1:3", "OMISSION"),
    ]
    assert "is empty" in rows[1]["message"]
    [finding] = gap_findings(rows[:1])
    assert finding["category"] == "STRUCTURE"
    assert finding["target_reference"] == "MAT 1:2"


def test_a_chapter_missing_from_the_wip_is_reported_once(tmp_path) -> None:
    """A whole chapter the WIP lacks is one chapter-level omission, not one row per verse."""
    wip = (_record("MAT", 1, 1, "one"), _record("MAT", 1, 2, "two"))
    reference = (*(_record("MAT", 1, verse, "r") for verse in (1, 2)), *(_record("MAT", 2, verse, "r") for verse in (1, 2)))
    rows = _rows(tmp_path, wip, reference, "MAT 1-2", vrs="MAT 1:2 2:2\n")

    assert [(row["code"], row["reference"]) for row in rows] == [("SOURCE_CHAPTER_MISSING_IN_WIP", "MAT 2")]


def test_psalm_title_matches_the_reference_title_verse(tmp_path) -> None:
    """A WIP \\d title carries the REFERENCE's leading title verse instead of being an omission."""
    sfm = "\\id PSA\n\\c 3\n\\d A psalm of David.\n\\v 1 Text.\n"
    assert psalm_title_chapters(sfm) == frozenset({3})
    wip = (_record("PSA", 3, 2, "text"),)
    reference = (_record("PSA", 3, 1, "title"), _record("PSA", 3, 2, "text"))
    rows = _rows(tmp_path, wip, reference, "PSA 3", vrs="PSA 3:2\n", titles=psalm_title_chapters(sfm))
    assert rows == []
    assert [row["reference"] for row in _rows(tmp_path, wip, reference, "PSA 3", vrs="PSA 3:2\n")] == ["PSA 3:1"]
