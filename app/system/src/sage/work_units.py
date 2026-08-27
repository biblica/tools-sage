"""Section-preferred bounded work-unit planning with labeled context overlap."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .errors import EvidenceLimitError, ValidationError
from .evidence import (
    EvidenceMeasurement,
    EvidencePolicy,
    evidence_within_limits,
    measure_evidence,
)
from .references import BOOK_ORDER, ScriptureScope
from .vrs import VerseRef


_WORD_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class _SerializedStats:
    """Additive statistics for already serialized JSON text."""

    serialized_bytes: int = 0
    unicode_characters: int = 0
    ascii_characters: int = 0
    non_ascii_characters: int = 0
    words: int = 0

    def __add__(self, other: "_SerializedStats") -> "_SerializedStats":
        """Combine two measurements without losing any component totals."""
        return _SerializedStats(
            serialized_bytes=self.serialized_bytes + other.serialized_bytes,
            unicode_characters=self.unicode_characters + other.unicode_characters,
            ascii_characters=self.ascii_characters + other.ascii_characters,
            non_ascii_characters=self.non_ascii_characters + other.non_ascii_characters,
            words=self.words + other.words,
        )

    def __sub__(self, other: "_SerializedStats") -> "_SerializedStats":
        """Subtract one measurement while preserving component alignment."""
        return _SerializedStats(
            serialized_bytes=self.serialized_bytes - other.serialized_bytes,
            unicode_characters=self.unicode_characters - other.unicode_characters,
            ascii_characters=self.ascii_characters - other.ascii_characters,
            non_ascii_characters=self.non_ascii_characters - other.non_ascii_characters,
            words=self.words - other.words,
        )

    def measurement(self) -> EvidenceMeasurement:
        """Return the aggregate size measurement for this work-unit record."""
        character_estimate = (
            self.ascii_characters / 4.0 + self.non_ascii_characters / 2.0
        )
        word_estimate = self.words * 1.35
        return EvidenceMeasurement(
            serialized_bytes=self.serialized_bytes,
            unicode_characters=self.unicode_characters,
            words=self.words,
            estimated_tokens=max(1, math.ceil(max(character_estimate, word_estimate))),
        )


def _serialized_stats_text(text: str) -> _SerializedStats:
    """Measure a text payload using the same UTF-8 and token estimator as ACT generation."""
    ascii_count = sum(1 for char in text if ord(char) < 128)
    return _SerializedStats(
        serialized_bytes=len(text.encode("utf-8")),
        unicode_characters=len(text),
        ascii_characters=ascii_count,
        non_ascii_characters=len(text) - ascii_count,
        words=len(_WORD_RE.findall(text)),
    )


def _serialized_stats_json(value: Any) -> _SerializedStats:
    """Serialize JSON deterministically before measuring its context cost."""
    return _serialized_stats_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _sum_stats(values: Iterable[_SerializedStats]) -> _SerializedStats:
    """Add byte, character, line, and token measurements component by component."""
    total = _SerializedStats()
    for value in values:
        total = total + value
    return total


class _PacketSizer:
    """Measure candidate packets in O(1) after one serialization pass.

    Candidate selection previously serialized every growing verse span. That was
    quadratic in payload size for large books. This sizer pre-serializes each
    evidence item once, keeps additive prefix statistics, and still verifies each
    final packet through the normal exact serializer before it can be emitted.
    """

    _PREFIX = _serialized_stats_text('{"context_after":[')
    _BETWEEN_AFTER_BEFORE = _serialized_stats_text('],"context_before":[')
    _BETWEEN_BEFORE_PRIMARY = _serialized_stats_text('],"primary":[')
    _BETWEEN_PRIMARY_SHARED = _serialized_stats_text('],"shared":')
    _BETWEEN_SHARED_UNIT = _serialized_stats_text(',"unit_id":')
    _SUFFIX = _serialized_stats_text('}')
    _COMMA = _serialized_stats_text(',')

    def __init__(
        self,
        primary_records: tuple["EvidenceRecord", ...],
        context_pool: tuple["EvidenceRecord", ...],
        shared: dict[str, Any] | None,
    ) -> None:
        """Initialize the instance with the supplied governed state."""
        self._shared = _serialized_stats_json(shared or {})
        self._primary_by_key: dict[tuple[str, int, int, int], _SerializedStats] = {}
        self._context_by_key: dict[tuple[str, int, int, int], _SerializedStats] = {}
        for record in context_pool:
            key = _record_key(record)
            self._context_by_key[key] = _serialized_stats_json(
                {
                    "reference": record.reference,
                    "context_only": True,
                    "evidence": record.payload,
                }
            )
        prefix = [_SerializedStats()]
        atomic_prefix = [0]
        for record in primary_records:
            key = _record_key(record)
            stats = _serialized_stats_json(
                {
                    "reference": record.reference,
                    "context_only": False,
                    "evidence": record.payload,
                }
            )
            self._primary_by_key[key] = stats
            prefix.append(prefix[-1] + stats)
            atomic_prefix.append(atomic_prefix[-1] + record.atomic_count)
        self._primary_prefix = tuple(prefix)
        self._atomic_prefix = tuple(atomic_prefix)

    @staticmethod
    def _list_stats(values: Iterable[_SerializedStats], count: int) -> _SerializedStats:
        """Measure and sum a sequence of serialized evidence items."""
        stats = _sum_stats(values)
        if count > 1:
            stats = stats + _SerializedStats(
                serialized_bytes=count - 1,
                unicode_characters=count - 1,
                ascii_characters=count - 1,
            )
        return stats

    def measure(
        self,
        start: int,
        end: int,
        before: tuple["EvidenceRecord", ...],
        after: tuple["EvidenceRecord", ...],
        *,
        unit_id: str = "PLANNING",
    ) -> tuple[EvidenceMeasurement, int]:
        """Measure serialized packet content against configured context limits."""
        primary_count = end - start + 1
        primary_stats = self._primary_prefix[end + 1] - self._primary_prefix[start]
        if primary_count > 1:
            primary_stats = primary_stats + _SerializedStats(
                serialized_bytes=primary_count - 1,
                unicode_characters=primary_count - 1,
                ascii_characters=primary_count - 1,
            )
        before_values = [self._context_by_key[_record_key(item)] for item in before]
        after_values = [self._context_by_key[_record_key(item)] for item in after]
        before_stats = self._list_stats(before_values, len(before_values))
        after_stats = self._list_stats(after_values, len(after_values))
        total = (
            self._PREFIX
            + after_stats
            + self._BETWEEN_AFTER_BEFORE
            + before_stats
            + self._BETWEEN_BEFORE_PRIMARY
            + primary_stats
            + self._BETWEEN_PRIMARY_SHARED
            + self._shared
            + self._BETWEEN_SHARED_UNIT
            + _serialized_stats_json(unit_id)
            + self._SUFFIX
        )
        atomic_count = self._atomic_prefix[end + 1] - self._atomic_prefix[start]
        return total.measurement(), atomic_count


@dataclass(frozen=True)
class EvidenceRecord:
    """One indivisible local verse record and its serialized evidence payload."""

    book: str
    chapter: int
    verse_start: int
    verse_end: int
    payload: dict[str, Any]
    boundaries_before: tuple[dict[str, Any], ...] = ()
    section_id: str = ""
    poetry_block_id: str = ""
    paragraph_id: str = ""
    discourse_unit_id: str = ""
    discourse_unit_kind: str = ""
    discourse_unit_marker: str = ""

    @property
    def reference(self) -> str:
        """Return the canonical reference represented by this record."""
        suffix = f"-{self.verse_end}" if self.verse_end != self.verse_start else ""
        return f"{self.book} {self.chapter}:{self.verse_start}{suffix}"

    @property
    def atomic_count(self) -> int:
        """Return the number of atomic Scripture coordinates in this record."""
        return self.verse_end - self.verse_start + 1

    @property
    def refs(self) -> tuple[VerseRef, ...]:
        """Return ordered canonical references represented by this record."""
        return tuple(
            VerseRef(self.book, self.chapter, verse)
            for verse in range(self.verse_start, self.verse_end + 1)
        )

    @property
    def boundary_score(self) -> int:
        """Return the configured split score for this record boundary."""
        if not self.boundaries_before:
            return 0
        return max(int(item.get("score", 0)) for item in self.boundaries_before)

    @property
    def boundary_kind(self) -> str:
        """Return the strongest governed boundary type at this record."""
        if not self.boundaries_before:
            return "VERSE"
        item = max(
            self.boundaries_before,
            key=lambda value: (int(value.get("score", 0)), str(value.get("kind", ""))),
        )
        return str(item.get("kind", "VERSE"))

    @property
    def boundary_marker(self) -> str:
        """Return the strongest marker associated with this record boundary."""
        if not self.boundaries_before:
            return "v"
        item = max(
            self.boundaries_before,
            key=lambda value: (int(value.get("score", 0)), str(value.get("kind", ""))),
        )
        return str(item.get("marker", "v"))


@dataclass(frozen=True)
class WorkUnit:
    """One primary evidence unit with optional labeled context-only records."""

    unit_id: str
    primary: tuple[EvidenceRecord, ...]
    context_before: tuple[EvidenceRecord, ...]
    context_after: tuple[EvidenceRecord, ...]
    measurement: EvidenceMeasurement
    split_boundary: str
    split_boundary_marker: str

    @property
    def primary_refs(self) -> frozenset[VerseRef]:
        """Return references inside the requested primary task scope."""
        return frozenset(ref for record in self.primary for ref in record.refs)

    @property
    def context_refs(self) -> frozenset[VerseRef]:
        """Return routed context references outside the primary task scope."""
        return frozenset(
            ref
            for record in self.context_before + self.context_after
            for ref in record.refs
        )

    @property
    def primary_atomic_count(self) -> int:
        """Return the atomic-coordinate count for primary task evidence."""
        return sum(record.atomic_count for record in self.primary)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for reports and state files."""
        return {
            "unit_id": self.unit_id,
            "primary_scope": _range_label(self.primary),
            "primary_references": [record.reference for record in self.primary],
            "context_before": [record.reference for record in self.context_before],
            "context_after": [record.reference for record in self.context_after],
            "context_mode": "CONTEXT_ONLY",
            "primary_atomic_coordinates": self.primary_atomic_count,
            "measurement": self.measurement.to_dict(),
            "split_boundary": self.split_boundary,
            "split_boundary_marker": self.split_boundary_marker,
            "primary_discourse_units": sorted({
                item.discourse_unit_id or item.reference for item in self.primary
            }),
            "primary_discourse_kinds": sorted({
                item.discourse_unit_kind or "UNCLASSIFIED" for item in self.primary
            }),
        }


def _record_key(record: EvidenceRecord) -> tuple[str, int, int, int]:
    """Return the stable ordering key for one Scripture work-unit record."""
    return (record.book, record.chapter, record.verse_start, record.verse_end)


def _range_label(records: tuple[EvidenceRecord, ...]) -> str:
    """Render the smallest canonical range label covering selected records."""
    if not records:
        return ""
    first = records[0]
    last = records[-1]
    if first.book != last.book:
        return f"{first.reference}-{last.reference}"
    if first.chapter == last.chapter:
        if first.verse_start == last.verse_end:
            return f"{first.book} {first.chapter}:{first.verse_start}"
        return f"{first.book} {first.chapter}:{first.verse_start}-{last.verse_end}"
    return (
        f"{first.book} {first.chapter}:{first.verse_start}-"
        f"{last.chapter}:{last.verse_end}"
    )


def _packet(
    unit_id: str,
    primary: tuple[EvidenceRecord, ...],
    before: tuple[EvidenceRecord, ...],
    after: tuple[EvidenceRecord, ...],
    shared: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the exact evidence packet used for candidate measurement and final writing."""
    return {
        "unit_id": unit_id,
        "shared": shared or {},
        "primary": [
            {"reference": item.reference, "context_only": False, "evidence": item.payload}
            for item in primary
        ],
        "context_before": [
            {"reference": item.reference, "context_only": True, "evidence": item.payload}
            for item in before
        ],
        "context_after": [
            {"reference": item.reference, "context_only": True, "evidence": item.payload}
            for item in after
        ],
    }


def build_evidence_packet(unit: WorkUnit, shared: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the exact labeled packet represented by a planned work unit."""
    return _packet(
        unit.unit_id,
        unit.primary,
        unit.context_before,
        unit.context_after,
        shared,
    )


def _context_records(
    records: tuple[EvidenceRecord, ...],
    start: int,
    end: int,
    policy: EvidencePolicy,
    context_pool: tuple[EvidenceRecord, ...],
    context_positions: dict[tuple[str, int, int, int], int],
) -> tuple[tuple[EvidenceRecord, ...], tuple[EvidenceRecord, ...]]:
    """Select actual adjacent resource records, including operator-scope edges."""
    first = records[start]
    last = records[end]
    try:
        pool_start = context_positions[_record_key(first)]
        pool_end = context_positions[_record_key(last)]
    except KeyError as exc:
        raise ValidationError("Primary evidence record is absent from the context pool") from exc
    before_start = max(0, pool_start - policy.context_before_verses)
    after_end = min(len(context_pool), pool_end + 1 + policy.context_after_verses)
    before = tuple(
        item
        for item in context_pool[before_start:pool_start]
        if item.book == first.book
    )
    after = tuple(
        item
        for item in context_pool[pool_end + 1 : after_end]
        if item.book == last.book
    )
    return before, after


def _measure_candidate(
    records: tuple[EvidenceRecord, ...],
    start: int,
    end: int,
    policy: EvidencePolicy,
    context_pool: tuple[EvidenceRecord, ...],
    context_positions: dict[tuple[str, int, int, int], int],
    packet_sizer: _PacketSizer,
) -> tuple[EvidenceMeasurement, int, tuple[EvidenceRecord, ...], tuple[EvidenceRecord, ...]]:
    """Measure one proposed work unit, including manifest and routed context overhead."""
    primary = records[start : end + 1]
    before, after = _context_records(
        records,
        start,
        end,
        policy,
        context_pool,
        context_positions,
    )
    measurement, atomic_count = packet_sizer.measure(start, end, before, after)
    return measurement, atomic_count, before, after


def _fits(
    records: tuple[EvidenceRecord, ...],
    start: int,
    end: int,
    policy: EvidencePolicy,
    context_pool: tuple[EvidenceRecord, ...],
    context_positions: dict[tuple[str, int, int, int], int],
    packet_sizer: _PacketSizer,
) -> bool:
    """Return whether a measured candidate satisfies every configured hard limit."""
    measurement, atomic_count, _, _ = _measure_candidate(
        records,
        start,
        end,
        policy,
        context_pool,
        context_positions,
        packet_sizer,
    )
    if not evidence_within_limits(measurement, policy, primary_verse_units=atomic_count):
        return False
    if not policy.allow_cross_chapter_units:
        chapters = {(item.book, item.chapter) for item in records[start : end + 1]}
        if len(chapters) > 1:
            return False
    if policy.maximum_primary_discourse_units:
        discourse_units = {
            item.discourse_unit_id or item.reference
            for item in records[start : end + 1]
        }
        if len(discourse_units) > policy.maximum_primary_discourse_units:
            return False
    return True


def _section_ranges(records: tuple[EvidenceRecord, ...]) -> tuple[tuple[int, int], ...]:
    """Return contiguous semantic section spans for preferred split selection.

    Real project records carry stable ``section_id`` values. Synthetic/legacy records
    may not, so a governed SECTION boundary still starts a new span. Each span remains
    intact unless it cannot satisfy a hard limit. Adjacent complete spans may later be
    coalesced when their combined evidence packet still satisfies every hard limit.
    """
    if not records:
        return ()
    ranges: list[tuple[int, int]] = []
    start = 0
    active_id = records[0].section_id
    for index in range(1, len(records)):
        record = records[index]
        explicit_section = any(
            str(item.get("kind") or "").upper() == "SECTION"
            for item in record.boundaries_before
        )
        id_changed = bool(record.section_id) and bool(active_id) and record.section_id != active_id
        id_started = bool(record.section_id) and not active_id
        if explicit_section or id_changed or id_started:
            ranges.append((start, index - 1))
            start = index
        if record.section_id:
            active_id = record.section_id
    ranges.append((start, len(records) - 1))
    return tuple(ranges)


def _primary_discourse_count(
    records: tuple[EvidenceRecord, ...],
    start: int,
    end: int,
) -> int:
    """Return the number of natural discourse units in one primary range."""
    return len({
        item.discourse_unit_id or item.reference
        for item in records[start : end + 1]
    })


def _furthest_fitting_end(
    records: tuple[EvidenceRecord, ...],
    start: int,
    limit: int,
    policy: EvidencePolicy,
    context_pool: tuple[EvidenceRecord, ...],
    context_positions: dict[tuple[str, int, int, int], int],
    packet_sizer: _PacketSizer,
) -> int:
    """Return the last monotonically growing candidate that still fits hard limits."""
    furthest = start - 1
    for end in range(start, limit + 1):
        if _fits(
            records,
            start,
            end,
            policy,
            context_pool,
            context_positions,
            packet_sizer,
        ):
            furthest = end
        else:
            break
    return furthest


def _balanced_section_end(
    records: tuple[EvidenceRecord, ...],
    start: int,
    section_end: int,
    furthest: int,
    policy: EvidencePolicy,
    context_pool: tuple[EvidenceRecord, ...],
    context_positions: dict[tuple[str, int, int, int], int],
    packet_sizer: _PacketSizer,
) -> int:
    """Choose a balanced structural split after looking through the remaining section.

    The old greedy selector optimized the current packet in isolation. That could
    create a near-target first packet followed by a tiny story tail. Here SAGE first
    measures the complete remaining section, estimates how many balanced pieces it
    needs, then selects a natural boundary near that balanced target. Structural
    boundaries break ties; they do not justify a severely unbalanced orphan tail.
    """
    remaining_measurement, remaining_atomic, _, _ = _measure_candidate(
        records,
        start,
        section_end,
        policy,
        context_pool,
        context_positions,
        packet_sizer,
    )
    total_tokens = remaining_measurement.estimated_tokens
    target = max(1, policy.target_estimated_tokens)
    hard = max(target, policy.hard_estimated_tokens)
    pieces_by_target = max(2, int(math.floor((total_tokens / target) + 0.5)))
    pieces_by_hard = max(2, math.ceil(total_tokens / hard))
    pieces_by_verse = max(1, math.ceil(remaining_atomic / policy.maximum_primary_verse_units))
    pieces_by_discourse = 1
    if policy.maximum_primary_discourse_units:
        pieces_by_discourse = max(
            1,
            math.ceil(
                _primary_discourse_count(records, start, section_end)
                / policy.maximum_primary_discourse_units
            ),
        )
    pieces = max(pieces_by_target, pieces_by_hard, pieces_by_verse, pieces_by_discourse)
    ideal_tokens = max(1.0, total_tokens / pieces)
    balance_window = max(750.0, ideal_tokens * 0.20)

    candidates: list[tuple[tuple[Any, ...], int]] = []
    natural_candidates = False
    for end in range(start, furthest + 1):
        if end >= section_end:
            break
        measurement, _, _, _ = _measure_candidate(
            records,
            start,
            end,
            policy,
            context_pool,
            context_positions,
            packet_sizer,
        )
        next_record = records[end + 1]
        current_discourse = records[end].discourse_unit_id or records[end].reference
        next_discourse = next_record.discourse_unit_id or next_record.reference
        natural = current_discourse != next_discourse
        natural_candidates = natural_candidates or natural
        distance = abs(measurement.estimated_tokens - ideal_tokens)
        preferred_delta = 0
        if policy.preferred_primary_discourse_units:
            preferred_delta = abs(
                _primary_discourse_count(records, start, end)
                - policy.preferred_primary_discourse_units
            )
        # Natural discourse boundaries are strongly preferred. Within the balanced
        # window, stronger USFM structure wins; outside it, balance wins first.
        score = (
            0 if natural else 1,
            0 if distance <= balance_window else 1,
            -next_record.boundary_score if distance <= balance_window else 0,
            distance,
            preferred_delta,
            -next_record.boundary_score,
            -end,
        )
        candidates.append((score, end))

    if not candidates:
        return furthest
    pool = [item for item in candidates if item[0][0] == 0] if natural_candidates else candidates
    return min(pool, key=lambda item: item[0])[1]


def _plan_section_ranges(
    records: tuple[EvidenceRecord, ...],
    section_start: int,
    section_end: int,
    policy: EvidencePolicy,
    context_pool: tuple[EvidenceRecord, ...],
    context_positions: dict[tuple[str, int, int, int], int],
    packet_sizer: _PacketSizer,
) -> list[tuple[int, int]]:
    """Plan one semantic section intact or as balanced bounded subdivisions."""
    ranges: list[tuple[int, int]] = []
    start = section_start
    while start <= section_end:
        # Bounded lookahead: if everything left before the next section marker fits,
        # absorb it now so an intact section is never subdivided unnecessarily.
        if _fits(
            records,
            start,
            section_end,
            policy,
            context_pool,
            context_positions,
            packet_sizer,
        ):
            ranges.append((start, section_end))
            break

        furthest = _furthest_fitting_end(
            records,
            start,
            section_end,
            policy,
            context_pool,
            context_positions,
            packet_sizer,
        )
        if furthest < start:
            measurement, count, _, _ = _measure_candidate(
                records,
                start,
                start,
                policy,
                context_pool,
                context_positions,
                packet_sizer,
            )
            raise EvidenceLimitError(
                f"Single verse record {records[start].reference} exceeds hard limits: "
                f"bytes={measurement.serialized_bytes}, tokens={measurement.estimated_tokens}, "
                f"atomic_coordinates={count}"
            )
        end = _balanced_section_end(
            records,
            start,
            section_end,
            furthest,
            policy,
            context_pool,
            context_positions,
            packet_sizer,
        )
        ranges.append((start, end))
        start = end + 1

    # First rebalance inside this semantic section. A later packing pass may combine
    # this intact span with adjacent intact sections when the combined packet fits.
    _rebalance_short_tail(
        ranges,
        records,
        policy,
        context_pool,
        context_positions,
        packet_sizer,
    )
    return ranges


def _coalesce_adjacent_ranges(
    ranges: list[tuple[int, int]],
    records: tuple[EvidenceRecord, ...],
    policy: EvidencePolicy,
    context_pool: tuple[EvidenceRecord, ...],
    context_positions: dict[tuple[str, int, int, int], int],
    packet_sizer: _PacketSizer,
) -> list[tuple[int, int]]:
    """Pack adjacent section-derived ranges without crossing a configured hard limit."""
    if len(ranges) < 2:
        return ranges
    packed: list[tuple[int, int]] = []
    for start, end in ranges:
        merge = False
        if packed and _fits(
            records,
            packed[-1][0],
            end,
            policy,
            context_pool,
            context_positions,
            packet_sizer,
        ):
            merge = True
            if policy.preferred_max_estimated_tokens:
                combined, _, _, _ = _measure_candidate(
                    records,
                    packed[-1][0],
                    end,
                    policy,
                    context_pool,
                    context_positions,
                    packet_sizer,
                )
                merge = combined.estimated_tokens <= policy.preferred_max_estimated_tokens
        if merge:
            packed[-1] = (packed[-1][0], end)
        else:
            packed.append((start, end))
    _rebalance_short_tail(
        packed,
        records,
        policy,
        context_pool,
        context_positions,
        packet_sizer,
    )
    return packed

def _validate_records(records: tuple[EvidenceRecord, ...]) -> None:
    """Require ordered, unique, non-empty records before work-unit planning begins."""
    if not records:
        raise ValidationError("No evidence records are available for work-unit planning")
    previous: tuple[int, int, int, int] | None = None
    seen: set[VerseRef] = set()
    for record in records:
        key = (
            BOOK_ORDER.get(record.book, 999),
            record.chapter,
            record.verse_start,
            record.verse_end,
        )
        if previous and key < previous:
            raise ValidationError("Evidence records are not in Scripture order")
        previous = key
        overlap = seen.intersection(record.refs)
        if overlap:
            labels = ", ".join(sorted(ref.label() for ref in overlap))
            raise ValidationError(f"Evidence records overlap: {labels}")
        seen.update(record.refs)


def _rebalance_short_tail(
    ranges: list[tuple[int, int]],
    records: tuple[EvidenceRecord, ...],
    policy: EvidencePolicy,
    context_pool: tuple[EvidenceRecord, ...],
    context_positions: dict[tuple[str, int, int, int], int],
    packet_sizer: _PacketSizer,
) -> None:
    """Merge or rebalance the final pair so a tiny avoidable tail is not emitted."""
    if len(ranges) < 2:
        return
    last_start, last_end = ranges[-1]
    last_measurement, _, _, _ = _measure_candidate(
        records,
        last_start,
        last_end,
        policy,
        context_pool,
        context_positions,
        packet_sizer,
    )
    if last_measurement.estimated_tokens >= policy.minimum_target_tokens:
        return
    prior_start, _ = ranges[-2]
    # RTC-style soft packing must not erase a clean tail boundary merely because
    # the combined packet remains below the absolute hard ceiling.
    if _fits(
        records,
        prior_start,
        last_end,
        policy,
        context_pool,
        context_positions,
        packet_sizer,
    ):
        combined, _, _, _ = _measure_candidate(
            records,
            prior_start,
            last_end,
            policy,
            context_pool,
            context_positions,
            packet_sizer,
        )
        if not policy.preferred_max_estimated_tokens or combined.estimated_tokens <= policy.preferred_max_estimated_tokens:
            ranges[-2] = (prior_start, last_end)
            ranges.pop()
            return

    candidates: list[tuple[int, int, int, int, int]] = []
    for split_end in range(prior_start, last_end):
        left_unit = records[split_end].discourse_unit_id or records[split_end].reference
        right_unit = records[split_end + 1].discourse_unit_id or records[split_end + 1].reference
        if left_unit == right_unit:
            continue
        if not _fits(
            records,
            prior_start,
            split_end,
            policy,
            context_pool,
            context_positions,
            packet_sizer,
        ) or not _fits(
            records,
            split_end + 1,
            last_end,
            policy,
            context_pool,
            context_positions,
            packet_sizer,
        ):
            continue
        left_measurement, _, _, _ = _measure_candidate(
            records,
            prior_start,
            split_end,
            policy,
            context_pool,
            context_positions,
            packet_sizer,
        )
        right_measurement, _, _, _ = _measure_candidate(
            records,
            split_end + 1,
            last_end,
            policy,
            context_pool,
            context_positions,
            packet_sizer,
        )
        left_tokens = left_measurement.estimated_tokens
        right_tokens = right_measurement.estimated_tokens
        candidates.append(
            (
                split_end,
                left_tokens,
                right_tokens,
                records[split_end + 1].boundary_score,
                abs(left_tokens - policy.target_estimated_tokens)
                + abs(right_tokens - policy.target_estimated_tokens),
            )
        )
    if not candidates:
        return

    both_above_minimum = [
        item
        for item in candidates
        if min(item[1], item[2]) >= policy.minimum_target_tokens
    ]
    if both_above_minimum:
        selected = max(
            both_above_minimum,
            key=lambda item: (item[3], -item[4], min(item[1], item[2]), item[0]),
        )
    else:
        selected = max(
            candidates,
            key=lambda item: (
                min(item[1], item[2]),
                item[3],
                -abs(item[1] - item[2]),
                item[0],
            ),
        )
    if min(selected[1], selected[2]) <= last_measurement.estimated_tokens:
        return
    ranges[-2] = (prior_start, selected[0])
    ranges[-1] = (selected[0] + 1, last_end)


def plan_work_units(
    records: Iterable[EvidenceRecord],
    policy: EvidencePolicy,
    *,
    unit_prefix: str,
    shared: dict[str, Any] | None = None,
    context_pool: Iterable[EvidenceRecord] | None = None,
) -> tuple[WorkUnit, ...]:
    """Plan stable contiguous units with exact coverage and real context routing."""
    # Partition contiguously and verify exact coverage after budgeting; no coordinate may be lost or duplicated.
    ordered = tuple(records)
    _validate_records(ordered)
    full_context = tuple(context_pool) if context_pool is not None else ordered
    _validate_records(full_context)
    context_positions = {
        _record_key(record): index for index, record in enumerate(full_context)
    }
    if len(context_positions) != len(full_context):
        raise ValidationError("Context pool contains duplicate verse records")
    packet_sizer = _PacketSizer(ordered, full_context, shared)

    ranges: list[tuple[int, int]] = []
    for section_start, section_end in _section_ranges(ordered):
        ranges.extend(
            _plan_section_ranges(
                ordered,
                section_start,
                section_end,
                policy,
                full_context,
                context_positions,
                packet_sizer,
            )
        )
    ranges = _coalesce_adjacent_ranges(
        ranges,
        ordered,
        policy,
        full_context,
        context_positions,
        packet_sizer,
    )

    units: list[WorkUnit] = []
    for index, (unit_start, unit_end) in enumerate(ranges, start=1):
        unit_id = f"{unit_prefix}-U{index:03d}"
        primary = ordered[unit_start : unit_end + 1]
        before, after = _context_records(
            ordered,
            unit_start,
            unit_end,
            policy,
            full_context,
            context_positions,
        )
        measurement = measure_evidence(_packet(unit_id, primary, before, after, shared))
        atomic_count = sum(item.atomic_count for item in primary)
        if not evidence_within_limits(
            measurement,
            policy,
            primary_verse_units=atomic_count,
        ):
            raise EvidenceLimitError(
                f"Final packet {unit_id} exceeds a hard limit after context routing"
            )
        split_boundary = (
            ordered[unit_end + 1].boundary_kind
            if unit_end + 1 < len(ordered)
            else "END_OF_SCOPE"
        )
        split_boundary_marker = (
            ordered[unit_end + 1].boundary_marker
            if unit_end + 1 < len(ordered)
            else ""
        )
        units.append(
            WorkUnit(
                unit_id=unit_id,
                primary=primary,
                context_before=before,
                context_after=after,
                measurement=measurement,
                split_boundary=split_boundary,
                split_boundary_marker=split_boundary_marker,
            )
        )
    validate_exact_primary_coverage(ordered, units)
    return tuple(units)


def validate_exact_primary_coverage(
    records: Iterable[EvidenceRecord],
    units: Iterable[WorkUnit],
) -> None:
    """Require every requested atomic coordinate in exactly one primary unit."""
    expected = [ref for record in records for ref in record.refs]
    observed = [ref for unit in units for record in unit.primary for ref in record.refs]
    if len(observed) != len(set(observed)):
        raise ValidationError("Work-unit plan duplicates a primary coordinate")
    if set(observed) != set(expected):
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        raise ValidationError(
            "Work-unit primary coverage mismatch: "
            f"missing={[ref.label() for ref in missing]}, "
            f"extra={[ref.label() for ref in extra]}"
        )


def select_records_for_scope(
    records: Iterable[EvidenceRecord],
    scope: ScriptureScope,
) -> tuple[EvidenceRecord, ...]:
    """Select indivisible verse records that intersect an operator scope."""
    selected = tuple(
        record
        for record in records
        if any(scope.contains(ref) for ref in record.refs)
    )
    if not selected:
        raise ValidationError(f"Scope has no evidence records: {scope.label()}")
    return selected


def manifest(
    units: Iterable[WorkUnit],
    policy: EvidencePolicy,
    *,
    operator_scope: str,
    project_id: str,
    plan_id: str,
    plan_fingerprint: str,
    workflow_id: str,
    operation: str,
    shared_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Serialize a complete work-unit plan for audit and later task routing."""
    normalized_plan_id = plan_id.strip()
    if not normalized_plan_id:
        raise ValidationError("Work-unit manifest plan_id is required")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]*", normalized_plan_id):
        raise ValidationError("Work-unit manifest plan_id must use uppercase letters, digits, and hyphens")
    normalized_fingerprint = plan_fingerprint.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized_fingerprint):
        raise ValidationError("Work-unit manifest plan_fingerprint must be a SHA-256 digest")
    normalized_workflow = workflow_id.strip().lower()
    normalized_operation = operation.strip().lower()
    if not normalized_workflow or not normalized_operation:
        raise ValidationError("Work-unit manifest workflow_id and operation are required")
    unit_list = tuple(units)
    return {
        "schema_version": "1.2",
        "plan_id": normalized_plan_id,
        "plan_fingerprint": normalized_fingerprint,
        "workflow_id": normalized_workflow,
        "operation": normalized_operation,
        "operator_scope": operator_scope,
        "project_id": project_id,
        "policy": policy.to_dict(),
        "shared_hashes": shared_hashes or {},
        "units": [unit.to_dict() for unit in unit_list],
        "summary": {
            "work_units": len(unit_list),
            "primary_atomic_coordinates": sum(
                unit.primary_atomic_count for unit in unit_list
            ),
            "context_atomic_coordinates": sum(
                len(unit.context_refs) for unit in unit_list
            ),
            "largest_serialized_bytes": max(
                (unit.measurement.serialized_bytes for unit in unit_list),
                default=0,
            ),
            "largest_estimated_tokens": max(
                (unit.measurement.estimated_tokens for unit in unit_list),
                default=0,
            ),
        },
    }


def records_from_project_result(
    project_id: str,
    project_result: dict[str, Any],
    *,
    resource_role: str = "PRIMARY",
) -> tuple[EvidenceRecord, ...]:
    """Load compact planning records from validated content-addressed USJ caches.

    Project identity, resource role, and resource hashes belong in the packet's
    shared provenance block. Keeping those values out of every verse record
    materially reduces evidence size without discarding analytical content.
    """
    records: list[EvidenceRecord] = []
    for file_result in project_result.get("files", []):
        cache_path = Path(str(file_result.get("cache", "")))
        if not cache_path.is_file():
            raise ValidationError(f"USJ cache is missing for planning: {cache_path}")
        try:
            usj = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"Invalid USJ cache for planning {cache_path}: {exc}") from exc
        book = str(usj.get("sage", {}).get("book_code", "UNK"))
        source_name = str(usj.get("sage", {}).get("source_name", cache_path.name))
        for item in usj.get("sage", {}).get("verse_records", []):
            if not isinstance(item, dict):
                continue
            structure: dict[str, list[str]] = {}
            section_id = str(item.get("section_id", ""))
            section_marker = str(item.get("section_marker", ""))
            section_title = str(item.get("section_title", ""))
            if section_id or section_marker or section_title:
                structure["section"] = [section_id, section_marker, section_title]
            poetry_id = str(item.get("poetry_block_id", ""))
            poetry_marker = str(item.get("poetry_block_marker", ""))
            poetry_title = str(item.get("poetry_block_title", ""))
            if poetry_id or poetry_marker or poetry_title:
                structure["poetry"] = [poetry_id, poetry_marker, poetry_title]
            paragraph_id = str(item.get("paragraph_id", ""))
            paragraph_marker = str(item.get("paragraph_marker", ""))
            if paragraph_id or paragraph_marker:
                structure["paragraph"] = [paragraph_id, paragraph_marker]
            discourse_id = str(item.get("discourse_unit_id", ""))
            discourse_kind = str(item.get("discourse_unit_kind", ""))
            discourse_marker = str(item.get("discourse_unit_marker", ""))
            if discourse_id or discourse_kind or discourse_marker:
                structure["discourse_unit"] = [discourse_id, discourse_kind, discourse_marker]
            payload = {
                "body_text": str(
                    item.get("body_text_exact", item.get("body_text", ""))
                ),
                "source": source_name,
                "source_lines": [
                    int(item.get("line_start", 0) or 0),
                    int(item.get("line_end", item.get("line_start", 0)) or 0),
                ],
            }
            if structure:
                payload["structure"] = structure
            records.append(
                EvidenceRecord(
                    book=book,
                    chapter=int(item["chapter"]),
                    verse_start=int(item["verse_start"]),
                    verse_end=int(item["verse_end"]),
                    payload=payload,
                    boundaries_before=tuple(item.get("boundaries_before", [])),
                    section_id=section_id,
                    poetry_block_id=poetry_id,
                    paragraph_id=paragraph_id,
                    discourse_unit_id=discourse_id,
                    discourse_unit_kind=discourse_kind,
                    discourse_unit_marker=discourse_marker,
                )
            )
    records.sort(
        key=lambda item: (
            BOOK_ORDER.get(item.book, 999),
            item.chapter,
            item.verse_start,
            item.verse_end,
        )
    )
    return tuple(records)
