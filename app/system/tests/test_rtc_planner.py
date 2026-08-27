"""RTC WIP slicing and complete correlated-package validation."""

from sage.evidence import EvidencePolicy, RTCSizingPolicy
from sage.rtc_planner import plan_rtc_work_units
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


def _sizing() -> RTCSizingPolicy:
    """Return the release-governed RTC sizing fixture."""
    return RTCSizingPolicy.from_mapping({
        "provider": "codex",
        "estimator": "SAGE_MULTILINGUAL_HEURISTIC_1",
        "wip_target_min_tokens": 6000,
        "wip_target_max_tokens": 7000,
        "wip_hard_exclusive_tokens": 8000,
        "governed_wip_ceiling_tokens": 8000,
        "package_hard_max_tokens": 32000,
        "provider_handoff_max_tokens": 32000,
        "package_hard_serialized_bytes": 224000,
        "minimum_reference_reserve_tokens": 8000,
        "minimum_overhead_reserve_tokens": 6000,
        "minimum_overhead_serialized_bytes": 24000,
    })


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
    assert effective.hard_estimated_tokens < 7999
    assert all(item["wip"]["estimated_tokens"] < 8000 for item in packages)
    assert all(item["pack"]["estimated_tokens"] <= 32000 for item in packages)
    assert all(item["pack"]["serialized_bytes"] <= 224000 for item in packages)
