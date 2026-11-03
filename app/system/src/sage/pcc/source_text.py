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
