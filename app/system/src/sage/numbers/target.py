"""Project existing SAGE USJ into separate, locatable NCA evidence streams."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sage.errors import ValidationError
from sage.usj import visible_text
from sage.vrs import VerseRef

from .models import TargetNote, TargetUnit

_NOTES = frozenset({"f", "fe", "ef", "efe"})
_LOCATORS = frozenset({"fr", "fv"})


def _note_content(nodes: list[Any]) -> tuple[str, tuple[Mapping[str, object], ...]]:
    """Remove caller/locator fields while recording exact visible note offsets."""
    chunks: list[str] = []
    spans: list[dict[str, object]] = []

    def visit(items: list[Any], *, top: bool = False) -> None:
        """Collect note fields without treating callers or locators as evidence."""
        for index, node in enumerate(items):
            if isinstance(node, str):
                if top and index == 0:
                    # USJ stores the USFM note caller before the first field.
                    node = re.sub(r"^\s*\S+\s*", "", node, count=1)
                if node:
                    start = sum(map(len, chunks))
                    chunks.append(node)
                    spans.append({"kind": "CONTENT", "start": start,
                                  "end": start + len(node), "text": node})
            elif isinstance(node, Mapping):
                marker = str(node.get("marker", "")).lstrip("+")
                content = list(node.get("content", []))
                if marker in _LOCATORS:
                    spans.append({"kind": "LOCATOR", "marker": marker,
                                  "text": visible_text(content)})
                elif marker not in {"x", "ex"} and node.get("type") != "note":
                    if marker == "w":
                        visit([visible_text([dict(node)])])
                    else:
                        visit(content)

    visit(nodes, top=True)
    raw = "".join(chunks)
    left = len(raw) - len(raw.lstrip())
    end = len(raw.rstrip())
    text = raw[left:end]
    adjusted: list[Mapping[str, object]] = []
    for span in spans:
        if span["kind"] == "LOCATOR":
            adjusted.append(span)
            continue
        start = max(int(span["start"]), left)
        stop = min(int(span["end"]), end)
        if stop > start:
            adjusted.append({"kind": "CONTENT", "start": start - left,
                             "end": stop - left, "text": raw[start:stop]})
    return text, tuple(adjusted)


def _notes(nodes: list[Any], refs: tuple[VerseRef, ...], unit_id: str) -> tuple[TargetNote, ...]:
    """Visit only target footnotes, preserving explicit unambiguous anchors."""
    found: list[TargetNote] = []

    def visit(items: list[Any]) -> None:
        """Walk nested inline styles without entering excluded cross-references."""
        for node in items:
            if not isinstance(node, Mapping):
                continue
            marker = str(node.get("marker", "")).lstrip("+")
            content = list(node.get("content", []))
            if node.get("type") == "note":
                if marker not in _NOTES:
                    continue
                text, spans = _note_content(content)
                anchors = refs
                locators = [str(span["text"]).strip() for span in spans
                            if span["kind"] == "LOCATOR" and span["marker"] == "fr"]
                if locators:
                    anchors = ()
                if len(locators) == 1:
                    match = re.fullmatch(r"(?:(?P<book>[1-3]?[A-Z]{2,3})\s+)?(?P<chapter>[0-9]+):(?P<start>[0-9]+)(?:[-–](?P<end>[0-9]+))?[.:]?", locators[0])
                    if match:
                        book = match["book"] or refs[0].book
                        first, last = int(match["start"]), int(match["end"] or match["start"])
                        if int(match["chapter"]) > 0 and first <= last and last - first <= 200:
                            anchors = tuple(VerseRef(book, int(match["chapter"]), v)
                                            for v in range(first, last + 1))
                found.append(TargetNote(f"{unit_id}:note:{len(found) + 1}", marker,
                                        text, anchors, spans))
            elif marker not in {"x", "ex"}:
                visit(content)

    visit(nodes)
    return tuple(found)


def target_units(usj: Mapping[str, object], *, source_sha256: str) -> tuple[TargetUnit, ...]:
    """Extract exact compiler records plus canonical Psalm superscriptions.

    Parser failures are blocking because dropping damaged content could produce
    a false all-clear. The caller can preserve the error as incomplete coverage.
    """
    sage = usj.get("sage")
    if not isinstance(sage, Mapping) or sage.get("errors"):
        raise ValidationError("NCA requires error-free SAGE USJ compiler records.",
                              code="NCA_TARGET_PARSE_ERROR",
                              details={"errors": list(sage.get("errors", [])) if isinstance(sage, Mapping) else []})
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ValidationError("NCA target source hash is invalid.", code="NCA_TARGET_HASH_INVALID")
    book = str(sage.get("book_code", ""))
    records = sage.get("verse_records")
    if not isinstance(records, (list, tuple)) or not book or book == "UNK":
        raise ValidationError("NCA requires book and verse compiler records.", code="NCA_TARGET_PARSE_ERROR")
    units: list[TargetUnit] = []
    seen: set[VerseRef] = set()
    for record in records:
        refs = tuple(VerseRef(book, int(record["chapter"]), verse)
                     for verse in range(int(record["verse_start"]), int(record["verse_end"]) + 1))
        if not refs or seen.intersection(refs):
            raise ValidationError("Repeated or invalid NCA target reference.", code="NCA_TARGET_DUPLICATE_REFERENCE")
        seen.update(refs)
        identity = f"{source_sha256}:{book}:{record['chapter']}:{record['number']}"
        nodes = list(record.get("content", []))
        units.append(TargetUnit(identity, refs, visible_text(nodes), _notes(nodes, refs, identity),
                                source_sha256, {"line_start": int(record["line_start"]),
                                                "line_end": int(record["line_end"])}))
    if book == "PSA":
        chapter = 0
        chapter_verse_seen = False
        titles: dict[VerseRef, list[tuple[int, list[Any]]]] = {}
        for index, node in enumerate(usj.get("content", [])):
            if not isinstance(node, Mapping):
                continue
            if node.get("type") == "chapter":
                chapter = int(node["number"])
                chapter_verse_seen = False
            elif node.get("marker") == "d" and chapter and not chapter_verse_seen:
                ref = VerseRef(book, chapter, 0)
                if ref in seen:
                    continue
                nodes = []
                for child in node.get("content", []):
                    if isinstance(child, Mapping) and child.get("type") == "verse":
                        break
                    nodes.append(child)
                titles.setdefault(ref, []).append((index, nodes))
            if node.get("type") == "verse" or any(
                isinstance(child, Mapping) and child.get("type") == "verse"
                for child in node.get("content", [])
            ):
                chapter_verse_seen = True
        for ref, paragraphs in titles.items():
            identity = f"{source_sha256}:{book}:{ref.chapter}:superscription"
            texts = [visible_text(nodes).strip() for _, nodes in paragraphs]
            locator = {"content_index": paragraphs[0][0]}
            offset = 0
            for part, (index, _) in enumerate(paragraphs):
                locator[f"paragraph_{part}_content_index"] = index
                locator[f"paragraph_{part}_start"] = offset
                locator[f"paragraph_{part}_end"] = offset + len(texts[part])
                offset += len(texts[part]) + 1
            notes = tuple(note for part, (_, nodes) in enumerate(paragraphs)
                          for note in _notes(nodes, (ref,), f"{identity}:{part}"))
            units.append(TargetUnit(identity, (ref,), "\n".join(texts), notes,
                                    source_sha256, locator))
    return tuple(sorted(units, key=lambda unit: unit.target_references[0]))


def extract_heading_units(usj: Mapping[str, object], *, source_sha256: str) -> tuple[TargetUnit, ...]:
    """Preserve editorial headings as separate style-only streams anchored forward.

    Canonical Psalm superscriptions already belong to accuracy-bearing verse
    units and are excluded here. A verse milestone ends heading content even
    when the compiler retains it in the same paragraph node.
    """
    target_units(usj, source_sha256=source_sha256)
    book = str(usj['sage']['book_code'])
    content = list(usj.get('content', []))
    chapter, verse_seen = 0, False
    results = []
    for index, node in enumerate(content):
        if not isinstance(node, Mapping):
            continue
        if node.get('type') == 'chapter':
            chapter, verse_seen = int(node['number']), False
            continue
        marker = str(node.get('marker', ''))
        heading = bool(re.fullmatch(r'(?:s[1-5]?|ms[1-3]?|mt[1-4]?|mte[1-2]?|cl|cd|r|mr|d)', marker))
        if marker == 'd' and book == 'PSA' and chapter and not verse_seen:
            heading = False
        nodes = list(node.get('content', []))
        before = []
        for child in nodes:
            if isinstance(child, Mapping) and child.get('type') == 'verse':
                break
            before.append(child)
        if heading:
            text = visible_text(before).strip()
            if text:
                refs = _following_heading_reference(content, index, book, chapter)
                identity = f'{source_sha256}:{book}:heading:{index}'
                notes = _notes(before, refs, identity) if refs else ()
                results.append(TargetUnit(identity, refs, text, notes, source_sha256,
                                          {'heading': 1, 'content_index': index, 'chapter': chapter}))
        if node.get('type') == 'verse' or any(isinstance(child, Mapping) and child.get('type') == 'verse' for child in nodes):
            verse_seen = True
    return tuple(results)


def _following_heading_reference(content: list[object], start: int, book: str, chapter: int) -> tuple[VerseRef, ...]:
    """Anchor a heading to the following body verse without claiming numeric equivalence."""
    for node in content[start:]:
        if not isinstance(node, Mapping):
            continue
        if node.get('type') == 'chapter':
            chapter = int(node['number'])
        children = [node] if node.get('type') == 'verse' else node.get('content', [])
        for child in children:
            if isinstance(child, Mapping) and child.get('type') == 'verse' and chapter:
                number = str(child.get('number', '')).split('-')[0]
                if number.isdigit():
                    return (VerseRef(book, chapter, int(number)),)
    return ()
