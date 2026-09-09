"""Bounded BIC TARGET book merge, history, restart, and revert helpers."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .atomic import atomic_write_json, atomic_write_text
from .errors import ValidationError
from .hashing import sha256_bytes, sha256_file
from .references import ScriptureScope, parse_scope
from .transactions import FileTransaction
from .usfm_stream import iter_logical_usfm_lines
from .vrs import VerseRef

_CHAPTER_RE = re.compile(r"^\\c\s+(\d+)\b")
_VERSE_RE = re.compile(r"^\\v\s+([^\s]+)(?:\s|$)")
_VERSE_NUMBER_RE = re.compile(r"^(\d+)(?:-(\d+))?$")


@dataclass(frozen=True)
class VerseBlock:
    """One ordered USFM verse block and the structural markers immediately preceding it."""

    chapter: int
    start_verse: int
    end_verse: int
    lines: tuple[str, ...]

    @property
    def refs(self) -> tuple[VerseRef, ...]:
        """Return every coordinate covered by the verse or bridge marker."""
        return tuple(VerseRef("", self.chapter, verse) for verse in range(self.start_verse, self.end_verse + 1))


@dataclass(frozen=True)
class RawBlock:
    """One sequence of logical USFM lines not owned by a verse block."""

    lines: tuple[str, ...]


def _verse_bounds(label: str) -> tuple[int, int]:
    """Parse one simple USFM verse or bridge label and fail closed on unsupported labels."""
    match = _VERSE_NUMBER_RE.fullmatch(label.strip())
    if not match:
        raise ValidationError(
            f"Bounded TARGET merge does not support complex verse label {label!r}; split or normalize the scope first",
            code="TARGET_SCOPE_COMPLEX_VERSE_UNSUPPORTED",
        )
    start = int(match.group(1))
    end = int(match.group(2) or start)
    if end < start:
        raise ValidationError(f"Invalid verse bridge {label!r}")
    return start, end


def _parse_blocks(text: str) -> list[RawBlock | VerseBlock]:
    """Parse logical USFM into stable raw and verse blocks without reinterpreting inline content."""
    blocks: list[RawBlock | VerseBlock] = []
    pending: list[str] = []
    chapter: int | None = None
    for _, fragment in iter_logical_usfm_lines(text):
        stripped = fragment.strip()
        chapter_match = _CHAPTER_RE.match(stripped)
        if chapter_match:
            if pending:
                blocks.append(RawBlock(tuple(pending)))
                pending = []
            chapter = int(chapter_match.group(1))
            blocks.append(RawBlock((stripped,)))
            continue
        verse_match = _VERSE_RE.match(stripped)
        if verse_match:
            if chapter is None:
                raise ValidationError("USFM verse occurs before an explicit chapter marker")
            start, end = _verse_bounds(verse_match.group(1))
            lines = tuple([*pending, stripped])
            pending = []
            blocks.append(VerseBlock(chapter, start, end, lines))
            continue
        pending.append(stripped)
    if pending:
        blocks.append(RawBlock(tuple(pending)))
    return blocks


def _block_inside_scope(block: VerseBlock, scope: ScriptureScope) -> tuple[bool, bool]:
    """Return whether a verse block is fully or partly inside a requested scope."""
    refs = [VerseRef(scope.book, block.chapter, verse) for verse in range(block.start_verse, block.end_verse + 1)]
    inside = [scope.contains(ref) for ref in refs]
    return all(inside), any(inside)


def _scope_blocks(text: str, scope: ScriptureScope) -> list[VerseBlock]:
    """Return exact verse blocks wholly contained by the scope; reject crossing bridges."""
    result: list[VerseBlock] = []
    for block in _parse_blocks(text):
        if not isinstance(block, VerseBlock):
            continue
        full, partial = _block_inside_scope(block, scope)
        if partial and not full:
            raise ValidationError(
                f"Verse bridge {block.chapter}:{block.start_verse}-{block.end_verse} crosses bounded scope {scope.label()}",
                code="TARGET_SCOPE_BRIDGE_CROSSES_BOUNDARY",
            )
        if full:
            result.append(block)
    return result


def _render_blocks(blocks: Iterable[RawBlock | VerseBlock]) -> str:
    """Render logical blocks deterministically while preserving their internal line text."""
    lines: list[str] = []
    for block in blocks:
        lines.extend(block.lines)
    return "\n".join(lines).rstrip() + "\n"


def extract_scope_usfm(text: str, scope_value: str) -> str:
    """Extract one self-contained bounded USFM fragment for history and comparison."""
    scope = parse_scope(scope_value)
    blocks = _scope_blocks(text, scope)
    if not blocks:
        return ""
    rendered: list[RawBlock | VerseBlock] = []
    current_chapter: int | None = None
    for block in blocks:
        if block.chapter != current_chapter:
            rendered.append(RawBlock((f"\\c {block.chapter}",)))
            current_chapter = block.chapter
        rendered.append(block)
    return _render_blocks(rendered)




def _scope_shape(text: str, scope: ScriptureScope) -> tuple[tuple[tuple[int, int, int], ...], frozenset[int]]:
    """Return simple verse/bridge shapes intersecting scope without parsing unrelated complex labels."""
    chapter: int | None = None
    chapters: set[int] = set()
    ranges: list[tuple[int, int, int]] = []
    for _, fragment in iter_logical_usfm_lines(text):
        stripped = fragment.strip()
        chapter_match = _CHAPTER_RE.match(stripped)
        if chapter_match:
            chapter = int(chapter_match.group(1))
            if scope.start_chapter is None or (scope.start_chapter <= chapter <= (scope.end_chapter or scope.start_chapter)):
                chapters.add(chapter)
            continue
        verse_match = _VERSE_RE.match(stripped)
        if verse_match is None or chapter is None:
            continue
        label = verse_match.group(1).strip()
        simple = _VERSE_NUMBER_RE.fullmatch(label)
        if simple is None:
            numeric = re.match(r"^(\d+)", label)
            relevant = False
            if scope.start_chapter is None:
                relevant = True
            elif scope.start_verse is None:
                relevant = scope.start_chapter <= chapter <= (scope.end_chapter or scope.start_chapter)
            elif numeric is None:
                relevant = scope.start_chapter <= chapter <= (scope.end_chapter or scope.start_chapter)
            else:
                relevant = scope.contains(VerseRef(scope.book, chapter, int(numeric.group(1))))
            if relevant:
                raise ValidationError(
                    f"Bounded TARGET commit does not support complex verse label {label!r} inside {scope.label()}",
                    code="TARGET_SCOPE_COMPLEX_VERSE_UNSUPPORTED",
                    details={"scope": scope.label(), "chapter": chapter, "label": label},
                )
            continue
        start = int(simple.group(1))
        end = int(simple.group(2) or start)
        block = VerseBlock(chapter, start, end, (stripped,))
        full, partial = _block_inside_scope(block, scope)
        if partial and not full:
            raise ValidationError(
                f"Verse bridge {chapter}:{start}-{end} crosses bounded scope {scope.label()}",
                code="TARGET_SCOPE_BRIDGE_CROSSES_BOUNDARY",
                details={"scope": scope.label(), "target": (chapter, start, end)},
            )
        if full:
            ranges.append((chapter, start, end))
    return tuple(ranges), frozenset(chapters)


def preflight_bounded_target_commit(
    target_text: str,
    source_text: str,
    scope_value: str,
    *,
    expected_shapes: Iterable[Iterable[int]] | None = None,
) -> dict[str, Any]:
    """Fail before execution when TARGET cannot accept the projected verse shape."""
    scope = parse_scope(scope_value)
    if expected_shapes is None:
        source_ranges, _ = _scope_shape(source_text, scope)
    else:
        normalized_shapes: list[tuple[int, int, int]] = []
        for raw_shape in expected_shapes:
            values = tuple(int(value) for value in raw_shape)
            if len(values) != 3:
                raise ValidationError(
                    "Projected BIC TARGET shape must contain chapter, start verse, and end verse",
                    code="BIC_TARGET_VRS_ALIGNMENT_REQUIRED",
                    details={"scope": scope.label()},
                )
            chapter, start, end = values
            block = VerseBlock(chapter, start, end, ())
            full, _ = _block_inside_scope(block, scope)
            if start < 1 or end < start or not full:
                raise ValidationError(
                    "Projected BIC TARGET shape falls outside its sealed TARGET scope",
                    code="BIC_TARGET_VRS_ALIGNMENT_REQUIRED",
                    details={"scope": scope.label(), "shape": values},
                )
            normalized_shapes.append(values)
        source_ranges = tuple(normalized_shapes)
        if len(source_ranges) != len(set(source_ranges)):
            raise ValidationError(
                "Projected BIC TARGET shape contains duplicate verse blocks",
                code="BIC_TARGET_VRS_ALIGNMENT_REQUIRED",
                details={"scope": scope.label()},
            )
    if not source_ranges:
        raise ValidationError(
            f"BIC has no projected TARGET verse blocks for bounded scope {scope.label()}",
            code="TARGET_SCOPE_SOURCE_EMPTY",
            details={"scope": scope.label()},
        )
    if not target_text.strip():
        return {"status": "READY_NEW_TARGET", "scope": scope.label(), "source_shapes": list(source_ranges)}
    target_ranges, target_chapters = _scope_shape(target_text, scope)
    required_chapters = {chapter for chapter, _start, _end in source_ranges}
    missing_chapters = sorted(required_chapters - set(target_chapters))
    if missing_chapters:
        raise ValidationError(
            f"TARGET book is missing chapter(s) required for bounded commit: {', '.join(str(value) for value in missing_chapters)}",
            code="TARGET_SCOPE_CHAPTER_MISSING",
            details={"scope": scope.label(), "chapters": missing_chapters},
        )
    source_set = set(source_ranges)
    target_set = set(target_ranges)
    incompatible_existing = sorted(target_set - source_set)
    if incompatible_existing:
        raise ValidationError(
            "Existing TARGET verse/bridge shape differs from the projected BIC output inside the bounded scope",
            code="TARGET_SCOPE_VERSE_SHAPE_MISMATCH",
            details={"scope": scope.label(), "target_only_shapes": incompatible_existing, "source_shapes": list(source_ranges)},
        )
    missing_bridges = sorted(shape for shape in source_set - target_set if shape[1] != shape[2])
    if missing_bridges:
        raise ValidationError(
            "TARGET is missing a bridged verse shape that bounded commit cannot insert automatically",
            code="TARGET_SCOPE_INSERT_BRIDGE_UNSUPPORTED",
            details={"scope": scope.label(), "missing_bridges": missing_bridges},
        )
    return {
        "status": "READY",
        "scope": scope.label(),
        "source_shapes": list(source_ranges),
        "target_shapes": list(target_ranges),
        "ordinary_insertions_allowed": [list(shape) for shape in sorted(source_set - target_set)],
    }


def merge_bounded_usfm(target_text: str, candidate_text: str, scope_value: str) -> str:
    """Replace only bounded verse blocks in one TARGET book and preserve all other book content."""
    scope = parse_scope(scope_value)
    candidate_blocks = _scope_blocks(candidate_text, scope)
    if not candidate_blocks:
        raise ValidationError(f"Bounded candidate contains no verse blocks for {scope.label()}")
    target_blocks = _parse_blocks(target_text)

    candidate_by_range = {
        (block.chapter, block.start_verse, block.end_verse): block for block in candidate_blocks
    }
    if len(candidate_by_range) != len(candidate_blocks):
        raise ValidationError("Bounded candidate repeats a verse/bridge block")

    output: list[RawBlock | VerseBlock] = []
    used: set[tuple[int, int, int]] = set()
    for block in target_blocks:
        if not isinstance(block, VerseBlock):
            output.append(block)
            continue
        full, partial = _block_inside_scope(block, scope)
        if partial and not full:
            raise ValidationError(
                f"Existing TARGET bridge {block.chapter}:{block.start_verse}-{block.end_verse} crosses bounded scope {scope.label()}",
                code="TARGET_SCOPE_BRIDGE_CROSSES_BOUNDARY",
            )
        if not full:
            output.append(block)
            continue
        key = (block.chapter, block.start_verse, block.end_verse)
        replacement = candidate_by_range.get(key)
        if replacement is None:
            raise ValidationError(
                "Existing TARGET verse/bridge shape differs from the bounded candidate; SAGE will not guess a bridge split/merge",
                code="TARGET_SCOPE_VERSE_SHAPE_MISMATCH",
                details={"target": key, "scope": scope.label()},
            )
        output.append(replacement)
        used.add(key)

    missing = [block for key, block in candidate_by_range.items() if key not in used]
    if missing:
        # Insert missing ordinary verse blocks inside their existing chapter. Never
        # search globally by verse coordinate: doing so can place a verse after the
        # next ``\c`` marker when the insertion belongs at the end of a chapter.
        for new_block in missing:
            if new_block.start_verse != new_block.end_verse:
                raise ValidationError(
                    "Cannot insert a new bridged verse into an existing TARGET book automatically",
                    code="TARGET_SCOPE_INSERT_BRIDGE_UNSUPPORTED",
                )
            chapter_marker_index: int | None = None
            for idx, item in enumerate(output):
                if not isinstance(item, RawBlock):
                    continue
                if any(
                    (match := _CHAPTER_RE.match(line))
                    and int(match.group(1)) == new_block.chapter
                    for line in item.lines
                ):
                    chapter_marker_index = idx
                    break
            if chapter_marker_index is None:
                raise ValidationError(
                    f"TARGET book has no chapter {new_block.chapter}; create the book/chapter explicitly before bounded insertion",
                    code="TARGET_SCOPE_CHAPTER_MISSING",
                )

            insert_at: int | None = None
            last_same_chapter_verse: int | None = None
            for idx in range(chapter_marker_index + 1, len(output)):
                item = output[idx]
                if isinstance(item, RawBlock) and any(_CHAPTER_RE.match(line) for line in item.lines):
                    break
                if not isinstance(item, VerseBlock) or item.chapter != new_block.chapter:
                    continue
                if item.start_verse > new_block.start_verse:
                    insert_at = idx
                    break
                last_same_chapter_verse = idx
            if insert_at is None:
                insert_at = (last_same_chapter_verse + 1) if last_same_chapter_verse is not None else (chapter_marker_index + 1)
            output.insert(insert_at, new_block)

    merged = _render_blocks(output)
    _validate_bounded_merge(target_text, candidate_text, merged, scope_value)
    return merged


def _validate_bounded_merge(
    before_text: str,
    candidate_text: str,
    merged_text: str,
    scope_value: str,
) -> None:
    """Fail closed unless a merge reproduces the candidate and preserves out-of-scope content."""
    expected_scope = extract_scope_usfm(candidate_text, scope_value)
    actual_scope = extract_scope_usfm(merged_text, scope_value)
    if not actual_scope.strip() or actual_scope != expected_scope:
        raise ValidationError(
            "Bounded TARGET merge did not reproduce the candidate at the requested coordinates",
            code="TARGET_SCOPE_POST_MERGE_MISMATCH",
            details={
                "scope": parse_scope(scope_value).label(),
                "expected_scope_sha256": sha256_bytes(expected_scope.encode("utf-8")),
                "actual_scope_sha256": sha256_bytes(actual_scope.encode("utf-8")),
            },
        )
    before_outside = remove_scope_usfm(before_text, scope_value)
    after_outside = remove_scope_usfm(merged_text, scope_value)
    if before_outside != after_outside:
        raise ValidationError(
            "Bounded TARGET merge changed content outside the requested scope",
            code="TARGET_SCOPE_OUTSIDE_CONTENT_CHANGED",
            details={"scope": parse_scope(scope_value).label()},
        )


def remove_scope_usfm(target_text: str, scope_value: str) -> str:
    """Remove only verse blocks wholly inside one scope, preserving every other TARGET block."""
    scope = parse_scope(scope_value)
    output: list[RawBlock | VerseBlock] = []
    for block in _parse_blocks(target_text):
        if not isinstance(block, VerseBlock):
            output.append(block)
            continue
        full, partial = _block_inside_scope(block, scope)
        if partial and not full:
            raise ValidationError(
                "Cannot remove part of a bridged TARGET verse",
                code="TARGET_SCOPE_BRIDGE_CROSSES_BOUNDARY",
            )
        if not full:
            output.append(block)
    return _render_blocks(output)


def history_root(job_root: Path) -> Path:
    """Return the BIC Job-owned bounded TARGET history directory."""
    return job_root / "target-history"


def record_target_commit(
    *,
    job_root: Path,
    target_file: Path,
    scope_value: str,
    before_text: str,
    after_text: str,
    transaction_id: str,
    task_id: str,
    run_id: str,
    created_utc: str,
) -> dict[str, Any]:
    """Record immutable bounded before/after TARGET evidence for one successful commit."""
    root = history_root(job_root)
    root.mkdir(parents=True, exist_ok=True)
    before_scope = extract_scope_usfm(before_text, scope_value) if before_text.strip() else ""
    after_scope = extract_scope_usfm(after_text, scope_value)
    if not after_scope.strip():
        raise ValidationError(
            "Successful TARGET commit produced an empty committed scope",
            code="TARGET_HISTORY_AFTER_SCOPE_EMPTY",
            details={"scope": parse_scope(scope_value).label()},
        )
    ordering_ns = time.time_ns()
    commit_id = (
        f"{created_utc.replace(':', '').replace('+00:00', 'Z').replace('-', '')}-"
        f"{ordering_ns:020d}-{transaction_id[:12]}"
    )
    entry = root / commit_id
    entry.mkdir(parents=True, exist_ok=False)
    atomic_write_text(entry / "before-scope.usfm", before_scope)
    atomic_write_text(entry / "after-scope.usfm", after_scope)
    manifest = {
        "schema_version": "1.0",
        "commit_id": commit_id,
        "scope": scope_value,
        "target_file": str(target_file),
        "transaction_id": transaction_id,
        "task_id": task_id,
        "run_id": run_id,
        "created_utc": created_utc,
        "ordering_ns": ordering_ns,
        "before_scope_sha256": sha256_bytes(before_scope.encode("utf-8")),
        "after_scope_sha256": sha256_bytes(after_scope.encode("utf-8")),
        "before_book_sha256": sha256_bytes(before_text.encode("utf-8")),
        "after_book_sha256": sha256_bytes(after_text.encode("utf-8")),
    }
    atomic_write_json(entry / "manifest.json", manifest)
    return {**manifest, "history_path": str(entry / "manifest.json")}


def list_target_history(job_root: Path, *, scope_value: str | None = None) -> list[dict[str, Any]]:
    """List bounded TARGET commits newest-first, optionally filtered to one exact scope."""
    root = history_root(job_root)
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in root.glob("*/manifest.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(row, dict):
            continue
        if scope_value is not None and row.get("scope") != scope_value:
            continue
        row = dict(row)
        row["history_path"] = str(path)
        rows.append(row)
    rows.sort(
        key=lambda row: (
            str(row.get("created_utc", "")),
            int(row.get("ordering_ns", 0) or 0),
            str(row.get("commit_id", "")),
        ),
        reverse=True,
    )
    return rows


def revert_target_scope(
    *,
    job_root: Path,
    target_file: Path,
    scope_value: str,
    transaction_root: Path,
    allowed_roots: tuple[Path, ...],
) -> dict[str, Any]:
    """Restore the immediately previous committed content for one exact TARGET scope."""
    rows = list_target_history(job_root, scope_value=scope_value)
    if not rows:
        raise ValidationError(f"No TARGET history exists for scope {scope_value}", code="TARGET_HISTORY_NOT_FOUND")
    latest = rows[0]
    entry = Path(str(latest["history_path"])).parent
    before_scope = (entry / "before-scope.usfm").read_text(encoding="utf-8")
    current_text = target_file.read_text(encoding="utf-8")
    current_scope = extract_scope_usfm(current_text, scope_value)
    current_scope_hash = sha256_bytes(current_scope.encode("utf-8"))
    if current_scope_hash != latest["after_scope_sha256"]:
        raise ValidationError(
            "TARGET scope no longer matches the latest committed version; revert refused",
            code="TARGET_REVERT_CONFLICT",
            details={"expected": latest["after_scope_sha256"], "current": current_scope_hash},
        )
    if before_scope.strip():
        restored = merge_bounded_usfm(current_text, before_scope, scope_value)
    else:
        restored = remove_scope_usfm(current_text, scope_value)
    restored_scope = extract_scope_usfm(restored, scope_value)
    if restored_scope != before_scope:
        raise ValidationError(
            "TARGET revert did not restore the exact historical scope; write refused",
            code="TARGET_REVERT_POST_MERGE_MISMATCH",
            details={"scope": parse_scope(scope_value).label()},
        )
    transaction = FileTransaction(transaction_root, operation="BIC_TARGET_SCOPE_REVERT", allowed_roots=allowed_roots)
    transaction.stage_bytes(target_file, restored.encode("utf-8"))
    transaction.commit()
    receipt = {
        "schema_version": "1.0",
        "status": "REVERTED",
        "scope": scope_value,
        "reverted_commit_id": latest["commit_id"],
        "transaction_id": transaction.transaction_id,
        "target_file": str(target_file),
        "target_sha256": sha256_file(target_file),
    }
    atomic_write_json(entry / f"revert-{transaction.transaction_id}.json", receipt)
    return receipt
