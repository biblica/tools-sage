"""General routed-SFM slicer regression coverage."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sage.evidence import EvidencePolicy
from sage.sfm_slicer import SfmAnalysisRoute, SfmStream, plan_sfm_work_units, render_sfm_slice
from sage.work_units import EvidenceRecord


def _record(verse: int, text: str, *, role: str = "WIP", controller_noise: str = "") -> EvidenceRecord:
    """Build one Scripture record with optional controller noise for sizing-invariance tests."""
    return EvidenceRecord(
        book="MAT",
        chapter=1,
        verse_start=verse,
        verse_end=verse,
        payload={"body_text": text, "role": role, "controller_noise": controller_noise},
        sfm=f"\\v {verse} {text}",
        discourse_unit_id=f"MAT-1-{verse}",
    )


def _policy(*, hard: int = 90) -> EvidencePolicy:
    """Return a compact routed-SFM policy for deterministic slicer regressions."""
    return EvidencePolicy(
        target_estimated_tokens=45,
        hard_estimated_tokens=hard,
        hard_serialized_bytes=100000,
        minimum_target_tokens=1,
        maximum_primary_verse_units=50,
        context_before_verses=0,
        context_after_verses=0,
    )


def test_render_sfm_slice_contains_only_scripture_sfm() -> None:
    """Render analytical Scripture without serializing controller metadata into the slice."""
    record = _record(1, "Alpha beta", controller_noise="X" * 10000)
    rendered = render_sfm_slice((record,))
    assert rendered == "\\id MAT\n\\c 1\n\\v 1 Alpha beta\n"
    assert "controller_noise" not in rendered
    assert "XXXXX" not in rendered


def test_controller_metadata_cannot_change_work_unit_boundaries() -> None:
    """Prove controller-only changes cannot alter SFM token counts or work-unit boundaries."""
    base = tuple(_record(i, "word " * 45) for i in range(1, 5))
    noisy = tuple(replace(row, payload={**row.payload, "noise": "Z" * 500000}) for row in base)
    route_a = SfmAnalysisRoute("RTC", (SfmStream("WIP", base),))
    route_b = SfmAnalysisRoute("RENAMED-CONTROLLER-ROUTE", (SfmStream("WIP", noisy),))
    units_a = plan_sfm_work_units(base, _policy(), unit_prefix="A", route=route_a)
    units_b = plan_sfm_work_units(noisy, _policy(), unit_prefix="B", route=route_b)
    assert [u.to_dict()["primary_scope"] for u in units_a] == [u.to_dict()["primary_scope"] for u in units_b]
    assert [u.measurement.estimated_tokens for u in units_a] == [u.measurement.estimated_tokens for u in units_b]


def test_all_routed_sfm_streams_contribute_to_review_item_budget() -> None:
    """Count every SFM stream actually routed to one review item in its hard budget."""
    wip = tuple(_record(i, "w " * 35, role="WIP") for i in range(1, 5))
    ref = tuple(_record(i, "r " * 35, role="REFERENCE") for i in range(1, 5))
    single = SfmAnalysisRoute("WIP_ONLY", (SfmStream("WIP", wip),))
    paired = SfmAnalysisRoute("RTC", (SfmStream("WIP", wip), SfmStream("REFERENCE", ref)))
    single_units = plan_sfm_work_units(wip, _policy(hard=130), unit_prefix="S", route=single)
    paired_units = plan_sfm_work_units(wip, _policy(hard=130), unit_prefix="P", route=paired)
    assert len(paired_units) >= len(single_units)
    assert paired_units[0].measurement.estimated_tokens > single_units[0].measurement.estimated_tokens


def test_model_facing_modules_do_not_expose_or_call_independent_token_sizers() -> None:
    """Keep all model-route token estimation behind the general SFM sizing module."""
    import sage.llm_tasks as llm_tasks

    assert not hasattr(llm_tasks, "estimate_initial_handoff")
    root = __import__("pathlib").Path(__file__).resolve().parents[1] / "src" / "sage"
    for name in ("act_tasks.py", "llm_tasks.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "estimate_tokens(" not in text, name


def test_general_sfm_slicer_is_the_only_public_model_sizing_authority() -> None:
    """Reject legacy public JSON/packet measurement APIs outside the routed-SFM slicer."""
    import sage.evidence as evidence

    assert not hasattr(evidence, "measure_evidence")
    assert not hasattr(evidence, "enforce_evidence_limits")
    source = Path(evidence.__file__).read_text(encoding="utf-8")
    assert "serialized packet" not in source


def test_operator_sizing_labels_name_routed_sfm_not_packets() -> None:
    """Keep work-unit measurement labels aligned with routed-SFM-only sizing."""
    root = Path(__file__).resolve().parents[1] / "src" / "sage"
    human_output = (root / "human_output.py").read_text(encoding="utf-8")
    assert "Largest estimated packet tokens" not in human_output
    assert "Largest serialized packet bytes" not in human_output
    assert "Largest estimated routed-SFM tokens" in human_output
    assert "Largest routed-SFM bytes" in human_output
