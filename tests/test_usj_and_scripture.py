"""Strict USJ, body-text, cache, and coordinate validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_core.errors import ValidationError
from sage_core.registry import load_ecosystem
from sage_core.scripture import compile_project
from sage_core.usj import compile_usfm_file, compile_usfm_text, parse_usj_units


def test_notes_and_xrefs_are_excluded_without_invented_space() -> None:
    """Verify that notes and xrefs are excluded without invented space."""
    text = (
        "\\id MAT Fixture\n"
        "\\c 1\n"
        "\\p\n"
        "\\v 1 \\wj кодранта\\wj*\\f + \\fr 1:1 \\ft note\\f*\\wj .\\wj*\n"
        "\\v 2 Word\\x + \\xo 1:2 \\xt JHN 1:1\\x* continues.\n"
    )
    usj = compile_usfm_text(text, "fixture.SFM")
    units = parse_usj_units(usj)
    assert units[0]["body_text_exact"] == "кодранта."
    assert "note" not in units[0]["body_text_exact"]
    assert units[1]["body_text_exact"] == "Word continues."


def test_qa_heading_is_structure_not_visible_verse_text() -> None:
    """Verify that QA heading is structure not visible verse text."""
    text = (
        "\\id PSA Fixture\n"
        "\\c 119\n"
        "\\q1\n"
        "\\v 8 Previous stanza.\n"
        "\\qa Beth\n"
        "\\q1\n"
        "\\v 9 New stanza.\n"
    )
    units = parse_usj_units(compile_usfm_text(text, "fixture.SFM"))
    assert units[0]["body_text_exact"] == "Previous stanza."
    assert units[1]["body_text_exact"] == "New stanza."
    assert "Beth" not in units[0]["body_text_exact"]
    assert units[1]["poetry_block_marker"] == "qa"
    assert units[1]["poetry_block_title"] == "Beth"


def test_invalid_utf8_is_a_hard_failure(tmp_path: Path) -> None:
    """Verify that invalid utf8 is a hard failure."""
    path = tmp_path / "41MAT.SFM"
    path.write_bytes(b"\\id MAT\n\\c 1\n\\v 1 bad\xff\n")
    with pytest.raises(UnicodeDecodeError):
        compile_usfm_file(path)


def test_excluded_coordinate_absence_is_not_missing(make_workspace) -> None:
    """Verify that excluded coordinate absence is not missing."""
    root = make_workspace(verse_max=3)
    project_root = root / "projects" / "usNIVv2"
    (project_root / "custom.vrs").write_text("#! -MAT 1:2\n", encoding="utf-8")
    (project_root / "41MAT.SFM").write_text(
        "\\id MAT Fixture\n\\c 1\n\\p\n\\v 1 One.\n\\v 3 Three.\n",
        encoding="utf-8",
    )
    config = load_ecosystem(root / "ecosystem.yml")
    result = compile_project(config, config.project("usNIVv2"))
    assert result["status"] in {"READY", "READY_WITH_WARNINGS"}
    assert not any(
        item["reference"] == "MAT 1:2" and item["code"] == "EXPECTED_COORDINATE_MISSING"
        for item in result["issues"]
    )


def test_excluded_coordinate_present_is_blocked(make_workspace) -> None:
    """Verify that excluded coordinate present is blocked."""
    root = make_workspace(verse_max=3)
    project_root = root / "projects" / "usNIVv2"
    (project_root / "custom.vrs").write_text("#! -MAT 1:2\n", encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")
    result = compile_project(config, config.project("usNIVv2"))
    assert result["status"] == "BLOCKED"
    assert any(item["code"] == "EXCLUDED_COORDINATE_PRESENT" for item in result["issues"])


def test_content_addressed_usj_cache_is_reused(make_workspace) -> None:
    """Verify that content addressed USJ cache is reused."""
    root = make_workspace()
    config = load_ecosystem(root / "ecosystem.yml")
    first = compile_project(config, config.project("idKKHv0"))
    first_cache = Path(first["files"][0]["cache"])
    assert first_cache.exists()
    first_mtime = first_cache.stat().st_mtime_ns
    second = compile_project(config, config.project("idKKHv0"))
    assert Path(second["files"][0]["cache"]) == first_cache
    assert first_cache.stat().st_mtime_ns == first_mtime


def test_project_compile_wraps_invalid_utf8(make_workspace) -> None:
    """Verify that project compile wraps invalid utf8."""
    root = make_workspace()
    source = root / "projects" / "idKKHv0" / "41MAT.SFM"
    source.write_bytes(b"\\id MAT\n\\c 1\n\\v 1 bad\xff\n")
    config = load_ecosystem(root / "ecosystem.yml")
    with pytest.raises(ValidationError, match="Invalid UTF-8"):
        compile_project(config, config.project("idKKHv0"))


def test_note_only_coordinate_is_recorded_as_warning(make_workspace) -> None:
    """Verify that note only coordinate is recorded as warning."""
    root = make_workspace(verse_max=1)
    source = root / "projects" / "idKKHv0" / "41MAT.SFM"
    source.write_text(
        "\\id MAT Fixture\n\\c 1\n\\p\n\\v 1 \\f + \\fr 1:1 \\ft note only\\f*\n",
        encoding="utf-8",
    )
    config = load_ecosystem(root / "ecosystem.yml")
    result = compile_project(config, config.project("idKKHv0"))
    assert result["status"] == "READY_WITH_WARNINGS"
    assert any(item["code"] == "PRESENT_NOTE_ONLY" for item in result["warnings"])


def test_scope_limited_compile_reads_only_requested_book(make_workspace) -> None:
    """Verify that scope limited compile reads only requested book."""
    root = make_workspace()
    projects_root = root / "projects"
    for project_id in ("idKKHv0", "usNIRVv2", "usBOLx1", "usNIVv2", "GRK", "HEB"):
        (projects_root / project_id / "42MRK.SFM").write_bytes(
            b"\\id MRK Fixture\n\\c 1\n\\v 1 invalid later: \xff\n"
        )
    config = load_ecosystem(root / "ecosystem.yml")
    selected = compile_project(config, config.project("idKKHv0"), books={"MAT"})
    assert selected["status"] == "READY"
    assert selected["summary"]["scope_limited"] is True
    assert selected["summary"]["requested_books"] == ["MAT"]
    assert selected["summary"]["files"] == 1
    with pytest.raises(ValidationError, match="Invalid UTF-8"):
        compile_project(config, config.project("idKKHv0"))


def test_inline_paragraph_and_verse_markers_produce_verse_records() -> None:
    """Verify that inline paragraph and verse markers produce verse records."""
    text = (
        "\\id MAT Fixture\n"
        "\\c 1\n"
        "\\p \\v 1 First verse. \\v 2 Second verse.\n"
    )
    units = parse_usj_units(compile_usfm_text(text, "fixture.SFM"))
    assert [
        f"MAT {item['chapter']}:{item['verse_start']}" for item in units
    ] == ["MAT 1:1", "MAT 1:2"]
    assert [item["body_text_exact"] for item in units] == ["First verse.", "Second verse."]
    assert all(item["paragraph_marker"] == "p" for item in units)


def test_line_level_markers_inside_footnotes_are_not_split_as_verses() -> None:
    """Verify that line level markers inside footnotes are not split as verses."""
    text = (
        "\\id MAT Fixture\n"
        "\\c 1\n"
        "\\p \\v 1 Body\\f + \\ft note mentioning \\v 99 only\\f* continues.\n"
    )
    units = parse_usj_units(compile_usfm_text(text, "fixture.SFM"))
    assert [
        f"MAT {item['chapter']}:{item['verse_start']}" for item in units
    ] == ["MAT 1:1"]
    assert units[0]["body_text_exact"] == "Body continues."


def test_unnumbered_m_text_after_header_is_not_lost_from_current_verse() -> None:
    """Verify that unnumbered m text after header is not lost from current verse."""
    text = (
        "\\id MAT Fixture\n"
        "\\c 5\n"
        "\\p\n"
        "\\v 2 He began to teach them.\n"
        "\\s1 The Beatitudes\n"
        "\\m He said:\n"
        "\\q1\n"
        "\\v 3 Blessed are the poor.\n"
    )
    units = parse_usj_units(compile_usfm_text(text, "fixture.SFM"))
    assert units[0]["body_text_exact"] == "He began to teach them.\nHe said:"
    assert units[0]["line_start"] == 4
    assert units[0]["line_end"] == 6
    assert units[1]["section_title"] == "The Beatitudes"
    assert units[1]["paragraph_marker"] == "m"


def test_unnumbered_m_text_after_poetry_break_is_not_lost() -> None:
    """Verify that unnumbered m text after poetry break is not lost."""
    text = (
        "\\id EZK Fixture\n"
        "\\c 1\n"
        "\\q1\n"
        "\\v 1 First line.\n"
        "\\b\n"
        "\\m Closing statement.\n"
        "\\v 2 Next verse.\n"
    )
    units = parse_usj_units(compile_usfm_text(text, "fixture.SFM"))
    assert units[0]["body_text_exact"] == "First line.\nClosing statement."
    assert units[1]["paragraph_marker"] == "m"
