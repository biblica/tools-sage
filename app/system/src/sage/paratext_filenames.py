"""Select Project Scripture using the filename contract in Paratext Settings.xml."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .canon import BOOKS_66
from .errors import ValidationError

BOOK_ID_BYTES_RE = re.compile(rb"(?m)^\\id[ \t]+([A-Za-z0-9]{3})(?:[ \t\r]|$)")
# Paratext book numbers, including publication matter. Filename numbering skips
# 40 and uses A0 onwards after 100. Reference: SIL machine.py scripture/canon.py
# and corpora/paratext_project_settings.py (get_book_file_name).
_BOOKS = BOOKS_66 + tuple(
    "TOB JDT ESG WIS SIR BAR LJE S3Y SUS BEL 1MA 2MA 3MA 4MA 1ES 2ES MAN PS2 "
    "ODA PSS JSA JDB TBS SST DNT BLT XXA XXB XXC XXD XXE XXF XXG FRT BAK OTH "
    "3ES EZA 5EZ 6EZ INT CNC GLO TDX NDX DAG PS3 2BA LBA JUB ENO 1MQ 2MQ "
    "3MQ REP 4BA LAO".split()
)
_FIELDS = ("FileNamePrePart", "FileNamePostPart", "FileNameBookNameForm")


def peek_book_code(path: Path) -> str | None:
    """Read the ASCII book ID without decoding the Scripture body."""
    try:
        with path.open("rb") as source:
            prefix = source.read(65536)
    except OSError as exc:
        raise ValidationError(f"Unable to inspect USFM book ID in {path}: {exc}") from exc
    if prefix.startswith(b"\xef\xbb\xbf"):
        prefix = prefix[3:]
    match = BOOK_ID_BYTES_RE.search(prefix)
    return match.group(1).decode("ascii").upper() if match else None


def find_settings_file(root: Path) -> Path | None:
    """Find Settings.xml with Windows-compatible casing on every platform."""
    if not root.is_dir():
        return None
    matches = [p for p in root.iterdir() if p.name.casefold() == "settings.xml" and p.is_file()]
    if len(matches) > 1:
        raise ValidationError(
            f"Multiple Settings.xml files found in {root}.", code="PARATEXT_SETTINGS_INVALID"
        )
    return matches[0] if matches else None


def _read_template(path: Path | None) -> dict[str, str] | None:
    """Read a complete template, distinguishing an empty prefix from a missing field."""
    if path is None:
        return None
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValidationError(
            f"Invalid Paratext Settings.xml: {path}: {exc}", code="PARATEXT_SETTINGS_INVALID"
        ) from exc
    fields: dict[str, str] = {}
    wanted = {name.casefold(): name for name in _FIELDS}
    for element in root.iter():
        name = wanted.get(str(element.tag).rsplit("}", 1)[-1].casefold())
        if name:
            if name in fields:
                raise ValidationError(
                    f"Duplicate filename template field {name} in {path}.",
                    code="PARATEXT_FILENAME_TEMPLATE_INVALID",
                )
            fields[name] = element.text or ""
    if not fields:
        return None  # Legacy/non-Paratext Projects retain .SFM discovery.
    if (set(fields) != set(_FIELDS)
        or fields.get("FileNameBookNameForm") not in {"MAT", "40", "41", "40MAT", "41MAT"}
        or any(char in value for value in fields.values() for char in ("/", "\\", "\x00"))):
        raise ValidationError(
            f"Incomplete or unsupported Scripture filename template in {path}.",
            code="PARATEXT_FILENAME_TEMPLATE_INVALID",
            next_action="Correct FileNamePrePart, FileNamePostPart and FileNameBookNameForm in Settings.xml.",
        )
    return fields


def paratext_book_digits(book: str) -> str:
    """Return the Paratext filename number, including its skipped number 40."""
    number = _BOOKS.index(book) + 1
    return (f"{number if number < 40 else number + 1:02d}" if number < 100
            else f"{chr(ord('A') + (number - 100) // 10)}{number % 10}")


def _template_filename(template: dict[str, str], book: str) -> str:
    """Render the shared filename contract for discovery and book creation."""
    prefix, suffix, form = (template[name] for name in _FIELDS)
    digits = paratext_book_digits(book)
    book_part = book if form == "MAT" else digits if form in {"40", "41"} else digits + book
    return prefix + book_part + suffix


def template_book_filename(root: Path, book: str) -> str | None:
    """Render a Project's declared template, or signal legacy naming fallback."""
    template = _read_template(find_settings_file(root))
    return _template_filename(template, book) if template is not None else None


def select_scripture_files(
    root: Path, *, books: set[str] | frozenset[str] | None = None,
    validate_ids: bool = True,
) -> tuple[list[Path], dict[str, Any]]:
    """Select exact template matches and verify their declared book identity."""
    selected = {book.upper() for book in books} if books is not None else None
    settings_path = find_settings_file(root)
    template = _read_template(settings_path)
    report: dict[str, Any] = {
        "settings_file": str(settings_path) if settings_path else None,
        "template": template,
        "excluded_files": [],
    }
    if not root.is_dir():
        return [], report
    candidates = sorted(p for p in root.iterdir()
                        if p.is_file() and not p.is_symlink() and not p.name.startswith("."))
    if template is None:
        files = [p for p in candidates if p.suffix.casefold() == ".sfm"]
        if selected is not None:
            files = [p for p in files if peek_book_code(p) in selected]
        return files, report
    suffix = template["FileNamePostPart"]
    expected = {_template_filename(template, book).casefold(): book for book in _BOOKS}
    files = []
    for path in candidates:
        book = expected.get(path.name.casefold())
        if book is None:
            if path.suffix.casefold() in {".sfm", ".usfm"} or (suffix and path.name.casefold().endswith(suffix.casefold())):
                report["excluded_files"].append(path.name)
            continue
        if selected is not None and book not in selected:
            continue
        actual = peek_book_code(path) if validate_ids else book
        if actual != book:
            raise ValidationError(
                f"{path.name}: Settings.xml filename requires \\id {book}; found {actual or 'no book ID'}.",
                code="PARATEXT_FILENAME_BOOK_ID_MISMATCH",
                affected_scope=book,
                details={"file": str(path), "expected_book": book, "actual_book": actual},
            )
        files.append(path)
    return files, report
