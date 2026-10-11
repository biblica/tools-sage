"""Read a local NIV Paratext project (usNIVv2) into plain verse text and footnotes.

The NIV is Biblica, Inc. text and is never vendored into the public SAGE repository; the
builder reads the operator's local Paratext project and ships only the per-verse evidence
the number index needs. Verse text keeps every character marker's content (\\nd, \\wj,
\\litl, list and table cells) and drops footnotes, headings, introductions and published
verse labels. A Psalm title (\\d before verse 1) is verse 0, matching Western numbering.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re

from sage.canon import NT_27, OT_39
from sage.errors import ValidationError

CANON = tuple(OT_39) + tuple(NT_27)
EDITION = "New International Version (NIV) 2011, Biblica, Inc."
RIGHTS = "Copyright © 1973, 1978, 1984, 2011 by Biblica, Inc."

# Paragraph markers whose whole line is not Scripture text.
_DROP_LINES = {
    "id", "rem", "h", "toc1", "toc2", "toc3", "mt1", "mt2", "imt", "im", "ip", "ie", "iex", "ili1",
    "periph", "s", "s1", "s2", "s3", "ms1", "ms2", "mr", "sp", "cl", "qa", "r", "sr", "fig",
}
# Inline spans dropped with their content (published verse labels, inline references).
_DROP_SPANS = re.compile(r"\\(vp|rq|fig)\s.*?\\\1\*", re.S)
_NOTE = re.compile(r"\\(f|fe|x)\s.*?\\\1\*", re.S)
_NOTE_TEXT = re.compile(r"\\(?:ft|fq|fqa|fl|fv|fk|fp)\s")
_NOTE_DROP = re.compile(r"\\(?:fr|cat)\s[^\\]*(?:\\cat\*)?|\\\+?xt\*?|\\fm.*?\\fm\*", re.S)
_ATTRIBUTE = re.compile(r"\|[^\\]*(?=\\[a-z+]+[0-9]*\*)")
_MARKER = re.compile(r"\\\+?[a-z]+[0-9]*\*?")
_SPACE = re.compile(r"\s+")
_LINE = re.compile(r"^\\([a-z]+[0-9]*)\b ?(.*)$")
_VERSE = re.compile(r"\\v\s+(\d+[a-z]?)(?:[-‑]\d+[a-z]?)?\s?")


@dataclass
class Verse:
    """One NIV verse: plain text and the plain text of its footnotes."""

    ref: str
    text: str = ""
    notes: list[str] = field(default_factory=list)


def book_files(project: Path) -> dict[str, Path]:
    """The 66 canonical book files of one Paratext project, keyed by book code."""
    files: dict[str, Path] = {}
    for path in sorted(project.glob("*.SFM")):
        match = re.match(r"\\id\s+([1-4A-Z]{3})", path.read_text(encoding="utf-8-sig")[:200])
        if match and match[1] in CANON:
            files[match[1]] = path
    missing = [book for book in CANON if book not in files]
    if missing:
        raise ValidationError(f"NIV project is missing canonical books: {', '.join(missing)}",
                              code="NCA_INDEX_SOURCE_INVALID",
                              next_action="Point --niv at the complete usNIVv2 Paratext project.")
    return {book: files[book] for book in CANON}


def fingerprint(project: Path) -> dict[str, object]:
    """Per-book and combined SHA-256 of the source files the build read."""
    books = {book: hashlib.sha256(path.read_bytes()).hexdigest() for book, path in book_files(project).items()}
    combined = hashlib.sha256("".join(f"{book}:{digest}\n" for book, digest in books.items()).encode()).hexdigest()
    return {"edition": EDITION, "rights": RIGHTS, "books": books, "sha256": combined}


def _plain(text: str) -> str:
    """Strip markers and attributes from Scripture text, keeping marker content."""
    text = _DROP_SPANS.sub(" ", text)
    text = _ATTRIBUTE.sub("", text)
    return _MARKER.sub("", text)


def _note_plain(note: str) -> str:
    """Readable text of one footnote, without its caller, reference and category."""
    body = re.sub(r"^\\(?:f|fe|x)\s+\S+\s?", "", note)
    body = _NOTE_DROP.sub(" ", _ATTRIBUTE.sub("", body))
    body = _NOTE_TEXT.sub(" ", body)
    body = re.sub(r"\\(?:f|fe|x)\*$", "", body)
    return _SPACE.sub(" ", _MARKER.sub("", body)).strip()


def read_book(path: Path, book: str) -> "OrderedDict[str, Verse]":
    """Every verse of one NIV book, keyed 'BOOK C:V' in source order."""
    verses: OrderedDict[str, Verse] = OrderedDict()
    chapter, current = 0, None
    parts: dict[str, list[str]] = {}

    def append(text: str) -> None:
        """Add one stretch of source text and its notes to the current verse."""
        if current is None or not text.strip():
            return
        for note in _NOTE.finditer(text):
            verses[current].notes.append(_note_plain(note[0]))
        # A note inside a hyphenated number ("forty-\\f ...\\f* two") must not split it.
        parts[current].append(_plain(re.sub(r"([-‑])\x00\s*", r"\1", _NOTE.sub("\x00", text)).replace("\x00", "")))

    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = _LINE.match(line.strip())
        if match is None:
            append(line)
            continue
        marker, rest = match[1], match[2]
        if marker == "c":
            chapter, current = int(rest.split()[0]), None
            continue
        if marker in _DROP_LINES or chapter == 0:
            continue
        if marker == "d" and (current is None or current.endswith(":0")):
            current = f"{book} {chapter}:0"
            verses.setdefault(current, Verse(current))
            parts.setdefault(current, [])
            append(rest)
            continue
        pieces = _VERSE.split(line.strip() if marker == "v" else rest)
        append(pieces[0])
        for number, text in zip(pieces[1::2], pieces[2::2]):
            # A lettered sub-verse ("1b", the Greek additions to Esther) stays a separate label.
            current = f"{book} {chapter}:{int(number)}" if number.isdigit() else f"{book} {chapter}:{number}"
            verses.setdefault(current, Verse(current))
            parts.setdefault(current, [])
            append(text)
    for ref, verse in verses.items():
        verse.text = _SPACE.sub(" ", " ".join(parts[ref])).strip()
    return OrderedDict((ref, verse) for ref, verse in verses.items() if verse.text or not ref.endswith(":0"))


def read_project(project: Path, linker=None) -> "OrderedDict[str, Verse]":
    """Every canonical NIV verse in canonical order, keyed by Western (eng.vrs) coordinate.

    With a ``linker`` (index_build/versify.py) each NIV label is linked to its Western
    coordinate; NIV verses that land on the same Western verse are joined in reading order.
    """
    verses: OrderedDict[str, Verse] = OrderedDict()
    for book, path in book_files(project).items():
        verses.update(read_book(path, book))
    if linker is None:
        return verses
    linked: OrderedDict[str, Verse] = OrderedDict()
    for label, verse in verses.items():
        western = linker.english_to_western(label)
        if western in linked:
            joined = linked[western]
            joined.text = (joined.text + " " + verse.text).strip()
            joined.notes.extend(verse.notes)
        else:
            linked[western] = Verse(western, verse.text, list(verse.notes))
    return linked
