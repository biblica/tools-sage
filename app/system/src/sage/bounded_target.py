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
    # A book generated one scope at a time legitimately lacks later chapters; the merge creates them.
    missing_chapters = sorted(required_chapters - set(target_chapters))
    source_set = set(source_ranges)
    target_set = set(target_ranges)
    incompatible_existing = sorted(target_set - source_set)
    if incompatible_existing:
        raise ValidationError(
            "Existing TARGET verse/bridge shape differs from the projected BIC output inside the bounded scope",
            code="TARGET_SCOPE_VERSE_SHAPE_MISMATCH",
            details={"scope": scope.label(), "target_only_shapes": incompatible_existing, "source_shapes": list(source_ranges)},
        )
    return {
        "status": "READY",
        "scope": scope.label(),
        "source_shapes": list(source_ranges),
        "target_shapes": list(target_ranges),
        "ordinary_insertions_allowed": [list(shape) for shape in sorted(source_set - target_set)],
        "chapters_to_create": missing_chapters,
    }


_TAIL_LINE_RE = re.compile(
    r"^\\(?:p|m|mi|nb|pc|pm|pmo|pmc|pmr|pr|pi\d*|ph\d*|q\d*|qm\d*|qr|qc|qa|li\d*|lim\d*)\s+\S"
)


def expand_unsafe_drops(
    candidate_text: str,
    scope_value: str,
    drop: Iterable[tuple[int, int, int]],
) -> set[tuple[int, int, int]]:
    """Widen a set of failing verses so no kept verse is joined to the wrong half of a neighbour.

    A verse block owns the lines before its ``\\v`` marker, and those lines can be the text-bearing tail
    (poetry or continuation paragraph) of the previous verse. Mixing a kept verse with its dropped
    neighbour's tail would splice two versions of one verse, so such neighbours are dropped as well.
    """
    scope = parse_scope(scope_value)
    blocks = _scope_blocks(candidate_text, scope)
    keys = [(block.chapter, block.start_verse, block.end_verse) for block in blocks]
    has_tail = [any(_TAIL_LINE_RE.match(line.strip()) for line in block.lines[:-1]) for block in blocks]
    dropped = set(drop)
    changed = True
    while changed:
        changed = False
        for index, key in enumerate(keys):
            if key in dropped:
                if has_tail[index] and index > 0 and keys[index - 1] not in dropped:
                    dropped.add(keys[index - 1])
                    changed = True
                if index + 1 < len(keys) and has_tail[index + 1] and keys[index + 1] not in dropped:
                    dropped.add(keys[index + 1])
                    changed = True
    return dropped


def drop_verse_blocks(candidate_text: str, drop: Iterable[tuple[int, int, int]]) -> str:
    """Return the candidate without the verse blocks keyed ``(chapter, start_verse, end_verse)`` in ``drop``."""
    dropped = set(drop)
    kept: list[RawBlock | VerseBlock] = []
    previous_dropped = False
    for block in _parse_blocks(candidate_text):
        if isinstance(block, VerseBlock):
            previous_dropped = (block.chapter, block.start_verse, block.end_verse) in dropped
            if not previous_dropped:
                kept.append(block)
            continue
        # Lines trailing a dropped verse (before the next chapter marker or the end) are that verse's tail.
        is_chapter_marker = any(_CHAPTER_RE.match(line) for line in block.lines)
        if previous_dropped and not is_chapter_marker:
            previous_dropped = False
            continue
        previous_dropped = False
        kept.append(block)
    return _render_blocks(kept)


def _is_chapter_marker(block: RawBlock | VerseBlock, chapter: int | None = None) -> bool:
    """Return whether a block carries a ``\\c`` marker, optionally for one chapter number."""
    if not isinstance(block, RawBlock):
        return False
    for line in block.lines:
        match = _CHAPTER_RE.match(line)
        if match and (chapter is None or int(match.group(1)) == chapter):
            return True
    return False


def _chapter_marker_index(blocks: list[RawBlock | VerseBlock], chapter: int) -> int | None:
    """Return the index of the block carrying one chapter marker, if the book has it."""
    for idx, block in enumerate(blocks):
        if _is_chapter_marker(block, chapter):
            return idx
    return None


def _insert_chapter_marker(blocks: list[RawBlock | VerseBlock], chapter: int) -> int:
    """Insert a bare chapter marker before the next higher chapter, or at the end of the book."""
    insert_at = len(blocks)
    for idx, block in enumerate(blocks):
        if not isinstance(block, RawBlock):
            continue
        numbers = [int(match.group(1)) for line in block.lines if (match := _CHAPTER_RE.match(line))]
        if numbers and numbers[0] > chapter:
            insert_at = idx
            break
    blocks.insert(insert_at, RawBlock((f"\\c {chapter}",)))
    return insert_at


def chapter_numbers(text: str) -> set[int]:
    """Return every chapter number declared by ``\\c`` markers in one book."""
    numbers: set[int] = set()
    for _, fragment in iter_logical_usfm_lines(text):
        match = _CHAPTER_RE.match(fragment.strip())
        if match:
            numbers.add(int(match.group(1)))
    return numbers


def _remove_empty_chapters(text: str, chapters: Iterable[int]) -> str:
    """Drop bare chapter markers for the given chapters when no verse remains in them."""
    wanted = set(chapters)
    if not wanted:
        return text
    blocks = _parse_blocks(text)
    occupied = {block.chapter for block in blocks if isinstance(block, VerseBlock)}
    kept = [
        block
        for block in blocks
        if not (
            isinstance(block, RawBlock)
            and len(block.lines) == 1
            and (match := _CHAPTER_RE.fullmatch(block.lines[0].strip()))
            and int(match.group(1)) in wanted - occupied
        )
    ]
    return _render_blocks(kept)


def merge_bounded_usfm(
    target_text: str,
    candidate_text: str,
    scope_value: str,
    *,
    keep_existing: Iterable[tuple[int, int, int]] = (),
) -> str:
    """Replace only bounded verse blocks in one TARGET book and preserve all other book content.

    A verse keyed ``(chapter, start_verse, end_verse)`` in ``keep_existing`` is deliberately absent from the
    candidate: its existing TARGET block is kept unchanged instead of being treated as a shape mismatch.
    """
    scope = parse_scope(scope_value)
    keep = set(keep_existing)
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
        if replacement is None and key in keep:
            output.append(block)
            continue
        if replacement is None:
            raise ValidationError(
                "Existing TARGET verse/bridge shape differs from the bounded candidate; SAGE will not guess a bridge split/merge",
                code="TARGET_SCOPE_VERSE_SHAPE_MISMATCH",
                details={"target": key, "scope": scope.label()},
            )
        output.append(replacement)
        used.add(key)

    missing = sorted(
        (block for key, block in candidate_by_range.items() if key not in used),
        key=lambda block: (block.chapter, block.start_verse),
    )
    if missing:
        # Insert missing verse blocks inside their chapter, creating the chapter in book
        # order when the TARGET does not have it yet. Never search globally by verse
        # coordinate: doing so can place a verse after the next ``\c`` marker when the
        # insertion belongs at the end of a chapter.
        for new_block in missing:
            chapter_marker_index = _chapter_marker_index(output, new_block.chapter)
            if chapter_marker_index is None:
                chapter_marker_index = _insert_chapter_marker(output, new_block.chapter)

            insert_at: int | None = None
            last_same_chapter_verse: int | None = None
            for idx in range(chapter_marker_index + 1, len(output)):
                item = output[idx]
                if isinstance(item, RawBlock) and any(_CHAPTER_RE.match(line) for line in item.lines):
                    break
                if not isinstance(item, VerseBlock) or item.chapter != new_block.chapter:
                    continue
                if item.start_verse <= new_block.end_verse and new_block.start_verse <= item.end_verse:
                    # Only reachable for verses outside the scope; SAGE will not guess a bridge split/merge.
                    raise ValidationError(
                        "Cannot insert a verse/bridge that overlaps an existing TARGET verse",
                        code="TARGET_SCOPE_INSERT_BRIDGE_UNSUPPORTED",
                        details={
                            "scope": scope.label(),
                            "candidate": (new_block.chapter, new_block.start_verse, new_block.end_verse),
                            "target": (item.chapter, item.start_verse, item.end_verse),
                        },
                    )
                if item.start_verse > new_block.start_verse:
                    insert_at = idx
                    break
                last_same_chapter_verse = idx
            if insert_at is None:
                insert_at = (last_same_chapter_verse + 1) if last_same_chapter_verse is not None else (chapter_marker_index + 1)
            output.insert(insert_at, new_block)

    merged = _render_blocks(output)
    _validate_bounded_merge(target_text, candidate_text, merged, scope_value, keep_existing=keep)
    return merged


def _validate_bounded_merge(
    before_text: str,
    candidate_text: str,
    merged_text: str,
    scope_value: str,
    *,
    keep_existing: Iterable[tuple[int, int, int]] = (),
) -> None:
    """Fail closed unless a merge reproduces the candidate and preserves out-of-scope content.

    Verses in ``keep_existing`` are checked separately: they must remain exactly as they were in the TARGET.
    """
    keep = set(keep_existing)
    scope = parse_scope(scope_value)
    if keep:
        def keyed(text: str) -> dict[tuple[int, int, int], tuple[str, ...]]:
            """Map each in-scope kept verse key to its exact lines."""
            return {
                (block.chapter, block.start_verse, block.end_verse): block.lines
                for block in _scope_blocks(text, scope)
                if (block.chapter, block.start_verse, block.end_verse) in keep
            }

        if keyed(before_text) != keyed(merged_text):
            raise ValidationError(
                "Bounded TARGET merge changed a verse that was meant to stay unchanged",
                code="TARGET_SCOPE_KEPT_VERSE_CHANGED",
                details={"scope": scope.label()},
            )
        merged_scope_text = drop_verse_blocks(merged_text, keep)
    else:
        merged_scope_text = merged_text
    expected_scope = extract_scope_usfm(candidate_text, scope_value)
    actual_scope = extract_scope_usfm(merged_scope_text, scope_value)
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
    # Chapter markers the merge created for new in-scope verses are the only permitted addition.
    created = chapter_numbers(merged_text) - chapter_numbers(before_text)
    after_outside = _remove_empty_chapters(remove_scope_usfm(merged_text, scope_value), created)
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


_NOTE_SPAN_RE = re.compile(r"\\(f|fe|x)\s.*?\\\1\*")
_INLINE_MARKER_RE = re.compile(r"\\\+?[A-Za-z]+\d*\*?")


def _line_has_text(line: str) -> bool:
    """Return whether one logical USFM line carries readable text beyond markers, numbers, and notes."""
    body = re.sub(r"^\\v\s+\S+", "", line.strip())
    body = _INLINE_MARKER_RE.sub(" ", _NOTE_SPAN_RE.sub(" ", body))
    return any(character.isalpha() for character in body)


def _verse_text_map(text: str, scope: ScriptureScope) -> dict[tuple[int, int, int], tuple[str, ...]]:
    """Map each in-scope verse to its text lines: the verse line plus any poetry or paragraph tail."""
    blocks = _parse_blocks(text)
    result: dict[tuple[int, int, int], tuple[str, ...]] = {}
    for index, block in enumerate(blocks):
        if not isinstance(block, VerseBlock) or not _block_inside_scope(block, scope)[1]:
            continue
        lines = [block.lines[-1]]
        following = blocks[index + 1] if index + 1 < len(blocks) else None
        tail = following.lines[:-1] if isinstance(following, VerseBlock) else (
            following.lines if isinstance(following, RawBlock) and not _is_chapter_marker(following) else ()
        )
        lines.extend(line for line in tail if _TAIL_LINE_RE.match(line))
        result[(block.chapter, block.start_verse, block.end_verse)] = tuple(lines)
    return result


def _verse_label(book: str, key: tuple[int, int, int]) -> str:
    """Render one (chapter, start, end) verse key as a reference label."""
    chapter, start, end = key
    return f"{book} {chapter}:{start}" + (f"-{end}" if end != start else "")


def existing_text_references(text: str, scope_value: str) -> list[str]:
    """Return the in-scope TARGET verses that already carry text; a bare verse marker does not count."""
    if not text.strip():
        return []
    scope = parse_scope(scope_value)
    return [
        _verse_label(scope.book, key)
        for key, lines in _verse_text_map(text, scope).items()
        if any(_line_has_text(line) for line in lines)
    ]


def _replaced_existing_text(before_text: str, after_text: str, scope_value: str) -> list[str]:
    """Return the in-scope verses whose existing TARGET text a commit replaced."""
    if not before_text.strip():
        return []
    scope = parse_scope(scope_value)
    before = _verse_text_map(before_text, scope)
    after = _verse_text_map(after_text, scope)
    return [
        _verse_label(scope.book, key)
        for key, lines in before.items()
        if any(_line_has_text(line) for line in lines) and after.get(key) != lines
    ]


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
        "created_chapters": sorted(chapter_numbers(after_text) - chapter_numbers(before_text)) if before_text.strip() else [],
        "replaced_existing_text": _replaced_existing_text(before_text, after_text, scope_value),
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
    # Remove the committed scope first so verses the commit inserted do not read as a shape
    # mismatch, then put the historical verses back and drop chapters the commit created.
    restored = remove_scope_usfm(current_text, scope_value)
    if before_scope.strip():
        restored = merge_bounded_usfm(restored, before_scope, scope_value)
    restored = _remove_empty_chapters(restored, latest.get("created_chapters") or ())
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
