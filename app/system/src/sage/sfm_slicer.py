"""General deterministic Scripture slicer sized only from routed analytical SFM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .errors import ValidationError
from .evidence import EvidenceMeasurement, EvidencePolicy, WORD_RE, estimate_tokens
from .verse_alignment import ProjectVerseIndex
from .vrs import VerseRef
from .work_units import EvidenceRecord, WorkUnit, _plan_work_units_with_sizer


@dataclass(frozen=True)
class SfmStream:
    """One Scripture SFM stream routed to a model review item."""

    stream_id: str
    records: tuple[EvidenceRecord, ...]
    require_primary_coverage: bool = True
    verse_index: ProjectVerseIndex | None = None


@dataclass(frozen=True)
class SfmAnalysisRoute:
    """All Scripture SFM streams physically routed to one analytical review item."""

    route_id: str
    streams: tuple[SfmStream, ...]
    target_stream_ids: tuple[str, ...] = ()
    stream_hard_token_limits: tuple[tuple[str, int], ...] = ()
    primary_stream_id: str | None = None
    primary_index: ProjectVerseIndex | None = None

    def protected_spans(self) -> tuple[tuple[VerseRef, ...], ...]:
        """Return every multi-coordinate source span that a boundary may not bisect."""
        spans: list[tuple[VerseRef, ...]] = []
        for stream in self.streams:
            for record in stream.records:
                if len(record.refs) <= 1:
                    continue
                if self.primary_index is None or stream.verse_index is None:
                    spans.append(record.refs)
                    continue
                canonical_refs = stream.verse_index.canonical_refs_for_records((record,))
                primary_refs = self.primary_index.local_refs_for_canonical(
                    canonical_refs,
                    existing_only=True,
                )
                spans.append(tuple(sorted(primary_refs)))
        return tuple(spans)


def _record_sfm(record: EvidenceRecord) -> str:
    """Return one record's Scripture SFM without incorporating controller metadata."""
    raw = record.sfm.strip("\n")
    if raw:
        return raw
    body = str(record.payload.get("body_text", "")).strip()
    label = str(record.verse_start)
    if record.verse_end != record.verse_start:
        label += f"-{record.verse_end}"
    return f"\\v {label}" + (f" {body}" if body else "")


def render_sfm_slice(records: Iterable[EvidenceRecord]) -> str:
    """Render exact bounded analytical SFM for one routed Scripture stream."""
    ordered = tuple(records)
    if not ordered:
        return ""
    lines: list[str] = [f"\\id {ordered[0].book}"]
    chapter: int | None = None
    for record in ordered:
        if record.chapter != chapter:
            chapter = record.chapter
            lines.append(f"\\c {chapter}")
        lines.extend(_record_sfm(record).splitlines())
    return "\n".join(lines).rstrip() + "\n"


def measure_sfm_text(text: str) -> EvidenceMeasurement:
    """Measure exact routed Scripture SFM text without serializing controller metadata."""
    return EvidenceMeasurement(
        serialized_bytes=len(text.encode("utf-8")),
        unicode_characters=len(text),
        words=len(WORD_RE.findall(text)),
        estimated_tokens=estimate_tokens(text),
    )


def measure_sfm_slice(records: Iterable[EvidenceRecord]) -> EvidenceMeasurement:
    """Measure one exact rendered Scripture SFM slice without serializing metadata."""
    return measure_sfm_text(render_sfm_slice(records))


def _refs(records: Iterable[EvidenceRecord]) -> frozenset[VerseRef]:
    """Return Project-local coordinates covered by the supplied Scripture records."""
    return frozenset(ref for record in records for ref in record.refs)


def _select_for_refs(records: tuple[EvidenceRecord, ...], refs: frozenset[VerseRef]) -> tuple[EvidenceRecord, ...]:
    """Select routed Scripture records intersecting the requested coordinate set."""
    return tuple(record for record in records if refs.intersection(record.refs))


def _select_indexed_stream_records(
    stream: SfmStream,
    refs: frozenset[VerseRef],
) -> tuple[EvidenceRecord, ...]:
    """Select canonically matching records without expanding the declared stream."""
    if stream.verse_index is None:
        return ()
    return tuple(
        record
        for record in stream.verse_index.records_for_canonical(refs)
        if record in stream.records
    )


class _SfmSizer:
    """Measure candidates solely from the SFM streams routed to the review item."""

    def __init__(
        self,
        primary_records: tuple[EvidenceRecord, ...],
        route: SfmAnalysisRoute,
    ) -> None:
        """Bind immutable primary records and the exact model-facing SFM route."""
        self._primary_records = primary_records
        if not route.streams:
            raise ValidationError("An analysis route must contain at least one SFM stream")
        self._route = route

    def measure(
        self,
        start: int,
        end: int,
        before: tuple[EvidenceRecord, ...],
        after: tuple[EvidenceRecord, ...],
        *,
        unit_id: str = "PLANNING",
    ) -> tuple[EvidenceMeasurement, int]:
        """Measure routed SFM; ``unit_id`` is intentionally ignored for sizing."""
        primary = self._primary_records[start : end + 1]
        context = (*before, *after)
        return self._measure_streams(primary, context, stream_ids=None), sum(
            record.atomic_count for record in primary
        )

    def target_tokens(
        self,
        start: int,
        end: int,
        before: tuple[EvidenceRecord, ...],
        after: tuple[EvidenceRecord, ...],
    ) -> int:
        """Return the soft-target token metric declared by the review-item profile."""
        if not self._route.target_stream_ids:
            measurement, _ = self.measure(start, end, before, after)
            return measurement.estimated_tokens
        primary = self._primary_records[start : end + 1]
        context = (*before, *after)
        return self._measure_streams(
            primary,
            context,
            stream_ids=frozenset(value.upper() for value in self._route.target_stream_ids),
        ).estimated_tokens

    def within_hard_limits(
        self,
        start: int,
        end: int,
        before: tuple[EvidenceRecord, ...],
        after: tuple[EvidenceRecord, ...],
    ) -> bool:
        """Enforce profile-specific per-stream hard guards without serializing metadata."""
        if not self._route.stream_hard_token_limits:
            return True
        primary = self._primary_records[start : end + 1]
        context = (*before, *after)
        for stream_id, limit in self._route.stream_hard_token_limits:
            measurement = self._measure_streams(
                primary,
                context,
                stream_ids=frozenset({stream_id.upper()}),
            )
            if measurement.estimated_tokens > int(limit):
                return False
        return True

    def _measure_streams(
        self,
        primary: tuple[EvidenceRecord, ...],
        context: tuple[EvidenceRecord, ...],
        *,
        stream_ids: frozenset[str] | None,
    ) -> EvidenceMeasurement:
        """Measure only selected SFM streams; route/controller labels are never serialized."""
        primary_refs = _refs(primary)
        context_refs = _refs(context)
        primary_canonical: frozenset[VerseRef] | None = None
        context_canonical: frozenset[VerseRef] | None = None
        if self._route.primary_index is not None:
            primary_canonical = self._route.primary_index.canonical_refs_for_records(primary)
            context_canonical = self._route.primary_index.canonical_refs_for_records(context)
        byte_count = 0
        char_count = 0
        word_count = 0
        token_count = 0
        for stream in self._route.streams:
            if stream_ids is not None and stream.stream_id.upper() not in stream_ids:
                continue
            # Authority streams correlate canonically; Primary and legacy streams retain local records.
            indexed = (
                primary_canonical is not None
                and context_canonical is not None
                and stream.verse_index is not None
            )
            is_primary_stream = (
                self._route.primary_stream_id is not None
                and stream.stream_id.upper() == self._route.primary_stream_id.upper()
            )
            if indexed and not is_primary_stream:
                selected_primary = _select_indexed_stream_records(stream, primary_canonical)
                selected = _select_indexed_stream_records(
                    stream,
                    primary_canonical.union(context_canonical)
                )
                covered = stream.verse_index.canonical_refs_for_records(selected_primary)
                required = primary_canonical
            else:
                selected_primary = _select_for_refs(stream.records, primary_refs)
                covered = (
                    stream.verse_index.canonical_refs_for_records(selected_primary)
                    if indexed
                    else _refs(selected_primary)
                )
                required = primary_canonical if indexed else primary_refs
                selected_context = _select_for_refs(stream.records, context_refs)
                selected = tuple(sorted(
                    (*selected_context, *selected_primary),
                    key=lambda record: (record.chapter, record.verse_start, record.verse_end),
                ))
            if stream.require_primary_coverage and not required.issubset(covered):
                missing = sorted(required - covered)
                raise ValidationError(
                    f"SFM stream {stream.stream_id} does not exactly cover the planned primary range: "
                    f"missing={[ref.label() for ref in missing]}",
                    code="SFM_ROUTE_PRIMARY_COVERAGE_MISMATCH",
                )
            text = render_sfm_slice(selected)
            byte_count += len(text.encode("utf-8"))
            char_count += len(text)
            word_count += len(WORD_RE.findall(text))
            token_count += estimate_tokens(text)
        return EvidenceMeasurement(
            serialized_bytes=byte_count,
            unicode_characters=char_count,
            words=word_count,
            estimated_tokens=max(1, token_count),
        )


def plan_sfm_work_units(
    records: Iterable[EvidenceRecord],
    policy: EvidencePolicy,
    *,
    unit_prefix: str,
    route: SfmAnalysisRoute,
    context_pool: Iterable[EvidenceRecord] | None = None,
    required_spans: Iterable[Iterable[VerseRef]] = (),
) -> tuple[WorkUnit, ...]:
    """Plan deterministic work units using only routed analytical SFM as the size basis."""
    ordered = tuple(records)
    full_context = tuple(context_pool) if context_pool is not None else ordered
    protected = tuple(required_spans) + route.protected_spans()
    return _plan_work_units_with_sizer(
        ordered,
        policy,
        unit_prefix=unit_prefix,
        context_pool=full_context,
        required_spans=protected,
        sizer=_SfmSizer(ordered, route),
    )


def route_streams_from_records(**streams: tuple[EvidenceRecord, ...]) -> SfmAnalysisRoute:
    """Convenience constructor for tests and simple single-review workflows."""
    return SfmAnalysisRoute(
        route_id="ANALYSIS",
        streams=tuple(SfmStream(stream_id=name.upper(), records=records) for name, records in streams.items()),
    )
