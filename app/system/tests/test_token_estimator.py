"""Calibrated token estimator and routed Hebrew cantillation removal."""

from __future__ import annotations

import json

from sage.act_evidence import _bounded_sfm_packet
from sage.evidence import TOKEN_ESTIMATOR, EvidencePolicy, estimate_tokens
from sage.references import parse_scope
from sage.stc import (
    LEGACY_STC_PLANNER_VERSION,
    plan_stc_work_units,
    routed_ol_text_filter_for_book,
    stc_package_measurements,
    strip_hebrew_cantillation,
)
from sage.work_units import EvidenceRecord

# One pointed word with a cantillation accent (U+0591 etnahta) and a meteg (U+05BD), then maqaf and sof pasuq.
ACCENTED = "בְּרֵאשִׁ֑ית בָּרָֽא־אֱלֹהִים׃"
UNACCENTED = "בְּרֵאשִׁית בָּרָֽא־אֱלֹהִים׃"


def _record(book: str, verse: int, text: str, *, role: str) -> EvidenceRecord:
    """Build one routed SFM Scripture record."""
    return EvidenceRecord(
        book=book,
        chapter=1,
        verse_start=verse,
        verse_end=verse,
        payload={"body_text": text, "resource_role": role},
        sfm=f"\\v {verse} {text}",
        section_id=f"{book}-S1",
        paragraph_id=f"{book}-P{verse}",
        discourse_unit_id=f"{book}-D{verse}",
        discourse_unit_kind="PARAGRAPH",
        discourse_unit_marker="p",
    )


def test_estimator_identity_and_per_script_costs() -> None:
    """Script-calibrated costs: Hebrew marks count, Latin letters are cheap, unknown scripts cost 1 per character."""
    assert TOKEN_ESTIMATOR == "SAGE_MULTILINGUAL_HEURISTIC_2"
    assert estimate_tokens("") == 1
    # Vowel points and accents are real tokenizer cost, not free combining marks.
    assert estimate_tokens(ACCENTED) > estimate_tokens(UNACCENTED) > estimate_tokens("בראשית ברא־אלהים׃")
    # A pointed Hebrew word costs far more than an English word of the same length.
    assert estimate_tokens("בְּרֵאשִׁית") > 3 * estimate_tokens("beginning")
    # Georgian has no calibration data: one token per character, deliberately on the high side.
    assert estimate_tokens("ქართული") == len("ქართული")


def test_strip_hebrew_cantillation_keeps_letters_points_maqaf_and_sof_pasuq() -> None:
    """Only U+0591-U+05AF accents are removed; meteg, maqaf, sof pasuq, and ketiv/qere marks stay."""
    assert strip_hebrew_cantillation(ACCENTED) == UNACCENTED
    assert "ֽ" in strip_hebrew_cantillation(ACCENTED)  # meteg
    assert strip_hebrew_cantillation("*כתיב **קְרֵי") == "*כתיב **קְרֵי"
    assert routed_ol_text_filter_for_book("GEN") is strip_hebrew_cantillation
    assert routed_ol_text_filter_for_book("JHN") is None
    assert routed_ol_text_filter_for_book("TOB") is None


def test_stc_packet_and_planner_sizing_route_hebrew_without_cantillation(tmp_path) -> None:
    """The STC Hebrew packet and the planner's OL measurement both see the accent-free text."""
    source = tmp_path / "01GENhebSRC.SFM"
    source.write_text(f"\\id GEN\n\\c 1\n\\p\n\\v 1 {ACCENTED}\n", encoding="utf-8")
    destination = tmp_path / "original-language.sfm"
    _bounded_sfm_packet(source, parse_scope("GEN 1:1"), destination, text_filter=routed_ol_text_filter_for_book("GEN"))
    packet = destination.read_text(encoding="utf-8")
    assert UNACCENTED in packet and "֑" not in packet

    policy = EvidencePolicy(
        target_estimated_tokens=500, hard_estimated_tokens=800, hard_serialized_bytes=20000,
        minimum_target_tokens=1, maximum_primary_verse_units=220, context_before_verses=0, context_after_verses=0,
    )
    wip = (_record("GEN", 1, "In the beginning God created.", role="WIP"),)
    measured = {}
    # The filter is applied per stream whatever the planner version; the legacy planner needs no verse indexes.
    for label, text in (("accented", ACCENTED), ("plain", UNACCENTED)):
        ol = (_record("GEN", 1, text, role="HEB"),)
        units = plan_stc_work_units(wip, ol, policy, unit_prefix="STC-GEN", planner_version=LEGACY_STC_PLANNER_VERSION)
        package = stc_package_measurements(units, ol, planner_version=LEGACY_STC_PLANNER_VERSION)[0]
        measured[label] = (units[0].measurement.estimated_tokens, json.dumps(package["ol"], sort_keys=True))
    assert measured["accented"] == measured["plain"]


def test_rtc_ol_adjudication_packet_routes_hebrew_without_cantillation(tmp_path) -> None:
    """The RTC selective-OL packet (USJ and model SFM) carries the accent-free Hebrew."""
    from sage.act_evidence import _write_reference_inventory_usj_packet

    source = tmp_path / "01GENhebSRC.SFM"
    source.write_text(f"\\id GEN\n\\c 1\n\\p\n\\v 1 {ACCENTED}\n", encoding="utf-8")
    destination = tmp_path / "original-language.usj.json"
    _record_meta, model_sfm = _write_reference_inventory_usj_packet(
        source, ["GEN 1:1"], destination, parent_scope=parse_scope("GEN 1"),
        text_filter=routed_ol_text_filter_for_book("GEN"),
    )
    assert UNACCENTED in model_sfm and "֑" not in model_sfm
    assert "֑" not in destination.read_text(encoding="utf-8")
