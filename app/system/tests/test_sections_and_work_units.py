"""Section hierarchy, context routing, and bounded work-unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sage.storage import storage_layout
from sage.evidence import EvidencePolicy
from sage.errors import EvidenceLimitError
from sage.registry import load_ecosystem
from sage.scripture import compile_project
from sage.sections import index_usfm_structure
from sage.work_units import (
    EvidenceRecord,
    records_from_project_result,
    select_records_for_scope,
)
from sage.references import parse_scope
from sage.sfm_slicer import SfmAnalysisRoute, SfmStream, plan_sfm_work_units


def plan_work_units(records, policy, *, unit_prefix, shared=None, context_pool=None, required_spans=()):
    """Exercise the production general SFM slicer with one routed Scripture stream."""
    ordered = tuple(records)
    pool = tuple(context_pool) if context_pool is not None else ordered
    return plan_sfm_work_units(
        ordered, policy, unit_prefix=unit_prefix,
        route=SfmAnalysisRoute(
            route_id="TEST",
            streams=(SfmStream("SCRIPTURE", pool),),
            target_stream_ids=("SCRIPTURE",),
        ),
        context_pool=pool, required_spans=required_spans,
    )


def record(
    verse: int,
    *,
    chapter: int = 1,
    text: str = "text",
    boundary: tuple[str, int] | None = None,
) -> EvidenceRecord:
    """Build one deterministic work-unit record for this test."""
    boundaries = ()
    if boundary:
        kind, score = boundary
        boundaries = ({"kind": kind, "marker": kind.lower(), "score": score},)
    return EvidenceRecord(
        book="MAT",
        chapter=chapter,
        verse_start=verse,
        verse_end=verse,
        payload={"body_text": text, "reference": f"MAT {chapter}:{verse}"},
        boundaries_before=boundaries,
    )


def test_section_index_ignores_s3_and_preserves_cross_chapter_section() -> None:
    """Verify that section index ignores s3 and preserves cross chapter section."""
    text = (
        "\\id JHN Fixture\n"
        "\\c 2\n"
        "\\s1 One discourse\n"
        "\\p\n"
        "\\v 23 First.\n"
        "\\s3 Ignored detail\n"
        "\\v 24 Second.\n"
        "\\c 3\n"
        "\\v 1 Continued paragraph.\n"
        "\\s2 New subsection\n"
        "\\p\n"
        "\\v 2 New subsection text.\n"
    )
    indexed = index_usfm_structure(text, "JHN")
    assert indexed[0]["section_marker"] == "s1"
    assert indexed[1]["section_marker"] == "s1"
    assert indexed[2]["section_marker"] == "s1"
    assert all(item["section_marker"] != "s3" for item in indexed)
    chapter_boundary = next(
        boundary
        for boundary in indexed[2]["boundaries_before"]
        if boundary["kind"] == "CHAPTER"
    )
    assert chapter_boundary["score"] < 0
    assert indexed[3]["section_marker"] == "s2"


def test_qa_and_b_are_poetry_block_boundaries_but_q_lines_are_not() -> None:
    """Verify that RTC and b are poetry block boundaries but q lines are not."""
    text = (
        "\\id PSA Fixture\n"
        "\\c 119\n"
        "\\qa Aleph\n"
        "\\q1\n"
        "\\v 1 First line.\n"
        "\\q2\n"
        "\\v 2 Second line.\n"
        "\\b\n"
        "\\q1\n"
        "\\v 3 New stanza.\n"
    )
    indexed = index_usfm_structure(text, "PSA")
    first_poetry = [
        item for item in indexed[0]["boundaries_before"] if item["kind"] == "POETRY_BLOCK"
    ]
    assert first_poetry == [
        {
            "kind": "POETRY_BLOCK",
            "marker": "qa",
            "score": 90,
            "continues_paragraph": False,
        }
    ]
    assert indexed[0]["poetry_block_marker"] == "qa"
    assert indexed[0]["poetry_block_title"] == "Aleph"
    assert indexed[0]["paragraph_id"] == indexed[1]["paragraph_id"]
    assert not any(
        item["kind"] == "PARAGRAPH" for item in indexed[1]["boundaries_before"]
    )
    assert any(
        item["kind"] == "POETRY_BLOCK" and item["marker"] == "b"
        for item in indexed[2]["boundaries_before"]
    )
    assert indexed[2]["paragraph_id"] != indexed[1]["paragraph_id"]


def test_m_attaches_to_prior_body_block_without_header() -> None:
    """Verify that m attaches to prior body block without header."""
    text = (
        "\\id PSA Fixture\n"
        "\\c 1\n"
        "\\p\n"
        "\\v 1 Prose opening.\n"
        "\\q1\n"
        "\\v 2 Poetic continuation.\n"
        "\\m\n"
        "\\v 3 Continued body text.\n"
    )
    indexed = index_usfm_structure(text, "PSA")
    assert len({item["paragraph_id"] for item in indexed}) == 1
    assert indexed[0]["paragraph_marker"] == "p"
    assert indexed[1]["paragraph_marker"] == "p"
    assert indexed[2]["paragraph_marker"] == "p"
    assert not any(
        item["kind"] == "PARAGRAPH" for item in indexed[2]["boundaries_before"]
    )


def test_m_starts_new_body_block_after_header_including_ignored_s3() -> None:
    """Verify that m starts new body block after header including ignored s3."""
    text = (
        "\\id MAT Fixture\n"
        "\\c 1\n"
        "\\p\n"
        "\\v 1 First paragraph.\n"
        "\\s3 Structural header ignored for split scoring\n"
        "\\m\n"
        "\\v 2 First body text after header.\n"
    )
    indexed = index_usfm_structure(text, "MAT")
    assert indexed[0]["paragraph_id"] != indexed[1]["paragraph_id"]
    assert indexed[1]["paragraph_marker"] == "m"
    assert any(
        item["kind"] == "PARAGRAPH" and item["marker"] == "m"
        for item in indexed[1]["boundaries_before"]
    )
    assert not any(
        item["kind"] == "SECTION" and item["marker"] == "s3"
        for item in indexed[1]["boundaries_before"]
    )


def test_m_starts_new_body_block_after_explicit_poetry_break() -> None:
    """Verify that m starts new body block after explicit poetry break."""
    text = (
        "\\id PSA Fixture\n"
        "\\c 1\n"
        "\\q1\n"
        "\\v 1 First stanza.\n"
        "\\b\n"
        "\\m\n"
        "\\v 2 Body text after stanza break.\n"
    )
    indexed = index_usfm_structure(text, "PSA")
    assert indexed[0]["paragraph_id"] != indexed[1]["paragraph_id"]
    assert any(
        item["kind"] == "POETRY_BLOCK" and item["marker"] == "b"
        for item in indexed[1]["boundaries_before"]
    )


def test_bare_s_and_ms_aliases_are_governed_section_boundaries() -> None:
    """Verify that bare s and ms aliases are governed section boundaries."""
    text = (
        "\\id MAT Fixture\n"
        "\\c 1\n"
        "\\ms Major\n"
        "\\p\n"
        "\\v 1 One.\n"
        "\\s Section\n"
        "\\p\n"
        "\\v 2 Two.\n"
    )
    indexed = index_usfm_structure(text, "MAT")
    assert indexed[0]["section_marker"] == "ms1"
    assert indexed[1]["section_marker"] == "s1"


def test_planner_prefers_section_boundary_over_weaker_boundaries() -> None:
    """Verify that planner prefers section boundary over weaker boundaries."""
    records = (
        record(1),
        record(2),
        record(3),
        record(4),
        record(5, boundary=("SECTION", 80)),
        record(6),
        record(7, boundary=("CHAPTER", 10)),
        record(8),
    )
    policy = EvidencePolicy(
        target_estimated_tokens=1000,
        hard_estimated_tokens=10000,
        hard_serialized_bytes=100000,
        minimum_target_tokens=1,
        maximum_primary_verse_units=6,
        context_before_verses=0,
        context_after_verses=0,
    )
    units = plan_work_units(records, policy, unit_prefix="MAT")
    assert units[0].primary[-1].reference == "MAT 1:4"
    assert units[0].split_boundary == "SECTION"
    assert units[0].split_boundary_marker == "section"



def test_short_jude_sections_coalesce_into_one_fitting_work_unit() -> None:
    """Section headings are preferred split points, not mandatory microtask boundaries."""
    records = tuple(
        EvidenceRecord(
            book="JUD",
            chapter=1,
            verse_start=verse,
            verse_end=verse,
            payload={"body_text": f"Jude verse {verse}."},
            boundaries_before=(
                ({"kind": "SECTION", "marker": "s1", "score": 80},)
                if verse in {6, 13, 20} else ()
            ),
            section_id=f"JUD-S{1 if verse < 6 else 2 if verse < 13 else 3 if verse < 20 else 4:03d}",
            discourse_unit_id=f"JUD-D{verse:03d}",
            discourse_unit_kind="PROSE_PARAGRAPH",
            discourse_unit_marker="p",
        )
        for verse in range(1, 26)
    )
    policy = EvidencePolicy(
        target_estimated_tokens=18000,
        hard_estimated_tokens=28000,
        hard_serialized_bytes=196000,
        minimum_target_tokens=6000,
        maximum_primary_verse_units=220,
        preferred_primary_discourse_units=4,
        context_before_verses=0,
        context_after_verses=0,
    )

    units = plan_work_units(records, policy, unit_prefix="JUD-RTC")

    assert [unit.to_dict()["primary_scope"] for unit in units] == ["JUD 1:1-25"]
    assert units[0].split_boundary == "END_OF_SCOPE"


def test_oversized_section_is_split_into_balanced_story_parts() -> None:
    """Lookahead should avoid a near-ceiling packet followed by a tiny section tail."""
    records = tuple(
        EvidenceRecord(
            book="MAT",
            chapter=1,
            verse_start=verse,
            verse_end=verse,
            payload={"body_text": (f"paragraph-{verse} " * 180)},
            boundaries_before=(
                ({"kind": "PARAGRAPH", "marker": "p", "score": 30},)
                if verse > 1 else ()
            ),
            section_id="MAT-S001",
            discourse_unit_id=f"MAT-D{verse:03d}",
            discourse_unit_kind="PROSE_PARAGRAPH",
            discourse_unit_marker="p",
        )
        for verse in range(1, 7)
    )
    policy = EvidencePolicy(
        target_estimated_tokens=1800,
        hard_estimated_tokens=2500,
        hard_serialized_bytes=100000,
        minimum_target_tokens=700,
        maximum_primary_verse_units=20,
        preferred_primary_discourse_units=4,
        context_before_verses=0,
        context_after_verses=0,
    )

    units = plan_work_units(records, policy, unit_prefix="MAT-RTC")

    assert len(units) == 2
    assert [len(unit.primary) for unit in units] == [3, 3]
    assert [unit.to_dict()["primary_scope"] for unit in units] == [
        "MAT 1:1-3",
        "MAT 1:4-6",
    ]
    sizes = [unit.measurement.estimated_tokens for unit in units]
    assert abs(sizes[0] - sizes[1]) <= max(sizes) * 0.15


def test_context_is_routed_from_outside_operator_scope() -> None:
    """Verify that context is routed from outside operator scope."""
    all_records = tuple(record(verse) for verse in range(1, 7))
    selected = select_records_for_scope(all_records, parse_scope("MAT 1:3-4"))
    policy = EvidencePolicy(
        target_estimated_tokens=1000,
        hard_estimated_tokens=10000,
        hard_serialized_bytes=100000,
        minimum_target_tokens=1,
        maximum_primary_verse_units=10,
        context_before_verses=2,
        context_after_verses=2,
    )
    units = plan_work_units(
        selected,
        policy,
        unit_prefix="MAT",
        context_pool=all_records,
    )
    assert len(units) == 1
    assert [item.reference for item in units[0].context_before] == ["MAT 1:1", "MAT 1:2"]
    assert [item.reference for item in units[0].context_after] == ["MAT 1:5", "MAT 1:6"]
    assert {item.reference for item in units[0].primary} == {"MAT 1:3", "MAT 1:4"}


def test_final_packet_hard_limit_is_enforced() -> None:
    """Verify that final packet hard limit is enforced."""
    huge = record(1, text="x" * 5000)
    policy = EvidencePolicy(
        target_estimated_tokens=10,
        hard_estimated_tokens=20,
        hard_serialized_bytes=200,
        minimum_target_tokens=1,
        maximum_primary_verse_units=2,
        context_before_verses=0,
        context_after_verses=0,
    )
    with pytest.raises(EvidenceLimitError, match="Single verse record"):
        plan_work_units((huge,), policy, unit_prefix="MAT")


def test_short_final_unit_is_rebalanced_when_hard_limit_prevents_merge() -> None:
    """A verse ceiling should produce balanced final units instead of a tiny tail."""
    records = tuple(record(verse, text="word " * 300) for verse in range(1, 11))
    policy = EvidencePolicy(
        target_estimated_tokens=10000,
        hard_estimated_tokens=20000,
        hard_serialized_bytes=200000,
        minimum_target_tokens=6000,
        maximum_primary_verse_units=6,
        context_before_verses=0,
        context_after_verses=0,
    )

    units = plan_work_units(records, policy, unit_prefix="MAT")

    assert [[item.verse_start for item in unit.primary] for unit in units] == [
        [1, 2, 3, 4, 5],
        [6, 7, 8, 9, 10],
    ]


def test_project_records_include_section_and_paragraph_metadata(make_workspace) -> None:
    """Verify that project records include section and paragraph metadata."""
    root = make_workspace(verse_max=4)
    source = storage_layout(root).projects_root / "idKKHv0" / "41MAT.SFM"
    source.write_text(
        "\\id MAT Fixture\n\\c 1\n\\s1 Heading\n\\p\n"
        "\\v 1 One.\n\\v 2 Two.\n\\s2 Detail\n\\p\n\\v 3 Three.\n\\v 4 Four.\n",
        encoding="utf-8",
    )
    config = load_ecosystem(root / "ecosystem.yml")
    result = compile_project(config, config.project("idKKHv0"))
    records = records_from_project_result("idKKHv0", result)
    assert records[0].payload["structure"]["section"][1] == "s1"
    assert records[2].payload["structure"]["section"][1] == "s2"
    assert "project_id" not in records[0].payload
    assert "resource_role" not in records[0].payload
    assert "reference" not in records[0].payload
    assert "poetry" not in records[0].payload["structure"]
    assert result["summary"]["sections"] == 2
    assert Path(result["files"][0]["section_index"]).exists()


def test_work_unit_manifest_uses_current_schema_version() -> None:
    """Verify that work unit manifest uses current schema version."""
    from sage.evidence import EvidencePolicy
    from sage.work_units import EvidenceRecord, manifest

    record = EvidenceRecord(
        book="MAT",
        chapter=1,
        verse_start=1,
        verse_end=1,
        payload={"body_text": "Text."},
    )
    policy = EvidencePolicy(
        target_estimated_tokens=100,
        hard_estimated_tokens=1000,
        hard_serialized_bytes=10000,
        minimum_target_tokens=1,
        maximum_primary_verse_units=10,
        context_before_verses=0,
        context_after_verses=0,
        allow_cross_chapter_units=True,
    )
    units = plan_work_units((record,), policy, unit_prefix="TEST")
    document = manifest(
        units,
        policy,
        operator_scope="MAT 1:1",
        project_id="fixture",
        plan_id="TEST-PLAN",
        plan_fingerprint="a" * 64,
        workflow_id="saw",
        operation="rtc",
    )
    assert document["schema_version"] == "1.2"
    assert document["plan_fingerprint"] == "a" * 64


def test_inline_p_q_m_sequence_keeps_conditional_m_attachment() -> None:
    """Verify that inline p q m sequence keeps conditional m attachment."""
    text = (
        "\\id PSA Fixture\n"
        "\\c 1\n"
        "\\p \\v 1 Prose.\n"
        "\\q1 \\v 2 Poetry line.\n"
        "\\m \\v 3 Continued body text.\n"
    )
    indexed = index_usfm_structure(text, "PSA")
    assert [item["reference"] for item in indexed] == ["PSA 1:1", "PSA 1:2", "PSA 1:3"]
    assert len({item["paragraph_id"] for item in indexed}) == 1
    assert all(item["paragraph_marker"] == "p" for item in indexed)



def test_nested_headers_preserve_strongest_split_signal() -> None:
    """Verify that nested headers preserve strongest split signal."""
    text = (
        "\\id PSA Fixture\n"
        "\\c 1\n"
        "\\ms1 Major collection\n"
        "\\s1 Psalm heading\n"
        "\\s2 Detail heading\n"
        "\\p\n"
        "\\v 1 Text.\n"
    )
    indexed = index_usfm_structure(text, "PSA")
    section = next(
        item for item in indexed[0]["boundaries_before"] if item["kind"] == "SECTION"
    )
    assert section["marker"] == "ms1"
    assert section["score"] == 100
    assert indexed[0]["section_marker"] == "s2"


def test_psalms_book_override_makes_c_and_cl_very_strong_qa_strong_and_b_last_resort() -> None:
    """Verify that psalms book override makes c and cl very strong RTC strong and b last resort."""
    text = (
        "\\id PSA Fixture\n"
        "\\c 1\n"
        "\\cl Psalm 1\n"
        "\\q1\n"
        "\\v 1 One.\n"
        "\\qa Aleph\n"
        "\\q1\n"
        "\\v 2 Two.\n"
        "\\b\n"
        "\\q1\n"
        "\\v 3 Three.\n"
        "\\c 2\n"
        "\\q1\n"
        "\\v 1 Four.\n"
    )
    indexed = index_usfm_structure(text, "PSA")
    first = indexed[0]["boundaries_before"]
    outer = [item for item in first if item["score"] == 110]
    assert len(outer) == 1
    assert outer[0]["marker"] in {"c", "cl"}
    assert any(item["marker"] == "qa" and item["score"] == 90 for item in indexed[1]["boundaries_before"])
    assert any(item["marker"] == "b" and item["score"] == 1 for item in indexed[2]["boundaries_before"])
    assert any(item["marker"] == "c" and item["score"] == 110 for item in indexed[3]["boundaries_before"])


def test_non_psalms_keep_default_chapter_qa_and_b_scores() -> None:
    """Verify that non psalms keep default chapter RTC and b scores."""
    text = (
        "\\id MAT Fixture\n"
        "\\c 1\n"
        "\\qa Heading\n"
        "\\q1\n"
        "\\v 1 One.\n"
        "\\b\n"
        "\\q1\n"
        "\\v 2 Two.\n"
    )
    indexed = index_usfm_structure(text, "MAT")
    assert any(item["marker"] == "c" and item["score"] == 10 for item in indexed[0]["boundaries_before"])
    assert any(item["marker"] == "qa" and item["score"] == 95 for item in indexed[0]["boundaries_before"])
    assert any(item["marker"] == "b" and item["score"] == 70 for item in indexed[1]["boundaries_before"])


def test_rtc_wip_policy_balances_near_six_thousand_without_packing_to_hard_max() -> None:
    """RTC WIP slicing targets about 6k tokens and keeps every planned packet below 8k."""
    records = tuple(
        EvidenceRecord(
            book="MAT",
            chapter=1,
            verse_start=verse,
            verse_end=verse,
            payload={"body_text": (f"word{verse} " * 550)},
            boundaries_before=(
                ({"kind": "PARAGRAPH", "marker": "p", "score": 30},)
                if verse > 1 else ()
            ),
            section_id="MAT-S001",
            discourse_unit_id=f"MAT-D{verse:03d}",
            discourse_unit_kind="PROSE_PARAGRAPH",
            discourse_unit_marker="p",
        )
        for verse in range(1, 15)
    )
    policy = EvidencePolicy(
        target_estimated_tokens=6000,
        hard_estimated_tokens=7999,
        hard_serialized_bytes=100000,
        minimum_target_tokens=5000,
        preferred_max_estimated_tokens=7000,
        maximum_primary_verse_units=80,
        context_before_verses=0,
        context_after_verses=0,
    )

    units = plan_work_units(records, policy, unit_prefix="SAW-RTC-MAT")

    assert len(units) == 2
    assert all(unit.measurement.estimated_tokens < 8000 for unit in units)
    assert all(5000 <= unit.measurement.estimated_tokens <= 7200 for unit in units)


def test_rtc_soft_pack_limit_does_not_merge_clean_sections_toward_eight_thousand() -> None:
    """Adjacent clean discourse sections stay separate when merging would exceed the 7k preference."""
    records = tuple(
        EvidenceRecord(
            book="MAT",
            chapter=1,
            verse_start=verse,
            verse_end=verse,
            payload={"body_text": (f"word{verse} " * 800)},
            boundaries_before=(
                ({"kind": "SECTION", "marker": "s1", "score": 80},)
                if verse == 4 else ()
            ),
            section_id="MAT-S001" if verse <= 3 else "MAT-S002",
            discourse_unit_id=f"MAT-D{verse:03d}",
            discourse_unit_kind="PROSE_PARAGRAPH",
            discourse_unit_marker="p",
        )
        for verse in range(1, 7)
    )
    policy = EvidencePolicy(
        target_estimated_tokens=6000,
        hard_estimated_tokens=7999,
        hard_serialized_bytes=100000,
        minimum_target_tokens=5000,
        preferred_max_estimated_tokens=7000,
        maximum_primary_verse_units=80,
        context_before_verses=0,
        context_after_verses=0,
    )

    units = plan_work_units(records, policy, unit_prefix="SAW-RTC-MAT")

    assert [unit.to_dict()["primary_scope"] for unit in units] == ["MAT 1:1-3", "MAT 1:4-6"]

    no_soft_limit = EvidencePolicy(
        target_estimated_tokens=6000,
        hard_estimated_tokens=7999,
        hard_serialized_bytes=100000,
        minimum_target_tokens=5000,
        maximum_primary_verse_units=80,
        context_before_verses=0,
        context_after_verses=0,
    )
    assert len(plan_work_units(records, no_soft_limit, unit_prefix="SAW-RTC-MAT-NOSOFT")) == 1
