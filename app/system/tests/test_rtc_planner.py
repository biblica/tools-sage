"""RTC WIP slicing and complete correlated-package validation."""

import pytest

from sage.errors import EvidenceLimitError, ValidationError
from sage.evidence import EvidencePolicy, RTCSizingPolicy
from sage.rtc_planner import plan_rtc_work_units, vrs_source_equivalence_spans
from sage.work_units import EvidenceRecord


def _record(verse: int, text: str, *, role: str) -> EvidenceRecord:
    """Build one synthetic discourse-classified Scripture evidence record."""
    return EvidenceRecord(
        book="MAT",
        chapter=1,
        verse_start=verse,
        verse_end=verse,
        payload={"body_text": text, "resource_role": role},
        section_id="MAT-S1",
        paragraph_id=f"MAT-P{(verse - 1) // 3}",
        discourse_unit_id=f"MAT-D{(verse - 1) // 3}",
        discourse_unit_kind="PARAGRAPH",
        discourse_unit_marker="p",
    )


def _bridge_record(start: int, end: int, text: str, *, role: str) -> EvidenceRecord:
    """Build one indivisible bridged source record for boundary regressions."""
    return EvidenceRecord(
        book="MAT",
        chapter=1,
        verse_start=start,
        verse_end=end,
        payload={"body_text": text, "resource_role": role},
        section_id="MAT-S1",
        paragraph_id=f"MAT-P{(start - 1) // 3}",
        discourse_unit_id=f"MAT-D{(start - 1) // 3}",
        discourse_unit_kind="PARAGRAPH",
        discourse_unit_marker="p",
    )


def _sizing() -> RTCSizingPolicy:
    """Return the release-governed RTC sizing fixture."""
    return RTCSizingPolicy.from_mapping({
        "provider": "codex",
        "estimator": "SAGE_MULTILINGUAL_HEURISTIC_1",
        "wip_target_min_tokens": 6000,
        "wip_target_max_tokens": 7000,
        "wip_hard_exclusive_tokens": 8000,
        "route_hard_max_tokens": 32000,
        "route_hard_serialized_bytes": 224000,
    })


def test_vrs_equivalence_spans_ignore_books_outside_requested_scope() -> None:
    """A JHN RTC plan must not parse an unrelated BAR mapping from the base VRS."""
    effective_vrs = {
        "mappings": [
            {"local": "BAR 6:1-73", "canonical": "LJE 1:1-73"},
            {"local": "JHN 1:1-2", "canonical": "JHN 1:1-2"},
        ]
    }

    spans = vrs_source_equivalence_spans(
        effective_vrs,
        requested_book="JHN",
    )

    assert [[ref.label() for ref in span] for span in spans] == [
        ["JHN 1:1", "JHN 1:2"]
    ]


def test_rtc_planning_requires_a_canonical_66_book_paratext_id() -> None:
    """Extended-canon Paratext IDs cannot become governed RTC work scopes."""
    with pytest.raises(ValidationError) as caught:
        vrs_source_equivalence_spans({}, requested_book="BAR")

    assert caught.value.code == "RTC_CANONICAL_BOOK_ID_REQUIRED"
    assert "three-character Paratext/USFM book ID" in caught.value.message
    assert "Protestant 66-book canon" in caught.value.message


def test_reference_heavy_rtc_package_is_resliced_after_wip_boundary_planning() -> None:
    """A REF-heavy completed package is resliced even when the initial WIP slice fits."""
    wip = tuple(_record(verse, "w" * 1800, role="WIP") for verse in range(1, 13))
    reference = tuple(
        _record(verse, "r" * 9000, role="REFERENCE") for verse in range(1, 13)
    )
    base = EvidencePolicy(
        target_estimated_tokens=28000,
        hard_estimated_tokens=32000,
        hard_serialized_bytes=224000,
        minimum_target_tokens=6000,
        maximum_primary_verse_units=220,
        context_before_verses=0,
        context_after_verses=0,
    )

    units, packages, effective = plan_rtc_work_units(
        wip,
        base,
        _sizing(),
        unit_prefix="SAW-RTC-MAT-TEST",
        shared={},
        wip_context_pool=wip,
        reference_records=reference,
    )

    assert len(units) > 1
    assert effective.target_estimated_tokens == 6000
    assert effective.hard_estimated_tokens == 32000
    assert all(item["wip"]["estimated_tokens"] < 8000 for item in packages)
    assert all(item["route"]["estimated_tokens"] <= 32000 for item in packages)
    assert all(item["route"]["serialized_bytes"] <= 224000 for item in packages)
    assert all(item["route"]["basis"] == "ROUTED_SFM_ONLY" for item in packages)


def test_rtc_planning_reports_missing_reference_coordinate_without_blocking() -> None:
    """A ready REFERENCE gap is a text issue while WIP coverage stays complete."""
    wip = tuple(_record(verse, "w", role="WIP") for verse in range(1, 3))
    reference = (_record(1, "r", role="REFERENCE"),)
    base = EvidencePolicy(
        target_estimated_tokens=100,
        hard_estimated_tokens=32000,
        hard_serialized_bytes=224000,
        minimum_target_tokens=1,
        maximum_primary_verse_units=220,
        context_before_verses=0,
        context_after_verses=0,
    )

    units, packages, _ = plan_rtc_work_units(
        wip,
        base,
        _sizing(),
        unit_prefix="SAW-RTC-MAT-SOURCE-GAP",
        shared={},
        wip_context_pool=wip,
        reference_records=reference,
    )

    assert [ref.label() for ref in sorted(units[0].primary_refs)] == [
        "MAT 1:1", "MAT 1:2"
    ]
    assert len(packages[0]["source_text_issues"]) == 1
    issue = packages[0]["source_text_issues"][0]
    assert issue["status"] == "REPORT_ONLY"
    assert issue["classification"] == "STRUCTURE_PROBLEM"
    assert issue["structure_status"] == "VERSIFICATION_MISMATCH"
    assert issue["text_relation"] == "ADDITION"
    assert issue["reference"] == "MAT 1:2"


def test_reference_bridge_moves_internal_wip_boundary_to_its_far_edge() -> None:
    """A REFERENCE 3-4 span keeps WIP atoms 3 and 4 in one primary owner."""
    wip = tuple(_record(verse, "w" * 6000, role="WIP") for verse in range(1, 7))
    reference = (
        _record(1, "r" * 200, role="REFERENCE"),
        _record(2, "r" * 200, role="REFERENCE"),
        _bridge_record(3, 4, "r" * 400, role="REFERENCE"),
        _record(5, "r" * 200, role="REFERENCE"),
        _record(6, "r" * 200, role="REFERENCE"),
    )
    base = EvidencePolicy(
        target_estimated_tokens=28000,
        hard_estimated_tokens=32000,
        hard_serialized_bytes=224000,
        minimum_target_tokens=6000,
        maximum_primary_verse_units=220,
        context_before_verses=0,
        context_after_verses=0,
    )

    units, packages, _ = plan_rtc_work_units(
        wip,
        base,
        _sizing(),
        unit_prefix="SAW-RTC-MAT-REF-BRIDGE",
        shared={},
        wip_context_pool=wip,
        reference_records=reference,
    )

    owners = {
        ref.label(): unit.unit_id
        for unit in units
        for ref in unit.primary_refs
    }
    assert len(units) == 2
    assert owners["MAT 1:3"] == owners["MAT 1:4"]
    assert packages[0]["source_spans"]["REFERENCE"] == [
        "MAT 1:1", "MAT 1:2", "MAT 1:3-4"
    ]
    assert packages[0]["primary_coverage_atoms"] == [
        "MAT 1:1", "MAT 1:2", "MAT 1:3", "MAT 1:4"
    ]


def test_opposing_wip_and_reference_bridges_close_boundary_until_stable() -> None:
    """REF 3-4 reaches WIP 4-5, so the stable far edge is after atom 5."""
    wip = (
        _record(1, "w" * 6000, role="WIP"),
        _record(2, "w" * 6000, role="WIP"),
        _record(3, "w" * 6000, role="WIP"),
        _bridge_record(4, 5, "w" * 12000, role="WIP"),
        _record(6, "w" * 6000, role="WIP"),
        _record(7, "w" * 6000, role="WIP"),
    )
    reference = (
        _record(1, "r" * 200, role="REFERENCE"),
        _record(2, "r" * 200, role="REFERENCE"),
        _bridge_record(3, 4, "r" * 400, role="REFERENCE"),
        _record(5, "r" * 200, role="REFERENCE"),
        _record(6, "r" * 200, role="REFERENCE"),
        _record(7, "r" * 200, role="REFERENCE"),
    )
    base = EvidencePolicy(
        target_estimated_tokens=28000,
        hard_estimated_tokens=32000,
        hard_serialized_bytes=224000,
        minimum_target_tokens=6000,
        maximum_primary_verse_units=220,
        context_before_verses=0,
        context_after_verses=0,
    )

    units, packages, _ = plan_rtc_work_units(
        wip,
        base,
        _sizing(),
        unit_prefix="SAW-RTC-MAT-OPPOSING-BRIDGES",
        shared={},
        wip_context_pool=wip,
        reference_records=reference,
    )

    assert len(units) == 2
    assert [ref.label() for ref in sorted(units[0].primary_refs)] == [
        "MAT 1:1", "MAT 1:2", "MAT 1:3", "MAT 1:4", "MAT 1:5"
    ]
    assert packages[0]["source_spans"]["WIP"][-1] == "MAT 1:4-5"
    assert "MAT 1:3-4" in packages[0]["source_spans"]["REFERENCE"]


def test_bridge_integrity_blocks_when_far_edge_exceeds_hard_wip_limit() -> None:
    """A hard WIP limit wins over the soft target without splitting REF 3-5."""
    wip = tuple(_record(verse, "w" * 6500, role="WIP") for verse in range(1, 7))
    reference = (
        _record(1, "r" * 200, role="REFERENCE"),
        _record(2, "r" * 200, role="REFERENCE"),
        _bridge_record(3, 5, "r" * 600, role="REFERENCE"),
        _record(6, "r" * 200, role="REFERENCE"),
    )
    base = EvidencePolicy(
        target_estimated_tokens=28000,
        hard_estimated_tokens=32000,
        hard_serialized_bytes=224000,
        minimum_target_tokens=6000,
        maximum_primary_verse_units=220,
        context_before_verses=0,
        context_after_verses=0,
    )

    with pytest.raises(EvidenceLimitError) as caught:
        plan_rtc_work_units(
            wip,
            base,
            _sizing(),
            unit_prefix="SAW-RTC-MAT-BRIDGE-HARD-LIMIT",
            shared={},
            wip_context_pool=wip,
            reference_records=reference,
        )

    assert caught.value.code == "SAW_RTC_UNSPLITTABLE_BRIDGE"
    assert caught.value.details["required_spans"]
