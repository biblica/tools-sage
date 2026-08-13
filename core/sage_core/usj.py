"""Strict USFM-to-USJ compiler shared by BIC and SAW."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable

from .sections import attach_structure_records, index_usfm_structure
from .structure_policy import StructurePolicy, default_structure_policy
from .usfm_stream import iter_logical_usfm_lines

USJ_VERSION = "3.1"
USJ_COMPILER = "SAGE-USJ-0.01-rc7"
USFM_SUFFIXES = {".sfm", ".usfm"}
BIDI_CONTROLS = "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
BIDI_RE = re.compile(f"[{BIDI_CONTROLS}]")
MARKER_RE = re.compile(r"\\(\+?[A-Za-z0-9][A-Za-z0-9-]*)(\*)?")
VERSE_RE = re.compile(r"^\\v\s+([^\s]+)\s*(.*)$")
CHAPTER_RE = re.compile(r"^\\c\s+([^\s]+)")
ID_RE = re.compile(r"^\\id\s+([1-3]?[A-Za-z]{2,3})\b\s*(.*)$", re.IGNORECASE | re.MULTILINE)

NOTE_CONTAINERS = {"f", "fe", "ef", "efe", "x", "ex"}
NON_VISIBLE_CHAR_MARKERS = {"fig", "cat", "fm", "vp"}
ATTRIBUTE_CHAR_MARKERS = {"w", "wa", "wg", "wh", "jmp", "rb"}
PAIRED_CHAR_MARKERS = {
    "add", "bd", "bdit", "bk", "dc", "em", "fig", "it", "k", "lik", "litl",
    "nd", "no", "ord", "pn", "png", "pro", "qac", "qs", "qt", "rb", "rq",
    "sc", "sig", "sls", "sup", "tl", "w", "wa", "wg", "wh", "wj", "jmp",
    "fr", "ft", "fk", "fq", "fqa", "fl", "fw", "fp", "fv", "fdc", "fm", "vp", "cat",
    "xo", "xop", "xt", "xta", "xk", "xq", "xot", "xnt", "xdc", "ref", "ior",
}

NON_VERSE_STRUCTURAL_RE = re.compile(
    r"^(?:s\d*|ms\d*|qa|b|mr|sr|r|d|sp|sd\d*|mt\d*|mte\d*|imt\d*|imte\d*|is\d*|"
    r"ip|ipi|im|imi|ipq|imq|ipr|iq\d*|ib|ili\d*|iot|io\d*|iex|cl|cd)$"
)
PARA_MARKER_RE = re.compile(
    r"^(?:p|m|po|pr|cls|pmo|pm|pmc|pmr|pi\d*|mi\d*|nb|pc|ph\d*|q\d*|qr|qc|qa|qm\d*|qd|"
    r"lh|li\d*|lf|lim\d*|tr|tc\d*|th\d*|tcr\d*|thr\d*|b|s\d*|ms\d*|mr|sr|r|d|sp|sd\d*|"
    r"mt\d*|mte\d*|imt\d*|imte\d*|is\d*|ip|ipi|im|imi|ipq|imq|ipr|iq\d*|ib|ili\d*|iot|io\d*|iex|cl|cd|lit)$"
)


def _sha256_bytes(data: bytes) -> str:
    """Return the SHA-256 digest used to bind compiled USJ to exact source bytes."""
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    """Hash one source file in bounded blocks for cache and provenance identity."""
    return _sha256_bytes(path.read_bytes())


def _clean_marker(name: str) -> str:
    """Return a canonical USFM marker name for inline and block parsing."""
    return name.lstrip("+").casefold()


def _consume_delimiter(text: str, pos: int) -> int:
    # In USFM, one ASCII space after a marker is syntax, not visible content.
    """Consume one expected parser delimiter and report its updated cursor."""
    return pos + 1 if pos < len(text) and text[pos] == " " else pos


def _find_close(text: str, start: int, marker: str) -> tuple[int, int] | None:
    """Find the matching close marker without crossing an enclosing parse boundary."""
    depth = 1
    for match in MARKER_RE.finditer(text, start):
        name = _clean_marker(match.group(1))
        closing = bool(match.group(2))
        if name != marker:
            continue
        if closing:
            depth -= 1
            if depth == 0:
                return match.start(), match.end()
        else:
            depth += 1
    return None


def _parse_inline(text: str, errors: list[str]) -> list[Any]:
    """Parse inline USFM into nested USJ nodes while preserving semantic markers."""
    nodes: list[Any] = []
    cursor = 0
    while cursor < len(text):
        match = MARKER_RE.search(text, cursor)
        if not match:
            if cursor < len(text):
                nodes.append(text[cursor:])
            break
        if match.start() > cursor:
            nodes.append(text[cursor:match.start()])
        marker = _clean_marker(match.group(1))
        closing = bool(match.group(2))
        after = match.end()
        if closing:
            errors.append(f"UNEXPECTED_CLOSING_MARKER:{marker}")
            cursor = after
            continue
        content_start = _consume_delimiter(text, after)
        if marker in NOTE_CONTAINERS:
            close = _find_close(text, content_start, marker)
            if not close:
                errors.append(f"UNCLOSED_NOTE_CONTAINER:{marker}")
                inner = text[content_start:]
                cursor = len(text)
            else:
                inner = text[content_start:close[0]]
                cursor = close[1]
            nodes.append({"type": "note", "marker": marker, "content": _parse_note_content(inner)})
            continue
        if marker in PAIRED_CHAR_MARKERS:
            close = _find_close(text, content_start, marker)
            if not close:
                errors.append(f"UNCLOSED_CHARACTER_MARKER:{marker}")
                inner = text[content_start:]
                cursor = len(text)
            else:
                inner = text[content_start:close[0]]
                cursor = close[1]
            nodes.append({"type": "char", "marker": marker, "content": _parse_inline(inner, errors)})
            continue
        # Milestones and implicit/unknown inline markers are represented but do not
        # create visible spacing. Their following text remains ordinary text.
        nodes.append({"type": "marker", "marker": marker})
        cursor = content_start
    return _merge_adjacent_text(nodes)


def _parse_note_content(text: str) -> list[Any]:
    # Notes are retained in USJ for audit, but are never emitted into body_text.
    """Parse footnote or cross-reference content without leaking it into verse text."""
    nodes: list[Any] = []
    cursor = 0
    for match in MARKER_RE.finditer(text):
        if match.start() > cursor:
            nodes.append(text[cursor:match.start()])
        nodes.append({
            "type": "marker",
            "marker": _clean_marker(match.group(1)),
            "closing": bool(match.group(2)),
        })
        cursor = _consume_delimiter(text, match.end())
    if cursor < len(text):
        nodes.append(text[cursor:])
    return _merge_adjacent_text(nodes)


def _merge_adjacent_text(nodes: list[Any]) -> list[Any]:
    """Coalesce adjacent text nodes so deterministic USJ output has no redundant fragments."""
    merged: list[Any] = []
    for node in nodes:
        if isinstance(node, str) and node == "":
            continue
        if isinstance(node, str) and merged and isinstance(merged[-1], str):
            merged[-1] += node
        else:
            merged.append(node)
    return merged


def visible_text(nodes: Iterable[Any]) -> str:
    """Return human-visible verse text with excluded notes removed."""
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, str):
            parts.append(node)
            continue
        if not isinstance(node, dict):
            continue
        kind = node.get("type")
        marker = str(node.get("marker", "")).casefold()
        if kind == "note":
            continue
        if kind == "char":
            if marker in NON_VISIBLE_CHAR_MARKERS:
                continue
            value = visible_text(node.get("content", []))
            if marker in ATTRIBUTE_CHAR_MARKERS and "|" in value:
                value = value.split("|", 1)[0]
            parts.append(value)
            continue
        if kind in {"para", "table", "sidebar"}:
            parts.append(visible_text(node.get("content", [])))
    return "".join(parts)


def _parse_verse_number(raw: str) -> tuple[int, int] | None:
    """Parse a verse number and retain its full submitted label for provenance."""
    cleaned = BIDI_RE.sub("", raw).strip()
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", cleaned)
    if not match:
        return None
    start = int(match.group(1))
    return start, int(match.group(2) or start)


def _raw_verse_records(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract ordered verse records from top-level USJ before VRS reconciliation."""
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    chapter: int | None = None
    current: dict[str, Any] | None = None
    for line_number, line in iter_logical_usfm_lines(text):
        chapter_match = CHAPTER_RE.match(line.strip())
        if chapter_match:
            cleaned = BIDI_RE.sub("", chapter_match.group(1))
            if cleaned.isdigit():
                chapter = int(cleaned)
            else:
                errors.append(f"INVALID_CHAPTER_NUMBER:line={line_number}:value={chapter_match.group(1)}")
            current = None
            continue
        verse_match = VERSE_RE.match(line.strip())
        if verse_match and chapter is not None:
            bounds = _parse_verse_number(verse_match.group(1))
            if not bounds:
                raw_number = BIDI_RE.sub("", verse_match.group(1)).strip()
                if re.fullmatch(r"\d+[A-Za-z]", raw_number):
                    errors.append(
                        f"UNSUPPORTED_SUBVERSE_LABEL:line={line_number}:value={raw_number}:"
                        "policy=use_explicit_VRS_mapping_or_normalize_source"
                    )
                else:
                    errors.append(f"INVALID_VERSE_NUMBER:line={line_number}:value={verse_match.group(1)}")
                current = None
                continue
            current = {
                "chapter": chapter,
                "verse_start": bounds[0],
                "verse_end": bounds[1],
                "number": BIDI_RE.sub("", verse_match.group(1)),
                "lines": [line],
                "line_start": line_number,
                "line_end": line_number,
                "fragments": [verse_match.group(2)],
            }
            records.append(current)
            continue
        if current is not None and line.strip():
            stripped = line.strip()
            marker_match = MARKER_RE.match(stripped)
            if marker_match:
                marker = _clean_marker(marker_match.group(1))
                if NON_VERSE_STRUCTURAL_RE.fullmatch(marker):
                    # Section and poetry-block markers do not close the current
                    # verse milestone. Ignore their heading/break content, but
                    # retain the verse so later unnumbered body text is not lost.
                    continue
                if PARA_MARKER_RE.fullmatch(marker):
                    remainder = stripped[_consume_delimiter(stripped, marker_match.end()):]
                    if not remainder:
                        continue
                    current["lines"].append(line)
                    current["fragments"].append(remainder)
                    current["line_end"] = line_number
                    continue
            current["lines"].append(line)
            current["fragments"].append(_remove_leading_structural_marker(line))
            current["line_end"] = line_number
    return records, errors


def _remove_leading_structural_marker(line: str) -> str:
    """Detach a leading structural marker from verse text without losing its metadata."""
    stripped = line.strip()
    match = MARKER_RE.match(stripped)
    if not match:
        return stripped
    marker = _clean_marker(match.group(1))
    if PARA_MARKER_RE.fullmatch(marker):
        return stripped[_consume_delimiter(stripped, match.end()):]
    return stripped


def _build_top_level_usj(text: str, book_code: str, errors: list[str]) -> list[Any]:
    """Build the top-level USJ document from streamed block and inline marker events."""
    content: list[Any] = []
    current_para: dict[str, Any] | None = None
    current_chapter: str | None = None

    def ensure_para(marker: str = "p") -> dict[str, Any]:
        """Ensure that the current USJ output has the required paragraph container."""
        nonlocal current_para
        if current_para is None:
            current_para = {"type": "para", "marker": marker, "content": []}
            content.append(current_para)
        return current_para

    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        newline = "\n" if raw.endswith(("\n", "\r")) else ""
        stripped = line.strip()
        if not stripped:
            if current_para is not None:
                current_para.setdefault("content", []).append(newline)
            continue
        id_match = ID_RE.match(stripped)
        if id_match:
            content.append({"type": "book", "marker": "id", "code": id_match.group(1).upper(), "content": [id_match.group(2)] if id_match.group(2) else []})
            current_para = None
            continue
        chapter_match = CHAPTER_RE.match(stripped)
        if chapter_match:
            current_chapter = BIDI_RE.sub("", chapter_match.group(1))
            content.append({"type": "chapter", "marker": "c", "number": current_chapter, "sid": f"{book_code} {current_chapter}"})
            current_para = None
            continue
        marker_match = MARKER_RE.match(stripped)
        if marker_match:
            marker = _clean_marker(marker_match.group(1))
            after = _consume_delimiter(stripped, marker_match.end())
            remainder = stripped[after:]
            if PARA_MARKER_RE.fullmatch(marker):
                current_para = {"type": "para", "marker": marker, "content": []}
                content.append(current_para)
                _append_line_payload(current_para["content"], remainder, book_code, current_chapter, errors)
                if newline:
                    current_para["content"].append(newline)
                continue
            if marker == "v":
                para = ensure_para()
                _append_line_payload(para["content"], stripped, book_code, current_chapter, errors)
                if newline:
                    para["content"].append(newline)
                continue
        para = ensure_para()
        para["content"].extend(_parse_inline(stripped, errors))
        if newline:
            para["content"].append(newline)
    return content


def _append_line_payload(target: list[Any], payload: str, book_code: str, chapter: str | None, errors: list[str]) -> None:
    """Append one parsed line payload to the active USJ container."""
    if not payload:
        return
    verse_match = VERSE_RE.match(payload)
    if verse_match:
        number = BIDI_RE.sub("", verse_match.group(1))
        target.append({
            "type": "verse", "marker": "v", "number": number,
            "sid": f"{book_code} {chapter}:{number}" if chapter else f"{book_code} {number}",
        })
        target.extend(_parse_inline(verse_match.group(2), errors))
    else:
        target.extend(_parse_inline(payload, errors))




def compile_usfm_text(
    text: str,
    source_name: str = "",
    *,
    structure_policy: StructurePolicy | None = None,
) -> dict[str, Any]:
    """Compile UTF-8 USFM text to SAGE USJ using one explicit structure policy."""
    policy = structure_policy or default_structure_policy()
    errors: list[str] = []
    id_match = ID_RE.search(text)
    book_code = id_match.group(1).upper() if id_match else "UNK"
    if book_code == "UNK":
        errors.append("MISSING_BOOK_ID")
    raw_records, raw_errors = _raw_verse_records(text)
    errors.extend(raw_errors)
    structure_records = index_usfm_structure(text, book_code, policy)
    content = _build_top_level_usj(text, book_code, errors)
    verse_records: list[dict[str, Any]] = []
    for record in raw_records:
        record_errors: list[str] = []
        nodes: list[Any] = []
        for index, fragment in enumerate(record.pop("fragments")):
            if index:
                nodes.append("\n")
            nodes.extend(_parse_inline(fragment, record_errors))
        raw_usfm = "\n".join(record["lines"])
        exact = visible_text(nodes)
        verse_records.append(
            {
                **record,
                "raw_usfm": raw_usfm,
                "content": nodes,
                "body_text": exact,
                "body_text_exact": exact,
                "body_text_normalized": re.sub(r"\s+", " ", exact).strip(),
                "line_end": int(record.get("line_end", record.get("line_start", 0))),
                "parser_errors": sorted(set(record_errors)),
            }
        )
        errors.extend(
            f"{book_code} {record['chapter']}:{record['number']}:{item}"
            for item in record_errors
        )
    errors.extend(attach_structure_records(verse_records, structure_records))
    return {
        "type": "USJ",
        "version": USJ_VERSION,
        "content": content,
        "sage": {
            "compiler": USJ_COMPILER,
            "source_name": source_name,
            "book_code": book_code,
            "structure_policy_id": policy.policy_id,
            "structure_policy_sha256": policy.effective_sha256,
            "verse_records": verse_records,
            "errors": sorted(set(errors)),
        },
    }


def compile_usfm_file(
    path: Path,
    *,
    structure_policy: StructurePolicy | None = None,
) -> dict[str, Any]:
    """Compile one USFM file with strict UTF-8 and governed structure metadata."""
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    if "\ufffd" in text:
        raise UnicodeError(
            f"Literal Unicode replacement character U+FFFD is not approved in {path}"
        )
    usj = compile_usfm_text(
        text,
        path.name,
        structure_policy=structure_policy,
    )
    usj["sage"].update(
        {
            "source_sha256": _sha256_bytes(raw),
            "source_size": len(raw),
        }
    )
    return usj

def parse_usj_units(usj: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert compiled USJ into ordered atomic content units for task selection."""
    if usj.get("type") != "USJ":
        raise ValueError("USJ document type is missing or invalid.")
    records = usj.get("sage", {}).get("verse_records", [])
    if not isinstance(records, list):
        raise ValueError("SAGE USJ verse_records must be a list.")
    units: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        units.append({
            "chapter": int(item["chapter"]),
            "verse_start": int(item["verse_start"]),
            "verse_end": int(item["verse_end"]),
            "lines": list(item.get("lines", [])),
            "text": str(item.get("body_text_exact", item.get("body_text", ""))),
            "body_text": str(item.get("body_text_exact", item.get("body_text", ""))),
            "body_text_exact": str(item.get("body_text_exact", item.get("body_text", ""))),
            "body_text_normalized": str(item.get("body_text_normalized", "")),
            "raw_usfm": str(item.get("raw_usfm", "")),
            "content": item.get("content", []),
            "parser_errors": list(item.get("parser_errors", [])),
            "line_start": int(item.get("line_start", 0) or 0),
            "line_end": int(item.get("line_end", item.get("line_start", 0)) or 0),
            "source_locator": {
                "line_start": int(item.get("line_start", 0) or 0),
                "line_end": int(item.get("line_end", item.get("line_start", 0)) or 0),
            },
            "section_id": str(item.get("section_id", "")),
            "section_marker": str(item.get("section_marker", "")),
            "section_title": str(item.get("section_title", "")),
            "poetry_block_id": str(item.get("poetry_block_id", "")),
            "poetry_block_marker": str(item.get("poetry_block_marker", "")),
            "poetry_block_title": str(item.get("poetry_block_title", "")),
            "paragraph_id": str(item.get("paragraph_id", "")),
            "paragraph_marker": str(item.get("paragraph_marker", "")),
            "boundaries_before": list(item.get("boundaries_before", [])),
        })
    return units


