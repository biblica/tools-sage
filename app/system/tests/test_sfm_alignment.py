"""VRS-aware routed-SFM selection and bridge-boundary contracts."""

from __future__ import annotations

from pathlib import Path

from sage.evidence import EvidencePolicy
from sage.sfm_slicer import (
    SfmAnalysisRoute,
    SfmStream,
    measure_sfm_slice,
    plan_sfm_work_units,
)
from sage.verse_alignment import ProjectVerseIndex
from sage.vrs import VerseRef, VersificationSchema, parse_vrs_file
from sage.work_units import EvidenceRecord


def _schema(tmp_path: Path, name: str, content: str) -> VersificationSchema:
    """Parse one compact Project VRS fixture against the shared org coordinates."""
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return parse_vrs_file(path, schema_id=name, canonical_id="org.vrs")


def _record(
    verse_start: int,
    text: str,
    *,
    verse_end: int | None = None,
    book: str = "MAT",
    chapter: int = 1,
) -> EvidenceRecord:
    """Build one exact Project-local SFM record, including real bridge records."""
    final_verse = verse_start if verse_end is None else verse_end
    label = str(verse_start) if final_verse == verse_start else f"{verse_start}-{final_verse}"
    return EvidenceRecord(
        book=book,
        chapter=chapter,
        verse_start=verse_start,
        verse_end=final_verse,
        payload={"body_text": text},
        sfm=f"\\v {label} {text}",
        discourse_unit_id=f"{book}-{chapter}-{label}",
    )


def _policy(
    *,
    target: int = 100,
    hard: int = 200,
    context_before: int = 0,
    context_after: int = 0,
) -> EvidencePolicy:
    """Return a compact no-context policy suitable for exact routing assertions."""
    return EvidencePolicy(
        target_estimated_tokens=target,
        hard_estimated_tokens=hard,
        hard_serialized_bytes=100000,
        minimum_target_tokens=1,
        maximum_primary_verse_units=50,
        context_before_verses=context_before,
        context_after_verses=context_after,
    )


def test_route_sizes_corresponding_records_across_different_local_labels(
    tmp_path: Path,
) -> None:
    """Budget the Authority record selected by canonical identity, not its local label."""
    wip = (_record(14, "wip words", book="2CO", chapter=13),)
    reference = (_record(13, "reference words", book="2CO", chapter=13),)
    wip_index = ProjectVerseIndex.build(
        "WIP",
        wip,
        _schema(tmp_path, "wip.vrs", "2CO 13:14\n2CO 13:14 = 2CO 13:13\n"),
    )
    reference_index = ProjectVerseIndex.build(
        "REFERENCE",
        reference,
        _schema(tmp_path, "reference.vrs", "2CO 13:13\n"),
    )
    route = SfmAnalysisRoute(
        "RTC",
        (
            SfmStream("WIP", wip, verse_index=wip_index),
            SfmStream("REFERENCE", reference, verse_index=reference_index),
        ),
        primary_stream_id="WIP",
        primary_index=wip_index,
    )

    units = plan_sfm_work_units(wip, _policy(), unit_prefix="RTC", route=route)

    expected_wip = measure_sfm_slice(wip)
    expected_reference = measure_sfm_slice(reference)
    assert len(units) == 1
    assert units[0].measurement.serialized_bytes == (
        expected_wip.serialized_bytes + expected_reference.serialized_bytes
    )
    assert units[0].measurement.estimated_tokens == (
        expected_wip.estimated_tokens + expected_reference.estimated_tokens
    )


def test_route_selects_authority_context_through_canonical_coordinates(
    tmp_path: Path,
) -> None:
    """Map Primary context to the Authority Project instead of reusing local labels."""
    wip = tuple(_record(verse, f"wip {verse}") for verse in range(1, 4))
    authority = tuple(_record(verse, f"authority {verse}") for verse in range(11, 14))
    wip_index = ProjectVerseIndex.build(
        "WIP",
        wip,
        _schema(tmp_path, "context-wip.vrs", "MAT 1:3\n"),
    )
    authority_index = ProjectVerseIndex.build(
        "AUTHORITY",
        authority,
        _schema(
            tmp_path,
            "context-authority.vrs",
            "MAT 1:13\nMAT 1:11-13 = MAT 1:1-3\n",
        ),
    )
    route = SfmAnalysisRoute(
        "RTC-CONTEXT",
        (
            SfmStream("WIP", wip, verse_index=wip_index),
            SfmStream("REFERENCE", authority, verse_index=authority_index),
        ),
        primary_stream_id="WIP",
        primary_index=wip_index,
    )

    units = plan_sfm_work_units(
        (wip[1],),
        _policy(context_before=1, context_after=1),
        unit_prefix="RTC-CONTEXT",
        route=route,
        context_pool=wip,
    )

    expected_wip = measure_sfm_slice(wip)
    expected_authority = measure_sfm_slice(authority)
    assert units[0].measurement.serialized_bytes == (
        expected_wip.serialized_bytes + expected_authority.serialized_bytes
    )


def test_indexed_selection_cannot_expand_beyond_routed_stream_records(
    tmp_path: Path,
) -> None:
    """A full-Project index must not add evidence absent from the declared SFM stream."""
    wip = (_record(2, "wip"),)
    authority = (_record(10, "routed"), _record(11, "not routed"))
    wip_index = ProjectVerseIndex.build(
        "WIP",
        wip,
        _schema(tmp_path, "bounded-wip.vrs", "MAT 1:2\n"),
    )
    authority_index = ProjectVerseIndex.build(
        "AUTHORITY",
        authority,
        _schema(
            tmp_path,
            "bounded-authority.vrs",
            "MAT 1:11\n#! &MAT 1:10-11 = MAT 1:2\n",
        ),
    )
    routed_authority = authority[:1]
    route = SfmAnalysisRoute(
        "RTC-BOUNDED",
        (
            SfmStream("WIP", wip, verse_index=wip_index),
            SfmStream("REFERENCE", routed_authority, verse_index=authority_index),
        ),
        primary_stream_id="WIP",
        primary_index=wip_index,
    )

    units = plan_sfm_work_units(
        wip,
        _policy(),
        unit_prefix="RTC-BOUNDED",
        route=route,
    )

    assert units[0].measurement.serialized_bytes == (
        measure_sfm_slice(wip).serialized_bytes
        + measure_sfm_slice(routed_authority).serialized_bytes
    )


def test_actual_authority_bridge_projects_to_primary_boundary_but_vrs_mapping_alone_does_not(
    tmp_path: Path,
) -> None:
    """Protect projected Primary atoms only when an Authority bridge really exists."""
    wip = tuple(
        _record(verse, text)
        for verse, text in ((1, "a" * 60), (2, "b" * 8), (3, "c" * 8), (4, "d" * 60))
    )
    wip_index = ProjectVerseIndex.build(
        "WIP",
        wip,
        _schema(tmp_path, "wip.vrs", "MAT 1:4\n"),
    )
    authority_schema = _schema(
        tmp_path,
        "authority.vrs",
        "MAT 1:11\nMAT 1:10-11 = MAT 1:2-3\n",
    )
    bridge = (_record(10, "authority", verse_end=11),)
    split = (_record(10, "authority"), _record(11, "authority"))
    bridge_index = ProjectVerseIndex.build("AUTHORITY-BRIDGE", bridge, authority_schema)
    split_index = ProjectVerseIndex.build("AUTHORITY-SPLIT", split, authority_schema)

    bridge_route = SfmAnalysisRoute(
        "RTC-BRIDGE",
        (
            SfmStream("WIP", wip, verse_index=wip_index),
            SfmStream("REFERENCE", bridge, False, bridge_index),
        ),
        primary_stream_id="WIP",
        primary_index=wip_index,
    )
    mapping_only_route = SfmAnalysisRoute(
        "RTC-MAPPING-ONLY",
        (
            SfmStream("WIP", wip, verse_index=wip_index),
            SfmStream("REFERENCE", split, False, split_index),
        ),
        primary_stream_id="WIP",
        primary_index=wip_index,
    )

    assert bridge_route.protected_spans() == (
        (VerseRef("MAT", 1, 2), VerseRef("MAT", 1, 3)),
    )
    assert mapping_only_route.protected_spans() == ()

    bridge_units = plan_sfm_work_units(
        wip,
        _policy(target=28, hard=38),
        unit_prefix="BRIDGE",
        route=bridge_route,
    )
    mapping_only_units = plan_sfm_work_units(
        wip,
        _policy(target=28, hard=38),
        unit_prefix="MAPPING",
        route=mapping_only_route,
    )
    bridge_owners = {
        ref: unit.unit_id for unit in bridge_units for ref in unit.primary_refs
    }
    mapping_only_owners = {
        ref: unit.unit_id for unit in mapping_only_units for ref in unit.primary_refs
    }
    second = VerseRef("MAT", 1, 2)
    third = VerseRef("MAT", 1, 3)
    assert bridge_owners[second] == bridge_owners[third]
    assert mapping_only_owners[second] != mapping_only_owners[third]
