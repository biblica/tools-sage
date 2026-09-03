"""Immutable evidence indexes for cross-Project canonical verse alignment."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Mapping

from .errors import ValidationError
from .references import BOOK_ORDER
from .vrs import VerseRef, VersificationSchema
from .work_units import EvidenceRecord

RecordKey = tuple[str, int, int, int]


def _record_key(record: EvidenceRecord) -> RecordKey:
    """Return the stable Project-local identity of one evidence record."""
    return (record.book, record.chapter, record.verse_start, record.verse_end)


def _record_order(record: EvidenceRecord) -> tuple[int, str, int, int, int]:
    """Return canonical book order followed by one Project's local coordinates."""
    return (
        BOOK_ORDER.get(record.book, len(BOOK_ORDER)),
        record.book,
        record.chapter,
        record.verse_start,
        record.verse_end,
    )


def _local_ref_is_valid(schema: VersificationSchema, ref: VerseRef) -> bool:
    """Return whether a local coordinate exists in and is not excluded by a schema."""
    maximum = schema.chapter_limit(ref.book, ref.chapter)
    return maximum is not None and 1 <= ref.verse <= maximum and ref not in schema.exclusions


def _local_projection_precision(
    schema: VersificationSchema,
    refs: Iterable[VerseRef],
) -> str:
    """Classify local projection as precise only when every coordinate reverses alone."""
    local_refs = tuple(refs)
    if schema.mapping_precision(local_refs) != "COORDINATE":
        return "EQUIVALENCE_GROUP"
    for local_ref in local_refs:
        canonical_refs = schema.local_to_canonical(local_ref)
        if len(canonical_refs) != 1:
            return "EQUIVALENCE_GROUP"
        canonical_ref = next(iter(canonical_refs))
        if schema.canonical_to_local(canonical_ref) != frozenset({local_ref}):
            return "EQUIVALENCE_GROUP"
    return "COORDINATE"


def _canonical_projection_precision(
    schema: VersificationSchema,
    refs: Iterable[VerseRef],
) -> str:
    """Classify canonical projection as precise only when each target coordinate reverses."""
    for canonical_ref in refs:
        local_refs = frozenset(
            local_ref
            for local_ref in schema.canonical_to_local(canonical_ref)
            if _local_ref_is_valid(schema, local_ref)
        )
        if len(local_refs) != 1:
            return "EQUIVALENCE_GROUP"
        local_ref = next(iter(local_refs))
        if schema.local_to_canonical(local_ref) != frozenset({canonical_ref}):
            return "EQUIVALENCE_GROUP"
    return "COORDINATE"


@dataclass(frozen=True)
class AlignedEvidenceRecord:
    """One exact Project record indexed by local and canonical coordinate sets."""

    record: EvidenceRecord
    local_refs: frozenset[VerseRef]
    canonical_refs: frozenset[VerseRef]
    mapping_precision: str


@dataclass(frozen=True)
class AlignmentSelection:
    """Authority evidence and coverage selected for one Primary record collection."""

    primary_local_refs: frozenset[VerseRef]
    canonical_refs: frozenset[VerseRef]
    authority_records: tuple[EvidenceRecord, ...]
    covered_canonical_refs: frozenset[VerseRef]
    missing_canonical_refs: frozenset[VerseRef]
    mapping_precision: str


@dataclass(frozen=True)
class CoordinateProjection:
    """Primary-local coverage projected into canonical and target-local coordinates."""

    primary_local_refs: frozenset[VerseRef]
    canonical_refs: frozenset[VerseRef]
    target_local_refs: frozenset[VerseRef]
    precision: str
    is_deterministic: bool


@dataclass(frozen=True)
class ProjectVerseIndex:
    """One Project's exact records indexed through its effective VRS schema."""

    project_id: str
    schema_id: str
    aligned_records: tuple[AlignedEvidenceRecord, ...]
    _schema: VersificationSchema = field(repr=False, compare=False)
    _by_record_key: Mapping[RecordKey, AlignedEvidenceRecord] = field(
        repr=False,
        compare=False,
    )
    _by_canonical: Mapping[VerseRef, tuple[EvidenceRecord, ...]] = field(
        repr=False,
        compare=False,
    )
    _existing_local_refs: frozenset[VerseRef] = field(repr=False, compare=False)

    @classmethod
    def build(
        cls,
        project_id: str,
        records: Iterable[EvidenceRecord],
        schema: VersificationSchema,
    ) -> ProjectVerseIndex:
        """Build a deterministic immutable index from validated Project-local records."""
        normalized_project_id = str(project_id).strip()
        if not normalized_project_id:
            raise ValidationError(
                "Verse alignment Project ID must not be empty",
                code="VERSE_ALIGNMENT_PROJECT_MISMATCH",
            )
        schema_snapshot = deepcopy(schema)
        aligned_rows: list[AlignedEvidenceRecord] = []
        by_record_key: dict[RecordKey, AlignedEvidenceRecord] = {}
        for record in sorted(tuple(records), key=_record_order):
            key = _record_key(record)
            if key in by_record_key:
                raise ValidationError(
                    f"Duplicate evidence record in Project {normalized_project_id}: {record.reference}",
                    code="VERSE_ALIGNMENT_RECORD_DUPLICATE",
                )
            local_refs = frozenset(record.refs)
            aligned = AlignedEvidenceRecord(
                record=record,
                local_refs=local_refs,
                canonical_refs=schema_snapshot.canonical_set(local_refs),
                mapping_precision=_local_projection_precision(schema_snapshot, local_refs),
            )
            aligned_rows.append(aligned)
            by_record_key[key] = aligned
        # Materialize the reverse map once so later packet routing stays deterministic.
        by_canonical_lists: dict[VerseRef, list[EvidenceRecord]] = {}
        for aligned in aligned_rows:
            for canonical_ref in aligned.canonical_refs:
                by_canonical_lists.setdefault(canonical_ref, []).append(aligned.record)
        by_canonical = {
            ref: tuple(sorted(rows, key=_record_order))
            for ref, rows in by_canonical_lists.items()
        }
        existing_local_refs = frozenset(
            ref
            for aligned in aligned_rows
            for ref in aligned.local_refs
            if _local_ref_is_valid(schema_snapshot, ref)
        )
        return cls(
            project_id=normalized_project_id,
            schema_id=schema_snapshot.schema_id,
            aligned_records=tuple(aligned_rows),
            _schema=schema_snapshot,
            _by_record_key=MappingProxyType(by_record_key),
            _by_canonical=MappingProxyType(by_canonical),
            _existing_local_refs=existing_local_refs,
        )

    def _aligned_for_records(
        self,
        records: Iterable[EvidenceRecord],
    ) -> tuple[AlignedEvidenceRecord, ...]:
        """Resolve selected records against this Project or reject foreign evidence."""
        selected: dict[RecordKey, AlignedEvidenceRecord] = {}
        for record in records:
            key = _record_key(record)
            aligned = self._by_record_key.get(key)
            if aligned is None or aligned.record != record:
                raise ValidationError(
                    f"Evidence record {record.reference} does not belong to Project {self.project_id}",
                    code="VERSE_ALIGNMENT_PROJECT_MISMATCH",
                )
            selected[key] = aligned
        return tuple(sorted(selected.values(), key=lambda row: _record_order(row.record)))

    def canonical_refs_for_records(
        self,
        records: Iterable[EvidenceRecord],
    ) -> frozenset[VerseRef]:
        """Return canonical coverage for records proven to belong to this Project index."""
        return frozenset(
            ref
            for aligned in self._aligned_for_records(records)
            for ref in aligned.canonical_refs
        )

    def records_for_canonical(
        self,
        refs: Iterable[VerseRef],
    ) -> tuple[EvidenceRecord, ...]:
        """Return actual Project records intersecting canonical coordinates exactly once."""
        selected: dict[RecordKey, EvidenceRecord] = {}
        for ref in refs:
            for record in self._by_canonical.get(ref, ()):
                selected[_record_key(record)] = record
        return tuple(sorted(selected.values(), key=_record_order))

    def local_refs_for_canonical(
        self,
        refs: Iterable[VerseRef],
        *,
        existing_only: bool = False,
    ) -> frozenset[VerseRef]:
        """Project canonical coordinates into valid local schema or evidence coordinates."""
        local_refs = frozenset(
            local_ref
            for canonical_ref in refs
            for local_ref in self._schema.canonical_to_local(canonical_ref)
            if _local_ref_is_valid(self._schema, local_ref)
        )
        if existing_only:
            return local_refs.intersection(self._existing_local_refs)
        return local_refs


def align_records(
    primary_records: Iterable[EvidenceRecord],
    primary_index: ProjectVerseIndex,
    authority_index: ProjectVerseIndex,
) -> AlignmentSelection:
    """Select exact Authority records through canonical coverage of Primary records."""
    selected_primary = primary_index._aligned_for_records(primary_records)
    primary_local_refs = frozenset(
        ref for aligned in selected_primary for ref in aligned.local_refs
    )
    canonical_refs = frozenset(
        ref for aligned in selected_primary for ref in aligned.canonical_refs
    )
    authority_records = authority_index.records_for_canonical(canonical_refs)
    selected_authority = authority_index._aligned_for_records(authority_records)
    authority_canonical_refs = frozenset(
        ref for aligned in selected_authority for ref in aligned.canonical_refs
    )
    covered = canonical_refs.intersection(authority_canonical_refs)
    precision = "COORDINATE"
    if any(
        aligned.mapping_precision != "COORDINATE"
        for aligned in selected_primary + selected_authority
    ):
        precision = "EQUIVALENCE_GROUP"
    return AlignmentSelection(
        primary_local_refs=primary_local_refs,
        canonical_refs=canonical_refs,
        authority_records=authority_records,
        covered_canonical_refs=covered,
        missing_canonical_refs=canonical_refs.difference(covered),
        mapping_precision=precision,
    )


def project_coordinates(
    primary_refs: Iterable[VerseRef],
    primary_index: ProjectVerseIndex,
    target_index: ProjectVerseIndex,
) -> CoordinateProjection:
    """Project existing Primary coordinates into valid target-local schema coordinates."""
    selected_primary_refs = frozenset(primary_refs)
    indexed_primary_refs = frozenset(
        ref for aligned in primary_index.aligned_records for ref in aligned.local_refs
    )
    if not selected_primary_refs.issubset(indexed_primary_refs):
        missing = sorted(selected_primary_refs.difference(indexed_primary_refs))
        label = missing[0].label() if missing else "unknown"
        raise ValidationError(
            f"Primary coordinate {label} does not belong to Project {primary_index.project_id}",
            code="VERSE_ALIGNMENT_PROJECT_MISMATCH",
        )
    canonical_refs = primary_index._schema.canonical_set(selected_primary_refs)
    target_local_refs = target_index.local_refs_for_canonical(canonical_refs)
    primary_precision = _local_projection_precision(
        primary_index._schema,
        selected_primary_refs,
    )
    target_precision = _canonical_projection_precision(
        target_index._schema,
        canonical_refs,
    )
    precision = (
        "COORDINATE"
        if primary_precision == target_precision == "COORDINATE"
        else "EQUIVALENCE_GROUP"
    )
    return CoordinateProjection(
        primary_local_refs=selected_primary_refs,
        canonical_refs=canonical_refs,
        target_local_refs=target_local_refs,
        precision=precision,
        is_deterministic=precision == "COORDINATE",
    )
