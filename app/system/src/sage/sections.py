"""USFM section, poetry-block, paragraph, chapter, and verse structure indexes."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .structure_policy import StructurePolicy, default_structure_policy
from .usfm_stream import iter_logical_usfm_lines

BIDI_CONTROLS = "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
BIDI_RE = re.compile(f"[{BIDI_CONTROLS}]")
MARKER_RE = re.compile(r"^\\(\+?[A-Za-z0-9][A-Za-z0-9-]*)(?:\*)?(?:\s+|$)(.*)$")
CHAPTER_RE = re.compile(r"^\\c\s+([^\s]+)")
VERSE_RE = re.compile(r"^\\v\s+([^\s]+)\s*(.*)$")
INLINE_MARKER_RE = re.compile(r"\\\+?[A-Za-z0-9][A-Za-z0-9-]*\*?(?:\s+)?")


def _clean_marker(value: str) -> str:
    """Return a canonical USFM marker name without slash, attributes, or numeric suffix noise."""
    marker = value.lstrip("+").casefold()
    return {"s": "s1", "ms": "ms1"}.get(marker, marker)


def _parse_verse_number(value: str) -> tuple[int, int] | None:
    """Parse the leading integer verse number used for section-boundary indexing."""
    cleaned = BIDI_RE.sub("", value).strip()
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", cleaned)
    if not match:
        return None
    start = int(match.group(1))
    return start, int(match.group(2) or start)


def _heading_text(value: str) -> str:
    """Return visible heading text with structural marker syntax removed."""
    return re.sub(r"\s+", " ", INLINE_MARKER_RE.sub("", value)).strip()


def _boundary(
    kind: str,
    marker: str,
    policy: StructurePolicy,
    *,
    continues_paragraph: bool = False,
    score_override: int | None = None,
) -> dict[str, Any]:
    """Create one scored structural boundary record at the supplied coordinate."""
    normalized = _clean_marker(marker)
    if score_override is not None:
        score = score_override
    elif kind == "SECTION":
        score = policy.section_score(normalized)
    elif kind == "POETRY_BLOCK":
        score = policy.poetry_score(normalized)
    elif kind == "PARAGRAPH":
        score = policy.paragraph_score
    elif kind == "CHAPTER":
        score = (
            policy.chapter_continuation_score
            if continues_paragraph
            else policy.chapter_score
        )
    else:
        score = policy.verse_score
    if score is None:
        raise ValueError(f"No configured score for {kind} marker {marker!r}")
    return {
        "kind": kind,
        "marker": normalized,
        "score": int(score),
        "continues_paragraph": continues_paragraph,
    }


def _replace_pending(
    pending: list[dict[str, Any]],
    boundary: dict[str, Any],
) -> None:
    """Keep the strongest same-kind boundary before the next verse.

    USFM can place a major heading and a subordinate heading before the same
    verse. The latest heading remains the active metadata, but planning must
    not lose the stronger major-boundary signal. Equal-strength candidates use
    the latest marker.
    """
    kind = boundary["kind"]
    existing = [item for item in pending if item["kind"] == kind]
    pending[:] = [item for item in pending if item["kind"] != kind]
    if existing and int(existing[-1].get("score", 0)) > int(boundary.get("score", 0)):
        pending.append(existing[-1])
    else:
        pending.append(boundary)


def index_usfm_structure(
    text: str,
    book_code: str,
    policy: StructurePolicy | None = None,
) -> list[dict[str, Any]]:
    """Index body records using the governed section and poetry-boundary model.

    The split hierarchy is section- and poetry-led. ``ms1``, ``ms2``, ``s1``
    and ``s2`` are section candidates; ``qa`` and ``b`` are poetry-block
    candidates; ``s3`` remains a structural header but is ignored for splitting.
    Poetry-line markers such as ``q1`` and ``qm1`` never split a work unit.

    ``m`` continues the immediately preceding non-header body block. A header or
    explicit poetry break prevents backward attachment, so ``m`` then starts a
    new body paragraph. A paragraph candidate is added only when no stronger
    section or poetry-block candidate is already pending.
    """
    active_policy = policy or default_structure_policy()
    book = book_code.upper()
    chapter: int | None = None
    section_sequence = 0
    poetry_sequence = 0
    paragraph_sequence = 0
    discourse_sequence = 0

    active_section_id = f"{book}-S000"
    active_section_marker = "book"
    active_section_title = ""
    active_poetry_id = ""
    active_poetry_marker = ""
    active_poetry_title = ""
    active_paragraph_id = ""
    active_paragraph_marker = "implicit"
    active_discourse_unit_id = ""
    active_discourse_unit_kind = ""
    active_discourse_unit_marker = ""

    pending_boundaries: list[dict[str, Any]] = []
    chapter_pending = False
    chapter_continues_paragraph = False
    body_attachment_open = False
    records: list[dict[str, Any]] = []

    def reset_discourse_unit() -> None:
        """Close the active natural RTC unit at one explicit structural breaker."""
        nonlocal active_discourse_unit_id
        nonlocal active_discourse_unit_kind
        nonlocal active_discourse_unit_marker
        active_discourse_unit_id = ""
        active_discourse_unit_kind = ""
        active_discourse_unit_marker = ""

    def start_discourse_unit(kind: str, marker: str) -> None:
        """Start one deterministic prose/list/poetry unit for bounded SAW RTC."""
        nonlocal discourse_sequence
        nonlocal active_discourse_unit_id
        nonlocal active_discourse_unit_kind
        nonlocal active_discourse_unit_marker
        discourse_sequence += 1
        active_discourse_unit_id = f"{book}-D{discourse_sequence:03d}"
        active_discourse_unit_kind = kind
        active_discourse_unit_marker = marker

    def start_paragraph(marker: str, *, add_boundary: bool) -> None:
        """Start a new paragraph boundary in the section index."""
        nonlocal paragraph_sequence
        nonlocal active_paragraph_id
        nonlocal active_paragraph_marker
        nonlocal body_attachment_open
        nonlocal chapter_continues_paragraph
        paragraph_sequence += 1
        active_paragraph_id = f"{book}-P{paragraph_sequence:03d}"
        active_paragraph_marker = marker
        body_attachment_open = True
        if chapter_pending:
            chapter_continues_paragraph = False
        if add_boundary:
            _replace_pending(
                pending_boundaries,
                _boundary("PARAGRAPH", marker, active_policy),
            )

    def ensure_body_block(marker: str) -> None:
        """Ensure that verse content is attached to an explicit body block."""
        nonlocal body_attachment_open
        if not body_attachment_open or not active_paragraph_id:
            start_paragraph(marker, add_boundary=not pending_boundaries)
        else:
            # q*/qm* and m continue the existing body block. Preserve the
            # marker that opened that block (commonly p in p...q...m...).
            body_attachment_open = True

    for line_number, stripped in iter_logical_usfm_lines(text):

        chapter_match = CHAPTER_RE.match(stripped)
        if chapter_match:
            number = BIDI_RE.sub("", chapter_match.group(1))
            if number.isdigit():
                chapter = int(number)
                chapter_pending = True
                chapter_continues_paragraph = body_attachment_open
                if book == "PSA":
                    # A Psalm chapter is an outer discourse boundary; ``\cl`` may
                    # immediately supply the display label for the same Psalm.
                    body_attachment_open = False
                    active_paragraph_id = ""
                    active_paragraph_marker = "implicit"
                    reset_discourse_unit()
            continue

        marker_match = MARKER_RE.match(stripped)
        marker = _clean_marker(marker_match.group(1)) if marker_match else ""
        remainder = marker_match.group(2) if marker_match else ""

        section_score = active_policy.section_score(marker, book) if marker else None
        if section_score is not None:
            section_sequence += 1
            active_section_id = f"{book}-S{section_sequence:03d}"
            active_section_marker = marker
            active_section_title = _heading_text(remainder)
            active_poetry_id = ""
            active_poetry_marker = ""
            active_poetry_title = ""
            body_attachment_open = False
            active_paragraph_id = ""
            active_paragraph_marker = "implicit"
            reset_discourse_unit()
            if chapter_pending:
                chapter_continues_paragraph = False
            _replace_pending(
                pending_boundaries,
                _boundary("SECTION", marker, active_policy, score_override=section_score),
            )
            continue

        poetry_score = active_policy.poetry_score(marker, book) if marker else None
        if poetry_score is not None:
            poetry_sequence += 1
            active_poetry_id = f"{book}-B{poetry_sequence:03d}"
            active_poetry_marker = marker
            active_poetry_title = _heading_text(remainder) if marker == "qa" else ""
            body_attachment_open = False
            active_paragraph_id = ""
            active_paragraph_marker = "implicit"
            reset_discourse_unit()
            if chapter_pending:
                chapter_continues_paragraph = False
            _replace_pending(
                pending_boundaries,
                _boundary("POETRY_BLOCK", marker, active_policy, score_override=poetry_score),
            )
            continue

        if marker and active_policy.is_header(marker):
            # Headers such as s3 remain structural barriers even when they are
            # intentionally excluded from work-unit split candidates.
            body_attachment_open = False
            active_paragraph_id = ""
            active_paragraph_marker = "implicit"
            reset_discourse_unit()
            if chapter_pending:
                chapter_continues_paragraph = False
            continue

        if marker and active_policy.is_continuation(marker):
            # ``m`` can continue prose layout, but a non-poetry paragraph marker
            # still terminates an operational poetry stanza.
            if active_discourse_unit_kind == "POETRY_STANZA":
                start_discourse_unit("PROSE_PARAGRAPH", marker)
            ensure_body_block(marker)
            if not active_discourse_unit_id:
                start_discourse_unit("PROSE_PARAGRAPH", marker)
            continue

        if marker and active_policy.is_poetry_line(marker):
            if not active_poetry_id:
                poetry_sequence += 1
                active_poetry_id = f"{book}-B{poetry_sequence:03d}"
                active_poetry_marker = marker
                active_poetry_title = ""
            if active_discourse_unit_kind != "POETRY_STANZA":
                start_discourse_unit("POETRY_STANZA", marker)
            ensure_body_block(marker)
            continue

        if marker and active_policy.is_body_paragraph(marker):
            active_poetry_id = ""
            active_poetry_marker = ""
            active_poetry_title = ""
            if marker == "lh":
                start_discourse_unit("LIST_HEADER", marker)
            elif marker == "li1":
                start_discourse_unit("LIST_MAJOR", marker)
            elif re.fullmatch(r"li[2-9]\d*", marker):
                if active_discourse_unit_kind != "LIST_MAJOR":
                    start_discourse_unit("LIST_SUBORDINATE", marker)
            elif marker == "lf":
                start_discourse_unit("LIST_FOOTER", marker)
            else:
                start_discourse_unit("PROSE_PARAGRAPH", marker)
            start_paragraph(marker, add_boundary=True)
            continue

        verse_match = VERSE_RE.match(stripped)
        if not verse_match or chapter is None:
            continue
        bounds = _parse_verse_number(verse_match.group(1))
        if bounds is None:
            continue
        if not body_attachment_open or not active_paragraph_id:
            start_paragraph("implicit", add_boundary=False)
        if not active_discourse_unit_id:
            start_discourse_unit("PROSE_PARAGRAPH", active_paragraph_marker or "implicit")
        if chapter_pending:
            has_colocated_label = book == "PSA" and any(
                item.get("kind") == "SECTION" and item.get("marker") == "cl"
                for item in pending_boundaries
            )
            if not has_colocated_label:
                _replace_pending(
                    pending_boundaries,
                    _boundary(
                        "CHAPTER",
                        "c",
                        active_policy,
                        continues_paragraph=chapter_continues_paragraph,
                        score_override=(active_policy.chapter_score_for(book) if book in active_policy.book_overrides else None),
                    ),
                )
        if not pending_boundaries and records:
            pending_boundaries.append(_boundary("VERSE", "v", active_policy))
        start, end = bounds
        records.append(
            {
                "book": book,
                "chapter": chapter,
                "verse_start": start,
                "verse_end": end,
                "reference": f"{book} {chapter}:{start}"
                + (f"-{end}" if end != start else ""),
                "line_start": line_number,
                "section_id": active_section_id,
                "section_marker": active_section_marker,
                "section_title": active_section_title,
                "poetry_block_id": active_poetry_id,
                "poetry_block_marker": active_poetry_marker,
                "poetry_block_title": active_poetry_title,
                "paragraph_id": active_paragraph_id,
                "paragraph_marker": active_paragraph_marker,
                "discourse_unit_id": active_discourse_unit_id,
                "discourse_unit_kind": active_discourse_unit_kind,
                "discourse_unit_marker": active_discourse_unit_marker,
                "boundaries_before": sorted(
                    pending_boundaries,
                    key=lambda item: (-int(item["score"]), item["kind"]),
                ),
            }
        )
        pending_boundaries = []
        chapter_pending = False
        chapter_continues_paragraph = False
        body_attachment_open = True
    return records


def attach_structure_records(
    verse_records: list[dict[str, Any]],
    structure_records: list[dict[str, Any]],
) -> list[str]:
    """Attach matching structure fields to compiled USJ verse records."""
    errors: list[str] = []
    buckets: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for record in structure_records:
        key = (
            int(record["chapter"]),
            int(record["verse_start"]),
            int(record["verse_end"]),
        )
        buckets.setdefault(key, []).append(record)
    for verse in verse_records:
        key = (
            int(verse["chapter"]),
            int(verse["verse_start"]),
            int(verse["verse_end"]),
        )
        matches = buckets.get(key, [])
        if not matches:
            errors.append(
                "STRUCTURE_RECORD_MISSING:"
                f"{verse['chapter']}:{verse['verse_start']}-{verse['verse_end']}"
            )
            continue
        structure = matches.pop(0)
        for field in (
            "section_id",
            "section_marker",
            "section_title",
            "poetry_block_id",
            "poetry_block_marker",
            "poetry_block_title",
            "paragraph_id",
            "paragraph_marker",
            "discourse_unit_id",
            "discourse_unit_kind",
            "discourse_unit_marker",
            "boundaries_before",
        ):
            verse[field] = structure[field]
    return errors


def section_index_from_usj(usj: dict[str, Any]) -> dict[str, Any]:
    """Return a compact, cacheable structure index from one SAGE USJ document."""
    records = []
    sage = usj.get("sage", {})
    book = str(sage.get("book_code", "UNK"))
    for record in sage.get("verse_records", []):
        if not isinstance(record, dict):
            continue
        records.append(
            {
                "book": book,
                "chapter": int(record["chapter"]),
                "verse_start": int(record["verse_start"]),
                "verse_end": int(record["verse_end"]),
                "reference": (
                    f"{book} {record['chapter']}:{record['verse_start']}"
                    + (
                        f"-{record['verse_end']}"
                        if int(record["verse_end"]) != int(record["verse_start"])
                        else ""
                    )
                ),
                "line_start": int(record.get("line_start", 0) or 0),
                "line_end": int(
                    record.get("line_end", record.get("line_start", 0)) or 0
                ),
                "section_id": str(record.get("section_id", "")),
                "section_marker": str(record.get("section_marker", "")),
                "section_title": str(record.get("section_title", "")),
                "poetry_block_id": str(record.get("poetry_block_id", "")),
                "poetry_block_marker": str(record.get("poetry_block_marker", "")),
                "poetry_block_title": str(record.get("poetry_block_title", "")),
                "paragraph_id": str(record.get("paragraph_id", "")),
                "paragraph_marker": str(record.get("paragraph_marker", "")),
                "discourse_unit_id": str(record.get("discourse_unit_id", "")),
                "discourse_unit_kind": str(record.get("discourse_unit_kind", "")),
                "discourse_unit_marker": str(record.get("discourse_unit_marker", "")),
                "boundaries_before": list(record.get("boundaries_before", [])),
            }
        )
    sections = Counter(record["section_id"] for record in records if record["section_id"])
    poetry_blocks = Counter(
        record["poetry_block_id"] for record in records if record["poetry_block_id"]
    )
    paragraphs = Counter(
        record["paragraph_id"] for record in records if record["paragraph_id"]
    )
    discourse_units = Counter(
        record["discourse_unit_id"] for record in records if record["discourse_unit_id"]
    )
    return {
        "schema_version": "1.2",
        "book": book,
        "source_sha256": str(sage.get("source_sha256", "")),
        "structure_policy": {
            "id": str(sage.get("structure_policy_id", "")),
            "sha256": str(sage.get("structure_policy_sha256", "")),
        },
        "summary": {
            "verse_records": len(records),
            "sections": len(sections),
            "poetry_blocks": len(poetry_blocks),
            "paragraphs": len(paragraphs),
            "discourse_units": len(discourse_units),
            "cross_chapter_sections": _count_cross_chapter_groups(records, "section_id"),
            "cross_chapter_poetry_blocks": _count_cross_chapter_groups(
                records,
                "poetry_block_id",
            ),
        },
        "records": records,
    }


def _count_cross_chapter_groups(records: list[dict[str, Any]], field: str) -> int:
    """Count section groups that span a chapter boundary."""
    chapters: dict[str, set[int]] = {}
    for record in records:
        group_id = str(record.get(field, ""))
        if group_id:
            chapters.setdefault(group_id, set()).add(int(record["chapter"]))
    return sum(1 for values in chapters.values() if len(values) > 1)
