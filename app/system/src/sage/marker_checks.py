"""Deterministic USFM marker checks for RTC: cross-reference targets, footnote structure, \\add and \\nd.

Code decides what it can: cross-reference targets are compared with the REFERENCE at the same canonical
verse, and footnotes must carry an origin (``\\fr``) matching their verse and a text (``\\ft``). Differing
``\\add`` and ``\\nd`` counts are only candidates: whether they matter is left to the model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .errors import ValidationError
from .verse_alignment import ProjectVerseIndex
from .work_units import EvidenceRecord

# Chapter:verse pairs inside a target list; book names are localized, so only the numbers are compared.
_TARGET_RE = re.compile(r"(\d+)\s*[:.]\s*(\d+)(?:\s*[-–]\s*(\d+))?")
_ORIGIN_RE = re.compile(r"^\s*(\d+)\s*[:.,]\s*(\d+)")


def _text(nodes: Iterable[Any]) -> str:
    """Flatten USJ inline content to plain text."""
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, Mapping):
            parts.append(_text(node.get("content") or []))
    return "".join(parts)


def _walk(nodes: Iterable[Any]) -> Iterable[Mapping[str, Any]]:
    """Yield every marker node in document order."""
    for node in nodes:
        if isinstance(node, Mapping):
            yield node
            yield from _walk(node.get("content") or [])


def verse_markers(content: Sequence[Any]) -> dict[str, Any]:
    """Summarize one verse's cross-references, footnotes, and \\add and \\nd spans."""
    targets: set[tuple[int, int, int]] = set()
    footnotes: list[dict[str, Any]] = []
    counts = {"add": 0, "nd": 0}
    for node in _walk(content):
        marker = str(node.get("marker") or "")
        if marker in counts and node.get("type") == "char":
            counts[marker] += 1
        elif marker == "xt":
            for chapter, start, end in _TARGET_RE.findall(_text(node.get("content") or [])):
                targets.add((int(chapter), int(start), int(end or start)))
        elif marker == "f" and node.get("type") == "note":
            children = [child for child in node.get("content") or [] if isinstance(child, Mapping)]
            origin = next((_text(child.get("content") or []) for child in children if child.get("marker") == "fr"), None)
            footnotes.append(
                {
                    "origin": origin.strip() if origin is not None else None,
                    "has_text": any(
                        child.get("marker") == "ft" and _text(child.get("content") or []).strip()
                        for child in children
                    ),
                }
            )
    return {"targets": targets, "footnotes": footnotes, **counts}


def load_verse_content(project_result: Mapping[str, Any]) -> dict[tuple[str, int, int, int], list[Any]]:
    """Load each verse's USJ inline content from a compiled Project's content-addressed caches."""
    content: dict[tuple[str, int, int, int], list[Any]] = {}
    for file_result in project_result.get("files", []):
        cache_path = Path(str(file_result.get("cache", "")))
        try:
            usj = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"USJ cache is unreadable for marker checks: {cache_path}: {exc}") from exc
        book = str(usj.get("sage", {}).get("book_code", "UNK"))
        for item in usj.get("sage", {}).get("verse_records", []):
            if isinstance(item, dict):
                key = (book, int(item["chapter"]), int(item["verse_start"]), int(item["verse_end"]))
                content[key] = list(item.get("content") or [])
    return content


def _key(record: EvidenceRecord) -> tuple[str, int, int, int]:
    """Return a record's content key."""
    return (record.book, record.chapter, record.verse_start, record.verse_end)


def _origin_matches(origin: str, record: EvidenceRecord) -> bool:
    """Return whether a footnote origin names a verse of its own record."""
    match = _ORIGIN_RE.match(origin)
    if not match:
        return False
    chapter, verse = int(match.group(1)), int(match.group(2))
    return chapter == record.chapter and record.verse_start <= verse <= record.verse_end


def marker_review(
    wip_records: Sequence[EvidenceRecord],
    wip_content: Mapping[tuple[str, int, int, int], Sequence[Any]],
    wip_index: ProjectVerseIndex,
    reference_index: ProjectVerseIndex,
    reference_content: Mapping[tuple[str, int, int, int], Sequence[Any]],
    *,
    wip_project_id: str,
    reference_project_id: str,
) -> dict[str, list[dict[str, Any]]]:
    """Return deterministic marker ``findings`` and ``candidates`` whose materiality the model decides."""
    findings: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    def finding(record: EvidenceRecord, issue: str, action: str) -> None:
        """Record one deterministic STRUCTURE finding at a WIP verse."""
        findings.append(
            {
                "finding_id": f"M{len(findings) + 1:03d}",
                "target_reference": record.reference,
                "category": "STRUCTURE",
                "issue": issue,
                "required_action": action,
                "action_level": "REVIEW",
                "confidence": "HIGH",
                "evidence_ids": ["WIP", "REFERENCE"],
                "grammar_rule_ids": [],
                "original_language_evidence": "",
                "detection": "DETERMINISTIC",
            }
        )

    for record in wip_records:
        wip = verse_markers(wip_content.get(_key(record), ()))
        for note in wip["footnotes"]:
            if note["origin"] is None:
                finding(record, f"A footnote at {record.reference} has no origin reference (\\fr).", "Add the footnote origin.")
            elif not _origin_matches(note["origin"], record):
                finding(
                    record,
                    f"A footnote at {record.reference} names origin {note['origin']}, which is not this verse.",
                    "Correct the footnote origin or move the footnote to its verse.",
                )
            if not note["has_text"]:
                finding(record, f"A footnote at {record.reference} has no footnote text (\\ft).", "Add the footnote text or remove the empty footnote.")
        canonical = wip_index.canonical_refs_for_records((record,))
        reference_records = reference_index.records_for_canonical(canonical)
        if not reference_records:
            continue
        reference_summary = [verse_markers(reference_content.get(_key(item), ())) for item in reference_records]
        reference_targets = set().union(*(item["targets"] for item in reference_summary))
        if (wip["targets"] or reference_targets) and wip["targets"] != reference_targets:
            missing = sorted(reference_targets - wip["targets"])
            extra = sorted(wip["targets"] - reference_targets)
            details = "; ".join(
                part
                for part in (
                    f"{reference_project_id} only: " + ", ".join(f"{c}:{s}" + (f"-{e}" if e != s else "") for c, s, e in missing)
                    if missing
                    else "",
                    f"{wip_project_id} only: " + ", ".join(f"{c}:{s}" + (f"-{e}" if e != s else "") for c, s, e in extra)
                    if extra
                    else "",
                )
                if part
            )
            finding(
                record,
                f"Cross-reference targets at {record.reference} differ from {reference_project_id} ({details}).",
                "Check the cross-reference targets against the Reference.",
            )
        for marker in ("add", "nd"):
            reference_count = sum(item[marker] for item in reference_summary)
            if wip[marker] != reference_count:
                candidates.append(
                    {
                        "target_reference": record.reference,
                        "marker": marker,
                        "wip_count": wip[marker],
                        "reference_count": reference_count,
                    }
                )
    return {"findings": findings, "candidates": candidates}


def packet_marker_candidates(wip_packet: Path, reference_packet: Path) -> list[dict[str, Any]]:
    """Compare \\add and \\nd counts between two bounded USJ packets verse by verse (same local label)."""

    def counts(path: Path) -> dict[str, dict[str, int]]:
        """Return per-verse marker counts keyed by verse label."""
        try:
            usj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        book = str(usj.get("sage", {}).get("book_code") or "")
        rows: dict[str, dict[str, int]] = {}
        for item in usj.get("sage", {}).get("verse_records", []):
            if not isinstance(item, dict):
                continue
            start, end = int(item["verse_start"]), int(item["verse_end"])
            label = f"{book} {item['chapter']}:{start}" + (f"-{end}" if end != start else "")
            summary = verse_markers(item.get("content") or [])
            rows[label] = {"add": summary["add"], "nd": summary["nd"]}
        return rows

    wip, reference = counts(wip_packet), counts(reference_packet)
    return [
        {"target_reference": label, "marker": marker, "wip_count": values[marker], "reference_count": reference[label][marker]}
        for label, values in wip.items()
        if label in reference
        for marker in ("add", "nd")
        if values[marker] != reference[label][marker]
    ]
