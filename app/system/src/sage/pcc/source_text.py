"""Read SOURCE verse text for PCC from a bound Scripture Project (visible body text only).

Notes, cross-references, figures and headings are not body text (``usj.visible_text``), so they never
enter discovery (PCC ``SRC10``). Offsets reported later index each unit's ``text`` exactly.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..numbers.target import target_units
from ..references import ScriptureScope, ScriptureScopeSet
from ..scripture import discover_usfm_files
from ..usj import compile_usfm_file
from .discovery import SourceUnit


def _book_files(project_path, books: set[str] | None = None) -> list:
    """Scripture files of a Project; a plain folder of ``*.usfm`` files (eBible layout) also works."""
    files = discover_usfm_files(project_path, books=books)
    if files:
        return files
    found = []
    for path in sorted(Path(project_path).glob("*.usfm")):
        match = re.search(r"\\id\s+([1-4A-Z]{3})", path.read_text(encoding="utf-8-sig")[:400])
        if match and (books is None or match[1] in books):
            found.append(path)
    return found


def source_units(project_path, scope: ScriptureScope | ScriptureScopeSet) -> list[SourceUnit]:
    """Return one ``SourceUnit`` per verse record of ``scope`` (a book, or chapters/verses of one)."""
    units: list[SourceUnit] = []
    for path in _book_files(project_path, {scope.book}):
        usj = compile_usfm_file(path)
        sha = usj["sage"]["source_sha256"]
        for unit in target_units(usj, source_sha256=sha):
            refs = unit.target_references
            if not any(scope.contains(ref) for ref in refs):
                continue
            labels = tuple(ref.label() for ref in refs)
            units.append(SourceUnit(unit.unit_id, labels[0], labels, unit.main_text))
    return units


def source_units_for_project(project_path) -> list[SourceUnit]:
    """Every verse record of every book in a Project folder (used by the index builder)."""
    units: list[SourceUnit] = []
    for path in _book_files(project_path):
        usj = compile_usfm_file(path)
        for unit in target_units(usj, source_sha256=usj["sage"]["source_sha256"]):
            labels = tuple(ref.label() for ref in unit.target_references)
            units.append(SourceUnit(unit.unit_id, labels[0], labels, unit.main_text))
    return units


def present_books(project_path) -> list[str]:
    """Book codes a Project folder holds, in canonical order (read from each file's ``\\id`` line)."""
    from ..canon import NT_27, OT_39
    present = set()
    for path in _book_files(project_path):
        match = re.search(r"\\id\s+([1-4A-Z]{3})", Path(path).read_text(encoding="utf-8-sig")[:400])
        if match:
            present.add(match[1])
    return [b for b in list(OT_39) + list(NT_27) if b in present]


def books_label(books: list[str]) -> str:
    """Coverage in words: '27 books (NT)', '66 books (OT and NT)', '30 books (NT and 3 OT books)', '2 books (MAT, JHN)'."""
    from ..canon import NT_27, OT_39
    if not books:
        return "no books"
    noun = "book" if len(books) == 1 else "books"
    if len(books) <= 3:
        return f"{len(books)} {noun} ({', '.join(books)})"
    chosen = set(books)
    parts = []
    for name, canon in (("OT", OT_39), ("NT", NT_27)):
        count = len(chosen & set(canon))
        if count == len(canon):
            parts.append(name)
        elif count:
            parts.append(f"{count} {name} book{'s' if count != 1 else ''}")
    parts.sort(key=lambda part: part[0].isdigit())
    return f"{len(books)} {noun} ({' and '.join(parts)})"


def reference_units(project_path, books: list[str] | None = None) -> list[SourceUnit]:
    """Every verse record of a Project (or of ``books``), in canonical book order.

    The reference-list builder and the terms Run both align this list, so the same text gives the same
    alignment cache entry.
    """
    from ..canon import NT_27, OT_39
    present = {}
    for path in _book_files(project_path):
        match = re.search(r"\\id\s+([1-4A-Z]{3})", Path(path).read_text(encoding="utf-8-sig")[:400])
        if match:
            present.setdefault(match[1], path)
    wanted = [b for b in list(OT_39) + list(NT_27) if b in present and (books is None or b in books)]
    units: list[SourceUnit] = []
    for book in wanted:
        usj = compile_usfm_file(present[book])
        for unit in target_units(usj, source_sha256=usj["sage"]["source_sha256"]):
            labels = tuple(ref.label() for ref in unit.target_references)
            units.append(SourceUnit(unit.unit_id, labels[0], labels, unit.main_text))
    return units


def source_content_sha256(project_path) -> str:
    """Content hash of a Project's Scripture files, as the PCC Run snapshot records it."""
    from ..hashing import sha256_paths
    files = _book_files(project_path)
    return sha256_paths(files, relative_to=Path(project_path))
