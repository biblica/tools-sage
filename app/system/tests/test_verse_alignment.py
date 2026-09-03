"""Canonical Project verse-index and cross-versification alignment contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from sage.errors import ValidationError
from sage.verse_alignment import ProjectVerseIndex, align_records, project_coordinates
from sage.vrs import VerseRef, VersificationSchema, parse_vrs_file
from sage.work_units import EvidenceRecord


def _schema(tmp_path: Path, name: str, content: str) -> VersificationSchema:
    """Parse one hand-authored VRS fixture under the canonical org coordinate system."""
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return parse_vrs_file(path, schema_id=name, canonical_id="org.vrs")


def _record(book: str, chapter: int, verse: int, text: str) -> EvidenceRecord:
    """Create one exact local Scripture record for an alignment fixture."""
    return EvidenceRecord(
        book=book,
        chapter=chapter,
        verse_start=verse,
        verse_end=verse,
        payload={"text": text},
        sfm=f"\\v {verse} {text}\n",
    )


def test_index_selects_authority_local_record_through_canonical_coordinate(
    tmp_path: Path,
) -> None:
    """Different local verse labels still select the canonically corresponding record."""
    wip_schema = _schema(
        tmp_path,
        "wip.vrs",
        "2CO 13:14\n2CO 13:14 = 2CO 13:13\n",
    )
    reference_schema = _schema(tmp_path, "reference.vrs", "2CO 13:13\n")
    wip = (_record("2CO", 13, 14, "wip"),)
    reference = (_record("2CO", 13, 13, "reference"),)

    selection = align_records(
        wip,
        ProjectVerseIndex.build("WIP", wip, wip_schema),
        ProjectVerseIndex.build("REFERENCE", reference, reference_schema),
    )

    assert [row.reference for row in selection.authority_records] == ["2CO 13:13"]
    assert selection.canonical_refs == frozenset({VerseRef("2CO", 13, 13)})
    assert selection.missing_canonical_refs == frozenset()
    assert selection.mapping_precision == "COORDINATE"


def test_many_to_one_mapping_routes_all_local_primary_records(tmp_path: Path) -> None:
    """A continuation group retains both Primary records and one Authority record."""
    wip_schema = _schema(
        tmp_path,
        "wip.vrs",
        "MAT 1:3\n#! &MAT 1:2-3 = MAT 1:2\n",
    )
    reference_schema = _schema(tmp_path, "reference.vrs", "MAT 1:2\n")
    wip = (
        _record("MAT", 1, 2, "first"),
        _record("MAT", 1, 3, "continuation"),
    )
    reference = (_record("MAT", 1, 2, "authority"),)

    selection = align_records(
        wip,
        ProjectVerseIndex.build("WIP", wip, wip_schema),
        ProjectVerseIndex.build("REFERENCE", reference, reference_schema),
    )

    assert selection.primary_local_refs == frozenset(
        {VerseRef("MAT", 1, 2), VerseRef("MAT", 1, 3)}
    )
    assert [row.reference for row in selection.authority_records] == ["MAT 1:2"]
    assert selection.mapping_precision == "EQUIVALENCE_GROUP"


def test_index_deduplicates_bridged_record_and_reports_missing_canonical_atom(
    tmp_path: Path,
) -> None:
    """One bridged record selected by two atoms appears once and leaves true gaps visible."""
    schema = _schema(tmp_path, "identity.vrs", "MAT 1:3\n")
    primary = (
        _record("MAT", 1, 1, "primary one"),
        _record("MAT", 1, 2, "primary two"),
        _record("MAT", 1, 3, "primary three"),
    )
    bridge = EvidenceRecord(
        book="MAT",
        chapter=1,
        verse_start=1,
        verse_end=2,
        payload={"text": "bridge"},
        sfm="\\v 1-2 bridge\n",
    )
    authority_index = ProjectVerseIndex.build("AUTHORITY", (bridge,), schema)

    selection = align_records(
        primary,
        ProjectVerseIndex.build("WIP", primary, schema),
        authority_index,
    )

    assert selection.authority_records == (bridge,)
    assert selection.covered_canonical_refs == frozenset(
        {VerseRef("MAT", 1, 1), VerseRef("MAT", 1, 2)}
    )
    assert selection.missing_canonical_refs == frozenset({VerseRef("MAT", 1, 3)})


def test_ambiguous_target_projection_is_explicit_and_schema_backed(
    tmp_path: Path,
) -> None:
    """Projection reaches an empty TARGET schema but cannot claim ambiguous coordinates."""
    source_schema = _schema(
        tmp_path,
        "source.vrs",
        "MAT 1:3\nMAT 1:2 = MAT 1:2-3\n",
    )
    target_schema = _schema(tmp_path, "target.vrs", "MAT 1:3\n")
    source = (_record("MAT", 1, 2, "source"),)
    source_index = ProjectVerseIndex.build("SOURCE", source, source_schema)
    target_index = ProjectVerseIndex.build("TARGET", (), target_schema)

    projection = project_coordinates(
        (VerseRef("MAT", 1, 2),),
        source_index,
        target_index,
    )

    assert projection.canonical_refs == frozenset(
        {VerseRef("MAT", 1, 2), VerseRef("MAT", 1, 3)}
    )
    assert projection.target_local_refs == frozenset(
        {VerseRef("MAT", 1, 2), VerseRef("MAT", 1, 3)}
    )
    assert target_index.local_refs_for_canonical(
        projection.canonical_refs,
        existing_only=True,
    ) == frozenset()
    assert projection.precision == "EQUIVALENCE_GROUP"
    assert projection.is_deterministic is False


def test_index_rejects_records_from_outside_its_project_evidence(tmp_path: Path) -> None:
    """A caller cannot align a record that was not sealed into the selected Project index."""
    schema = _schema(tmp_path, "identity.vrs", "MAT 1:2\n")
    index = ProjectVerseIndex.build(
        "WIP",
        (_record("MAT", 1, 1, "indexed"),),
        schema,
    )

    with pytest.raises(ValidationError) as caught:
        index.canonical_refs_for_records((_record("MAT", 1, 2, "foreign"),))

    assert caught.value.code == "VERSE_ALIGNMENT_PROJECT_MISMATCH"
