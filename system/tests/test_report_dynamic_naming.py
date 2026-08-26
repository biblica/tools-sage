"""Regression coverage for Scripture-aware SAW report naming."""

import pytest

from sage.plan_continuation import _append_parts, _report_book_code, _report_scope_parts, _report_scope_slug


@pytest.mark.parametrize(
    "book",
    (
        "1SA", "2SA", "1KI", "2KI", "1CH", "2CH", "1CO", "2CO",
        "1TH", "2TH", "1TI", "2TI", "1PE", "2PE", "1JN", "2JN", "3JN",
    ),
)
def test_numbered_book_code_is_never_zero_padded_or_split(book: str) -> None:
    """Numbered canonical book codes remain intact while coordinates receive padding."""
    assert _report_book_code(book) == book
    assert _report_scope_slug(book) == book
    assert _report_scope_slug(f"{book} 1") == f"{book}-001"


def test_numbered_book_alias_is_canonicalized_before_report_naming() -> None:
    """Book-name aliases canonicalize before report folder and scope names are composed."""
    assert _report_book_code("2 John 1") == "2JN"
    assert _report_scope_slug("2 John 1") == "2JN-001"
    assert _report_scope_slug("2JN 1:7-13") == "2JN-001-007-013"


def test_report_scope_slug_preserves_existing_coordinate_padding() -> None:
    """Ordinary book/chapter/verse scopes retain the established three-digit coordinate grammar."""
    assert _report_scope_slug("GEN 1") == "GEN-001"
    assert _report_scope_slug("MAT 1:1") == "MAT-001-001"
    assert _report_scope_slug("MAT 1:1-3") == "MAT-001-001-003"
    assert _report_scope_slug("MAT 1:1-2:3") == "MAT-001-001-002-003"
    assert _report_scope_slug("MAT 1-2") == "MAT-001-002"


def test_whole_book_report_scope_does_not_repeat_book_directory() -> None:
    """Whole-book output uses one Book directory rather than BOOK/BOOK duplication."""
    assert _report_scope_parts("1JN") == ("1JN",)
    assert _report_scope_parts("ZEC") == ("ZEC",)


def test_report_scope_directories_use_book_only() -> None:
    """Operator report directories stop at Book; scope detail belongs in filenames."""
    assert _report_scope_parts("1JN 1") == ("1JN",)
    assert _report_scope_parts("ZEC 3:2-9") == ("ZEC",)


def test_generated_path_builder_removes_adjacent_duplicate_segments(tmp_path) -> None:
    """Generated directory paths never append the same adjacent segment twice."""
    root = tmp_path / "reports" / "SAW_example" / "1JN"
    assert _append_parts(root, ("1JN",)) == root
    assert _append_parts(root, ("1JN", "1JN-001")) == root / "1JN-001"
