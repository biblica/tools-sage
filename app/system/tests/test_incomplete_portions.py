"""Detect real per-book complete/incomplete chapter coverage for imported WIP Scripture."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sage.errors import ValidationError
from sage.project_inventory import register_project
from sage.registry import load_ecosystem
from sage.scripture import detect_incomplete_portions, complete_chapters, incomplete_chapters
from sage.storage import storage_layout


def test_complete_chapters_excludes_chapters_with_an_empty_visible_body():
    """A chapter with even one EMPTY_VISIBLE_BODY warning is dropped from complete_chapters."""
    validation = {
        "chapters_present": [1, 2, 3],
        "warnings": [{"code": "EMPTY_VISIBLE_BODY", "reference": "MAT 2:5"}],
    }
    assert complete_chapters(validation) == (1, 3)
    assert incomplete_chapters(validation) == (2,)


def test_complete_chapters_ignores_unrelated_warning_codes():
    """A non-EMPTY_VISIBLE_BODY warning (e.g. an excluded/doubtful reading) never disqualifies a chapter."""
    validation = {
        "chapters_present": [1, 2],
        "warnings": [{"code": "EXCLUDED_COORDINATE_PRESENT", "reference": "MAT 1:2"}],
    }
    assert complete_chapters(validation) == (1, 2)
    assert incomplete_chapters(validation) == ()


def test_complete_chapters_is_empty_when_every_chapter_has_a_gap():
    """A book with no fully-complete chapter reports none as complete."""
    validation = {
        "chapters_present": [1, 2],
        "warnings": [
            {"code": "EMPTY_VISIBLE_BODY", "reference": "MAT 1:1"},
            {"code": "EMPTY_VISIBLE_BODY", "reference": "MAT 2:9"},
        ],
    }
    assert complete_chapters(validation) == ()
    assert incomplete_chapters(validation) == (1, 2)


def test_detect_incomplete_portions_against_a_real_project(make_workspace):
    """A real project directory with one complete book and one partial book splits correctly."""
    root = make_workspace(verse_max=3)
    project_path = storage_layout(root).projects_root / "usNIVv2"
    (project_path / "41MAT.SFM").write_text(
        "\\id MAT Fixture\n\\c 1\n\\p\n\\v 1 One.\n\\v 2 Two.\n\\v 3 Three.\n",
        encoding="utf-8",
    )
    (project_path / "42MRK.SFM").write_text(
        "\\id MRK Fixture\n\\c 1\n\\p\n\\v 1 One.\n\\v 2 \n\\v 3 Three.\n",
        encoding="utf-8",
    )
    config = load_ecosystem(root / "ecosystem.yml")

    result = detect_incomplete_portions(project_path=project_path, base_vrs_file="eng.vrs", config=config)

    assert result["MAT"] == {"complete": (1,), "incomplete": ()}
    assert result["MRK"] == {"complete": (), "incomplete": (1,)}


def test_detect_incomplete_portions_raises_for_an_unknown_base_vrs(make_workspace):
    """An unresolvable base VRS filename fails closed with a distinct error code."""
    root = make_workspace(verse_max=3)
    project_path = storage_layout(root).projects_root / "usNIVv2"
    (project_path / "41MAT.SFM").write_text("\\id MAT Fixture\n\\c 1\n\\p\n\\v 1 One.\n", encoding="utf-8")
    config = load_ecosystem(root / "ecosystem.yml")

    with pytest.raises(ValidationError) as excinfo:
        detect_incomplete_portions(project_path=project_path, base_vrs_file="nonexistent.vrs", config=config)
    assert excinfo.value.code == "BASE_VRS_FILE_NOT_FOUND"


def _register(tmp_path, project_path, *, incomplete_portions=None, declared_books=None):
    """Register a fresh test Project directly, without needing a full ecosystem."""
    root = tmp_path / "SAGE" / "app"
    root.mkdir(parents=True, exist_ok=True)
    return register_project(
        root,
        project_id="tstwip",
        project_path=project_path,
        language_code="en",
        base_vrs_file="eng.vrs",
        declared_books=declared_books,
        incomplete_portions=incomplete_portions,
        imported_at=datetime(2026, 9, 25, tzinfo=timezone.utc),
    )


def test_register_project_excludes_a_fully_incomplete_book_from_scope(tmp_path):
    """A book with zero complete chapters never counts as available scope, but the import still succeeds."""
    project_path = tmp_path / "project"
    project_path.mkdir()
    (project_path / "41MAT.SFM").write_text("\\id MAT\n\\c 1\n\\v 1 One.\n", encoding="utf-8")
    (project_path / "42MRK.SFM").write_text("\\id MRK\n\\c 1\n\\v 1 \n", encoding="utf-8")

    record = _register(tmp_path, project_path, incomplete_portions={
        "MAT": {"complete": (1,), "incomplete": ()},
        "MRK": {"complete": (), "incomplete": (1,)},
    })

    assert record["scope"]["expected_books"] == ["MAT"]
    assert record["sfm_books"] == ["MAT", "MRK"]
    assert record["detected_books"] == ["MAT", "MRK"]
    assert record["incomplete_portions"] == {
        "MAT": {"complete": [1], "incomplete": []},
        "MRK": {"complete": [], "incomplete": [1]},
    }


def test_register_project_falls_back_to_the_full_book_list_when_everything_is_incomplete(tmp_path):
    """If every detected book is fully incomplete, scope still names them rather than going empty."""
    project_path = tmp_path / "project"
    project_path.mkdir()
    (project_path / "41MAT.SFM").write_text("\\id MAT\n\\c 1\n\\v 1 \n", encoding="utf-8")

    record = _register(tmp_path, project_path, incomplete_portions={
        "MAT": {"complete": (), "incomplete": (1,)},
    })

    assert record["scope"]["expected_books"] == ["MAT"]
    assert record["incomplete_portions"] == {"MAT": {"complete": [], "incomplete": [1]}}


def test_register_project_with_no_incomplete_portions_data_is_unaffected(tmp_path):
    """Omitting incomplete_portions (the default) leaves scope exactly as it was before this feature."""
    project_path = tmp_path / "project"
    project_path.mkdir()
    (project_path / "41MAT.SFM").write_text("\\id MAT\n\\c 1\n\\v 1 One.\n", encoding="utf-8")

    record = _register(tmp_path, project_path)

    assert record["scope"]["expected_books"] == ["MAT"]
    assert record["incomplete_portions"] == {}


def test_register_catalogued_scripture_project_excludes_incomplete_books(make_workspace, tmp_path):
    """A cataloged PORTIONS-scope import with an incomplete book excludes it from scope end to end."""
    from sage.project_inventory import registered_project_records
    from sage.resource_registration import register_catalogued_scripture_project

    root = make_workspace()
    project = tmp_path / "tstwip"
    project.mkdir()
    (project / "41MAT.SFM").write_text("\\id MAT\n\\c 1\n\\v 1 One.\n", encoding="utf-8")
    (project / "42MRK.SFM").write_text("\\id MRK\n\\c 1\n\\v 1 \n", encoding="utf-8")

    row = {
        "project_code": "tstwip",
        "path": str(project),
        "language_iso": "en",
        "full_name": "Test WIP",
        "books": ["MAT", "MRK"],
        "versification": {"base_file": "eng.vrs"},
    }
    register_catalogued_scripture_project(root / "ecosystem.yml", catalogue_row=row)

    record = registered_project_records(root)["tstwip"]
    assert record["scope"]["expected_books"] == ["MAT"]
    assert record["incomplete_portions"]["MRK"]["incomplete"] == [1]
    assert record["incomplete_portions"]["MAT"]["complete"] == [1]


def test_register_catalogued_scripture_project_skips_detection_for_a_complete_import(make_workspace, tmp_path):
    """A full-canon (non-PORTIONS) import never runs portion detection at all."""
    from sage.project_inventory import BOOK_ORDER, registered_project_records
    from sage.resource_registration import register_catalogued_scripture_project

    root = make_workspace()
    project = tmp_path / "tstfull"
    project.mkdir()
    for book in BOOK_ORDER:
        (project / f"{book}.SFM").write_text(f"\\id {book}\n\\c 1\n\\v 1 One.\n", encoding="utf-8")

    row = {
        "project_code": "tstfull",
        "path": str(project),
        "language_iso": "en",
        "full_name": "Test Full",
        "books": list(BOOK_ORDER),
        "versification": {"base_file": "eng.vrs"},
    }
    register_catalogued_scripture_project(root / "ecosystem.yml", catalogue_row=row)

    record = registered_project_records(root)["tstfull"]
    assert record["incomplete_portions"] == {}


def test_register_catalogued_scripture_project_survives_a_badly_encoded_book_file(make_workspace, tmp_path):
    """A WIP book file with invalid encoding degrades detection gracefully instead of crashing the import.

    compile_usfm_file raises a raw UnicodeDecodeError for this, not a
    ValidationError -- the import must still succeed.
    """
    from sage.project_inventory import registered_project_records
    from sage.resource_registration import register_catalogued_scripture_project

    root = make_workspace()
    project = tmp_path / "tstbad"
    project.mkdir()
    (project / "41MAT.SFM").write_text("\\id MAT\n\\c 1\n\\v 1 One.\n", encoding="utf-8")
    (project / "42MRK.SFM").write_bytes(b"\\id MRK\n\\c 1\n\\v 1 bad\xff text.\n")

    row = {
        "project_code": "tstbad",
        "path": str(project),
        "language_iso": "en",
        "full_name": "Test Bad Encoding",
        "books": ["MAT", "MRK"],
        "versification": {"base_file": "eng.vrs"},
    }
    register_catalogued_scripture_project(root / "ecosystem.yml", catalogue_row=row)

    record = registered_project_records(root)["tstbad"]
    assert record["incomplete_portions"] == {}
    assert record["sfm_books"] == ["MAT", "MRK"]


def test_register_external_scripture_resource_excludes_incomplete_books(make_workspace, tmp_path):
    """The external-registration path (menu.py's import flow) also runs and applies detection."""
    from sage.project_inventory import registered_project_records
    from sage.resource_registration import register_external_scripture_resource

    root = make_workspace()
    project = tmp_path / "tstext"
    project.mkdir()
    (project / "41MAT.SFM").write_text("\\id MAT\n\\c 1\n\\v 1 One.\n", encoding="utf-8")
    (project / "42MRK.SFM").write_text("\\id MRK\n\\c 1\n\\v 1 \n", encoding="utf-8")

    register_external_scripture_resource(
        root / "ecosystem.yml",
        project_id="tstext",
        language_code="en",
        profile_variant=None,
        role=None,
        base_vrs_file="eng.vrs",
        external_path=project,
        declared_books=("MAT", "MRK"),
    )

    record = registered_project_records(root)["tstext"]
    assert record["scope"]["expected_books"] == ["MAT"]
    assert record["incomplete_portions"]["MRK"]["incomplete"] == [1]


def test_register_external_scripture_resource_survives_a_badly_encoded_book_file(make_workspace, tmp_path):
    """The external-registration path also degrades gracefully on invalid encoding, never crashing import."""
    from sage.project_inventory import registered_project_records
    from sage.resource_registration import register_external_scripture_resource

    root = make_workspace()
    project = tmp_path / "tsxbad"
    project.mkdir()
    (project / "41MAT.SFM").write_text("\\id MAT\n\\c 1\n\\v 1 One.\n", encoding="utf-8")
    (project / "42MRK.SFM").write_bytes(b"\\id MRK\n\\c 1\n\\v 1 bad\xff text.\n")

    register_external_scripture_resource(
        root / "ecosystem.yml",
        project_id="tsxbad",
        language_code="en",
        profile_variant=None,
        role=None,
        base_vrs_file="eng.vrs",
        external_path=project,
        declared_books=("MAT", "MRK"),
    )

    record = registered_project_records(root)["tsxbad"]
    assert record["incomplete_portions"] == {}
