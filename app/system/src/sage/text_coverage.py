"""Deterministic WIP omission detection: Authority text with no WIP text at the same canonical verse.

The ADDITION direction (WIP text without Authority text) is computed during packet routing. This module
adds the reverse direction for RTC (REFERENCE) and STC (original language): canonical Authority verses in
the scope window that no WIP verse carries, empty WIP verses, and chapters the WIP lacks entirely. Psalm
titles (``\\d``) are matched to the Authority's title verses instead of being reported as omissions.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from .references import ScriptureScope, ScriptureScopeSet
from .structural_issues import classify_text_relation, normalize_structure_problem
from .verse_alignment import ProjectVerseIndex
from .vrs import VerseRef
from .work_units import EvidenceRecord

SOURCE_TEXT_MISSING_IN_WIP = "SOURCE_TEXT_MISSING_IN_WIP"
SOURCE_CHAPTER_MISSING_IN_WIP = "SOURCE_CHAPTER_MISSING_IN_WIP"
# The Hebrew numbering gives a long Psalm title up to two verses (for example PSA 51:1-2).
_MAX_TITLE_VERSES = 2
_CHAPTER_RE = re.compile(r"^\s*\\c\s+(\d+)")
_TITLE_RE = re.compile(r"^\s*\\d(?:\s|$)")
_VERSE_RE = re.compile(r"^\s*\\v\s")


def _has_text(record: EvidenceRecord) -> bool:
    """Return whether one evidence record carries any body text."""
    return bool(str(record.payload.get("body_text") or "").strip())


def psalm_title_chapters(sfm_text: str) -> frozenset[int]:
    """Return the chapters whose SFM carries a ``\\d`` title before the first verse."""
    chapters: set[int] = set()
    chapter: int | None = None
    seen_verse = False
    for line in sfm_text.splitlines():
        match = _CHAPTER_RE.match(line)
        if match:
            chapter = int(match.group(1))
            seen_verse = False
            continue
        if _VERSE_RE.match(line):
            seen_verse = True
        elif chapter is not None and not seen_verse and _TITLE_RE.match(line):
            chapters.add(chapter)
    return frozenset(chapters)


def _scope_portions(scope: ScriptureScope | ScriptureScopeSet) -> tuple[ScriptureScope, ...]:
    """Flatten a scope or scope set into its portions."""
    return scope.portions if isinstance(scope, ScriptureScopeSet) else (scope,)


def omission_rows(
    wip_records: Sequence[EvidenceRecord],
    wip_index: ProjectVerseIndex,
    authority_records: Sequence[EvidenceRecord],
    authority_index: ProjectVerseIndex,
    scope: ScriptureScope | ScriptureScopeSet,
    *,
    workflow: str,
    authority_stream: str,
    authority_project_id: str,
    wip_project_id: str,
    title_chapters: Iterable[int] = (),
) -> list[dict[str, Any]]:
    """Return report-only OMISSION rows for Authority text the WIP does not carry inside ``scope``."""
    rows: list[dict[str, Any]] = []
    titles = frozenset(title_chapters)
    for portion in _scope_portions(scope):
        selected = [record for record in wip_records if any(portion.contains(ref) for ref in record.refs)]
        wip_canonical_text: set[VerseRef] = set()
        wip_canonical_all: set[VerseRef] = set()
        for record in selected:
            canonical = wip_index.canonical_refs_for_records((record,))
            wip_canonical_all.update(canonical)
            if _has_text(record):
                wip_canonical_text.update(canonical)
        if portion.start_chapter is None:
            chapters = sorted({record.chapter for record in authority_records if record.book == portion.book})
        else:
            chapters = list(range(portion.start_chapter, (portion.end_chapter or portion.start_chapter) + 1))
        whole_chapters = portion.start_verse is None
        if not whole_chapters and wip_canonical_all:
            # A verse-bounded scope compares only the canonical window its WIP verses span.
            low, high = min(wip_canonical_all), max(wip_canonical_all)
        else:
            low = high = None
        window_chapters = {ref.chapter for ref in wip_canonical_all} or set(chapters)
        if whole_chapters:
            window_chapters |= set(chapters)
        candidates: dict[VerseRef, EvidenceRecord] = {}
        for record in authority_records:
            if record.book != portion.book or not _has_text(record):
                continue
            for ref in authority_index.canonical_refs_for_records((record,)):
                if ref.chapter not in window_chapters:
                    continue
                if low is not None and not (low <= ref <= high):
                    continue
                candidates.setdefault(ref, record)
        wip_chapters = {record.chapter for record in selected}
        missing_chapters = sorted(
            {ref.chapter for ref in candidates} - {ref.chapter for ref in wip_canonical_all} - wip_chapters
        )
        for chapter in missing_chapters:
            rows.append(
                _row(
                    SOURCE_CHAPTER_MISSING_IN_WIP,
                    f"{portion.book} {chapter}",
                    f"{authority_project_id} has text in {portion.book} {chapter}, but {wip_project_id} has no "
                    "verses in this chapter.",
                    workflow=workflow,
                    authority_stream=authority_stream,
                    authority_project_id=authority_project_id,
                    wip_project_id=wip_project_id,
                    scope=portion.label(),
                )
            )
        missing = sorted(
            ref
            for ref in candidates
            if ref not in wip_canonical_text and ref.chapter not in set(missing_chapters)
        )
        if portion.book == "PSA":
            # A WIP \d title carries the Authority's leading title verse(s) of the same chapter.
            missing = [
                ref
                for ref in missing
                if not (
                    ref.chapter in titles
                    and ref.verse <= _MAX_TITLE_VERSES
                    and all(
                        other in missing
                        for other in (VerseRef(ref.book, ref.chapter, verse) for verse in range(1, ref.verse))
                    )
                )
            ]
        for ref in missing:
            local = sorted(wip_index.local_refs_for_canonical((ref,)))
            label = local[0].label() if local else ref.label()
            empty = ref in wip_canonical_all
            rows.append(
                _row(
                    SOURCE_TEXT_MISSING_IN_WIP,
                    label,
                    (
                        f"{wip_project_id} {label} is empty, but {authority_project_id} has text at the same "
                        f"verse ({ref.label()})."
                        if empty
                        else f"{authority_project_id} has text at {ref.label()} that no verse of "
                        f"{wip_project_id} carries."
                    ),
                    workflow=workflow,
                    authority_stream=authority_stream,
                    authority_project_id=authority_project_id,
                    wip_project_id=wip_project_id,
                    scope=portion.label(),
                    canonical=ref.label(),
                )
            )
    return rows


def _row(
    code: str,
    reference: str,
    message: str,
    *,
    workflow: str,
    authority_stream: str,
    authority_project_id: str,
    wip_project_id: str,
    scope: str,
    canonical: str | None = None,
) -> dict[str, Any]:
    """Build one normalized OMISSION structure problem."""
    relation = classify_text_relation(wip_has_text=False, authority_has_text=True)
    row = {
        "code": code,
        "workflow": str(workflow).strip().upper(),
        "source_stream": str(authority_stream).strip().upper(),
        "source_project_id": authority_project_id,
        "wip_project_id": wip_project_id,
        "scope": scope,
        "reference": reference,
        "message": message + " The Run continued and reported the omission.",
    }
    if canonical:
        row["canonical_references"] = [canonical]
    return normalize_structure_problem(row, versification=False, relation=relation)


def gap_findings(rows: Iterable[Mapping[str, Any]], *, prefix: str = "G") -> list[dict[str, Any]]:
    """Promote OMISSION and ADDITION rows to deterministic RTC STRUCTURE findings."""
    findings: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        relation = str(row.get("text_relation") or "").upper()
        if relation not in {"OMISSION", "ADDITION"}:
            continue
        authority = str(row.get("source_project_id") or row.get("source_stream") or "the comparison text")
        findings.append(
            {
                "finding_id": f"{prefix}{index:03d}",
                "target_reference": str(row.get("reference") or ""),
                "category": "STRUCTURE",
                "issue": str(row.get("message") or ""),
                "required_action": (
                    "Check whether text is missing from the WIP at this coordinate."
                    if relation == "OMISSION"
                    else f"Check whether this WIP text has no counterpart in {authority}."
                ),
                "action_level": "REVIEW",
                "confidence": "HIGH",
                "evidence_ids": ["WIP", "REFERENCE"],
                "grammar_rule_ids": [],
                "original_language_evidence": "",
                "detection": "DETERMINISTIC",
                "text_relation": relation,
            }
        )
    return findings
